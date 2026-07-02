"""OCR backends for the score/timer overlay.

All backends implement ``read_text(bgr_image) -> OcrResult``. The charset is
tiny (digits and ':'), so a built-in template matcher covers tests and clean
overlays with zero heavy dependencies; PaddleOCR/Tesseract wrappers are there
for real broadcast footage (`pip install -e ".[ocr]"`).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class OcrResult:
    text: str
    confidence: float  # 0..1; 0 when nothing legible


class TemplateDigitOCR:
    """Normalized-cross-correlation matcher for digits + ':'.

    Glyph templates are rendered with OpenCV's Hershey font. Works on crisp
    overlay crops (and our synthetic fixtures); real broadcasts with styled
    fonts should use the paddle/tesseract backends — the interface is the
    same, so they swap via config.
    """

    CHARS = "0123456789:"
    CELL = (20, 28)  # (w, h) all glyphs are resized to before matching

    def __init__(self) -> None:
        import cv2

        self._cv2 = cv2
        glyphs = []
        for ch in self.CHARS:
            canvas = np.zeros((64, 48), np.uint8)
            cv2.putText(canvas, ch, (8, 48), cv2.FONT_HERSHEY_SIMPLEX, 1.4, 255, 3)
            glyphs.append(self._ncc_normalize(self._normalize_glyph(canvas)))
        # (n_chars, h, w) stack of zero-mean unit-norm templates: NCC against
        # every glyph is a single tensordot (cv2.matchTemplate has ~1ms of
        # per-call overhead, far too slow for per-frame use)
        self._template_stack = np.stack(glyphs)

    @staticmethod
    def _ncc_normalize(img: np.ndarray) -> np.ndarray:
        f = img.astype(np.float32)
        f -= f.mean()
        norm = float(np.linalg.norm(f))
        return f / norm if norm else f

    def _normalize_glyph(self, mask: np.ndarray) -> np.ndarray:
        cv2 = self._cv2
        ys, xs = np.nonzero(mask)
        glyph = mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
        return cv2.resize(glyph, self.CELL, interpolation=cv2.INTER_AREA)

    def _binarize(self, bgr: np.ndarray) -> np.ndarray:
        cv2 = self._cv2
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY) if bgr.ndim == 3 else bgr
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        # text should be the minority (white on dark); invert if it isn't
        if np.count_nonzero(binary) > binary.size / 2:
            binary = 255 - binary
        return binary

    def _char_boxes(self, binary: np.ndarray) -> list[tuple[int, int, int, int]]:
        """Connected components merged into character cells (':' is two blobs)."""
        cv2 = self._cv2
        n, _, stats, _ = cv2.connectedComponentsWithStats(binary)
        boxes = [tuple(stats[i][:4]) for i in range(1, n) if stats[i][4] >= 6]
        boxes.sort(key=lambda b: b[0])
        merged: list[list[int]] = []
        for x, y, w, h in boxes:
            if merged:
                mx, my, mw, mh = merged[-1]
                overlap = min(mx + mw, x + w) - max(mx, x)
                if overlap > 0.4 * min(w, mw):
                    x0, y0 = min(mx, x), min(my, y)
                    merged[-1] = [x0, y0, max(mx + mw, x + w) - x0, max(my + mh, y + h) - y0]
                    continue
            merged.append([x, y, w, h])
        return [tuple(b) for b in merged]

    def read_text(self, bgr: np.ndarray) -> OcrResult:
        cv2 = self._cv2
        binary = self._binarize(bgr)
        if not np.count_nonzero(binary):
            return OcrResult("", 0.0)
        chars, scores = [], []
        for x, y, w, h in self._char_boxes(binary):
            cell = self._ncc_normalize(cv2.resize(
                binary[y:y + h, x:x + w], self.CELL, interpolation=cv2.INTER_AREA))
            ncc = np.tensordot(self._template_stack, cell, axes=([1, 2], [0, 1]))
            best = int(np.argmax(ncc))
            if ncc[best] > 0.3:
                chars.append(self.CHARS[best])
                scores.append(float(ncc[best]))
        if not chars:
            return OcrResult("", 0.0)
        return OcrResult("".join(chars), float(np.mean(scores)))


class TesseractOCR:
    """pytesseract wrapper (needs the tesseract binary installed)."""

    def __init__(self) -> None:
        import pytesseract  # noqa: F401

        self._tess = pytesseract

    def read_text(self, bgr: np.ndarray) -> OcrResult:
        text = self._tess.image_to_string(
            bgr, config="--psm 7 -c tessedit_char_whitelist=0123456789:").strip()
        return OcrResult(text, 0.8 if text else 0.0)


class PaddleOCR:
    """PaddleOCR wrapper (heavyweight; best accuracy on styled broadcast fonts)."""

    def __init__(self) -> None:
        from paddleocr import PaddleOCR as _Paddle

        self._paddle = _Paddle(use_angle_cls=False, lang="en", show_log=False)

    def read_text(self, bgr: np.ndarray) -> OcrResult:
        result = self._paddle.ocr(bgr, cls=False)
        if not result or not result[0]:
            return OcrResult("", 0.0)
        texts, confs = zip(*[(line[1][0], line[1][1]) for line in result[0]])
        keep = "".join(c for c in "".join(texts) if c in "0123456789:")
        return OcrResult(keep, float(np.mean(confs)))


_BACKENDS = {
    "template": TemplateDigitOCR,
    "tesseract": TesseractOCR,
    "paddleocr": PaddleOCR,
}


def get_backend(name: str):
    try:
        factory = _BACKENDS[name]
    except KeyError:
        raise ValueError(f"unknown OCR backend {name!r}; options: {sorted(_BACKENDS)}")
    return factory()

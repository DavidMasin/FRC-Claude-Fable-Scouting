"""Opportunistic bumper-number OCR.

Crops the bumper band out of a robot bounding box, upscales it, and runs the
configured OCR backend. This is *only* an evidence source for the assignment
solver — never open-set identification. Blurry frames simply return low/zero
confidence and contribute nothing.
"""

from __future__ import annotations

import numpy as np


def read_bumper(frame: np.ndarray, xyxy: tuple[float, float, float, float],
                backend, band: tuple[float, float] = (0.55, 1.0),
                upscale: int = 2) -> tuple[str, float]:
    """Return (digits, confidence). `band` selects the vertical slice of the
    robot box where the bumper lives (bottom ~half for full-robot boxes;
    (0, 1) when the box already is the bumper, e.g. color-blob detections).
    """
    import cv2

    h, w = frame.shape[:2]
    x0, y0, x1, y1 = (int(round(v)) for v in xyxy)
    top = y0 + int((y1 - y0) * band[0])
    bottom = y0 + int((y1 - y0) * band[1])
    x0, x1 = max(0, x0), min(w, x1)
    top, bottom = max(0, top), min(h, bottom)
    if x1 - x0 < 8 or bottom - top < 6:
        return "", 0.0

    crop = frame[top:bottom, x0:x1]
    if upscale > 1:
        crop = cv2.resize(crop, None, fx=upscale, fy=upscale,
                          interpolation=cv2.INTER_CUBIC)
    result = backend.read_text(crop)
    digits = "".join(c for c in result.text if c.isdigit())
    return digits, (result.confidence if digits else 0.0)

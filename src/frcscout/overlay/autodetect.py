"""Auto-detect the FMS overlay crop regions.

Overlay layout varies per event/broadcaster; hand-measuring crop boxes for
every stream is tedious. This scans a handful of frames spread across live
match play and finds the regions itself:

1. bright text-like blobs are extracted per frame and merged into line boxes;
2. each candidate line is OCR'd; lines parsing as ``m:ss`` or small integers
   survive;
3. candidates are clustered across frames — the overlay is *static*, so a
   real region recurs at the same pixels while robot bumper numbers drift or
   fail the parse;
4. the **timer** is the cluster whose value strictly decreases across frames;
   **scores** are integer clusters vertically aligned with the timer whose
   values never decrease — nearest one on the left is red, on the right blue
   (the FMS convention; verify with one glance at the debug output).

The result is the same fractional-region dict `overlay.regions` takes, so
`frcscout overlay autodetect` prints a paste-ready config snippet.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .parse import parse_score, parse_timer

_MIN_OBSERVATIONS = 3


def _text_line_boxes(frame_bgr: np.ndarray) -> list[tuple[int, int, int, int]]:
    """Bright-text candidate boxes, chars joined into lines."""
    import cv2

    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    _, mask = cv2.threshold(gray, 170, 255, cv2.THRESH_BINARY)
    # join adjacent glyphs horizontally into one line component (wide enough
    # to bridge the whitespace around a narrow '1' or ':')
    mask = cv2.dilate(mask, np.ones((1, 17), np.uint8))
    n, _, stats, _ = cv2.connectedComponentsWithStats(mask)
    fh, fw = gray.shape
    boxes = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area < 40 or h < 8 or h > 0.15 * fh or w > 0.4 * fw or w < 0.5 * h:
            continue
        boxes.append((int(x), int(y), int(w), int(h)))
    return boxes


def _iou(a, b) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix0, iy0 = max(ax, bx), max(ay, by)
    ix1, iy1 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    inter = max(0, ix1 - ix0) * max(0, iy1 - iy0)
    return inter / (aw * ah + bw * bh - inter) if inter else 0.0


@dataclass
class _Cluster:
    box: tuple[int, int, int, int]
    timer_values: list[float] = field(default_factory=list)
    score_values: list[int] = field(default_factory=list)
    hits: int = 0


def _pad_box(box, frame_shape, pad_frac=0.30) -> list[float]:
    """Pixel box -> padded fractional [x, y, w, h]."""
    fh, fw = frame_shape[:2]
    x, y, w, h = box
    px, py = w * pad_frac, h * pad_frac
    x0, y0 = max(0.0, x - px), max(0.0, y - py)
    x1, y1 = min(float(fw), x + w + px), min(float(fh), y + h + py)
    return [round(x0 / fw, 4), round(y0 / fh, 4),
            round((x1 - x0) / fw, 4), round((y1 - y0) / fh, 4)]


def autodetect_regions(frames: list[np.ndarray], backend) -> dict[str, list[float]]:
    """Find match_timer / red_score / blue_score regions from sample frames.

    Frames should span live match play (values changing). Raises ValueError
    when no decreasing timer can be found — e.g. all frames are pre-match.
    """
    clusters: list[_Cluster] = []
    for frame in frames:
        for box in _text_line_boxes(frame):
            x, y, w, h = box
            pad = max(2, h // 4)
            crop = frame[max(0, y - pad):y + h + pad, max(0, x - pad):x + w + pad]
            text = backend.read_text(crop).text
            timer_v, score_v = parse_timer(text), parse_score(text)
            if timer_v is None and score_v is None:
                continue
            cluster = next((c for c in clusters if _iou(c.box, box) > 0.5), None)
            if cluster is None:
                cluster = _Cluster(box=box)
                clusters.append(cluster)
            cluster.hits += 1
            if timer_v is not None and ":" in text:
                cluster.timer_values.append(timer_v)
            elif score_v is not None:
                cluster.score_values.append(score_v)

    stable = [c for c in clusters if c.hits >= min(_MIN_OBSERVATIONS, len(frames))]

    def decreases(values: list[float]) -> int:
        return sum(1 for a, b in zip(values, values[1:]) if b < a)

    timers = [c for c in stable
              if len(c.timer_values) >= 2 and decreases(c.timer_values) >= 1
              and all(b <= a for a, b in zip(c.timer_values, c.timer_values[1:]))]
    if not timers:
        raise ValueError(
            "no decreasing match timer found — sample frames during live play")
    timer = max(timers, key=lambda c: (len(c.timer_values), decreases(c.timer_values)))

    tx, ty, tw, th = timer.box

    def aligned(c: _Cluster) -> bool:
        _, y, _, h = c.box
        return y < ty + th and y + h > ty  # vertical overlap with the timer

    def monotonic(c: _Cluster) -> bool:
        return all(b >= a for a, b in zip(c.score_values, c.score_values[1:]))

    score_clusters = [c for c in stable
                      if len(c.score_values) >= 2 and aligned(c) and monotonic(c)]
    left = [c for c in score_clusters if c.box[0] + c.box[2] <= tx]
    right = [c for c in score_clusters if c.box[0] >= tx + tw]
    if not left or not right:
        raise ValueError("could not find score displays on both sides of the timer")
    red = max(left, key=lambda c: c.box[0])      # nearest to the timer
    blue = min(right, key=lambda c: c.box[0])

    shape = frames[0].shape
    return {
        "match_timer": _pad_box(timer.box, shape),
        "red_score": _pad_box(red.box, shape),
        "blue_score": _pad_box(blue.box, shape),
    }

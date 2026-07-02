"""Fractional overlay crop regions.

Broadcast layouts differ per event/broadcaster, so regions live in config
(overlay.regions) as fractional [x, y, w, h] of the frame — resolution
independent. Auto-detection can refine these later; config is the contract.
"""

from __future__ import annotations

import numpy as np


def crop_region(frame: np.ndarray, box: list[float] | tuple[float, ...]) -> np.ndarray:
    """Crop a fractional (x, y, w, h) box out of a frame."""
    x, y, w, h = box
    if not (0 <= x < 1 and 0 <= y < 1 and 0 < w <= 1 and 0 < h <= 1):
        raise ValueError(f"fractional box out of range: {box}")
    fh, fw = frame.shape[:2]
    x0, y0 = int(round(x * fw)), int(round(y * fh))
    x1, y1 = min(fw, int(round((x + w) * fw))), min(fh, int(round((y + h) * fh)))
    if x1 <= x0 or y1 <= y0:
        raise ValueError(f"box {box} collapses to nothing at {fw}x{fh}")
    return frame[y0:y1, x0:x1]

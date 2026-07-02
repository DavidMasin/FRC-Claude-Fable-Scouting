"""Bumper-color blob detector.

FRC rules require solid red/blue bumpers around every robot, which makes
saturated red/blue blobs a surprisingly usable robot signal on broadcast
footage — and a zero-dependency detector for tests and for degrading
gracefully when no YOLO weights are available. The fine-tuned YOLO detector
(yolo_detector.py) is the production path; both emit the same Detection type.
"""

from __future__ import annotations

import numpy as np

from .detections import Detection

# HSV ranges (OpenCV: H in 0..180). Red wraps around 0.
_RED_LOW1, _RED_HIGH1 = (0, 110, 60), (10, 255, 255)
_RED_LOW2, _RED_HIGH2 = (170, 110, 60), (180, 255, 255)
_BLUE_LOW, _BLUE_HIGH = (95, 110, 60), (135, 255, 255)


class ColorBlobDetector:
    def __init__(self, min_area_frac: float = 0.0004, max_area_frac: float = 0.05,
                 merge_gap_frac: float = 0.01) -> None:
        import cv2

        self._cv2 = cv2
        self.min_area_frac = min_area_frac
        self.max_area_frac = max_area_frac
        self.merge_gap_frac = merge_gap_frac

    def _blobs(self, mask: np.ndarray, alliance: str, frame_area: float) -> list[Detection]:
        cv2 = self._cv2
        kernel = np.ones((3, 3), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        n, _, stats, _ = cv2.connectedComponentsWithStats(mask)
        out = []
        for i in range(1, n):
            x, y, w, h, area = stats[i]
            if not (self.min_area_frac <= area / frame_area <= self.max_area_frac):
                continue
            fill = area / max(1, w * h)          # bumper blobs are dense
            out.append(Detection(
                xyxy=(float(x), float(y), float(x + w), float(y + h)),
                conf=min(0.95, 0.5 + 0.5 * fill),
                label="robot",
                alliance=alliance,
            ))
        return out

    def detect(self, frame_bgr: np.ndarray) -> list[Detection]:
        cv2 = self._cv2
        hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
        frame_area = float(frame_bgr.shape[0] * frame_bgr.shape[1])
        red_mask = cv2.inRange(hsv, np.array(_RED_LOW1), np.array(_RED_HIGH1)) | \
            cv2.inRange(hsv, np.array(_RED_LOW2), np.array(_RED_HIGH2))
        blue_mask = cv2.inRange(hsv, np.array(_BLUE_LOW), np.array(_BLUE_HIGH))
        return self._blobs(red_mask, "red", frame_area) + \
            self._blobs(blue_mask, "blue", frame_area)

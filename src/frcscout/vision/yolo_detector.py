"""Ultralytics YOLO detector (production path; `pip install -e ".[vision]"`).

Expects weights fine-tuned on FRC broadcast frames with classes named
robot / bumper-red / bumper-blue / fuel (see the labeling bootstrap in the
README; `frcscout ingest sample` produces frames for annotation). bumper-*
detections are folded into robot detections with the alliance attached.
"""

from __future__ import annotations

import numpy as np

from .detections import Detection

_ALLIANCE_BY_CLASS = {"bumper-red": "red", "bumper-blue": "blue"}


class YoloDetector:
    def __init__(self, weights: str, conf: float = 0.35, device: str | None = None) -> None:
        from ultralytics import YOLO

        self.model = YOLO(weights)
        self.conf = conf
        self.device = device

    def detect(self, frame_bgr: np.ndarray) -> list[Detection]:
        results = self.model.predict(frame_bgr, conf=self.conf, device=self.device,
                                     verbose=False)
        out: list[Detection] = []
        for r in results:
            names = r.names
            for box in r.boxes:
                cls_name = names[int(box.cls)]
                if cls_name == "fuel":
                    label, alliance = "fuel", None
                elif cls_name in _ALLIANCE_BY_CLASS or cls_name == "robot":
                    label, alliance = "robot", _ALLIANCE_BY_CLASS.get(cls_name)
                else:
                    continue
                out.append(Detection(
                    xyxy=tuple(float(v) for v in box.xyxy[0].tolist()),
                    conf=float(box.conf),
                    label=label,
                    alliance=alliance,
                ))
        return out

"""Active-learning dataset miner for the robot detector.

Runs a detector over broadcast footage and splits frames into two buckets:

- **pseudo-labeled** (`images/train` + `labels/train`, YOLO format): frames
  where every detection is confident — free training signal, sampled at a
  steady interval so one match doesn't produce thousands of near-duplicates.
- **label queue** (`queue/`): frames containing *low-confidence* detections —
  exactly the frames the current detector is worst at, which is where human
  labels buy the most. Each queued JPEG ships with a JSON of the detector's
  own guesses to pre-fill the annotation tool.

The output directory is a ready-to-train ultralytics dataset:

    yolo detect train data=<out>/dataset.yaml model=yolo11n.pt

After training, point ``models.detector_weights`` at the run's best.pt and
mine again with ``--detector yolo`` — each round the queue shrinks toward the
genuinely hard frames.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

CLASSES = ["robot", "bumper-red", "bumper-blue", "fuel"]
_CLASS_IDS = {name: i for i, name in enumerate(CLASSES)}


def detection_class(det) -> str:
    if det.label == "fuel":
        return "fuel"
    if det.alliance == "red":
        return "bumper-red"
    if det.alliance == "blue":
        return "bumper-blue"
    return "robot"


def yolo_label_line(det, frame_shape: tuple[int, int]) -> str:
    h, w = frame_shape
    x0, y0, x1, y1 = det.xyxy
    cx, cy = (x0 + x1) / 2 / w, (y0 + y1) / 2 / h
    bw, bh = (x1 - x0) / w, (y1 - y0) / h
    return (f"{_CLASS_IDS[detection_class(det)]} "
            f"{cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}")


@dataclass
class MinerStats:
    frames_seen: int = 0
    pseudo_labeled: int = 0
    queued: int = 0
    detections: int = 0
    by_class: dict = field(default_factory=lambda: {c: 0 for c in CLASSES})


class DatasetMiner:
    def __init__(self, detector, out_dir: str | Path, low_conf: float = 0.55,
                 pseudo_min_conf: float = 0.8, pseudo_every_s: float = 5.0,
                 source_tag: str = "match") -> None:
        self.detector = detector
        self.low_conf = low_conf
        self.pseudo_min_conf = pseudo_min_conf
        self.pseudo_every_s = pseudo_every_s
        self.source_tag = source_tag

        self.out_dir = Path(out_dir)
        self.images_dir = self.out_dir / "images" / "train"
        self.labels_dir = self.out_dir / "labels" / "train"
        self.queue_dir = self.out_dir / "queue"
        for d in (self.images_dir, self.labels_dir, self.queue_dir):
            d.mkdir(parents=True, exist_ok=True)

        self.stats = MinerStats()
        self._last_pseudo_t: float | None = None

    def _write_image(self, directory: Path, stem: str, image: np.ndarray) -> Path:
        import cv2

        path = directory / f"{stem}.jpg"
        cv2.imwrite(str(path), image)
        return path

    def process(self, image: np.ndarray, t_video: float, frame_index: int) -> str | None:
        """Returns 'queued', 'pseudo', or None for skipped frames."""
        detections = self.detector.detect(image)
        self.stats.frames_seen += 1
        if not detections:
            return None
        stem = f"{self.source_tag}_{frame_index:07d}"

        uncertain = [d for d in detections if d.conf < self.low_conf]
        if uncertain:
            self._write_image(self.queue_dir, stem, image)
            (self.queue_dir / f"{stem}.json").write_text(json.dumps({
                "t_video": round(t_video, 2),
                "frame_index": frame_index,
                "prelabels": [{
                    "class": detection_class(d),
                    "xyxy": [round(v, 1) for v in d.xyxy],
                    "conf": round(d.conf, 3),
                } for d in detections],
            }, indent=2))
            self.stats.queued += 1
            return "queued"

        confident = all(d.conf >= self.pseudo_min_conf for d in detections)
        due = (self._last_pseudo_t is None
               or t_video - self._last_pseudo_t >= self.pseudo_every_s)
        if confident and due:
            self._write_image(self.images_dir, stem, image)
            lines = [yolo_label_line(d, image.shape[:2]) for d in detections]
            (self.labels_dir / f"{stem}.txt").write_text("\n".join(lines) + "\n")
            self._last_pseudo_t = t_video
            self.stats.pseudo_labeled += 1
            self.stats.detections += len(detections)
            for d in detections:
                self.stats.by_class[detection_class(d)] += 1
            return "pseudo"
        return None

    def finalize(self) -> dict:
        (self.out_dir / "dataset.yaml").write_text(
            f"path: {self.out_dir.resolve()}\n"
            "train: images/train\n"
            "val: images/train  # split off a val set once you have volume\n"
            f"names: {json.dumps(CLASSES)}\n")
        return {
            "frames_seen": self.stats.frames_seen,
            "pseudo_labeled": self.stats.pseudo_labeled,
            "queued_for_labeling": self.stats.queued,
            "detections": self.stats.detections,
            "by_class": self.stats.by_class,
        }

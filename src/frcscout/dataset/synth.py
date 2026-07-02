"""Synthetic bootstrap data for the robot detector.

Real labeled FRC broadcast frames beat synthetic ones — see the README's
data sources (Roboflow Universe FRC sets, Dataset Colab). But a synthetic set
gets a first detector off the ground with zero labeling work: randomized
field carpet, perimeter, FMS-style overlay bar, robots with mandated
red/blue bumpers + white numbers, drive bases above the bumpers, yellow
Fuel balls, motion blur, lighting jitter, and partial occlusion.

Labels are YOLO format with the same classes the pipeline expects
(robot / bumper-red / bumper-blue / fuel): the bumper band is labeled as
bumper-<alliance> and the full robot extent as robot.
"""

from __future__ import annotations

import random
from pathlib import Path

import numpy as np

from .miner import CLASSES


def _clip_box(x0, y0, x1, y1, w, h):
    return max(0, x0), max(0, y0), min(w, x1), min(h, y1)


def _yolo_line(cls: str, box, w, h) -> str:
    x0, y0, x1, y1 = box
    return (f"{CLASSES.index(cls)} {(x0 + x1) / 2 / w:.6f} {(y0 + y1) / 2 / h:.6f} "
            f"{(x1 - x0) / w:.6f} {(y1 - y0) / h:.6f}")


def _render_frame(rng: random.Random, w: int, h: int):
    import cv2

    labels: list[str] = []
    carpet = np.array([rng.randint(40, 80), rng.randint(90, 150),
                       rng.randint(40, 80)], np.uint8)
    frame = np.full((h, w, 3), carpet, np.uint8)

    # perimeter + field lines
    cv2.rectangle(frame, (10, int(h * 0.25)), (w - 10, h - 10),
                  (200, 200, 200), 2)
    for _ in range(rng.randint(1, 3)):
        y = rng.randint(int(h * 0.3), h - 20)
        cv2.line(frame, (10, y), (w - 10, y), (220, 220, 220), 1)

    # FMS-style overlay bar (sometimes)
    if rng.random() < 0.7:
        frame[:int(h * 0.12)] = (25, 25, 25)
        for text, x in ((str(rng.randint(0, 150)), int(w * 0.07)),
                        (f"{rng.randint(0, 2)}:{rng.randint(0, 59):02d}", int(w * 0.45)),
                        (str(rng.randint(0, 150)), int(w * 0.85))):
            cv2.putText(frame, text, (x, int(h * 0.09)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (240, 240, 240), 2)

    # fuel balls
    for _ in range(rng.randint(0, 8)):
        r = rng.randint(4, 10)
        cx, cy = rng.randint(r, w - r), rng.randint(int(h * 0.3), h - r)
        cv2.circle(frame, (cx, cy), r, (30, 200, 235), -1)
        cv2.circle(frame, (cx - r // 3, cy - r // 3), max(1, r // 3),
                   (90, 230, 250), -1)
        labels.append(_yolo_line("fuel", (cx - r, cy - r, cx + r, cy + r), w, h))

    # robots: mandated bumpers + a drive base above them
    for _ in range(rng.randint(2, 6)):
        alliance = rng.choice(["red", "blue"])
        bw = rng.randint(40, 120)
        bh = max(10, int(bw * rng.uniform(0.18, 0.35)))
        body_h = int(bh * rng.uniform(0.8, 2.5))
        x0 = rng.randint(-bw // 4, w - 3 * bw // 4)
        y1 = rng.randint(int(h * 0.35), h - 4)
        y0b, y1b = y1 - bh, y1                       # bumper band
        y0r = y1 - bh - body_h                       # full robot extent
        bumper_color = ((rng.randint(10, 60), rng.randint(10, 60), rng.randint(170, 255))
                        if alliance == "red" else
                        (rng.randint(150, 255), rng.randint(40, 120), rng.randint(0, 60)))
        body_gray = rng.randint(50, 140)
        cv2.rectangle(frame, (x0, y0r), (x0 + bw, y0b), (body_gray,) * 3, -1)
        cv2.rectangle(frame, (x0, y0b), (x0 + bw, y1b), bumper_color, -1)
        number = str(rng.randint(1, 9999))
        scale = bh / 32.0
        cv2.putText(frame, number, (x0 + 4, y1b - max(2, bh // 5)),
                    cv2.FONT_HERSHEY_SIMPLEX, max(0.3, scale),
                    (255, 255, 255), max(1, int(scale * 2)))
        labels.append(_yolo_line(f"bumper-{alliance}",
                                 _clip_box(x0, y0b, x0 + bw, y1b, w, h), w, h))
        labels.append(_yolo_line("robot",
                                 _clip_box(x0, y0r, x0 + bw, y1b, w, h), w, h))

    # broadcast artifacts: motion blur + lighting jitter + noise
    if rng.random() < 0.5:
        k = rng.choice([3, 5, 7])
        kernel = np.zeros((k, k), np.float32)
        kernel[k // 2, :] = 1.0 / k
        frame = cv2.filter2D(frame, -1, kernel)
    alpha = rng.uniform(0.75, 1.25)
    beta = rng.uniform(-25, 25)
    frame = cv2.convertScaleAbs(frame, alpha=alpha, beta=beta)
    noise = np.random.default_rng(rng.randint(0, 2**31)).normal(
        0, rng.uniform(1, 6), frame.shape)
    frame = np.clip(frame.astype(np.float32) + noise, 0, 255).astype(np.uint8)
    return frame, labels


def generate_synthetic_dataset(out_dir: str | Path, n_images: int = 300,
                               image_size: tuple[int, int] = (640, 360),
                               seed: int = 0, val_frac: float = 0.15) -> dict:
    import cv2

    out = Path(out_dir)
    rng = random.Random(seed)
    w, h = image_size
    counts = {"train": 0, "val": 0}
    for split in ("train", "val"):
        (out / "images" / split).mkdir(parents=True, exist_ok=True)
        (out / "labels" / split).mkdir(parents=True, exist_ok=True)

    for i in range(n_images):
        split = "val" if rng.random() < val_frac else "train"
        frame, labels = _render_frame(rng, w, h)
        stem = f"synth_{i:05d}"
        cv2.imwrite(str(out / "images" / split / f"{stem}.jpg"), frame)
        (out / "labels" / split / f"{stem}.txt").write_text(
            "\n".join(labels) + ("\n" if labels else ""))
        counts[split] += 1

    import json
    (out / "dataset.yaml").write_text(
        f"path: {out.resolve()}\n"
        "train: images/train\n"
        "val: images/val\n"
        f"names: {json.dumps(CLASSES)}\n")
    return {"train": counts["train"], "val": counts["val"],
            "classes": CLASSES, "out": str(out)}

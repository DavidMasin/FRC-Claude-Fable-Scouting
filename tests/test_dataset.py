import json

import numpy as np
import pytest

from frcscout.dataset import CLASSES, DatasetMiner
from frcscout.vision import ColorBlobDetector, Detection

from test_vision import _field_frame, _six_robots


class FakeDetector:
    def __init__(self, detections):
        self.detections = detections

    def detect(self, frame):
        return self.detections


def test_confident_frames_become_pseudo_labels(tmp_path):
    miner = DatasetMiner(ColorBlobDetector(), tmp_path, pseudo_every_s=5.0)
    assert miner.process(_field_frame(_six_robots(0)), 0.0, 0) == "pseudo"
    # too soon: interval gate
    assert miner.process(_field_frame(_six_robots(1)), 1.0, 30) is None
    assert miner.process(_field_frame(_six_robots(6)), 6.0, 180) == "pseudo"

    images = sorted((tmp_path / "images" / "train").glob("*.jpg"))
    labels = sorted((tmp_path / "labels" / "train").glob("*.txt"))
    assert len(images) == len(labels) == 2

    lines = labels[0].read_text().strip().splitlines()
    assert len(lines) == 6
    for line in lines:
        parts = line.split()
        assert len(parts) == 5
        cls = int(parts[0])
        assert CLASSES[cls] in ("bumper-red", "bumper-blue")
        assert all(0.0 <= float(v) <= 1.0 for v in parts[1:])


def test_uncertain_frames_go_to_queue_with_prelabels(tmp_path):
    dets = [
        Detection(xyxy=(10, 10, 40, 30), conf=0.9, alliance="red"),
        Detection(xyxy=(100, 100, 130, 120), conf=0.4, alliance="blue"),  # weak
    ]
    miner = DatasetMiner(FakeDetector(dets), tmp_path, low_conf=0.55)
    frame = np.zeros((240, 320, 3), np.uint8)
    assert miner.process(frame, 3.0, 90) == "queued"

    (jpg,) = (tmp_path / "queue").glob("*.jpg")
    meta = json.loads(jpg.with_suffix(".json").read_text())
    assert meta["frame_index"] == 90
    assert len(meta["prelabels"]) == 2
    assert meta["prelabels"][1]["conf"] == pytest.approx(0.4)
    # nothing pseudo-labeled from an uncertain frame
    assert not list((tmp_path / "images" / "train").glob("*.jpg"))


def test_empty_frames_skipped(tmp_path):
    miner = DatasetMiner(FakeDetector([]), tmp_path)
    assert miner.process(np.zeros((240, 320, 3), np.uint8), 0.0, 0) is None
    assert miner.finalize()["frames_seen"] == 1


def test_finalize_writes_dataset_yaml(tmp_path):
    miner = DatasetMiner(ColorBlobDetector(), tmp_path)
    miner.process(_field_frame(_six_robots(0)), 0.0, 0)
    stats = miner.finalize()
    assert stats["pseudo_labeled"] == 1
    assert stats["by_class"]["bumper-red"] == 3
    yaml_text = (tmp_path / "dataset.yaml").read_text()
    assert "images/train" in yaml_text
    assert "bumper-blue" in yaml_text


def test_cli_dataset_mine(tmp_path, capsys):
    import cv2

    from frcscout.cli import main

    video = tmp_path / "field.avi"
    writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"MJPG"), 10, (320, 240))
    for t in range(30):
        writer.write(_field_frame(_six_robots(t * 0.5)))
    writer.release()

    out = tmp_path / "ds"
    assert main(["dataset", "mine", str(video), "--out", str(out),
                 "--fps", "2", "--pseudo-every", "1.0"]) == 0
    stdout = capsys.readouterr().out
    assert "pseudo_labeled" in stdout
    assert (out / "dataset.yaml").exists()
    assert list((out / "images" / "train").glob("*.jpg"))

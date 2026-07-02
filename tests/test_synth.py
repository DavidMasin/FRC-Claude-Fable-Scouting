from frcscout.dataset import CLASSES
from frcscout.dataset.synth import generate_synthetic_dataset
from frcscout.vision import ColorBlobDetector


def test_generate_synthetic_dataset(tmp_path):
    stats = generate_synthetic_dataset(tmp_path, n_images=20, seed=42)
    assert stats["train"] + stats["val"] == 20
    assert stats["val"] >= 1

    images = list((tmp_path / "images" / "train").glob("*.jpg"))
    labels = list((tmp_path / "labels" / "train").glob("*.txt"))
    assert len(images) == len(labels) == stats["train"]

    seen_classes = set()
    for label in labels:
        for line in label.read_text().splitlines():
            parts = line.split()
            assert len(parts) == 5
            cls = int(parts[0])
            assert 0 <= cls < len(CLASSES)
            seen_classes.add(CLASSES[cls])
            for v in parts[1:]:
                assert 0.0 <= float(v) <= 1.0
    # all four classes appear somewhere in 20 images
    assert seen_classes == set(CLASSES)
    assert "dataset.yaml" in [p.name for p in tmp_path.iterdir()]


def test_deterministic_with_seed(tmp_path):
    a = generate_synthetic_dataset(tmp_path / "a", n_images=5, seed=7)
    b = generate_synthetic_dataset(tmp_path / "b", n_images=5, seed=7)
    assert a["train"] == b["train"]
    for name in ("synth_00000.txt", "synth_00001.txt"):
        for split in ("train", "val"):
            pa = tmp_path / "a" / "labels" / split / name
            pb = tmp_path / "b" / "labels" / split / name
            assert pa.exists() == pb.exists()
            if pa.exists():
                assert pa.read_text() == pb.read_text()


def test_synthetic_frames_exercise_color_detector(tmp_path):
    """Sanity: the renderer's bumpers are findable by the HSV detector on at
    least some frames — the synthetic look isn't disconnected from the
    pipeline's own notion of a bumper."""
    generate_synthetic_dataset(tmp_path, n_images=10, seed=1)
    import cv2

    detector = ColorBlobDetector()
    hits = 0
    for img in (tmp_path / "images" / "train").glob("*.jpg"):
        if detector.detect(cv2.imread(str(img))):
            hits += 1
    assert hits >= 3


def test_cli_dataset_synth(tmp_path, capsys):
    from frcscout.cli import main

    assert main(["dataset", "synth", "--out", str(tmp_path / "ds"), "--n", "6"]) == 0
    out = capsys.readouterr().out
    assert "yolo detect train" in out
    assert (tmp_path / "ds" / "dataset.yaml").exists()

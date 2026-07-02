import numpy as np
import pytest

from frcscout.overlay.autodetect import autodetect_regions
from frcscout.overlay.ocr import TemplateDigitOCR
from frcscout.overlay.parse import read_overlay

W, H = 640, 360


def _broadcast_frame(timer: str, red: int, blue: int,
                     with_robots: bool = True) -> np.ndarray:
    import cv2

    frame = np.full((H, W, 3), 25, np.uint8)
    frame[80:] = (60, 130, 60)
    for text, x in ((str(red), 40), (timer, 275), (str(blue), 520)):
        cv2.putText(frame, text, (x, 40), cv2.FONT_HERSHEY_SIMPLEX,
                    0.9, (240, 240, 240), 2)
    if with_robots:
        # moving robots with bright bumper numbers: decoys the detector must reject
        x0 = 100 + (red * 13) % 200
        cv2.rectangle(frame, (x0, 200), (x0 + 90, 240), (30, 30, 220), -1)
        cv2.putText(frame, "5987", (x0 + 8, 230), cv2.FONT_HERSHEY_SIMPLEX,
                    0.7, (255, 255, 255), 2)
    return frame


@pytest.fixture(scope="module")
def sample_frames():
    # mid-teleop: timer counting down, scores creeping up
    script = [("1:45", 20, 12), ("1:43", 20, 14), ("1:41", 23, 14),
              ("1:39", 23, 14), ("1:37", 26, 17), ("1:35", 26, 17)]
    return [_broadcast_frame(t, r, b) for t, r, b in script]


def test_autodetect_finds_all_three_regions(sample_frames):
    regions = autodetect_regions(sample_frames, TemplateDigitOCR())
    assert set(regions) == {"match_timer", "red_score", "blue_score"}
    # red left of timer, blue right of timer
    assert regions["red_score"][0] < regions["match_timer"][0] < regions["blue_score"][0]
    # all boxes in the overlay bar, not down in the field
    for box in regions.values():
        assert box[1] + box[3] < 0.3


def test_autodetected_regions_actually_read(sample_frames):
    backend = TemplateDigitOCR()
    regions = autodetect_regions(sample_frames, backend)
    reading = read_overlay(_broadcast_frame("1:33", 29, 17), 0.0, regions, backend)
    assert reading.timer_s == 93.0
    assert (reading.red, reading.blue) == (29, 17)


def test_autodetect_needs_a_running_timer():
    frames = [_broadcast_frame("0:00", 0, 0) for _ in range(5)]
    with pytest.raises(ValueError, match="no decreasing match timer"):
        autodetect_regions(frames, TemplateDigitOCR())


def test_cli_overlay_autodetect(tmp_path, capsys):
    import cv2

    from frcscout.cli import main

    video = tmp_path / "clip.avi"
    writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"MJPG"), 2, (W, H))
    for i in range(30):
        remaining = 120 - i // 2
        writer.write(_broadcast_frame(f"{remaining // 60}:{remaining % 60:02d}",
                                      10 + i // 3, 8 + i // 4))
    writer.release()

    assert main(["overlay", "autodetect", str(video), "--frames", "5",
                 "--spacing", "2"]) == 0
    out = capsys.readouterr().out
    assert "match_timer" in out and "red_score" in out and "blue_score" in out

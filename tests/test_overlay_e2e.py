"""End-to-end milestone 4: render a synthetic broadcast with a burned-in
FMS-style overlay (timer + scores), then run `frcscout overlay read` on it and
check the reconstructed phase timeline and final score."""

import numpy as np
import pytest

REGIONS = {
    "red_score":   [0.05, 0.03, 0.14, 0.12],
    "match_timer": [0.42, 0.03, 0.16, 0.12],
    "blue_score":  [0.80, 0.03, 0.14, 0.12],
}
W, H, FPS = 640, 360, 2

AUTO_S, TELEOP_S = 20, 140
# (video-time span, timer formatter, red score, blue score)
#   pre-match 2s -> auto 20s -> between 3s -> teleop 140s -> post 3s


def _timer_text(t: float) -> str:
    if t < 2:
        return "0:20"
    if t < 22:  # auto
        remaining = AUTO_S - int(t - 2)
        return f"0:{remaining:02d}"
    if t < 25:  # between periods
        return "0:00"
    if t < 165:  # teleop
        remaining = TELEOP_S - int(t - 25)
        return f"{remaining // 60}:{remaining % 60:02d}"
    return "0:00"


def _scores(t: float) -> tuple[int, int]:
    match_t = None
    if 2 <= t < 22:
        match_t = t - 2
    elif t >= 25:
        match_t = AUTO_S + (t - 25) if t < 165 else AUTO_S + TELEOP_S
    if match_t is None:
        return 0, 0
    red = 0
    if match_t >= 10:
        red += 12          # auto fuel burst
    if match_t >= 145:
        red += 20          # endgame climb
    blue = 25 if match_t >= 60 else 0
    return red, blue


@pytest.fixture(scope="module")
def broadcast_video(tmp_path_factory):
    import cv2

    path = tmp_path_factory.mktemp("broadcast") / "match.avi"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), FPS, (W, H))
    assert writer.isOpened()
    total_frames = 168 * FPS
    for i in range(total_frames):
        t = i / FPS
        frame = np.full((H, W, 3), 25, np.uint8)
        frame[80:] = (60, 90, 60)  # fake field area
        red, blue = _scores(t)
        for text, x in ((str(red), 40), (_timer_text(t), 275), (str(blue), 520)):
            cv2.putText(frame, text, (x, 40), cv2.FONT_HERSHEY_SIMPLEX,
                        0.9, (240, 240, 240), 2)
        writer.write(frame)
    writer.release()
    return str(path)


def test_overlay_read_cli_end_to_end(broadcast_video, tmp_path, capsys):
    import yaml

    from frcscout.cli import main

    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump({
        "overlay": {"regions": REGIONS, "ocr_backend": "template"},
        "rubric_path": str(tmp_path / "absent.json"),  # defaults: 20/140/30
    }))

    rc = main(["overlay", "read", broadcast_video, "--config", str(config),
               "--fps", "2", "--expect-final", "32:25"])
    out = capsys.readouterr().out
    assert rc == 0, out

    phase_lines = [line for line in out.splitlines() if "phase ->" in line]
    phases = [line.split("phase -> ")[1] for line in phase_lines]
    assert phases == ["auto", "between_periods", "teleop", "endgame", "post_match"]

    assert "red +12 -> 12" in out
    assert "blue +25 -> 25" in out
    assert "red +20 -> 32" in out
    assert "final: red 32 - blue 25" in out
    assert "scoreboard cross-check: OK" in out

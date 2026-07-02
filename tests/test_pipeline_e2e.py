"""Full-pipeline end-to-end test: a synthetic broadcast with an FMS overlay
AND six numbered robots moving through zones, scouted by `frcscout scout`.

Scripted match (default rubric timing: auto 20s / teleop 140s / endgame 30s;
video = 2s pre-match + auto + 3s between + teleop + 3s post):

- red 1690 parks in the red hub zone; red +12 during auto -> its fuel
- blue 5987 parks in the blue hub zone; blue +25 at match_t 60 -> its fuel
- red 2630 drives loading zone -> hub zone (one cycle)
- red 1690 drives to the red tower for endgame; red +20 at match_t 145
  -> climb_level_2 for 1690
"""

import json

import numpy as np
import pytest

from frcscout.schedule.model import lineup_from_alliances

W, H, FPS = 640, 360, 2
RED = [1690, 2630, 3339]
BLUE = [5987, 1577, 4590]
LINEUP = lineup_from_alliances("2026isde1_qm14", "2026isde1", "tba", RED, BLUE)

REGIONS = {
    "red_score":   [0.05, 0.03, 0.14, 0.12],
    "match_timer": [0.42, 0.03, 0.16, 0.12],
    "blue_score":  [0.80, 0.03, 0.14, 0.12],
}
# field occupies the frame below the overlay bar (y >= 100 px)
CALIBRATION = {
    "image_points": [[0, 100], [640, 100], [640, 360], [0, 360]],
    "field_points": [[0, 0], [16.54, 0], [16.54, 8.07], [0, 8.07]],
}
ZONES = {
    "hub_zone_red":      [[0, 2], [4.5, 2], [4.5, 6.5], [0, 6.5]],
    "hub_zone_blue":     [[12, 2], [16.54, 2], [16.54, 6.5], [12, 6.5]],
    "tower_zone_red":    [[0, 0], [3.5, 0], [3.5, 2], [0, 2]],
    "loading_zone_red":  [[13.5, 0], [16.54, 0], [16.54, 2], [13.5, 2]],
    "neutral_zone":      [[5.5, 0], [11, 0], [11, 8.07], [5.5, 8.07]],
}

AUTO_S, TELEOP_S = 20, 140
T_AUTO0, T_TELEOP0 = 2.0, 25.0  # video times
T_END = T_TELEOP0 + TELEOP_S


def _match_t(t):
    if T_AUTO0 <= t < T_AUTO0 + AUTO_S:
        return t - T_AUTO0
    if t >= T_TELEOP0:
        return AUTO_S + min(t - T_TELEOP0, TELEOP_S)
    return None


def _timer_text(t):
    if t < T_AUTO0:
        return "0:20"
    if t < T_AUTO0 + AUTO_S:
        return f"0:{AUTO_S - int(t - T_AUTO0):02d}"
    if t < T_TELEOP0:
        return "0:00"
    if t < T_END:
        remaining = TELEOP_S - int(t - T_TELEOP0)
        return f"{remaining // 60}:{remaining % 60:02d}"
    return "0:00"


def _scores(t):
    mt = _match_t(t)
    if mt is None:
        return (0, 0) if t < T_AUTO0 else _scores(T_AUTO0 + AUTO_S - 0.01)
    red = (12 if mt >= 10 else 0) + (20 if mt >= 145 else 0)
    blue = 25 if mt >= 60 else 0
    return red, blue


def _px(fx, fy):
    """field meters -> pixel ground point."""
    return 640 * fx / 16.54, 100 + 260 * fy / 8.07


def _lerp(a, b, frac):
    return a + (b - a) * max(0.0, min(1.0, frac))


def _robot_positions(t):
    """(team, alliance, field_xy) for all six robots at video time t."""
    mt = _match_t(t)
    mt = mt if mt is not None else (0 if t < T_AUTO0 else AUTO_S)
    # 1690: hub zone, then drives to the tower zone during t in [130, 140]
    x1690 = (_lerp(2.5, 1.5, (mt - 130) / 10), _lerp(4.0, 1.0, (mt - 130) / 10))
    # 2630: neutral -> loading (mt 60..70) -> hub (mt 70..85) -> neutral
    if mt < 60:
        x2630 = (8.0, 6.5)
    elif mt < 70:
        x2630 = (_lerp(8.0, 15.0, (mt - 60) / 8), _lerp(6.5, 1.0, (mt - 60) / 8))
    elif mt < 85:
        x2630 = (_lerp(15.0, 2.5, (mt - 71) / 10), _lerp(1.0, 5.5, (mt - 71) / 10))
    else:
        x2630 = (7.0, 5.5)
    return [
        (1690, "red", x1690),
        (2630, "red", x2630),
        (3339, "red", (6.5, 2.0)),
        (5987, "blue", (14.0, 4.0)),
        (1577, "blue", (10.0, 6.5)),
        (4590, "blue", (10.0, 1.5)),
    ]


@pytest.fixture(scope="module")
def match_video(tmp_path_factory):
    import cv2

    path = tmp_path_factory.mktemp("match") / "match.avi"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), FPS, (W, H))
    assert writer.isOpened()
    for i in range(int((T_END + 3) * FPS)):
        t = i / FPS
        frame = np.full((H, W, 3), 25, np.uint8)
        frame[100:] = (60, 130, 60)
        red, blue = _scores(t)
        for text, x in ((str(red), 40), (_timer_text(t), 275), (str(blue), 520)):
            cv2.putText(frame, text, (x, 40), cv2.FONT_HERSHEY_SIMPLEX,
                        0.9, (240, 240, 240), 2)
        for team, alliance, (fx, fy) in _robot_positions(t):
            gx, gy = _px(fx, fy)
            x0, y0 = int(gx - 45), int(gy - 40)
            color = (30, 30, 220) if alliance == "red" else (210, 90, 20)
            cv2.rectangle(frame, (x0, y0), (x0 + 90, y0 + 40), color, -1)
            cv2.putText(frame, str(team), (x0 + 8, y0 + 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        writer.write(frame)
    writer.release()
    return str(path)


def test_scout_cli_end_to_end(match_video, tmp_path, capsys):
    import yaml

    from frcscout.cli import main
    from frcscout.rubric.build import build_rubric, write_rubric

    rubric, _ = build_rubric(None)
    rubric_path = write_rubric(rubric, tmp_path / "rubric.json")
    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump({
        "rubric_path": str(rubric_path),
        "overlay": {"regions": REGIONS, "ocr_backend": "template"},
        "field": {"size_m": [16.54, 8.07], "red_on_left": True,
                  "calibration": CALIBRATION, "zones": ZONES},
    }))
    lineup_path = tmp_path / "lineup.json"
    lineup_path.write_text(json.dumps(LINEUP.to_dict()))
    out_dir = tmp_path / "out"

    rc = main(["scout", match_video, "--config", str(config),
               "--lineup", str(lineup_path), "--fps", "2",
               "--out-dir", str(out_dir)])
    stdout = capsys.readouterr().out
    assert rc == 0, stdout

    record = json.loads((out_dir / "2026isde1_qm14.json").read_text())

    # overlay reconciliation: everything attributed, no mismatch
    assert record["alliances"]["red"]["overlay_final"] == 32
    assert record["alliances"]["blue"]["overlay_final"] == 25
    assert record["alliances"]["red"].get("flag") is None, record["alliances"]
    assert record["alliances"]["blue"].get("flag") is None

    robots = {r["team"]: r for r in record["robots"]}
    assert robots[1690]["auto"]["fuel_scored"] == 12
    assert robots[1690]["endgame"]["climb"] == "level_2"
    assert robots[1690]["endgame"]["success"] is True
    assert robots[5987]["teleop"]["fuel_scored"] == 25
    assert robots[5987]["alliance"] == "blue"
    assert len(robots[2630]["teleop"]["cycles"]) == 1
    for team in RED + BLUE:
        assert robots[team]["assignment_confidence"] > 0.5, \
            f"team {team}: {robots[team]['assignment_confidence']}"

    # incremental JSONL got the same events
    lines = (out_dir / "2026isde1_qm14_events.jsonl").read_text().splitlines()
    assert len(lines) == sum(len(r["events"]) for r in record["robots"]) \
        + len(record["unattributed_events"])

    csv_text = (out_dir / "2026isde1_qm14.csv").read_text()
    assert "1690" in csv_text and "level_2" in csv_text


def test_scout_zero_config_auto_mode(match_video, tmp_path):
    """No overlay regions, no homography, nothing measured: the pipeline
    auto-detects the overlay and falls back to pixel-band zones."""
    from frcscout.pipeline import ScoutingPipeline
    from frcscout.rubric.build import build_rubric

    rubric, _ = build_rubric(None)
    pipeline = ScoutingPipeline({}, rubric, LINEUP)  # empty config
    result = pipeline.run(match_video, sample_fps=2)
    record = result.record

    assert pipeline.regions, "overlay regions were not auto-detected"
    assert record["alliances"]["red"]["overlay_final"] == 32
    assert record["alliances"]["blue"]["overlay_final"] == 25
    assert record["alliances"]["red"].get("flag") is None
    assert record["alliances"]["blue"].get("flag") is None

    robots = {r["team"]: r for r in record["robots"]}
    assert robots[1690]["auto"]["fuel_scored"] == 12
    assert robots[1690]["endgame"]["climb"] == "level_2"
    assert robots[5987]["teleop"]["fuel_scored"] == 25
    assert len(robots[2630]["teleop"]["cycles"]) == 1
    for team in RED + BLUE:
        assert robots[team]["assignment_confidence"] > 0.5

import json

import numpy as np
import pytest

from frcscout.identify import TeamAssigner, digit_similarity, read_bumper
from frcscout.overlay.ocr import TemplateDigitOCR
from frcscout.schedule.model import lineup_from_alliances

RED = [1690, 2630, 3339]
BLUE = [5987, 1577, 4590]
LINEUP = lineup_from_alliances("2026isde1_qm14", "2026isde1", "tba", RED, BLUE)


class FakeTrack:
    def __init__(self, track_id, cx, cy, alliance):
        self.track_id = track_id
        self.center = (cx, cy)
        self.alliance = alliance


# ---- fuzzy digit matching -----------------------------------------------------

@pytest.mark.parametrize("read,team,expected", [
    ("5987", 5987, 1.0),
    ("598", 5987, 0.75),      # partial read still counts
    ("5887", 5987, 0.75),     # one bad digit
    ("1577", 5987, 0.25),     # different team: below the 0.5 evidence threshold
    ("", 5987, 0.0),
])
def test_digit_similarity(read, team, expected):
    assert digit_similarity(read, team) == pytest.approx(expected)


# ---- assignment logic -----------------------------------------------------------

def test_station_prior_seeds_left_to_right():
    assigner = TeamAssigner(LINEUP)
    tracks = [FakeTrack(1, 50, 60, "red"), FakeTrack(2, 150, 60, "red"),
              FakeTrack(3, 250, 60, "red"),
              FakeTrack(4, 60, 180, "blue"), FakeTrack(5, 160, 180, "blue"),
              FakeTrack(6, 260, 180, "blue")]
    assigner.seed_station_prior(tracks)
    a = assigner.assignments()
    assert [a[i].team for i in (1, 2, 3)] == RED
    assert [a[i].team for i in (4, 5, 6)] == BLUE
    assert all(0 < a[i].confidence < 0.9 for i in range(1, 7))  # prior only: not certain


def test_ocr_evidence_assigns_team():
    assigner = TeamAssigner(LINEUP)
    for _ in range(3):
        assigner.add_ocr(7, "blue", "5987", conf=0.9)
    a = assigner.assignments()[7]
    assert a.team == 5987
    assert a.confidence > 0.7


def test_single_noisy_read_cannot_flip_confident_assignment():
    assigner = TeamAssigner(LINEUP)
    for _ in range(4):
        assigner.add_ocr(1, "red", "1690", conf=0.9)
    assert assigner.assignments()[1].team == 1690
    # one misread suggesting a different red team
    assigner.add_ocr(1, "red", "2630", conf=0.6)
    a = assigner.assignments()[1]
    assert a.team == 1690
    assert a.confidence > 0.5


def test_repeated_contrary_evidence_does_flip():
    assigner = TeamAssigner(LINEUP)
    assigner.add_ocr(1, "red", "1690", conf=0.5)
    for _ in range(6):
        assigner.add_ocr(1, "red", "2630", conf=0.9)
    assert assigner.assignments()[1].team == 2630


def test_assignment_is_bijective_within_alliance():
    assigner = TeamAssigner(LINEUP)
    # both tracks read like 1690, one more convincingly
    for _ in range(3):
        assigner.add_ocr(1, "red", "1690", conf=0.9)
    assigner.add_ocr(2, "red", "1690", conf=0.4)
    assigner.add_ocr(2, "red", "2630", conf=0.4)
    a = assigner.assignments()
    assert a[1].team == 1690
    assert a[2].team == 2630          # bumped to its second-best, not duplicated
    teams = [x.team for x in a.values()]
    assert len(teams) == len(set(teams))


def test_unknown_track_gets_no_team():
    assigner = TeamAssigner(LINEUP)
    assigner.add_ocr(9, "blue", "8888", conf=0.9)  # matches nobody
    a = assigner.assignments()[9]
    assert a.team is None or a.confidence < 0.4


def test_team_labels_flag_low_confidence():
    assigner = TeamAssigner(LINEUP, min_conf=0.6)
    assigner.add_ocr(1, "red", "1690", conf=0.2)   # weak evidence
    for _ in range(4):
        assigner.add_ocr(2, "blue", "5987", conf=0.9)
    labels = assigner.team_labels()
    assert labels[1] == "1690?"
    assert labels[2] == "5987"


# ---- bumper OCR -----------------------------------------------------------------

def _robot_frame(number: str) -> np.ndarray:
    import cv2

    frame = np.full((120, 160, 3), (60, 130, 60), np.uint8)
    frame[40:80, 30:130] = (30, 30, 220)  # red bumper block
    cv2.putText(frame, number, (44, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                (255, 255, 255), 2)
    return frame


def test_read_bumper_full_box():
    digits, conf = read_bumper(_robot_frame("5987"), (30, 40, 130, 80),
                               TemplateDigitOCR(), band=(0.0, 1.0))
    assert digits == "5987"
    assert conf > 0.5


def test_read_bumper_too_small_returns_nothing():
    digits, conf = read_bumper(_robot_frame("5987"), (0, 0, 5, 4),
                               TemplateDigitOCR())
    assert (digits, conf) == ("", 0.0)


# ---- end-to-end CLI --------------------------------------------------------------

def test_cli_track_with_lineup_assigns_all_six(tmp_path, capsys):
    import cv2

    from frcscout.cli import main

    W, H = 640, 360
    video = tmp_path / "field.avi"
    writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"MJPG"), 10, (W, H))
    for t in range(50):
        frame = np.full((H, W, 3), (60, 130, 60), np.uint8)
        # red on top row (stations left->right), blue on bottom; slow drift
        for i, team in enumerate(RED):
            x = 40 + 200 * i + t
            frame[60:100, x:x + 90] = (30, 30, 220)
            cv2.putText(frame, str(team), (x + 8, 90), cv2.FONT_HERSHEY_SIMPLEX,
                        0.7, (255, 255, 255), 2)
        for i, team in enumerate(BLUE):
            x = 40 + 200 * i + (50 - t)
            frame[260:300, x:x + 90] = (210, 90, 20)
            cv2.putText(frame, str(team), (x + 8, 290), cv2.FONT_HERSHEY_SIMPLEX,
                        0.7, (255, 255, 255), 2)
        writer.write(frame)
    writer.release()

    lineup_json = tmp_path / "lineup.json"
    lineup_json.write_text(json.dumps(LINEUP.to_dict()))

    rc = main(["track", str(video), "--fps", "10", "--lineup", str(lineup_json)])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "confirmed tracks: 6 (red 3, blue 3, unknown 0)" in out
    for team in RED + BLUE:
        assert f" {team} " in out or f" {team}\n" in out or f": {team}" in out

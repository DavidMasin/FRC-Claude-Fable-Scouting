import numpy as np
import pytest

from frcscout.overlay.ocr import TemplateDigitOCR, get_backend
from frcscout.overlay.parse import OverlayReading, parse_score, parse_timer
from frcscout.overlay.regions import crop_region
from frcscout.overlay.timeline import (
    AUTO, BETWEEN, ENDGAME, POST_MATCH, TELEOP,
    OverlayTimeline, PhaseChange, ScoreChange,
)


# ---- parsing ---------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("2:07", 127.0), ("0:15", 15.0), ("15", 15.0), ("0:00", 0.0), ("140", 140.0),
    ("", None), ("2:73", None), ("ab", None), ("12:345", None),
])
def test_parse_timer(text, expected):
    assert parse_timer(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("0", 0), ("112", 112), (" 47 ", 47), ("", None), ("12a", None), ("5987", None),
])
def test_parse_score(text, expected):
    assert parse_score(text) == expected


def test_crop_region():
    frame = np.arange(100 * 200 * 3, dtype=np.uint8).reshape(100, 200, 3)
    crop = crop_region(frame, [0.5, 0.1, 0.25, 0.5])
    assert crop.shape == (50, 50, 3)
    with pytest.raises(ValueError):
        crop_region(frame, [1.2, 0, 0.1, 0.1])


# ---- template OCR -----------------------------------------------------------

def _render(text: str, invert=False) -> np.ndarray:
    import cv2

    img = np.full((40, 20 * len(text) + 20, 3), 255 if invert else 20, np.uint8)
    color = (10, 10, 10) if invert else (240, 240, 240)
    cv2.putText(img, text, (8, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.9, color, 2)
    return img


@pytest.mark.parametrize("text", ["0:15", "2:07", "112", "47", "0", "360"])
def test_template_ocr_roundtrip(text):
    ocr = TemplateDigitOCR()
    result = ocr.read_text(_render(text))
    assert result.text == text
    assert result.confidence > 0.6


def test_template_ocr_dark_on_light():
    assert TemplateDigitOCR().read_text(_render("128", invert=True)).text == "128"


def test_template_ocr_blank():
    result = TemplateDigitOCR().read_text(np.full((40, 80, 3), 30, np.uint8))
    assert result.text == "" and result.confidence == 0.0


def test_get_backend():
    assert get_backend("template").read_text(_render("7")).text == "7"
    with pytest.raises(ValueError, match="unknown OCR backend"):
        get_backend("nope")


# ---- timeline ---------------------------------------------------------------

def _feed(timeline, rows):
    """rows: (t, timer, red, blue)"""
    events = []
    for t, timer, red, blue in rows:
        events += timeline.add(OverlayReading(t_video=t, timer_s=timer, red=red, blue=blue))
    return events


def test_phase_progression_full_match():
    tl = OverlayTimeline(auto_s=20, teleop_s=140, endgame_s=30)
    rows = (
        [(i * 0.5, 20 - i * 0.5, 0, 0) for i in range(41)]        # auto 20 -> 0
        + [(21.0, 0, 0, 0), (21.5, 0, 0, 0)]                      # hold at 0
        + [(23 + i * 0.5, 140 - i * 0.5, 0, 0) for i in range(281)]  # teleop 140 -> 0
        + [(165.0, 0, 0, 0), (165.5, 0, 0, 0)]
    )
    _feed(tl, rows)
    phases = [e.phase for e in tl.events if isinstance(e, PhaseChange)]
    assert phases == [AUTO, BETWEEN, TELEOP, ENDGAME, POST_MATCH]


def test_match_time_mapping():
    tl = OverlayTimeline(auto_s=20, teleop_s=140, endgame_s=30)
    _feed(tl, [(0.0, 18, 0, 0)])
    assert tl.match_time() == pytest.approx(2.0)
    # timer restart needs consecutive agreeing reads
    _feed(tl, [(30.0, 135, 0, 0), (30.5, 134.5, 0, 0)])
    assert tl.match_time() == pytest.approx(25.5)


def test_single_timer_spike_does_not_advance_period():
    tl = OverlayTimeline(auto_s=20, teleop_s=140, endgame_s=30)
    # mid-teleop
    _feed(tl, [(30.0, 100, 0, 0), (30.5, 99.5, 0, 0)])
    assert tl.phase == TELEOP
    # one '0:07'-as-'2:07'-style spike, then sane reads again
    _feed(tl, [(31.0, 127, 0, 0), (31.5, 99, 0, 0), (32.0, 98.5, 0, 0)])
    assert tl.phase == TELEOP
    assert tl.match_time() == pytest.approx(20 + 140 - 98.5)


def test_joining_mid_match_lands_in_teleop():
    tl = OverlayTimeline()
    _feed(tl, [(0.0, 95, 12, 30)])
    assert tl.phase == TELEOP


def test_score_needs_two_consecutive_reads():
    tl = OverlayTimeline()
    events = _feed(tl, [(0, 15, 0, 0), (1, 14, 3, 0)])
    assert not [e for e in events if isinstance(e, ScoreChange)]
    events = _feed(tl, [(2, 13, 3, 0)])
    (change,) = [e for e in events if isinstance(e, ScoreChange)]
    assert (change.alliance, change.delta, change.total) == ("red", 3, 3)
    assert change.t_video == 1  # stamped at first sighting


def test_ocr_spike_rejected():
    tl = OverlayTimeline()
    _feed(tl, [(0, 15, 5, 0), (1, 14, 5, 0)])
    assert tl.scores["red"] == 5
    # a single misread '58' between good reads never confirms
    events = _feed(tl, [(2, 13, 58, 0), (3, 12, 5, 0), (4, 11, 5, 0)])
    assert not [e for e in events if isinstance(e, ScoreChange)]
    assert tl.scores["red"] == 5


def test_huge_jump_needs_more_reads():
    # large but physically possible (<= hard_max_delta): extra reads confirm it
    tl = OverlayTimeline(max_plausible_delta=30, hard_max_delta=50)
    events = _feed(tl, [(t, 100 - t, 45, 0) for t in range(4)])
    changes = [e for e in events if isinstance(e, ScoreChange)]
    assert len(changes) == 1 and changes[0].total == 45  # 4 reads confirm it


def test_impossible_delta_rejected_and_counted():
    """A wrong OCR region reading a team/match number as 'score' must never
    become an event, no matter how consistently it reads (the flta ×132)."""
    tl = OverlayTimeline(hard_max_delta=50)
    events = _feed(tl, [(t, 15 - t, 132, 0) for t in range(8)])
    assert [e for e in events if isinstance(e, ScoreChange)] == []
    assert tl.scores["red"] == 0
    assert tl.suspect_deltas["red"] >= 1
    # sane readings afterwards still work
    events = _feed(tl, [(9, 6, 4, 0), (10, 5, 4, 0)])
    (change,) = [e for e in events if isinstance(e, ScoreChange)]
    assert change.total == 4


def test_oscillating_region_gets_suppressed():
    """Region alternates reading '9' and '49' (neighboring digit caught
    intermittently): after max_corrections bounces, no more phantom fuel
    events — but the running total stays honest (the flta ×126 case)."""
    tl = OverlayTimeline()
    events = []
    value = 9
    for cycle in range(12):
        base_t = cycle * 20
        events += _feed(tl, [(base_t + i, 100, value, 0) for i in range(4)])
        value = 49 if value == 9 else 9
    changes = [e for e in events if isinstance(e, ScoreChange)]
    # the first bounces get through, then suppression kicks in for good
    assert 0 < len(changes) <= 7
    assert changes[-1].t_video < 8 * 20  # nothing emitted in the later cycles
    assert tl.corrections["red"] >= tl.max_corrections
    assert tl.suspect_deltas["red"] > 0
    assert tl.scores["red"] in (9, 49)  # total still tracks the readings


def test_score_correction_downward():
    tl = OverlayTimeline()
    _feed(tl, [(0, 100, 20, 0), (1, 99, 20, 0)])
    events = _feed(tl, [(t + 2, 97 - t, 16, 0) for t in range(4)])
    (change,) = [e for e in events if isinstance(e, ScoreChange)]
    assert change.kind == "correction" and change.delta == -4 and tl.scores["red"] == 16


def test_dropouts_are_harmless():
    tl = OverlayTimeline()
    events = _feed(tl, [(0, 15, 0, 0), (1, None, None, None), (2, 13, 4, 4), (3, 12, 4, 4)])
    changes = [e for e in events if isinstance(e, ScoreChange)]
    assert {(c.alliance, c.total) for c in changes} == {("red", 4), ("blue", 4)}


def test_from_rubric():
    from frcscout.rubric.seed import seed_rubric

    tl = OverlayTimeline.from_rubric(seed_rubric())
    assert (tl.auto_s, tl.teleop_s, tl.endgame_s) == (20, 140, 30)

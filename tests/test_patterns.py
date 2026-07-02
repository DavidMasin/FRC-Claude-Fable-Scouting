"""Every extraction spec must find its value in the manual-style fixture.

The fixture mirrors the manual's published phrasing; if the real manual text
differs, update pattern + fixture together so this suite stays the contract.
"""

import pytest

from frcscout.rubric.patterns import MANUAL_VERSION_PATTERN, SPECS

EXPECTED = {
    ("match_timing", "auto_s"): 20,
    ("match_timing", "teleop_s"): 140,
    ("match_timing", "endgame_s"): 30,
    ("scoring", "fuel_hub_auto", "points"): 1,
    ("scoring", "fuel_hub_teleop", "points"): 1,
    ("scoring", "tower_level_1_auto", "points"): 15,
    ("scoring", "tower_level_1_teleop", "points"): 10,
    ("scoring", "tower_level_2_teleop", "points"): 20,
    ("scoring", "tower_level_3_teleop", "points"): 30,
    ("ranking_points", "energized", "threshold"): 100,
    ("ranking_points", "supercharged", "threshold"): 360,
    ("ranking_points", "traversal", "threshold"): 50,
    ("ranking_points", "win", "ranking_points"): 3,
    ("ranking_points", "tie", "ranking_points"): 1,
}


def test_every_spec_has_an_expectation():
    assert {s.path for s in SPECS} == set(EXPECTED)


@pytest.mark.parametrize("spec", SPECS, ids=lambda s: ".".join(s.path))
def test_spec_extracts_expected_value(spec, manual_text):
    hit = spec.extract(manual_text)
    assert hit is not None, f"no pattern matched for {'.'.join(spec.path)}"
    value, _pattern = hit
    assert value == EXPECTED[spec.path]


def test_spec_returns_none_on_unrelated_text():
    for spec in SPECS:
        assert spec.extract("nothing about the game in here") is None


def test_manual_version_detected(manual_text):
    m = MANUAL_VERSION_PATTERN.search(manual_text)
    assert m and m.group(1) == "TU22"

import pytest

from frcscout.aggregate import build_match_record, write_csv, write_json
from frcscout.events.model import ScoutingEvent
from frcscout.rubric.seed import seed_rubric
from frcscout.schedule.model import lineup_from_alliances

RED = [1690, 2630, 3339]
BLUE = [5987, 1577, 4590]
LINEUP = lineup_from_alliances("2026isde1_qm14", "2026isde1", "tba", RED, BLUE)


def _ev(t, type_, team=None, alliance="red", count=1, points=None,
        conf=0.85, match_t=None, flags=()):
    return ScoutingEvent(t_video=t, type=type_, match_time_s=match_t if match_t is not None else t,
                         alliance=alliance, team=team, track_id=1,
                         count=count, points=points, conf=conf, flags=tuple(flags))


def _record(events, finals=None, confs=None):
    return build_match_record("2026isde1_qm14", LINEUP, events,
                              confs or {t: 0.9 for t in RED + BLUE},
                              finals or {"red": 0, "blue": 0},
                              seed_rubric(), match_end_t=160.0)


def test_auto_teleop_fuel_split():
    events = [
        _ev(12.0, "fuel_scored", team=1690, count=6, points=6, match_t=12.0),
        _ev(60.0, "fuel_scored", team=1690, count=15, points=15, match_t=60.0),
        _ev(90.0, "fuel_scored", team=1690, count=6, points=6, match_t=90.0),
    ]
    record = _record(events, finals={"red": 27, "blue": 0})
    robot = next(r for r in record["robots"] if r["team"] == 1690)
    assert robot["auto"]["fuel_scored"] == 6
    assert robot["teleop"]["fuel_scored"] == 21
    assert record["alliances"]["red"].get("flag") is None


def test_cycles_paired_and_averaged():
    events = [
        _ev(40.0, "cycle_start", team=2630), _ev(52.0, "cycle_end", team=2630),
        _ev(60.0, "cycle_start", team=2630), _ev(70.0, "cycle_end", team=2630),
        _ev(150.0, "cycle_start", team=2630),  # unfinished at match end
    ]
    robot = next(r for r in _record(events)["robots"] if r["team"] == 2630)
    assert len(robot["teleop"]["cycles"]) == 2
    assert robot["teleop"]["avg_cycle_s"] == pytest.approx(11.0)


def test_endgame_climb_record():
    events = [
        _ev(141.3, "climb_attempt_start", team=5987, alliance="blue", conf=0.7),
        _ev(150.0, "climb_level_2", team=5987, alliance="blue", points=20),
    ]
    robot = next(r for r in _record(events)["robots"] if r["team"] == 5987)
    assert robot["endgame"] == {
        "climb": "level_2", "climb_start_t": 141.3,
        "attempted": True, "success": True,
    }


def test_failed_climb_attempt():
    events = [_ev(141.0, "climb_attempt_start", team=5987, alliance="blue")]
    robot = next(r for r in _record(events)["robots"] if r["team"] == 5987)
    assert robot["endgame"]["attempted"] is True
    assert robot["endgame"]["success"] is False
    assert robot["endgame"]["climb"] is None


def test_defense_seconds_summed():
    events = [
        _ev(30.0, "defense_start", team=3339), _ev(42.0, "defense_end", team=3339),
        _ev(90.0, "defense_start", team=3339), _ev(95.5, "defense_end", team=3339),
    ]
    robot = next(r for r in _record(events)["robots"] if r["team"] == 3339)
    assert robot["defense_played_s"] == pytest.approx(17.5)


def test_scoreboard_mismatch_flags_alliance():
    events = [_ev(60.0, "fuel_scored", team=1690, count=10, points=10)]
    record = _record(events, finals={"red": 14, "blue": 0})
    assert record["alliances"]["red"]["flag"] == "overlay_score_mismatch"
    assert record["alliances"]["red"]["vision_attributed_points"] == 10
    for robot in record["robots"]:
        if robot["alliance"] == "red":
            assert "overlay_score_mismatch" in robot["flags"]
        else:
            assert "overlay_score_mismatch" not in robot["flags"]


def test_unattributed_events_surface():
    events = [_ev(60.0, "fuel_scored", team=None, count=3, points=3,
                  conf=0.3, flags=["no_robot_in_zone"])]
    record = _record(events, finals={"red": 3, "blue": 0})
    assert len(record["unattributed_events"]) == 1
    assert record["alliances"]["red"]["unattributed_events"] == 1
    # unattributed points still count toward the alliance reconciliation
    assert record["alliances"]["red"].get("flag") is None


def test_low_confidence_flag():
    events = [_ev(60.0, "fuel_scored", team=1690, count=2, points=2, conf=0.5,
                  flags=["ambiguous_attribution"])]
    robot = next(r for r in _record(events)["robots"] if r["team"] == 1690)
    assert "low_confidence_events" in robot["flags"]
    assert "ambiguous_attribution" in robot["flags"]


def test_exports(tmp_path):
    events = [
        _ev(12.0, "fuel_scored", team=1690, count=6, points=6),
        _ev(150.0, "climb_level_3", team=1690, points=30),
    ]
    record = _record(events, finals={"red": 36, "blue": 0})
    json_path = write_json(record, tmp_path / "match.json")
    csv_path = write_csv(record, tmp_path / "match.csv")

    import csv as csv_mod
    import json as json_mod

    saved = json_mod.loads(json_path.read_text())
    assert saved["match_key"] == "2026isde1_qm14"
    assert len(saved["robots"]) == 6

    with csv_path.open() as fh:
        rows = list(csv_mod.DictReader(fh))
    assert len(rows) == 6
    row = next(r for r in rows if r["team"] == "1690")
    assert row["auto_fuel"] == "6"
    assert row["endgame_climb"] == "level_3"
    assert row["climb_success"] == "True"

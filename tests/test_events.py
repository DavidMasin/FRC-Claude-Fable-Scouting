import pytest

from frcscout.events import EventEngine, FrameContext, TrackSnapshot
from frcscout.overlay.timeline import ScoreChange
from frcscout.rubric.seed import seed_rubric


def _snap(tid, alliance, team=None, zones=(), xy=(8.0, 4.0)):
    return TrackSnapshot(track_id=tid, alliance=alliance, team=team,
                         xyxy=(0, 0, 10, 10), field_xy=xy,
                         zones=frozenset(zones))


def _ctx(t, phase, tracks, changes=(), match_t=None):
    return FrameContext(t_video=t, frame_index=int(t * 30), phase=phase,
                        match_time_s=match_t if match_t is not None else t,
                        tracks=list(tracks), score_changes=list(changes))


def _engine(**kwargs):
    return EventEngine(seed_rubric(), **kwargs)


# ---- fuel attribution --------------------------------------------------------

def test_single_candidate_high_confidence():
    engine = _engine()
    robot = _snap(1, "red", team=1690, zones={"hub_zone_red"}, xy=(1.5, 4.0))
    other = _snap(2, "red", team=2630, zones={"neutral_zone"})
    engine.step(_ctx(10.0, "teleop", [robot, other]))
    events = engine.step(_ctx(10.5, "teleop", [robot, other],
                              [ScoreChange(t_video=10.5, alliance="red", delta=3, total=3)]))
    (ev,) = events
    assert ev.type == "fuel_scored"
    assert (ev.team, ev.track_id) == (1690, 1)
    assert ev.count == 3           # 1 point per fuel
    assert ev.conf == pytest.approx(0.85)
    assert "ambiguous_attribution" not in ev.flags


def test_ambiguous_attribution_flagged_and_most_recent_wins():
    engine = _engine()
    r1 = _snap(1, "red", team=1690, zones={"hub_zone_red"})
    r2_out = _snap(2, "red", team=2630, zones={"neutral_zone"})
    r2_in = _snap(2, "red", team=2630, zones={"hub_zone_red"})
    engine.step(_ctx(10.0, "teleop", [r1, r2_out]))
    engine.step(_ctx(11.0, "teleop", [r1, r2_in]))  # r2 arrives later
    events = engine.step(_ctx(11.5, "teleop", [r1, r2_in],
                              [ScoreChange(t_video=11.5, alliance="red", delta=5, total=5)]))
    (ev,) = events
    assert ev.track_id == 2
    assert ev.conf == pytest.approx(0.5)
    assert "ambiguous_attribution" in ev.flags


def test_vlm_resolves_ambiguity():
    class FakeVlm:
        def choose_scorer(self, candidates, context):
            assert set(candidates) == {1, 2}
            return 1, 0.9

    engine = _engine(vlm=FakeVlm())
    r1 = _snap(1, "red", team=1690, zones={"hub_zone_red"})
    r2 = _snap(2, "red", team=2630, zones={"hub_zone_red"})
    engine.step(_ctx(10.0, "teleop", [r1, r2]))
    events = engine.step(_ctx(10.5, "teleop", [r1, r2],
                              [ScoreChange(t_video=10.5, alliance="red", delta=2, total=2)]))
    (ev,) = events
    assert (ev.track_id, ev.source, ev.conf) == (1, "vlm", 0.9)


def test_no_candidate_is_flagged_not_fabricated():
    engine = _engine()
    away = _snap(1, "red", team=1690, zones={"neutral_zone"})
    events = engine.step(_ctx(10.0, "teleop", [away],
                              [ScoreChange(t_video=10.0, alliance="red", delta=4, total=4)]))
    (ev,) = events
    assert ev.track_id is None and ev.team is None
    assert "no_robot_in_zone" in ev.flags
    assert ev.conf == pytest.approx(0.3)


def test_wrong_alliance_robot_never_credited():
    engine = _engine()
    blue_in_red_zone = _snap(9, "blue", team=5987, zones={"hub_zone_red"})
    events = engine.step(_ctx(10.0, "teleop", [blue_in_red_zone],
                              [ScoreChange(t_video=10.0, alliance="red", delta=2, total=2)]))
    (ev,) = events
    assert ev.track_id is None
    assert "no_robot_in_zone" in ev.flags


def test_score_correction_becomes_observation():
    engine = _engine()
    events = engine.step(_ctx(50.0, "teleop", [],
                              [ScoreChange(t_video=50.0, alliance="blue", delta=-4,
                                           total=20, kind="correction")]))
    (ev,) = events
    assert ev.type == "score_correction"
    assert ev.count == 4


def test_points_unverified_flag_from_seed_rubric():
    engine = _engine()
    robot = _snap(1, "red", team=1690, zones={"hub_zone_red"})
    engine.step(_ctx(10.0, "teleop", [robot]))
    (ev,) = engine.step(_ctx(10.5, "teleop", [robot],
                             [ScoreChange(t_video=10.5, alliance="red", delta=1, total=1)]))
    assert "points_unverified" in ev.flags  # seed rubric is unverified by design


# ---- endgame climbs ------------------------------------------------------------

def test_endgame_tower_delta_becomes_climb_event():
    engine = _engine()
    climber = _snap(3, "blue", team=5987, zones={"tower_zone_blue"}, xy=(15.0, 7.0))
    engine.step(_ctx(150.0, "endgame", [climber]))
    events = engine.step(_ctx(150.5, "endgame", [climber],
                              [ScoreChange(t_video=150.5, alliance="blue", delta=20, total=60)]))
    climb = next(e for e in events if e.type == "climb_level_2")
    assert climb.team == 5987
    assert climb.points == 20


def test_endgame_fuel_delta_still_fuel_when_nobody_at_tower():
    engine = _engine()
    shooter = _snap(1, "red", team=1690, zones={"hub_zone_red"})
    engine.step(_ctx(150.0, "endgame", [shooter]))
    events = engine.step(_ctx(150.5, "endgame", [shooter],
                              [ScoreChange(t_video=150.5, alliance="red", delta=10, total=40)]))
    (ev,) = events
    assert ev.type == "fuel_scored"
    assert "endgame_delta_maybe_tower" in ev.flags


def test_climb_attempt_requires_dwell():
    engine = _engine()
    climber = _snap(3, "blue", team=5987, zones={"tower_zone_blue"})
    assert engine.step(_ctx(150.0, "endgame", [climber])) == []
    assert engine.step(_ctx(150.5, "endgame", [climber])) == []
    events = engine.step(_ctx(151.6, "endgame", [climber]))
    (ev,) = events
    assert ev.type == "climb_attempt_start"
    assert ev.t_video == pytest.approx(150.0)  # stamped at dwell start
    # and only once
    assert engine.step(_ctx(152.0, "endgame", [climber])) == []


def test_no_climb_attempt_outside_endgame():
    engine = _engine()
    climber = _snap(3, "blue", team=5987, zones={"tower_zone_blue"})
    for t in (10.0, 12.0, 14.0):
        assert engine.step(_ctx(t, "teleop", [climber])) == []


# ---- defense ----------------------------------------------------------------------

def test_defense_interval_detected():
    engine = _engine(defense_min_s=2.0, defense_dist_m=2.0)
    # red robot deep in blue half (x > 8.27), glued to a blue robot
    defender = _snap(1, "red", team=1690, xy=(12.0, 4.0))
    victim = _snap(4, "blue", team=5987, xy=(12.5, 4.0))
    events = []
    for t in (30.0, 31.0, 32.5):
        events += engine.step(_ctx(t, "teleop", [defender, victim]))
    (start,) = [e for e in events if e.type == "defense_start"]
    assert start.team == 1690 and start.t_video == pytest.approx(30.0)
    # defender drives away -> defense_end
    gone = _snap(1, "red", team=1690, xy=(4.0, 4.0))
    events = engine.step(_ctx(34.0, "teleop", [gone, victim]))
    (end,) = [e for e in events if e.type == "defense_end"]
    assert end.t_video == pytest.approx(34.0)


def test_brief_contact_is_not_defense():
    engine = _engine(defense_min_s=2.0)
    defender = _snap(1, "red", team=1690, xy=(12.0, 4.0))
    victim = _snap(4, "blue", team=5987, xy=(12.5, 4.0))
    events = engine.step(_ctx(30.0, "teleop", [defender, victim]))
    gone = _snap(1, "red", team=1690, xy=(4.0, 4.0))
    events += engine.step(_ctx(31.0, "teleop", [gone, victim]))
    assert [e for e in events if e.type.startswith("defense")] == []


def test_own_half_proximity_is_not_defense():
    engine = _engine()
    red_home = _snap(1, "red", team=1690, xy=(3.0, 4.0))   # red half (left)
    blue_visitor = _snap(4, "blue", team=5987, xy=(3.2, 4.0))
    for t in (30.0, 31.0, 33.5):
        events = engine.step(_ctx(t, "teleop", [red_home, blue_visitor]))
        assert [e for e in events if e.type == "defense_start" and e.track_id == 1] == []


# ---- cycles ---------------------------------------------------------------------------

def test_cycle_start_end():
    engine = _engine()
    loading = _snap(1, "red", team=1690, zones={"loading_zone_red"})
    transit = _snap(1, "red", team=1690, zones={"neutral_zone"})
    scoring = _snap(1, "red", team=1690, zones={"hub_zone_red"})
    events = engine.step(_ctx(40.0, "teleop", [loading]))
    assert [e.type for e in events] == ["cycle_start"]
    assert engine.step(_ctx(42.0, "teleop", [transit])) == []
    events = engine.step(_ctx(45.0, "teleop", [scoring]))
    assert [e.type for e in events] == ["cycle_end"]
    # re-entering the hub without reloading is not a new cycle
    assert engine.step(_ctx(47.0, "teleop", [scoring])) == []


def test_all_emitted_types_exist_in_rubric():
    rubric = seed_rubric()
    engine = EventEngine(rubric)
    robot = _snap(1, "red", team=1690, zones={"hub_zone_red"})
    engine.step(_ctx(10.0, "teleop", [robot]))
    engine.step(_ctx(10.5, "teleop", [robot],
                     [ScoreChange(t_video=10.5, alliance="red", delta=2, total=2)]))
    assert all(e.type in rubric["event_types"] for e in engine.events)

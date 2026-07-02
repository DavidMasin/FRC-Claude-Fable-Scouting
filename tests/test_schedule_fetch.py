import pytest

from frcscout.schedule import ScheduleError, fetch_lineup
from frcscout.schedule.model import LineupError, MatchLineup, RobotSlot, lineup_from_alliances

from test_schedule_providers import BLUE, RED, TBA_PAYLOAD, NEXUS_PAYLOAD, _config


def test_chain_prefers_tba(fake_session_cls, fake_response_cls):
    session = fake_session_cls({
        "/match/": fake_response_cls(200, TBA_PAYLOAD),
        "/event/": fake_response_cls(200, NEXUS_PAYLOAD),
    })
    lineup = fetch_lineup("2026isde1_qm14", _config(), session=session)
    assert lineup.source == "tba"


def test_chain_falls_back_when_tba_unconfigured(fake_session_cls, fake_response_cls):
    config = _config()
    config["apis"]["tba"]["auth_key"] = ""
    config["apis"]["frc_events"] = {}
    session = fake_session_cls({"/event/": fake_response_cls(200, NEXUS_PAYLOAD)})
    lineup = fetch_lineup("2026isde1_qm14", config, session=session)
    assert lineup.source == "nexus"
    assert lineup.teams("red") == RED


def test_chain_aggregates_all_errors(fake_session_cls):
    session = fake_session_cls({})  # every request 404s
    with pytest.raises(ScheduleError) as exc:
        fetch_lineup("2026isde1_qm14", _config(), session=session)
    msg = str(exc.value)
    assert "tba:" in msg and "frc_events:" in msg and "nexus:" in msg


def test_forced_provider_order(fake_session_cls, fake_response_cls):
    session = fake_session_cls({
        "/match/": fake_response_cls(200, TBA_PAYLOAD),
        "/event/": fake_response_cls(200, NEXUS_PAYLOAD),
    })
    lineup = fetch_lineup("2026isde1_qm14", _config(), session=session,
                          providers=("nexus",))
    assert lineup.source == "nexus"


def test_bad_match_key_raises_immediately():
    with pytest.raises(ValueError, match="unrecognized match key"):
        fetch_lineup("garbage", _config(), session=None, providers=())


# ---- lineup model invariants ----------------------------------------------

def test_lineup_helpers():
    lineup = lineup_from_alliances("2026isde1_qm14", "2026isde1", "tba", RED, BLUE)
    assert lineup.teams("blue") == BLUE
    assert lineup.slot_for_team(2630) == RobotSlot(team=2630, alliance="red", station=2)
    assert lineup.to_dict()["red"] == RED
    with pytest.raises(KeyError):
        lineup.slot_for_team(9999)


@pytest.mark.parametrize("red,blue,msg", [
    (RED, BLUE[:2], "expected 6 slots"),
    (RED, [5987, 1577, 1690], "duplicate team"),
    (RED, [5987, 1577, 0], "implausible team"),
])
def test_lineup_invariants(red, blue, msg):
    with pytest.raises(LineupError, match=msg):
        lineup_from_alliances("2026isde1_qm14", "2026isde1", "tba", red, blue)


def test_lineup_station_coverage_enforced():
    slots = tuple(RobotSlot(team=t, alliance="red", station=1) for t in RED) + \
            tuple(RobotSlot(team=t, alliance="blue", station=i + 1) for i, t in enumerate(BLUE))
    with pytest.raises(LineupError, match="stations"):
        MatchLineup("2026isde1_qm14", "2026isde1", slots, "tba")

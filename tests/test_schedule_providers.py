import pytest

from frcscout.schedule import frc_events, nexus, tba
from frcscout.schedule.errors import ScheduleError
from frcscout.schedule.matchkey import parse_match_key

MK = parse_match_key("2026isde1_qm14")

RED = [1690, 2630, 3339]
BLUE = [5987, 1577, 4590]

TBA_PAYLOAD = {
    "key": "2026isde1_qm14",
    "alliances": {
        "red": {"team_keys": [f"frc{t}" for t in RED]},
        "blue": {"team_keys": [f"frc{t}" for t in BLUE]},
    },
}

FRC_EVENTS_PAYLOAD = {
    "Schedule": [{
        "matchNumber": 14,
        "teams": [
            {"teamNumber": t, "station": f"Red{i+1}"} for i, t in enumerate(RED)
        ] + [
            {"teamNumber": t, "station": f"Blue{i+1}"} for i, t in enumerate(BLUE)
        ],
    }]
}

NEXUS_PAYLOAD = {
    "matches": [
        {"label": "Qualification 13", "redTeams": ["1", "2", "3"], "blueTeams": ["4", "5", "6"]},
        {"label": "Qualification 14",
         "redTeams": [str(t) for t in RED], "blueTeams": [str(t) for t in BLUE]},
    ]
}


def _config():
    return {"apis": {
        "tba": {"auth_key": "k"},
        "frc_events": {"username": "u", "auth_token": "t"},
        "nexus": {"api_key": "n"},
    }}


# ---- TBA ----------------------------------------------------------------

def test_tba_lineup(fake_session_cls, fake_response_cls):
    session = fake_session_cls({"/match/2026isde1_qm14": fake_response_cls(200, TBA_PAYLOAD)})
    lineup = tba.get_lineup(MK, _config(), session)
    assert lineup.source == "tba"
    assert lineup.teams("red") == RED
    assert lineup.teams("blue") == BLUE
    assert lineup.slot_for_team(5987).station == 1
    assert session.requests[0]["headers"]["X-TBA-Auth-Key"] == "k"


def test_tba_404_means_no_schedule(fake_session_cls):
    session = fake_session_cls({})
    with pytest.raises(ScheduleError, match="not found"):
        tba.get_lineup(MK, _config(), session)


def test_tba_requires_key(fake_session_cls):
    with pytest.raises(ScheduleError, match="auth_key"):
        tba.get_lineup(MK, {"apis": {}}, fake_session_cls({}))


def test_tba_rejects_malformed_payload(fake_session_cls, fake_response_cls):
    session = fake_session_cls({"/match/": fake_response_cls(200, {"alliances": {}})})
    with pytest.raises(ScheduleError, match="malformed"):
        tba.get_lineup(MK, _config(), session)


# ---- FRC Events ----------------------------------------------------------

def test_frc_events_lineup(fake_session_cls, fake_response_cls):
    session = fake_session_cls({"/2026/schedule/ISDE1": fake_response_cls(200, FRC_EVENTS_PAYLOAD)})
    lineup = frc_events.get_lineup(MK, _config(), session)
    assert lineup.source == "frc_events"
    assert lineup.teams("red") == RED
    assert lineup.teams("blue") == BLUE
    req = session.requests[0]
    assert req["auth"] == ("u", "t")
    assert req["params"] == {"tournamentLevel": "Qualification", "start": 14, "end": 14}


def test_frc_events_playoff_mapping(fake_session_cls, fake_response_cls):
    payload = {"Schedule": [dict(FRC_EVENTS_PAYLOAD["Schedule"][0], matchNumber=15)]}
    session = fake_session_cls({"/schedule/": fake_response_cls(200, payload)})
    mk = parse_match_key("2026isde1_f1m2")
    lineup = frc_events.get_lineup(mk, _config(), session)
    assert lineup.teams("red") == RED
    assert session.requests[0]["params"]["tournamentLevel"] == "Playoff"
    assert session.requests[0]["params"]["start"] == 15


def test_frc_events_event_code_override(fake_session_cls, fake_response_cls):
    config = _config()
    config["apis"]["frc_events"]["event_code_overrides"] = {"2026isde1": "ILDE1"}
    session = fake_session_cls({"/2026/schedule/ILDE1": fake_response_cls(200, FRC_EVENTS_PAYLOAD)})
    assert frc_events.get_lineup(MK, config, session).teams("red") == RED


def test_frc_events_match_missing(fake_session_cls, fake_response_cls):
    session = fake_session_cls({"/schedule/": fake_response_cls(200, {"Schedule": []})})
    with pytest.raises(ScheduleError, match="not in schedule"):
        frc_events.get_lineup(MK, _config(), session)


# ---- Nexus ----------------------------------------------------------------

def test_nexus_lineup(fake_session_cls, fake_response_cls):
    session = fake_session_cls({"/event/2026isde1": fake_response_cls(200, NEXUS_PAYLOAD)})
    lineup = nexus.get_lineup(MK, _config(), session)
    assert lineup.source == "nexus"
    assert lineup.teams("red") == RED
    assert lineup.teams("blue") == BLUE
    assert session.requests[0]["headers"]["Nexus-Api-Key"] == "n"


def test_nexus_missing_label(fake_session_cls, fake_response_cls):
    session = fake_session_cls({"/event/": fake_response_cls(200, {"matches": []})})
    with pytest.raises(ScheduleError, match="no match labeled"):
        nexus.get_lineup(MK, _config(), session)

import pytest

from frcscout.integrations import epa_crosscheck, push_match
from frcscout.integrations.galaxia import IntegrationError

RECORD = {
    "match_key": "2026isde1_qm14",
    "robots": [
        {"team": 1690, "alliance": "red", "events": [
            {"type": "fuel_scored", "points": 20},
            {"type": "climb_level_2", "points": 20},
            {"type": "score_correction", "points": 4},   # excluded
            {"type": "cycle_start", "points": None},
        ]},
        {"team": 5987, "alliance": "blue", "events": [
            {"type": "fuel_scored", "points": 5},
        ]},
    ],
}


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, response=None, get_responses=None):
        self.response = response or FakeResponse()
        self.get_responses = get_responses or {}
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return self.response

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        for fragment, resp in self.get_responses.items():
            if fragment in url:
                return resp
        return FakeResponse(404)


# ---- galaxia -----------------------------------------------------------------

def _galaxia_config(**over):
    return {"apis": {"galaxia": {
        "base_url": "https://galaxia.example.org", "api_key": "sekret", **over}}}


def test_push_match():
    session = FakeSession(FakeResponse(201, {"id": 42}))
    response = push_match(RECORD, _galaxia_config(), session=session)
    assert response == {"id": 42}
    method, url, kwargs = session.calls[0]
    assert url == "https://galaxia.example.org/api/scouting/matches/2026isde1_qm14"
    assert kwargs["json"] is RECORD
    assert kwargs["headers"]["Authorization"] == "Bearer sekret"


def test_push_custom_path_template():
    session = FakeSession()
    push_match(RECORD, _galaxia_config(path_template="/v2/m/{match_key}"),
               session=session)
    assert session.calls[0][1].endswith("/v2/m/2026isde1_qm14")


def test_push_requires_base_url():
    with pytest.raises(IntegrationError, match="base_url"):
        push_match(RECORD, {"apis": {}}, session=FakeSession())


def test_push_http_error():
    with pytest.raises(IntegrationError, match="HTTP 500"):
        push_match(RECORD, _galaxia_config(), session=FakeSession(FakeResponse(500)))


# ---- statbotics -----------------------------------------------------------------

def _stat_config():
    return {"apis": {"statbotics": {"base_url": "http://localhost:8000"}}}


def test_epa_crosscheck_ok_and_outlier():
    session = FakeSession(get_responses={
        "/v3/team_year/1690/2026": FakeResponse(200, {
            "epa": {"breakdown": {"total_points": {"mean": 45.0}}}}),
        "/v3/team_year/5987/2026": FakeResponse(200, {
            "epa": {"breakdown": {"total_points": {"mean": 60.0}}}}),
    })
    rows = {r["team"]: r for r in epa_crosscheck(RECORD, _stat_config(),
                                                 session=session)}
    assert rows[1690]["attributed_points"] == 40   # correction excluded
    assert rows[1690]["verdict"] == "ok"
    # 5 attributed vs EPA 60 -> outlier
    assert rows[5987]["verdict"] == "epa_outlier"


def test_epa_crosscheck_handles_missing_data():
    rows = epa_crosscheck(RECORD, _stat_config(), session=FakeSession())
    assert all(r["verdict"] == "no_epa_data" for r in rows)


def test_epa_alternate_payload_shapes():
    session = FakeSession(get_responses={
        "/1690/": FakeResponse(200, {"epa": {"total_points": {"mean": 39.5}}}),
        "/5987/": FakeResponse(200, {"epa": {"total_points": 12.0}}),
    })
    rows = {r["team"]: r for r in epa_crosscheck(RECORD, _stat_config(),
                                                 session=session)}
    assert rows[1690]["epa_mean"] == pytest.approx(39.5)
    assert rows[5987]["epa_mean"] == pytest.approx(12.0)

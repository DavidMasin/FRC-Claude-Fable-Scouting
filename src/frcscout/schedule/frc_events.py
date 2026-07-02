"""FRC Events API v3.0 provider (official FIRST API, fallback #1).

GET {base}/{season}/schedule/{EVENTCODE}?tournamentLevel=...&start=N&end=N
with HTTP Basic auth (username + auth token). Teams come back with station
labels 'Red1'..'Blue3'.

Note: the FRC Events event code is the *event* code without the season and
uppercased (TBA '2026isde1' -> 'ISDE1'). TBA event codes normally match the
official ones; if an event uses a divergent code, set
apis.frc_events.event_code_overrides in config.yaml.
"""

from __future__ import annotations

from .errors import ScheduleError
from .matchkey import MatchKey
from .model import MatchLineup, RobotSlot

_TIMEOUT = 20
_STATIONS = {f"{color}{n}": (color.lower(), n)
             for color in ("Red", "Blue") for n in (1, 2, 3)}


def get_lineup(mk: MatchKey, config: dict, session) -> MatchLineup:
    cfg = config.get("apis", {}).get("frc_events", {})
    username, token = cfg.get("username"), cfg.get("auth_token")
    if not (username and token):
        raise ScheduleError("frc_events: username/auth_token not configured")
    base = (cfg.get("base_url") or "https://frc-api.firstinspires.org/v3.0").rstrip("/")

    overrides = cfg.get("event_code_overrides") or {}
    event_code = overrides.get(mk.event_key, mk.event_code.upper())

    if mk.is_qual:
        level, number = "Qualification", mk.match_number
    else:
        number = mk.playoff_sequence
        if number is None:
            raise ScheduleError(f"frc_events: cannot map legacy playoff key {mk.key}")
        level = "Playoff"

    resp = session.get(
        f"{base}/{mk.season}/schedule/{event_code}",
        params={"tournamentLevel": level, "start": number, "end": number},
        auth=(username, token),
        timeout=_TIMEOUT,
    )
    if resp.status_code != 200:
        raise ScheduleError(f"frc_events: HTTP {resp.status_code}")

    matches = resp.json().get("Schedule") or []
    match = next((m for m in matches if m.get("matchNumber") == number), None)
    if match is None:
        raise ScheduleError(f"frc_events: match {level} {number} not in schedule")

    slots = []
    for entry in match.get("teams") or []:
        station = _STATIONS.get(entry.get("station"))
        team = entry.get("teamNumber")
        if station is None or team is None:
            raise ScheduleError(f"frc_events: malformed team entry {entry!r}")
        slots.append(RobotSlot(team=int(team), alliance=station[0], station=station[1]))
    return MatchLineup(match_key=mk.key, event_key=mk.event_key,
                       slots=tuple(slots), source="frc_events")

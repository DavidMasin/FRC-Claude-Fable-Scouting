"""The Blue Alliance API v3 provider (primary).

GET {base}/match/{match_key} with header X-TBA-Auth-Key. Station order is the
index within alliances.<color>.team_keys (TBA guarantees station order).
"""

from __future__ import annotations

from .errors import ScheduleError
from .matchkey import MatchKey
from .model import MatchLineup, lineup_from_alliances

_TIMEOUT = 20


def _team_number(team_key: str) -> int:
    if not team_key.startswith("frc"):
        raise ScheduleError(f"tba: unexpected team key {team_key!r}")
    return int(team_key[3:])


def get_lineup(mk: MatchKey, config: dict, session) -> MatchLineup:
    cfg = config.get("apis", {}).get("tba", {})
    auth_key = cfg.get("auth_key")
    if not auth_key:
        raise ScheduleError("tba: no auth_key configured")
    base = (cfg.get("base_url") or "https://www.thebluealliance.com/api/v3").rstrip("/")

    resp = session.get(f"{base}/match/{mk.key}",
                       headers={"X-TBA-Auth-Key": auth_key}, timeout=_TIMEOUT)
    if resp.status_code == 404:
        raise ScheduleError(f"tba: match {mk.key} not found (schedule not posted yet?)")
    if resp.status_code != 200:
        raise ScheduleError(f"tba: HTTP {resp.status_code}")
    data = resp.json()

    try:
        red = [_team_number(k) for k in data["alliances"]["red"]["team_keys"]]
        blue = [_team_number(k) for k in data["alliances"]["blue"]["team_keys"]]
    except (KeyError, TypeError) as exc:
        raise ScheduleError(f"tba: malformed match payload ({exc})") from exc
    return lineup_from_alliances(mk.key, mk.event_key, "tba", red, blue)

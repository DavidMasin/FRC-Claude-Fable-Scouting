"""Nexus (frc.nexus) API v1 provider (fallback #2).

GET {base}/event/{event_key} with header 'Nexus-Api-Key'. The event payload
carries a 'matches' list; each match has a human label ('Qualification 14',
'Playoff 3', 'Final 1') and station-ordered 'redTeams'/'blueTeams'.

Nexus's payload is less rigidly documented than TBA/FRC Events, so this
provider is deliberately defensive: any shape surprise raises ScheduleError
and the chain moves on.
"""

from __future__ import annotations

from .errors import ScheduleError
from .matchkey import MatchKey
from .model import MatchLineup, lineup_from_alliances

_TIMEOUT = 20


def _labels_for(mk: MatchKey) -> list[str]:
    if mk.is_qual:
        return [f"Qualification {mk.match_number}"]
    seq = mk.playoff_sequence
    labels = []
    if mk.comp_level == "f":
        labels.append(f"Final {mk.match_number}")
    if seq is not None:
        labels.append(f"Playoff {seq}")
        labels.append(f"Match {seq}")
    return labels


def get_lineup(mk: MatchKey, config: dict, session) -> MatchLineup:
    cfg = config.get("apis", {}).get("nexus", {})
    api_key = cfg.get("api_key")
    if not api_key:
        raise ScheduleError("nexus: no api_key configured")
    base = (cfg.get("base_url") or "https://frc.nexus/api/v1").rstrip("/")

    resp = session.get(f"{base}/event/{mk.event_key}",
                       headers={"Nexus-Api-Key": api_key}, timeout=_TIMEOUT)
    if resp.status_code != 200:
        raise ScheduleError(f"nexus: HTTP {resp.status_code}")

    matches = resp.json().get("matches") or []
    wanted = _labels_for(mk)
    match = next((m for m in matches if m.get("label") in wanted), None)
    if match is None:
        raise ScheduleError(f"nexus: no match labeled {wanted!r} at {mk.event_key}")

    try:
        red = [int(t) for t in match["redTeams"]]
        blue = [int(t) for t in match["blueTeams"]]
    except (KeyError, TypeError, ValueError) as exc:
        raise ScheduleError(f"nexus: malformed match payload ({exc})") from exc
    return lineup_from_alliances(mk.key, mk.event_key, "nexus", red, blue)

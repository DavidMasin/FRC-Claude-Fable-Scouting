"""Aggregate per-frame events into per-robot scouting records and reconcile
them against the overlay scoreboard. Mismatches become flags, not silent
adjustments — the record says what the vision pipeline actually saw."""

from __future__ import annotations

from ..events.model import ScoutingEvent
from ..schedule.model import MatchLineup


def _auto_cutoff(rubric: dict) -> float:
    return float(rubric["match_timing"]["auto_s"]["value"])


def _pair_intervals(events: list[ScoutingEvent], start_type: str, end_type: str,
                    match_end_t: float | None = None) -> list[tuple[float, float]]:
    intervals, open_t = [], None
    for ev in sorted(events, key=lambda e: e.t_video):
        if ev.type == start_type and open_t is None:
            open_t = ev.t_video
        elif ev.type == end_type and open_t is not None:
            intervals.append((open_t, ev.t_video))
            open_t = None
    if open_t is not None and match_end_t is not None and match_end_t > open_t:
        intervals.append((open_t, match_end_t))
    return intervals


def _robot_record(team: int, lineup: MatchLineup, events: list[ScoutingEvent],
                  assignment_conf: float, rubric: dict,
                  match_end_t: float | None) -> dict:
    slot = lineup.slot_for_team(team)
    auto_cutoff = _auto_cutoff(rubric)

    def in_auto(ev: ScoutingEvent) -> bool:
        return ev.match_time_s is not None and ev.match_time_s <= auto_cutoff

    fuel = [e for e in events if e.type == "fuel_scored"]
    auto_fuel = sum(e.count for e in fuel if in_auto(e))
    teleop_fuel = sum(e.count for e in fuel if not in_auto(e))

    cycles = [
        {"t_start": round(t0, 2), "t_end": round(t1, 2), "duration_s": round(t1 - t0, 2)}
        for t0, t1 in _pair_intervals(events, "cycle_start", "cycle_end")
    ]
    avg_cycle = (round(sum(c["duration_s"] for c in cycles) / len(cycles), 2)
                 if cycles else None)

    climb_events = sorted((e for e in events if e.type.startswith("climb_level_")),
                          key=lambda e: e.t_video)
    attempts = [e for e in events if e.type == "climb_attempt_start"]
    climb = climb_events[-1].type.removeprefix("climb_") if climb_events else None
    climb_start_t = attempts[0].t_video if attempts else (
        climb_events[-1].t_video if climb_events else None)

    defense_s = sum(t1 - t0 for t0, t1 in
                    _pair_intervals(events, "defense_start", "defense_end", match_end_t))

    flags = sorted({f for e in events for f in e.flags})
    if any(e.conf < 0.6 for e in fuel):
        flags.append("low_confidence_events")

    return {
        "team": team,
        "alliance": slot.alliance,
        "station": slot.station,
        "assignment_confidence": round(assignment_conf, 2),
        "auto": {
            "fuel_scored": auto_fuel,
            "leave": None,  # rubric marks auto_leave as unverified: never guessed
            "climb_level_1": any(in_auto(e) for e in climb_events),
        },
        "teleop": {
            "fuel_scored": teleop_fuel,
            "cycles": cycles,
            "avg_cycle_s": avg_cycle,
        },
        "endgame": {
            "climb": climb,
            "climb_start_t": round(climb_start_t, 2) if climb_start_t is not None else None,
            "attempted": bool(attempts or climb_events),
            "success": bool(climb_events),
        },
        "defense_played_s": round(defense_s, 2),
        "events": [e.to_dict() for e in sorted(events, key=lambda e: e.t_video)],
        "flags": sorted(set(flags)),
    }


def build_match_record(match_key: str, lineup: MatchLineup,
                       events: list[ScoutingEvent],
                       assignment_confidences: dict[int, float],
                       final_scores: dict[str, int], rubric: dict,
                       match_end_t: float | None = None,
                       overlay_suspect_deltas: dict[str, int] | None = None) -> dict:
    """assignment_confidences: team -> confidence of its track assignment."""
    by_team: dict[int, list[ScoutingEvent]] = {s.team: [] for s in lineup.slots}
    unattributed: list[ScoutingEvent] = []
    for ev in events:
        if ev.team in by_team:
            by_team[ev.team].append(ev)
        else:
            unattributed.append(ev)

    robots = [
        _robot_record(team, lineup, evs,
                      assignment_confidences.get(team, 0.0), rubric, match_end_t)
        for team, evs in by_team.items()
    ]

    # Reconcile: vision-attributed points vs the overlay scoreboard.
    alliances: dict[str, dict] = {}
    for alliance in ("red", "blue"):
        seen = sum((e.points or 0) for e in events
                   if e.alliance == alliance and e.points is not None
                   and e.type != "score_correction")
        overlay_total = final_scores.get(alliance)
        entry = {
            "overlay_final": overlay_total,
            "vision_attributed_points": seen,
            "unattributed_events": sum(
                1 for e in unattributed if e.alliance == alliance),
        }
        suspect = (overlay_suspect_deltas or {}).get(alliance, 0)
        if suspect:
            entry["overlay_suspect_deltas"] = suspect
            entry["flag"] = "overlay_readings_suspect"
        if overlay_total is not None and seen != overlay_total:
            entry["flag"] = "overlay_score_mismatch"
            for robot in robots:
                if robot["alliance"] == alliance:
                    robot["flags"] = sorted(set(robot["flags"] + ["overlay_score_mismatch"]))
        alliances[alliance] = entry

    return {
        "match_key": match_key,
        "event_key": lineup.event_key,
        "rubric_game": rubric.get("game"),
        "robots": robots,
        "alliances": alliances,
        "unattributed_events": [e.to_dict() for e in unattributed],
    }

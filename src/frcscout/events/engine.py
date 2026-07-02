"""Event detection: hybrid zone + overlay-delta attribution.

The workhorse signal: when the overlay score jumps for an alliance, credit
the robot of that alliance that was (most recently) in its scoring zone.
Everything is confidence-weighted and flagged rather than guessed:

- exactly one candidate in the zone  -> high confidence
- several candidates                 -> ambiguous: ask the VLM disambiguator
  if one is configured, else pick the most recent zone entrant with low
  confidence and an ``ambiguous_attribution`` flag
- nobody in the zone                 -> unattributed event, flagged

Endgame deltas matching a Tower level's point value with a robot in the
tower zone become climb events; defense and cycle observations come from
zone/proximity dwell heuristics. Point values are read from rubric.json —
if the rubric hasn't verified a value, events still flow but carry a
``points_unverified`` flag.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from .model import ScoutingEvent

_HISTORY_S = 4.0        # how far back "was in the zone" looks
_CLIMB_DWELL_S = 1.5    # tower-zone dwell before a climb attempt is called
_AMBIG_CONF = 0.5
_SINGLE_CONF = 0.85
_UNATTRIBUTED_CONF = 0.3

# every type the pipeline can emit; a rubric missing any of these would
# crash a run mid-match, so refuse it up front instead
REQUIRED_EVENT_TYPES = frozenset({
    "fuel_scored", "climb_level_1", "climb_level_2", "climb_level_3",
    "climb_attempt_start", "score_correction",
    "defense_start", "defense_end", "cycle_start", "cycle_end", "track_lost",
})


@dataclass(frozen=True)
class TrackSnapshot:
    track_id: int
    alliance: str | None
    team: int | None
    xyxy: tuple[float, float, float, float]
    field_xy: tuple[float, float] | None
    zones: frozenset[str] = frozenset()


@dataclass
class FrameContext:
    t_video: float
    frame_index: int
    phase: str                       # overlay.timeline phase constants
    match_time_s: float | None
    tracks: list[TrackSnapshot]
    score_changes: list = field(default_factory=list)   # overlay ScoreChange


def _points_value(rubric: dict, scoring_key: str) -> tuple[int | None, bool]:
    entry = rubric["scoring"][scoring_key]["points"]
    return entry["value"], entry["status"] == "verified-manual"


class EventEngine:
    def __init__(self, rubric: dict, vlm=None, defense_dist_m: float = 2.0,
                 defense_min_s: float = 2.0, field_length_m: float = 16.54,
                 red_on_left: bool = True) -> None:
        self.rubric = rubric
        self.vlm = vlm
        self.defense_dist_m = defense_dist_m
        self.defense_min_s = defense_min_s
        self.field_length_m = field_length_m
        self.red_on_left = red_on_left

        self._known_types = set(rubric["event_types"])
        missing = REQUIRED_EVENT_TYPES - self._known_types
        if missing:
            raise ValueError(
                f"rubric is missing event types {sorted(missing)} — it predates "
                "this version of frcscout. Regenerate it: "
                "`frcscout rubric build` (or delete rubric.json to fall back "
                "to the built-in seed)")
        self.fuel_pts_auto, self._fuel_auto_ok = _points_value(rubric, "fuel_hub_auto")
        self.fuel_pts_teleop, self._fuel_teleop_ok = _points_value(rubric, "fuel_hub_teleop")
        self.tower_pts = {}
        for level in (1, 2, 3):
            pts, ok = _points_value(rubric, f"tower_level_{level}_teleop")
            if pts is not None:
                self.tower_pts[pts] = (level, ok)

        self._history: dict[int, deque] = {}          # tid -> (t, zones, field_xy)
        self._defense: dict[int, dict] = {}           # tid -> {start, emitted}
        self._cycle: dict[int, str] = {}              # tid -> idle | loaded
        self._climb_dwell: dict[int, float] = {}      # tid -> tower-zone entry t
        self._climb_called: set[int] = set()
        self.events: list[ScoutingEvent] = []

    # ---- public ---------------------------------------------------------

    def step(self, ctx: FrameContext) -> list[ScoutingEvent]:
        for tr in ctx.tracks:
            self._history.setdefault(tr.track_id, deque(maxlen=64)).append(
                (ctx.t_video, tr.zones, tr.field_xy))
        events: list[ScoutingEvent] = []
        for change in ctx.score_changes:
            events += self._attribute_score(change, ctx)
        events += self._update_climb_attempts(ctx)
        events += self._update_defense(ctx)
        events += self._update_cycles(ctx)
        for ev in events:
            if ev.type not in self._known_types:
                raise ValueError(f"engine emitted unknown event type {ev.type!r}")
        self.events += events
        return events

    # ---- score attribution -------------------------------------------------

    def _recent_zone_candidates(self, alliance: str, zone: str, t: float
                                ) -> list[tuple[float, int]]:
        """(last-seen-in-zone time, track_id), best last."""
        out = []
        for tid, hist in self._history.items():
            for ht, zones, _ in reversed(hist):
                if ht < t - _HISTORY_S:
                    break
                if zone in zones:
                    out.append((ht, tid))
                    break
        return sorted(out)

    def _track(self, ctx: FrameContext, tid: int) -> TrackSnapshot | None:
        return next((tr for tr in ctx.tracks if tr.track_id == tid), None)

    def _attribute_score(self, change, ctx: FrameContext) -> list[ScoutingEvent]:
        if change.kind == "correction":
            return [ScoutingEvent(
                t_video=change.t_video, type="score_correction",
                match_time_s=ctx.match_time_s, alliance=change.alliance,
                count=abs(change.delta), conf=0.9, frame_index=ctx.frame_index,
                flags=("overlay_score_corrected",))]

        alliance = change.alliance
        # endgame: a delta equal to a tower level with a robot at the tower
        if ctx.phase == "endgame" and change.delta in self.tower_pts:
            candidates = self._recent_zone_candidates(
                alliance, f"tower_zone_{alliance}", change.t_video)
            candidates = [c for c in candidates
                          if self._alliance_of(ctx, c[1]) in (alliance, None)]
            if len(candidates) == 1:
                level, verified = self.tower_pts[change.delta]
                tr = self._track(ctx, candidates[0][1])
                return [self._event(
                    ctx, change, f"climb_level_{level}", tr, conf=0.8,
                    count=1, points=change.delta,
                    flags=() if verified else ("points_unverified",))]
            # fall through to fuel attribution, but note the possibility
            return self._attribute_fuel(change, ctx, extra_flags=("endgame_delta_maybe_tower",))
        return self._attribute_fuel(change, ctx)

    def _attribute_fuel(self, change, ctx: FrameContext,
                        extra_flags: tuple[str, ...] = ()) -> list[ScoutingEvent]:
        alliance = change.alliance
        in_auto = ctx.phase == "auto"
        fuel_pts = self.fuel_pts_auto if in_auto else self.fuel_pts_teleop
        verified = self._fuel_auto_ok if in_auto else self._fuel_teleop_ok
        flags = list(extra_flags)
        if not verified:
            flags.append("points_unverified")
        count = change.delta
        if fuel_pts and fuel_pts > 0:
            count, rem = divmod(change.delta, fuel_pts)
            if rem:
                flags.append("delta_not_multiple_of_fuel_points")
                count = max(1, count)

        candidates = self._recent_zone_candidates(
            alliance, f"hub_zone_{alliance}", change.t_video)
        candidates = [c for c in candidates
                      if self._alliance_of(ctx, c[1]) in (alliance, None)]

        if not candidates:
            return [ScoutingEvent(
                t_video=change.t_video, type="fuel_scored",
                match_time_s=ctx.match_time_s, alliance=alliance, count=count,
                points=change.delta, conf=_UNATTRIBUTED_CONF, frame_index=ctx.frame_index,
                flags=tuple(flags + ["no_robot_in_zone"]))]

        if len(candidates) == 1:
            tr = self._track(ctx, candidates[0][1])
            return [self._event(ctx, change, "fuel_scored", tr, conf=_SINGLE_CONF,
                                count=count, points=change.delta, flags=tuple(flags))]

        # ambiguous: several robots were in the zone recently
        if self.vlm is not None:
            tid, conf = self.vlm.choose_scorer(
                [c[1] for c in candidates],
                context={"alliance": alliance, "delta": change.delta,
                         "t": change.t_video, "phase": ctx.phase})
            if tid is not None:
                tr = self._track(ctx, tid)
                return [self._event(ctx, change, "fuel_scored", tr, conf=conf,
                                    count=count, points=change.delta,
                                    source="vlm", flags=tuple(flags))]
        tr = self._track(ctx, candidates[-1][1])  # most recent zone entrant
        return [self._event(ctx, change, "fuel_scored", tr, conf=_AMBIG_CONF,
                            count=count, points=change.delta,
                            flags=tuple(flags + ["ambiguous_attribution"]))]

    def _event(self, ctx: FrameContext, change, type_: str,
               tr: TrackSnapshot | None, conf: float, count: int,
               points: int | None, source: str = "zone+overlay",
               flags: tuple[str, ...] = ()) -> ScoutingEvent:
        return ScoutingEvent(
            t_video=change.t_video, type=type_, match_time_s=ctx.match_time_s,
            alliance=change.alliance,
            track_id=tr.track_id if tr else None,
            team=tr.team if tr else None,
            count=count, points=points, conf=conf, source=source,
            frame_index=ctx.frame_index, flags=flags)

    def _alliance_of(self, ctx: FrameContext, tid: int) -> str | None:
        tr = self._track(ctx, tid)
        return tr.alliance if tr else None

    # ---- climb attempts ------------------------------------------------------

    def _update_climb_attempts(self, ctx: FrameContext) -> list[ScoutingEvent]:
        if ctx.phase != "endgame":
            return []
        events = []
        for tr in ctx.tracks:
            if tr.alliance is None:
                continue
            in_tower = f"tower_zone_{tr.alliance}" in tr.zones
            if in_tower:
                start = self._climb_dwell.setdefault(tr.track_id, ctx.t_video)
                if (ctx.t_video - start >= _CLIMB_DWELL_S
                        and tr.track_id not in self._climb_called):
                    self._climb_called.add(tr.track_id)
                    events.append(ScoutingEvent(
                        t_video=start, type="climb_attempt_start",
                        match_time_s=ctx.match_time_s, alliance=tr.alliance,
                        track_id=tr.track_id, team=tr.team, conf=0.7,
                        source="heuristic", frame_index=ctx.frame_index))
            else:
                self._climb_dwell.pop(tr.track_id, None)
        return events

    # ---- defense ----------------------------------------------------------------

    def _opponent_half(self, tr: TrackSnapshot) -> bool:
        if tr.field_xy is None or tr.alliance is None:
            return False
        x = tr.field_xy[0]
        mid = self.field_length_m / 2
        own_left = (tr.alliance == "red") == self.red_on_left
        return x > mid if own_left else x < mid

    def _update_defense(self, ctx: FrameContext) -> list[ScoutingEvent]:
        events = []
        for tr in ctx.tracks:
            if tr.alliance is None or tr.field_xy is None:
                continue
            opponents = [o for o in ctx.tracks
                         if o.alliance not in (None, tr.alliance) and o.field_xy]
            near = any(
                ((tr.field_xy[0] - o.field_xy[0]) ** 2
                 + (tr.field_xy[1] - o.field_xy[1]) ** 2) ** 0.5 <= self.defense_dist_m
                for o in opponents)
            defending = self._opponent_half(tr) and near
            state = self._defense.get(tr.track_id)
            if defending:
                if state is None:
                    self._defense[tr.track_id] = {"start": ctx.t_video, "emitted": False}
                elif (not state["emitted"]
                      and ctx.t_video - state["start"] >= self.defense_min_s):
                    state["emitted"] = True
                    events.append(self._obs(ctx, tr, "defense_start", state["start"]))
            elif state is not None:
                if state["emitted"]:
                    events.append(self._obs(ctx, tr, "defense_end", ctx.t_video))
                del self._defense[tr.track_id]
        return events

    # ---- cycles --------------------------------------------------------------------

    def _update_cycles(self, ctx: FrameContext) -> list[ScoutingEvent]:
        events = []
        for tr in ctx.tracks:
            if tr.alliance is None:
                continue
            state = self._cycle.get(tr.track_id, "idle")
            if f"loading_zone_{tr.alliance}" in tr.zones and state == "idle":
                self._cycle[tr.track_id] = "loaded"
                events.append(self._obs(ctx, tr, "cycle_start", ctx.t_video))
            elif f"hub_zone_{tr.alliance}" in tr.zones and state == "loaded":
                self._cycle[tr.track_id] = "idle"
                events.append(self._obs(ctx, tr, "cycle_end", ctx.t_video))
        return events

    def _obs(self, ctx: FrameContext, tr: TrackSnapshot, type_: str,
             t: float) -> ScoutingEvent:
        return ScoutingEvent(
            t_video=t, type=type_, match_time_s=ctx.match_time_s,
            alliance=tr.alliance, track_id=tr.track_id, team=tr.team,
            conf=0.7, source="heuristic", frame_index=ctx.frame_index)

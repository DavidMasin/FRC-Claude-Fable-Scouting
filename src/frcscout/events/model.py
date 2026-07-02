"""Scouting events: everything downstream (aggregation, export, humans)
consumes these. Every event carries a confidence, a source, and a timestamp/
frame reference so a human can verify it against the video."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ScoutingEvent:
    t_video: float
    type: str                       # must exist in rubric event_types
    match_time_s: float | None = None
    alliance: str | None = None
    track_id: int | None = None
    team: int | None = None
    count: int = 1                  # e.g. fuel balls behind one score delta
    points: int | None = None       # rubric points credited, when known
    conf: float = 1.0
    source: str = "zone+overlay"    # zone+overlay | vlm | heuristic
    frame_index: int | None = None
    flags: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "t": round(self.t_video, 2),
            "match_t": round(self.match_time_s, 2) if self.match_time_s is not None else None,
            "type": self.type,
            "alliance": self.alliance,
            "track_id": self.track_id,
            "team": self.team,
            "count": self.count,
            "points": self.points,
            "conf": round(self.conf, 2),
            "source": self.source,
            "frame": self.frame_index,
            "flags": list(self.flags),
        }

"""Phase segmentation + debounced score timeline from noisy overlay readings.

OCR misreads happen constantly (a '3' seen as '8', dropouts during camera
wipes), so nothing is trusted from a single frame:

- a score value must be seen on 2 consecutive parses to be confirmed;
  decreases or implausibly large jumps need 4 (score corrections by the
  scorekeeper are real but rare — surfaced as their own event kind);
- the phase machine keys off the countdown clock: FRC broadcasts run one
  countdown for AUTO and a fresh one for TELEOP, so a big timer jump upward
  means the next period started. Endgame is the tail of teleop per the
  rubric's timing values.

Timing constants come from rubric.json (``OverlayTimeline.from_rubric``) —
the manual, not this module, owns them.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .parse import OverlayReading

PRE_MATCH = "pre_match"
AUTO = "auto"
BETWEEN = "between_periods"
TELEOP = "teleop"
ENDGAME = "endgame"
POST_MATCH = "post_match"


@dataclass(frozen=True)
class PhaseChange:
    t_video: float
    phase: str
    match_time_s: float | None  # seconds since AUTO start, when known


@dataclass(frozen=True)
class ScoreChange:
    t_video: float           # when the new value was first seen
    alliance: str
    delta: int
    total: int
    kind: str = "score"      # "score" | "correction"


@dataclass
class _PendingScore:
    value: int
    first_t: float
    count: int = 1


class OverlayTimeline:
    def __init__(self, auto_s: float = 20, teleop_s: float = 140,
                 endgame_s: float = 30, confirm_reads: int = 2,
                 suspicious_reads: int = 4, max_plausible_delta: int = 30) -> None:
        self.auto_s = auto_s
        self.teleop_s = teleop_s
        self.endgame_s = endgame_s
        self.confirm_reads = confirm_reads
        self.suspicious_reads = suspicious_reads
        self.max_plausible_delta = max_plausible_delta

        self.phase = PRE_MATCH
        self.scores = {"red": 0, "blue": 0}
        self.events: list = []
        self._period: int | None = None      # 0 = auto countdown, 1 = teleop countdown
        self._last_timer: float | None = None
        self._zero_reads = 0
        self._pending: dict[str, _PendingScore | None] = {"red": None, "blue": None}

    @classmethod
    def from_rubric(cls, rubric: dict, **kwargs) -> "OverlayTimeline":
        timing = rubric["match_timing"]
        return cls(
            auto_s=timing["auto_s"]["value"],
            teleop_s=timing["teleop_s"]["value"],
            endgame_s=timing["endgame_s"]["value"],
            **kwargs,
        )

    # ---- public -----------------------------------------------------------

    def add(self, reading: OverlayReading) -> list:
        """Feed one reading; returns the events it produced (also accumulated
        on .events)."""
        produced: list = []
        if reading.timer_s is not None:
            produced += self._advance_phase(reading.t_video, reading.timer_s)
        for alliance in ("red", "blue"):
            value = getattr(reading, alliance)
            if value is not None:
                produced += self._advance_score(alliance, value, reading.t_video)
        self.events.extend(produced)
        return produced

    def match_time(self, timer_s: float | None = None) -> float | None:
        """Seconds since AUTO start for the current phase/timer, if known."""
        timer = timer_s if timer_s is not None else self._last_timer
        if timer is None or self._period is None:
            return None
        if self._period == 0:
            return self.auto_s - timer
        return self.auto_s + (self.teleop_s - timer)

    # ---- phase machine ------------------------------------------------------

    def _advance_phase(self, t: float, timer: float) -> list:
        if self._last_timer is not None and timer > self._last_timer + 5:
            # countdown restarted: next period began
            self._period = 1 if self._period == 0 else (self._period or 0) + 1
        elif self._period is None and timer > 0:
            # first legible timer: infer which countdown we joined
            self._period = 0 if timer <= self.auto_s + 1 else 1

        self._zero_reads = self._zero_reads + 1 if timer == 0 else 0
        self._last_timer = timer

        phase = self.phase
        if self._period == 0:
            phase = BETWEEN if self._zero_reads >= self.confirm_reads else AUTO
        elif self._period == 1:
            if self._zero_reads >= self.confirm_reads:
                phase = POST_MATCH
            else:
                phase = ENDGAME if timer <= self.endgame_s else TELEOP

        if phase != self.phase:
            self.phase = phase
            return [PhaseChange(t_video=t, phase=phase, match_time_s=self.match_time(timer))]
        return []

    # ---- score machine ------------------------------------------------------

    def _advance_score(self, alliance: str, value: int, t: float) -> list:
        confirmed = self.scores[alliance]
        if value == confirmed:
            self._pending[alliance] = None
            return []

        pending = self._pending[alliance]
        if pending is None or pending.value != value:
            self._pending[alliance] = _PendingScore(value=value, first_t=t)
            return []
        pending.count += 1

        delta = value - confirmed
        suspicious = delta < 0 or delta > self.max_plausible_delta
        needed = self.suspicious_reads if suspicious else self.confirm_reads
        if pending.count < needed:
            return []

        self.scores[alliance] = value
        self._pending[alliance] = None
        return [ScoreChange(
            t_video=pending.first_t,
            alliance=alliance,
            delta=delta,
            total=value,
            kind="correction" if delta < 0 else "score",
        )]

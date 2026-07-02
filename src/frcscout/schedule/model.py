"""Match lineup: the 6 expected robots. This is the identity prior for the
whole vision pipeline — downstream, team identity is a 6-way assignment
problem against these slots, never open-set OCR."""

from __future__ import annotations

from dataclasses import dataclass, field

ALLIANCES = ("red", "blue")
STATIONS = (1, 2, 3)


class LineupError(ValueError):
    """Raised when a provider returns a malformed lineup."""


@dataclass(frozen=True)
class RobotSlot:
    team: int
    alliance: str  # "red" | "blue"
    station: int   # 1..3


@dataclass(frozen=True)
class MatchLineup:
    match_key: str
    event_key: str
    slots: tuple[RobotSlot, ...]
    source: str  # provider that supplied it: "tba" | "frc_events" | "nexus"

    def __post_init__(self) -> None:
        if len(self.slots) != 6:
            raise LineupError(f"{self.match_key}: expected 6 slots, got {len(self.slots)}")
        for alliance in ALLIANCES:
            stations = sorted(s.station for s in self.slots if s.alliance == alliance)
            if stations != list(STATIONS):
                raise LineupError(
                    f"{self.match_key}: {alliance} stations are {stations}, expected {list(STATIONS)}"
                )
        teams = [s.team for s in self.slots]
        if len(set(teams)) != 6:
            raise LineupError(f"{self.match_key}: duplicate team numbers: {sorted(teams)}")
        bad = [s.team for s in self.slots if not (1 <= s.team <= 99999)]
        if bad:
            raise LineupError(f"{self.match_key}: implausible team numbers: {bad}")

    def teams(self, alliance: str) -> list[int]:
        """Team numbers for one alliance, ordered by station 1..3."""
        return [s.team for s in sorted(
            (s for s in self.slots if s.alliance == alliance), key=lambda s: s.station)]

    def slot_for_team(self, team: int) -> RobotSlot:
        for s in self.slots:
            if s.team == team:
                return s
        raise KeyError(team)

    def to_dict(self) -> dict:
        return {
            "match_key": self.match_key,
            "event_key": self.event_key,
            "source": self.source,
            "red": self.teams("red"),
            "blue": self.teams("blue"),
        }


def lineup_from_alliances(match_key: str, event_key: str, source: str,
                          red: list[int], blue: list[int]) -> MatchLineup:
    """Build a lineup from station-ordered team lists (index 0 = station 1)."""
    slots = tuple(
        RobotSlot(team=t, alliance=alliance, station=i + 1)
        for alliance, teams in (("red", red), ("blue", blue))
        for i, t in enumerate(teams)
    )
    return MatchLineup(match_key=match_key, event_key=event_key, slots=slots, source=source)

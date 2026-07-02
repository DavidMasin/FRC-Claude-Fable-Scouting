"""TBA-style match key parsing: '2026isde1_qm14', '2026isde1_sf3m1', ..."""

from __future__ import annotations

import re
from dataclasses import dataclass

_KEY_RE = re.compile(
    r"^(?P<season>\d{4})(?P<event>[a-z0-9]+)_"
    r"(?P<level>qm|ef|qf|sf|f)(?P<a>\d+)(?:m(?P<b>\d+))?$"
)


@dataclass(frozen=True)
class MatchKey:
    key: str
    season: int
    event_code: str      # e.g. "isde1"
    comp_level: str      # qm | ef | qf | sf | f
    set_number: int | None
    match_number: int

    @property
    def event_key(self) -> str:
        return f"{self.season}{self.event_code}"

    @property
    def is_qual(self) -> bool:
        return self.comp_level == "qm"

    @property
    def playoff_sequence(self) -> int | None:
        """Overall playoff match number under the double-elimination bracket
        used since 2023 (SF sets 1..13 are matches 1..13, Finals are 14..16).
        None for quals; best-effort for legacy qf/ef brackets (returns None).
        """
        if self.comp_level == "sf":
            return self.set_number
        if self.comp_level == "f":
            return 13 + self.match_number
        return None


def parse_match_key(key: str) -> MatchKey:
    m = _KEY_RE.match(key.strip().lower())
    if not m:
        raise ValueError(
            f"unrecognized match key {key!r} (expected e.g. '2026isde1_qm14' or '2026isde1_sf3m1')"
        )
    level = m.group("level")
    a, b = int(m.group("a")), m.group("b")
    if level == "qm":
        if b is not None:
            raise ValueError(f"{key!r}: qual matches take no set number")
        set_number, match_number = None, a
    else:
        # playoff: 'a' is the set, trailing m<b> the match within the set
        set_number, match_number = a, int(b) if b is not None else 1
    return MatchKey(
        key=key.strip().lower(),
        season=int(m.group("season")),
        event_code=m.group("event"),
        comp_level=level,
        set_number=set_number,
        match_number=match_number,
    )

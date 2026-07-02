"""Extraction specs: regexes that pull rule values out of the manual text.

PDF text extraction mangles table layout, so every pattern tolerates
arbitrary whitespace/newlines between tokens and matches case-insensitively.
Each spec lists candidate patterns in priority order; the first that matches
wins. A spec that matches nothing leaves the seed value in place and the
entry stays ``needs-verification`` — the parser never guesses.

These patterns are unit-tested against fixture excerpts that mirror the
manual's published phrasing. When the real manual text disagrees, fix the
pattern here and the fixture together.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

_WS = r"[\s ]+"          # whitespace incl. non-breaking spaces
_ANY = r"[\s\S]{0,80}?"       # short non-greedy gap (table cells, line breaks)


@dataclass
class ExtractionSpec:
    """One rule value: where it lives in the rubric and how to find it."""
    path: tuple[str, ...]                 # path to the {value,status,...} entry
    patterns: list[str]                   # regexes with one capture group
    transform: Callable[[str], object] = int
    manual_ref: str | None = None         # section hint recorded on success
    flags: int = re.IGNORECASE
    extra: dict = field(default_factory=dict)

    def extract(self, text: str):
        """Return (value, pattern) on first match, else None."""
        for pat in self.patterns:
            m = re.search(pat, text, self.flags)
            if m:
                return self.transform(m.group(1)), pat
        return None


def _pts(*fragments: str) -> str:
    """Join fragments with tolerant whitespace gaps."""
    return _WS.join(fragments)


SPECS: list[ExtractionSpec] = [
    # ---- match timing -------------------------------------------------
    ExtractionSpec(
        path=("match_timing", "auto_s"),
        patterns=[
            r"first" + _WS + r"(\d+)" + _WS + r"seconds" + _ANY + r"aut",
            r"aut(?:o|onomous)[\s\S]{0,120}?(\d+)" + _WS + r"second",
        ],
        manual_ref="Match play / game overview",
    ),
    ExtractionSpec(
        path=("match_timing", "teleop_s"),
        patterns=[
            # "remaining 2 minutes and 20 seconds" -> 140
            r"remaining" + _WS + r"(\d)" + _WS + r"minutes?" + _WS + r"and" + _WS + r"20" + _WS + r"seconds",
        ],
        transform=lambda m: int(m) * 60 + 20,
        manual_ref="Match play / game overview",
    ),
    ExtractionSpec(
        path=("match_timing", "endgame_s"),
        patterns=[
            r"final" + _WS + r"(\d+)" + _WS + r"seconds" + _ANY + r"(?:endgame|end" + _WS + r"game)",
            r"endgame[\s\S]{0,100}?final" + _WS + r"(\d+)" + _WS + r"seconds",
            r"last" + _WS + r"(\d+)" + _WS + r"seconds" + _ANY + r"(?:endgame|all" + _WS + r"hubs)",
        ],
        manual_ref="Match play",
    ),

    # ---- fuel scoring -------------------------------------------------
    ExtractionSpec(
        path=("scoring", "fuel_hub_auto", "points"),
        patterns=[
            r"fuel" + _ANY + r"(?:active" + _WS + r")?hub" + _ANY + r"auto" + _ANY + r"(\d+)" + _WS + r"point",
            r"(\d+)" + _WS + r"point(?:s)?" + _ANY + r"(?:each|per)" + _WS + r"fuel" + _ANY + r"auto",
        ],
        manual_ref="Scoring table (sec. 6.5)",
    ),
    ExtractionSpec(
        path=("scoring", "fuel_hub_teleop", "points"),
        patterns=[
            r"fuel" + _ANY + r"(?:active" + _WS + r")?hub" + _ANY + r"teleop" + _ANY + r"(\d+)" + _WS + r"point",
            r"(\d+)" + _WS + r"point(?:s)?" + _ANY + r"(?:each|per)" + _WS + r"fuel" + _ANY + r"teleop",
        ],
        manual_ref="Scoring table (sec. 6.5)",
    ),

    # ---- tower --------------------------------------------------------
    ExtractionSpec(
        path=("scoring", "tower_level_1_auto", "points"),
        patterns=[
            r"level" + _WS + r"1" + _ANY + r"auto" + _ANY + r"(\d+)" + _WS + r"point",
            r"(\d+)" + _WS + r"points?" + _ANY + r"level" + _WS + r"1" + _ANY + r"auto",
        ],
        manual_ref="Scoring table (sec. 6.5)",
    ),
    ExtractionSpec(
        path=("scoring", "tower_level_1_teleop", "points"),
        patterns=[
            r"level" + _WS + r"1" + _ANY + r"teleop" + _ANY + r"(\d+)" + _WS + r"point",
            r"level" + _WS + r"1(?!" + _ANY + r"auto)" + _ANY + r"(\d+)" + _WS + r"point",
        ],
        manual_ref="Scoring table (sec. 6.5)",
    ),
    ExtractionSpec(
        path=("scoring", "tower_level_2_teleop", "points"),
        patterns=[r"level" + _WS + r"2" + _ANY + r"(\d+)" + _WS + r"point"],
        manual_ref="Scoring table (sec. 6.5)",
    ),
    ExtractionSpec(
        path=("scoring", "tower_level_3_teleop", "points"),
        patterns=[r"level" + _WS + r"3" + _ANY + r"(\d+)" + _WS + r"point"],
        manual_ref="Scoring table (sec. 6.5)",
    ),

    # ---- ranking points ------------------------------------------------
    ExtractionSpec(
        path=("ranking_points", "energized", "threshold"),
        patterns=[r"energized" + _ANY + r"(\d+)" + _ANY + r"fuel"],
        manual_ref="Ranking points",
    ),
    ExtractionSpec(
        path=("ranking_points", "supercharged", "threshold"),
        patterns=[r"supercharged" + _ANY + r"(\d+)" + _ANY + r"fuel"],
        manual_ref="Ranking points",
    ),
    ExtractionSpec(
        path=("ranking_points", "traversal", "threshold"),
        patterns=[r"traversal" + _ANY + r"(\d+)" + _ANY + r"tower" + _WS + r"point"],
        manual_ref="Ranking points",
    ),
    ExtractionSpec(
        path=("ranking_points", "win", "ranking_points"),
        patterns=[r"win(?:ning)?" + _ANY + r"(\d+)" + _WS + r"ranking" + _WS + r"points?"],
        manual_ref="Ranking points",
    ),
    ExtractionSpec(
        path=("ranking_points", "tie", "ranking_points"),
        patterns=[r"tie(?:d)?" + _ANY + r"(\d+)" + _WS + r"ranking" + _WS + r"point"],
        manual_ref="Ranking points",
    ),
]

MANUAL_VERSION_PATTERN = re.compile(r"version[:\s]+(TU\d+|\d+(?:\.\d+)*)", re.IGNORECASE)

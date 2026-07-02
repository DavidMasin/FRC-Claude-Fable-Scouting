"""Seed rubric for REBUILT (2026), built from *secondary* sources.

Every value here is marked ``needs-verification``: it was collected from
public summaries (team write-ups, frcmanual.com, frctools.com, official field
CAD/build documents) — NOT parsed out of the official game manual. Running

    frcscout rubric build --fetch

in an environment with network access parses the official manual and flips
each value the parser can confirm to ``verified-manual``. Values the parser
cannot find keep this seed value and stay flagged, per project policy:
never silently guess a rule.
"""

from __future__ import annotations

import copy
from typing import Any

MANUAL_PDF_URL = "https://firstfrc.blob.core.windows.net/frc2026/Manual/2026GameManual.pdf"
MANUAL_HTML_URL = "https://firstfrc.blob.core.windows.net/frc2026/Manual/HTML/2026GameManual.htm"

# Secondary sources used to seed values (provenance strings below).
_SRC_FRCMANUAL = "frcmanual.com/2026 (unofficial mirror, summary)"
_SRC_TEAM2502 = "team2502.com/game-breakdown (team summary)"
_SRC_FRCTOOLS = "frctools.com/2026/rule/6.5 (unofficial rule mirror)"
_SRC_TOWER_CAD = "TE-26500 Tower build instructions (official field assets)"
_SRC_SCOREBOARD = "community.firstinspires.org 2026 scoreboard/stream graphics doc"


def _seeded(value: Any, provenance: str, note: str | None = None) -> dict:
    d = {"value": value, "status": "needs-verification", "provenance": provenance}
    if note:
        d["note"] = note
    return d


def _missing(note: str) -> dict:
    return {"value": None, "status": "missing", "provenance": None, "note": note}


_SEED: dict[str, Any] = {
    "game": "REBUILT presented by Haas",
    "season": 2026,
    "manual": {
        "pdf_url": MANUAL_PDF_URL,
        "html_url": MANUAL_HTML_URL,
        "version": None,        # filled in by the parser (e.g. "TU22")
        "retrieved_at": None,   # filled in by the parser
        "parsed": False,
    },

    "match_timing": {
        "auto_s": _seeded(20, _SRC_FRCMANUAL, "AUTO period length in seconds"),
        "teleop_s": _seeded(140, _SRC_FRCMANUAL, "TELEOP length (2:20) incl. endgame"),
        "transition_shift_s": _seeded(10, _SRC_TEAM2502, "teleop clock 2:20-2:10"),
        "shift_s": _seeded(25, _SRC_TEAM2502, "each of SHIFTs 1-4"),
        "endgame_s": _seeded(30, _SRC_TEAM2502, "teleop clock 0:30-0:00; all HUBs active"),
    },

    # Broadcast-clock phase segmentation, in play order. The overlay OCR stage
    # keys off these names; durations reference match_timing semantics.
    "phases": [
        {"name": "auto", "duration_s": _seeded(20, _SRC_FRCMANUAL),
         "clock": "counts down 0:20 -> 0:00"},
        {"name": "transition_shift", "duration_s": _seeded(10, _SRC_TEAM2502),
         "clock": "teleop clock 2:20 -> 2:10"},
        {"name": "shift_1", "duration_s": _seeded(25, _SRC_TEAM2502), "clock": "2:10 -> 1:45"},
        {"name": "shift_2", "duration_s": _seeded(25, _SRC_TEAM2502), "clock": "1:45 -> 1:20"},
        {"name": "shift_3", "duration_s": _seeded(25, _SRC_TEAM2502), "clock": "1:20 -> 0:55"},
        {"name": "shift_4", "duration_s": _seeded(25, _SRC_TEAM2502), "clock": "0:55 -> 0:30"},
        {"name": "endgame", "duration_s": _seeded(30, _SRC_TEAM2502), "clock": "0:30 -> 0:00"},
    ],

    # Scoring elements. Names are the canonical IDs the event pipeline uses.
    "scoring": {
        "fuel_hub_auto": {
            "phase": "auto",
            "description": "FUEL scored in the alliance's active HUB during AUTO",
            "points": _seeded(1, _SRC_FRCMANUAL),
            "per": "fuel",
        },
        "fuel_hub_teleop": {
            "phase": "teleop",
            "description": "FUEL scored in an active HUB during TELEOP",
            "points": _seeded(1, _SRC_FRCMANUAL),
            "per": "fuel",
        },
        "tower_level_1_auto": {
            "phase": "auto",
            "description": "Robot climbs to TOWER LEVEL 1 in AUTO (off carpet/tower "
                           "base); secondary sources say at most 2 robots may earn "
                           "this in AUTO — verify against the manual",
            "points": _seeded(15, _SRC_TEAM2502),
            "per": "robot",
        },
        "tower_level_1_teleop": {
            "phase": "endgame",
            "description": "TOWER LEVEL 1: robot no longer touching carpet or tower base",
            "points": _seeded(10, _SRC_FRCTOOLS),
            "per": "robot",
        },
        "tower_level_2_teleop": {
            "phase": "endgame",
            "description": "TOWER LEVEL 2: bumpers completely above the LOW RUNG",
            "points": _seeded(20, _SRC_FRCTOOLS),
            "per": "robot",
        },
        "tower_level_3_teleop": {
            "phase": "endgame",
            "description": "TOWER LEVEL 3: bumpers completely above the MID RUNG",
            "points": _seeded(30, _SRC_FRCTOOLS),
            "per": "robot",
        },
        "auto_leave": {
            "phase": "auto",
            "description": "LEAVE/mobility credit in AUTO, if REBUILT awards one",
            "points": _missing("not confirmed to exist in REBUILT; do not emit "
                               "until verified against the manual"),
            "per": "robot",
        },
        "fouls_awarded": {
            "phase": "any",
            "description": "FOUL/TECH FOUL points awarded to the opposing alliance",
            "points": _missing("foul point values not yet parsed from manual"),
            "per": "foul",
        },
    },

    "ranking_points": {
        "win": {"description": "Winning alliance",
                "ranking_points": _seeded(3, _SRC_FRCMANUAL)},
        "tie": {"description": "Tied match",
                "ranking_points": _seeded(1, _SRC_FRCMANUAL)},
        "energized": {
            "description": "Alliance scores at least N FUEL in the HUB over the match",
            "threshold": _seeded(100, _SRC_FRCMANUAL, "fuel count"),
            "ranking_points": _seeded(1, _SRC_FRCMANUAL),
        },
        "supercharged": {
            "description": "Alliance scores at least N FUEL in the HUB over the match",
            "threshold": _seeded(360, _SRC_FRCMANUAL, "fuel count; team updates may "
                                 "have changed this — verify"),
            "ranking_points": _seeded(1, _SRC_FRCMANUAL),
        },
        "traversal": {
            "description": "Alliance earns at least N TOWER points in the match",
            "threshold": _seeded(50, _SRC_FRCMANUAL, "tower points"),
            "ranking_points": _seeded(1, _SRC_FRCMANUAL),
        },
    },

    # Game mechanics the event-attribution logic must model.
    "mechanics": {
        "hub_activation": {
            "description": "HUBs alternate being active during teleop SHIFTs; FUEL only "
                           "scores in an active HUB. Active-shift order is determined by "
                           "AUTO performance. All HUBs are active during endgame.",
            "status": "needs-verification",
            "provenance": _SRC_SCOREBOARD,
            "implications": [
                "overlay score deltas can only come from the alliance whose HUB is active",
                "hub LED state on broadcast (solid=active, pulsing=deactivating, off=inactive) "
                "is an additional OCR/vision cue",
            ],
        },
        "tower_level_progression": {
            "description": "A robot earns TOWER points for a single LEVEL in TELEOP; a robot "
                           "that scored TOWER points in AUTO may also earn TELEOP tower points.",
            "status": "needs-verification",
            "provenance": _SRC_FRCTOOLS,
        },
    },

    "field": {
        "game_piece": {
            "name": "FUEL",
            "description": "yellow foam ball",
            "diameter_in": _seeded(5.91, _SRC_FRCMANUAL, "15 cm"),
        },
        "tower": {
            "width_in": _seeded(32.25, _SRC_TOWER_CAD),
            "low_rung_height_in": _seeded(27, _SRC_TOWER_CAD),
            "mid_rung_height_in": _seeded(45, _SRC_TOWER_CAD),
            "high_rung_height_in": _seeded(63, _SRC_TOWER_CAD),
        },
    },

    # Field zones used by the homography stage. Geometry (field-coordinate
    # polygons) is filled in at milestone 7 from the field drawings; only the
    # semantic list lives in the rubric.
    "zones": [
        {"name": "hub_zone_red", "role": "scoring", "alliance": "red"},
        {"name": "hub_zone_blue", "role": "scoring", "alliance": "blue"},
        {"name": "tower_zone_red", "role": "endgame", "alliance": "red"},
        {"name": "tower_zone_blue", "role": "endgame", "alliance": "blue"},
        {"name": "loading_zone_red", "role": "acquisition", "alliance": "red"},
        {"name": "loading_zone_blue", "role": "acquisition", "alliance": "blue"},
        {"name": "neutral_zone", "role": "transit", "alliance": None},
    ],

    # Contract with the event-detection stage: every event the pipeline may
    # emit, and which scoring entry it maps to (scoring_ref: null = observation
    # only, contributes no points).
    "event_types": {
        "fuel_scored": {"scoring_ref": "fuel_hub_teleop",
                        "auto_ref": "fuel_hub_auto",
                        "description": "FUEL enters active HUB, attributed to a robot"},
        "climb_level_1": {"scoring_ref": "tower_level_1_teleop",
                          "auto_ref": "tower_level_1_auto"},
        "climb_level_2": {"scoring_ref": "tower_level_2_teleop"},
        "climb_level_3": {"scoring_ref": "tower_level_3_teleop"},
        "auto_leave": {"scoring_ref": "auto_leave"},
        "foul_committed": {"scoring_ref": "fouls_awarded"},
        "cycle_start": {"scoring_ref": None, "description": "robot enters loading zone"},
        "cycle_end": {"scoring_ref": None, "description": "robot completes scoring attempt"},
        "defense_start": {"scoring_ref": None},
        "defense_end": {"scoring_ref": None},
        "climb_attempt_start": {"scoring_ref": None},
        "track_lost": {"scoring_ref": None, "description": "tracking lost the robot; "
                       "no events fabricated while lost"},
    },
}


def seed_rubric() -> dict[str, Any]:
    """Return a fresh deep copy of the seed rubric."""
    return copy.deepcopy(_SEED)

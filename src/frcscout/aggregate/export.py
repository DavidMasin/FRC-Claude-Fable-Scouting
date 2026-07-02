"""Exports: full per-match JSON + a flat CSV for scouting-database import."""

from __future__ import annotations

import csv
import json
from pathlib import Path

CSV_COLUMNS = [
    "match_key", "team", "alliance", "station", "assignment_confidence",
    "auto_fuel", "teleop_fuel", "n_cycles", "avg_cycle_s",
    "endgame_climb", "climb_attempted", "climb_success",
    "defense_played_s", "flags",
]


def write_json(record: dict, path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
    return p


def write_csv(record: dict, path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for robot in record["robots"]:
            writer.writerow({
                "match_key": record["match_key"],
                "team": robot["team"],
                "alliance": robot["alliance"],
                "station": robot["station"],
                "assignment_confidence": robot["assignment_confidence"],
                "auto_fuel": robot["auto"]["fuel_scored"],
                "teleop_fuel": robot["teleop"]["fuel_scored"],
                "n_cycles": len(robot["teleop"]["cycles"]),
                "avg_cycle_s": robot["teleop"]["avg_cycle_s"] or "",
                "endgame_climb": robot["endgame"]["climb"] or "",
                "climb_attempted": robot["endgame"]["attempted"],
                "climb_success": robot["endgame"]["success"],
                "defense_played_s": robot["defense_played_s"],
                "flags": ";".join(robot["flags"]),
            })
    return p

"""Rubric data model and validation.

The rubric is a plain JSON-serializable dict. Every entry that carries a
game-rule *value* (points, seconds, thresholds) also carries a verification
status so downstream stages — and humans — know how much to trust it:

  - ``verified-manual``    the value was extracted from the official game
                           manual PDF/HTML by the parser in this package.
  - ``needs-verification`` the value was seeded from secondary sources
                           (team write-ups, calculators, field-asset drawings)
                           and has NOT been confirmed against the manual.
  - ``missing``            no value could be found anywhere; ``value`` is None.

Downstream event types (``event_types`` section) must each map to an existing
scoring entry — ``validate_rubric`` enforces that invariant.
"""

from __future__ import annotations

from typing import Any

STATUSES = {"verified-manual", "needs-verification", "missing"}

TOP_LEVEL_KEYS = {
    "game",
    "season",
    "manual",
    "match_timing",
    "phases",
    "scoring",
    "ranking_points",
    "mechanics",
    "field",
    "zones",
    "event_types",
}


class RubricError(ValueError):
    """Raised when a rubric fails validation."""


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise RubricError(msg)


def _check_valued(entry: dict, where: str) -> None:
    """Validate a {value, status, ...} leaf."""
    _require("status" in entry, f"{where}: missing 'status'")
    _require(entry["status"] in STATUSES, f"{where}: bad status {entry['status']!r}")
    _require("value" in entry, f"{where}: missing 'value'")
    if entry["status"] == "missing":
        _require(entry["value"] is None, f"{where}: status 'missing' but value set")
    else:
        _require(entry["value"] is not None, f"{where}: status {entry['status']!r} but value is None")
        _require("provenance" in entry and entry["provenance"], f"{where}: missing 'provenance'")


def validate_rubric(rubric: dict[str, Any]) -> None:
    """Raise RubricError if the rubric is structurally invalid."""
    missing = TOP_LEVEL_KEYS - rubric.keys()
    _require(not missing, f"missing top-level keys: {sorted(missing)}")
    _require(rubric["season"] == 2026, "season must be 2026")

    # Scoring entries: name -> {points: {value,status,...}, phase, ...}
    scoring = rubric["scoring"]
    _require(isinstance(scoring, dict) and scoring, "scoring must be a non-empty dict")
    for name, entry in scoring.items():
        _require("points" in entry, f"scoring.{name}: missing 'points'")
        _check_valued(entry["points"], f"scoring.{name}.points")
        _require(entry.get("phase") in {"auto", "teleop", "endgame", "any"},
                 f"scoring.{name}: bad phase {entry.get('phase')!r}")

    # Match timing
    for key, entry in rubric["match_timing"].items():
        _check_valued(entry, f"match_timing.{key}")

    # Phases must be contiguous, named, and reference timing
    for i, phase in enumerate(rubric["phases"]):
        _require("name" in phase and "duration_s" in phase, f"phases[{i}]: needs name+duration_s")
        _check_valued(phase["duration_s"], f"phases[{i}].duration_s")

    # Ranking points
    for name, rp in rubric["ranking_points"].items():
        _check_valued(rp["ranking_points"], f"ranking_points.{name}.ranking_points")
        if "threshold" in rp:
            _check_valued(rp["threshold"], f"ranking_points.{name}.threshold")

    # Every downstream event type must map to a scoring entry (or be a
    # non-scoring observation explicitly marked scoring: null).
    for ev, spec in rubric["event_types"].items():
        ref = spec.get("scoring_ref")
        if ref is not None:
            _require(ref in scoring, f"event_types.{ev}: scoring_ref {ref!r} not in scoring")


def unverified_entries(rubric: dict[str, Any]) -> list[str]:
    """Return dotted paths of every value still awaiting manual verification."""
    out: list[str] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            if "status" in node and "value" in node:
                if node["status"] != "verified-manual":
                    out.append(path)
                return
            for k, v in node.items():
                walk(v, f"{path}.{k}" if path else k)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")

    walk(rubric, "")
    return out

"""Build rubric.json: seed values, upgraded by whatever the manual confirms."""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import Any

from .model import unverified_entries, validate_rubric
from .patterns import MANUAL_VERSION_PATTERN, SPECS
from .seed import seed_rubric


def _get_entry(rubric: dict, path: tuple[str, ...]) -> dict:
    node: Any = rubric
    for key in path:
        node = node[key]
    return node


def apply_manual_text(rubric: dict, text: str) -> dict[str, list[tuple[str, Any, Any]]]:
    """Run every extraction spec against the manual text, in place.

    Returns {"verified": [(path, seed_value, manual_value)], "unmatched": [path]}.
    A confirmed value flips the entry to ``verified-manual``; a mismatch with
    the seed value still trusts the manual but records the conflict so a human
    can double-check the pattern didn't misfire.
    """
    report: dict[str, list] = {"verified": [], "unmatched": [], "conflicts": []}
    for spec in SPECS:
        entry = _get_entry(rubric, spec.path)
        dotted = ".".join(spec.path)
        hit = spec.extract(text)
        if hit is None:
            report["unmatched"].append(dotted)
            continue
        value, pattern = hit
        if entry["value"] is not None and entry["value"] != value:
            report["conflicts"].append((dotted, entry["value"], value))
        report["verified"].append((dotted, entry["value"], value))
        entry.update(
            value=value,
            status="verified-manual",
            provenance=f"game manual ({spec.manual_ref})" if spec.manual_ref else "game manual",
            matched_pattern=pattern,
        )

    m = MANUAL_VERSION_PATTERN.search(text[:2000])
    rubric["manual"]["version"] = m.group(1) if m else None
    rubric["manual"]["parsed"] = True
    rubric["manual"]["retrieved_at"] = (
        datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    )
    return report


def build_rubric(manual_text: str | None = None) -> tuple[dict, dict]:
    """Return (rubric, report). With no manual text, everything stays seeded."""
    rubric = seed_rubric()
    report = apply_manual_text(rubric, manual_text) if manual_text else \
        {"verified": [], "unmatched": [".".join(s.path) for s in SPECS], "conflicts": []}
    validate_rubric(rubric)
    report["needs_verification"] = unverified_entries(rubric)
    return rubric, report


def write_rubric(rubric: dict, out_path: str | Path = "rubric.json") -> Path:
    path = Path(out_path)
    path.write_text(json.dumps(rubric, indent=2, ensure_ascii=False) + "\n")
    return path

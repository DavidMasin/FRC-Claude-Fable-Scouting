import json

from frcscout.cli import main
from frcscout.rubric.build import build_rubric, write_rubric
from frcscout.rubric.model import unverified_entries, validate_rubric
from frcscout.rubric.patterns import SPECS


def test_build_without_manual_keeps_everything_seeded():
    rubric, report = build_rubric(None)
    validate_rubric(rubric)
    assert not report["verified"]
    assert len(report["unmatched"]) == len(SPECS)
    assert rubric["manual"]["parsed"] is False
    assert "match_timing.auto_s" in report["needs_verification"]


def test_build_with_manual_verifies_all_spec_fields(manual_text):
    rubric, report = build_rubric(manual_text)
    validate_rubric(rubric)
    assert not report["unmatched"]
    assert not report["conflicts"]
    assert len(report["verified"]) == len(SPECS)
    assert rubric["manual"]["parsed"] is True
    assert rubric["manual"]["version"] == "TU22"

    pts = rubric["scoring"]["tower_level_2_teleop"]["points"]
    assert pts["value"] == 20
    assert pts["status"] == "verified-manual"
    assert "game manual" in pts["provenance"]

    # Entries the parser has no spec for stay honest.
    assert rubric["field"]["tower"]["low_rung_height_in"]["status"] == "needs-verification"
    assert rubric["scoring"]["auto_leave"]["points"]["status"] == "missing"

    pending = unverified_entries(rubric)
    assert "scoring.tower_level_2_teleop.points" not in pending
    assert "field.tower.low_rung_height_in" in pending


def test_manual_disagreeing_with_seed_wins_but_is_flagged(manual_text):
    conflicting = manual_text.replace("LEVEL 3 earns 30 points", "LEVEL 3 earns 35 points")
    rubric, report = build_rubric(conflicting)
    assert rubric["scoring"]["tower_level_3_teleop"]["points"]["value"] == 35
    assert ("scoring.tower_level_3_teleop.points", 30, 35) in report["conflicts"]


def test_cli_build_and_validate_roundtrip(tmp_path, manual_text):
    manual = tmp_path / "manual.txt"
    manual.write_text(manual_text)
    out = tmp_path / "rubric.json"

    assert main(["rubric", "build", "--manual", str(manual), "--out", str(out)]) == 0
    saved = json.loads(out.read_text())
    validate_rubric(saved)
    assert saved["scoring"]["fuel_hub_teleop"]["points"]["status"] == "verified-manual"

    assert main(["rubric", "validate", str(out)]) == 0

    # Corrupt it: validation must fail.
    saved.pop("scoring")
    out.write_text(json.dumps(saved))
    assert main(["rubric", "validate", str(out)]) == 1


def test_write_rubric_roundtrip(tmp_path):
    rubric, _ = build_rubric(None)
    path = write_rubric(rubric, tmp_path / "rubric.json")
    assert json.loads(path.read_text()) == rubric

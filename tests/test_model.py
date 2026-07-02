import pytest

from frcscout.rubric.model import RubricError, unverified_entries, validate_rubric
from frcscout.rubric.seed import seed_rubric


def test_seed_rubric_is_valid():
    validate_rubric(seed_rubric())


def test_seed_rubric_is_fully_unverified():
    pending = unverified_entries(seed_rubric())
    assert pending, "seed rubric must be flagged for verification"
    assert "match_timing.auto_s" in pending
    assert "scoring.fuel_hub_teleop.points" in pending


def test_event_type_must_map_to_scoring_entry():
    rubric = seed_rubric()
    rubric["event_types"]["bogus_event"] = {"scoring_ref": "no_such_entry"}
    with pytest.raises(RubricError, match="bogus_event"):
        validate_rubric(rubric)


def test_observation_events_may_have_null_scoring_ref():
    rubric = seed_rubric()
    assert rubric["event_types"]["defense_start"]["scoring_ref"] is None
    validate_rubric(rubric)


def test_status_value_consistency_enforced():
    rubric = seed_rubric()
    entry = rubric["scoring"]["fuel_hub_teleop"]["points"]
    entry["status"] = "missing"  # but value is still set
    with pytest.raises(RubricError, match="fuel_hub_teleop"):
        validate_rubric(rubric)

    rubric = seed_rubric()
    rubric["scoring"]["fuel_hub_teleop"]["points"]["status"] = "made-up-status"
    with pytest.raises(RubricError):
        validate_rubric(rubric)


def test_missing_top_level_key_rejected():
    rubric = seed_rubric()
    del rubric["ranking_points"]
    with pytest.raises(RubricError, match="ranking_points"):
        validate_rubric(rubric)

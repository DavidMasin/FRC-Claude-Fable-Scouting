import pytest

from frcscout.schedule.matchkey import parse_match_key


def test_qualification_key():
    mk = parse_match_key("2026isde1_qm14")
    assert (mk.season, mk.event_code, mk.comp_level) == (2026, "isde1", "qm")
    assert mk.match_number == 14
    assert mk.set_number is None
    assert mk.event_key == "2026isde1"
    assert mk.is_qual
    assert mk.playoff_sequence is None


def test_double_elim_semifinal_key():
    mk = parse_match_key("2026isde1_sf3m1")
    assert mk.comp_level == "sf"
    assert (mk.set_number, mk.match_number) == (3, 1)
    assert mk.playoff_sequence == 3
    assert not mk.is_qual


def test_finals_key_sequence():
    assert parse_match_key("2026isde1_f1m1").playoff_sequence == 14
    assert parse_match_key("2026isde1_f1m2").playoff_sequence == 15
    assert parse_match_key("2026isde1_f1m3").playoff_sequence == 16


def test_key_is_normalized():
    assert parse_match_key("  2026ISDE1_QM3 ").key == "2026isde1_qm3"


def test_legacy_quarterfinal_has_no_sequence():
    assert parse_match_key("2022gal_qf2m1").playoff_sequence is None


@pytest.mark.parametrize("bad", ["nonsense", "2026isde1qm14", "2026isde1_xx3",
                                 "2026isde1_qm14m2", "isde1_qm14"])
def test_bad_keys_rejected(bad):
    with pytest.raises(ValueError):
        parse_match_key(bad)

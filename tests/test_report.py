import json

from frcscout.aggregate import build_match_record
from frcscout.events.model import ScoutingEvent
from frcscout.report import render_report, write_reports
from frcscout.rubric.seed import seed_rubric
from frcscout.schedule.model import lineup_from_alliances

LINEUP = lineup_from_alliances("2026isde1_qm14", "2026isde1", "tba",
                               [1690, 2630, 3339], [5987, 1577, 4590])


def _record():
    events = [
        ScoutingEvent(t_video=12.0, match_time_s=12.0, type="fuel_scored",
                      alliance="red", team=1690, track_id=1, count=6, points=6),
        ScoutingEvent(t_video=150.0, match_time_s=145.0, type="climb_level_2",
                      alliance="blue", team=5987, track_id=4, points=20),
    ]
    return build_match_record(
        "2026isde1_qm14", LINEUP, events,
        {t: 0.9 for t in (1690, 2630, 3339, 5987, 1577, 4590)},
        {"red": 6, "blue": 20}, seed_rubric(), match_end_t=163.0)


def test_english_report():
    text = render_report(_record(), "en")
    assert "# Scouting report — 2026isde1_qm14" in text
    assert "| 1690 |" in text
    assert "level_2" in text
    assert "Red 6 — Blue 20" in text
    assert "dir=\"rtl\"" not in text


def test_hebrew_report():
    text = render_report(_record(), "he")
    assert 'dir="rtl"' in text
    assert "דו\"ח סקאוטינג" in text
    assert "קבוצה" in text
    assert "טיפוס" in text
    assert "| 5987 |" in text


def test_mismatch_warning_rendered():
    record = _record()
    record["alliances"]["red"]["flag"] = "overlay_score_mismatch"
    assert "WARNING" in render_report(record, "en")
    assert "אזהרה" in render_report(record, "he")


def test_write_reports_and_cli(tmp_path, capsys):
    from frcscout.cli import main

    record = _record()
    paths = write_reports(record, tmp_path)
    assert [p.name for p in paths] == [
        "2026isde1_qm14_report.en.md", "2026isde1_qm14_report.he.md"]

    record_path = tmp_path / "match.json"
    record_path.write_text(json.dumps(record))
    assert main(["report", str(record_path), "--out-dir", str(tmp_path / "r"),
                 "--langs", "he"]) == 0
    out = capsys.readouterr().out
    assert "report.he.md" in out
    assert (tmp_path / "r" / "2026isde1_qm14_report.he.md").exists()

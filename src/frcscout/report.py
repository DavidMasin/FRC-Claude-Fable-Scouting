"""Bilingual (English / Hebrew) match report export, matching the team's
existing tooling conventions. Markdown output; the Hebrew variant is wrapped
in a dir="rtl" container so it renders right-to-left in any HTML viewer."""

from __future__ import annotations

from pathlib import Path

STRINGS = {
    "en": {
        "title": "Scouting report",
        "final_score": "Final score (overlay)",
        "red": "Red", "blue": "Blue",
        "team": "Team", "station": "Station",
        "auto_fuel": "Auto fuel", "teleop_fuel": "Teleop fuel",
        "cycles": "Cycles", "avg_cycle": "Avg cycle (s)",
        "climb": "Climb", "defense": "Defense (s)",
        "confidence": "ID conf.", "flags": "Flags",
        "no_climb": "none", "score_mismatch_warning":
            "WARNING: vision-attributed points do not match the overlay scoreboard for",
        "unattributed": "events could not be attributed to a specific robot",
        "generated_by": "Generated automatically from broadcast video — every event "
                        "carries a timestamp and confidence for human verification.",
    },
    "he": {
        "title": "דו\"ח סקאוטינג",
        "final_score": "תוצאה סופית (לפי שכבת השידור)",
        "red": "אדומה", "blue": "כחולה",
        "team": "קבוצה", "station": "עמדה",
        "auto_fuel": "דלק באוטונומי", "teleop_fuel": "דלק בטלאופ",
        "cycles": "מחזורים", "avg_cycle": "מחזור ממוצע (שנ')",
        "climb": "טיפוס", "defense": "הגנה (שנ')",
        "confidence": "ביטחון זיהוי", "flags": "דגלים",
        "no_climb": "ללא",
        "score_mismatch_warning":
            "אזהרה: הניקוד שזוהה בווידאו אינו תואם ללוח התוצאות עבור הברית ה",
        "unattributed": "אירועים שלא ניתן היה לשייך לרובוט מסוים",
        "generated_by": "נוצר אוטומטית מווידאו השידור — לכל אירוע חותמת זמן ורמת "
                        "ביטחון לאימות אנושי.",
    },
}


def _robot_row(robot: dict, s: dict) -> str:
    endgame = robot["endgame"]["climb"] or s["no_climb"]
    return (f"| {robot['team']} | {robot['station']} "
            f"| {robot['auto']['fuel_scored']} | {robot['teleop']['fuel_scored']} "
            f"| {len(robot['teleop']['cycles'])} "
            f"| {robot['teleop']['avg_cycle_s'] if robot['teleop']['avg_cycle_s'] is not None else '-'} "
            f"| {endgame} | {robot['defense_played_s']} "
            f"| {robot['assignment_confidence']:.2f} | {len(robot['flags'])} |")


def render_report(record: dict, lang: str = "en") -> str:
    s = STRINGS[lang]
    a = record["alliances"]
    lines = []
    if lang == "he":
        lines.append('<div dir="rtl">\n')
    lines.append(f"# {s['title']} — {record['match_key']}")
    lines.append("")
    lines.append(f"**{s['final_score']}**: "
                 f"{s['red']} {a['red']['overlay_final']} — "
                 f"{s['blue']} {a['blue']['overlay_final']}")
    lines.append("")

    header = (f"| {s['team']} | {s['station']} | {s['auto_fuel']} | {s['teleop_fuel']} "
              f"| {s['cycles']} | {s['avg_cycle']} | {s['climb']} | {s['defense']} "
              f"| {s['confidence']} | {s['flags']} |")
    divider = "|" + "---|" * 10
    for alliance in ("red", "blue"):
        lines.append(f"## {s[alliance]}")
        lines.append("")
        lines.append(header)
        lines.append(divider)
        for robot in record["robots"]:
            if robot["alliance"] == alliance:
                lines.append(_robot_row(robot, s))
        lines.append("")
        if a[alliance].get("flag"):
            lines.append(f"**{s['score_mismatch_warning']}{s[alliance]}** "
                         f"({a[alliance]['vision_attributed_points']} / "
                         f"{a[alliance]['overlay_final']})")
            lines.append("")

    n_unattr = len(record.get("unattributed_events", []))
    if n_unattr:
        lines.append(f"{n_unattr} {s['unattributed']}.")
        lines.append("")
    lines.append(f"*{s['generated_by']}*")
    if lang == "he":
        lines.append("\n</div>")
    return "\n".join(lines) + "\n"


def write_reports(record: dict, out_dir: str | Path,
                  langs: tuple[str, ...] = ("en", "he")) -> list[Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for lang in langs:
        path = out / f"{record['match_key']}_report.{lang}.md"
        path.write_text(render_report(record, lang), encoding="utf-8")
        paths.append(path)
    return paths

"""Cross-check vision-attributed contributions against Statbotics EPA
(self-hosted instance or statbotics.io). Purely informational: a big
deviation doesn't mean the pipeline is wrong — teams have breakout matches —
but it's a cheap sanity signal for reviewers, surfaced as a flag."""

from __future__ import annotations

_DEVIATION_FACTOR = 2.5   # attributed pts vs EPA beyond this ratio -> flag
_MIN_POINTS = 8           # don't flag noise on tiny contributions


def _epa_mean(payload: dict) -> float | None:
    """Statbotics v3 team_year payloads have moved the number around across
    versions; try the known shapes."""
    epa = payload.get("epa") or {}
    for probe in (
        lambda: epa["breakdown"]["total_points"]["mean"],
        lambda: epa["total_points"]["mean"],
        lambda: epa["total_points"],
        lambda: payload["epa_mean"],
    ):
        try:
            value = probe()
            if isinstance(value, (int, float)):
                return float(value)
        except (KeyError, TypeError):
            continue
    return None


def _attributed_points(record: dict, team: int) -> int:
    robot = next(r for r in record["robots"] if r["team"] == team)
    return sum(e["points"] or 0 for e in robot["events"]
               if e["points"] is not None and e["type"] != "score_correction")


def epa_crosscheck(record: dict, config: dict, season: int = 2026,
                   session=None) -> list[dict]:
    """Returns one row per robot: attributed points, EPA, and a verdict."""
    if session is None:
        import requests
        session = requests.Session()

    cfg = (config.get("apis") or {}).get("statbotics") or {}
    base = (cfg.get("base_url") or "https://api.statbotics.io").rstrip("/")

    rows = []
    for robot in record["robots"]:
        team = robot["team"]
        row = {"team": team, "alliance": robot["alliance"],
               "attributed_points": _attributed_points(record, team),
               "epa_mean": None, "verdict": "no_epa_data"}
        try:
            resp = session.get(f"{base}/v3/team_year/{team}/{season}", timeout=20)
            if resp.status_code == 200:
                row["epa_mean"] = _epa_mean(resp.json())
        except Exception:
            pass

        epa = row["epa_mean"]
        pts = row["attributed_points"]
        if epa is not None:
            if pts < _MIN_POINTS and epa < _MIN_POINTS:
                row["verdict"] = "ok"
            elif epa > 0 and (pts / epa > _DEVIATION_FACTOR
                              or (pts > 0 and epa / max(pts, 1) > _DEVIATION_FACTOR)):
                row["verdict"] = "epa_outlier"
            else:
                row["verdict"] = "ok"
        rows.append(row)
    return rows

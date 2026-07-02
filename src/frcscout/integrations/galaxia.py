"""Push match records to the Galaxia scouting stack (the team's existing
Flask app). The endpoint path is a config template so the Flask side can
evolve without code changes here."""

from __future__ import annotations


class IntegrationError(RuntimeError):
    pass


def push_match(record: dict, config: dict, session=None) -> dict:
    """POST the per-match record; returns the server's JSON response."""
    if session is None:
        import requests
        session = requests.Session()

    cfg = (config.get("apis") or {}).get("galaxia") or {}
    base = (cfg.get("base_url") or "").rstrip("/")
    if not base:
        raise IntegrationError("galaxia: no base_url configured (apis.galaxia)")
    path = cfg.get("path_template", "/api/scouting/matches/{match_key}")
    url = base + path.format(match_key=record["match_key"])

    headers = {}
    if cfg.get("api_key"):
        headers["Authorization"] = f"Bearer {cfg['api_key']}"

    resp = session.post(url, json=record, headers=headers, timeout=30)
    if resp.status_code >= 300:
        raise IntegrationError(f"galaxia: HTTP {resp.status_code} from {url}")
    try:
        return resp.json()
    except ValueError:
        return {"status": resp.status_code}

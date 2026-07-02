"""frcscout web UI: start scouting runs, watch events live, browse results.

Zero-config by design: with no config.yaml, no rubric.json, and no
calibration, runs use the seeded rubric, auto-detected overlay regions, and
pixel-band zones. Anything you do configure is picked up automatically.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from flask import (Flask, abort, jsonify, redirect, render_template, request,
                   send_from_directory, url_for)

from .jobs import Job, JobManager

_KEY_RE = re.compile(r"^[a-z0-9_]+$")


def _load_setup(config_path: str):
    from ..config import load_config
    from ..rubric.build import build_rubric

    # missing file is fine: API keys still arrive via environment variables
    config = load_config(config_path, allow_missing=True)
    rubric_path = Path(config.get("rubric_path", "rubric.json"))
    if rubric_path.exists():
        rubric = json.loads(rubric_path.read_text())
    else:
        rubric, _ = build_rubric(None)
    return config, rubric


def _parse_teams(text: str) -> list[int]:
    teams = [int(t) for t in re.split(r"[,\s]+", text.strip()) if t]
    if len(teams) != 3:
        raise ValueError(f"need exactly 3 team numbers, got {teams}")
    return teams


def create_app(config_path: str = "config.yaml", out_dir: str = "out") -> Flask:
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 ** 3  # 4 GB VOD uploads
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    uploads = out / "uploads"
    uploads.mkdir(exist_ok=True)
    manager = JobManager()

    def _runner(params: dict):
        def run(job: Job) -> None:
            from ..aggregate import write_csv, write_json
            from ..pipeline import ScoutingPipeline
            from ..report import write_reports
            from ..schedule import fetch_lineup
            from ..schedule.model import lineup_from_alliances

            config, rubric = _load_setup(config_path)
            if params.get("red_teams"):
                lineup = lineup_from_alliances(
                    params["match_key"], params["match_key"].split("_")[0],
                    "manual", _parse_teams(params["red_teams"]),
                    _parse_teams(params["blue_teams"]))
            else:
                lineup = fetch_lineup(params["match_key"], config)
            job.match_key = lineup.match_key

            pipeline = ScoutingPipeline(config, rubric, lineup)
            result = pipeline.run(
                params["source"], sample_fps=float(params.get("fps") or 6),
                start_s=float(params.get("start") or 0),
                duration_s=float(params["duration"]) if params.get("duration") else None,
                mode=params.get("mode", "replay"),
                on_event=lambda ev: job.events.append(ev.to_dict()),
                should_stop=lambda: job.cancel_requested)
            job.record = result.record
            job.n_frames = result.n_frames
            job.n_unstable = result.n_unstable
            write_json(result.record, out / f"{lineup.match_key}.json")
            write_csv(result.record, out / f"{lineup.match_key}.csv")
            write_reports(result.record, out)
        return run

    # ---- pages -------------------------------------------------------------

    @app.get("/")
    def index():
        matches = sorted(
            (json.loads(p.read_text()) for p in out.glob("*.json")
             if not p.name.endswith("_events.jsonl")),
            key=lambda r: r.get("match_key", ""))
        return render_template("index.html", matches=matches, jobs=manager.all())

    @app.get("/job/<int:job_id>")
    def job_page(job_id: int):
        job = manager.get(job_id) or abort(404)
        return render_template("job.html", job=job)

    @app.get("/match/<key>")
    def match_page(key: str):
        _KEY_RE.match(key) or abort(404)
        path = out / f"{key}.json"
        path.exists() or abort(404)
        record = json.loads(path.read_text())
        downloads = [p.name for p in out.iterdir()
                     if p.name.startswith(key) and p.is_file()]
        return render_template("match.html", record=record, key=key,
                               downloads=sorted(downloads))

    # ---- API ------------------------------------------------------------------

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    @app.post("/api/scout")
    def api_scout():
        params = request.get_json(force=True) if request.is_json \
            else request.form.to_dict()
        upload = request.files.get("video")
        if upload and upload.filename:
            safe = re.sub(r"[^A-Za-z0-9._-]", "_", upload.filename)
            dest = uploads / safe
            upload.save(dest)
            params["source"] = str(dest)
        source = (params.get("source") or "").strip()
        if not source:
            return jsonify({"error": "source is required (URL, path, or upload)"}), 400
        match_key = (params.get("match_key") or "").strip().lower() or "manual_qm1"
        if not _KEY_RE.match(match_key):
            return jsonify({"error": "match key: lowercase letters/digits/_ only"}), 400
        if params.get("red_teams"):
            try:
                _parse_teams(params["red_teams"])
                _parse_teams(params.get("blue_teams", ""))
            except ValueError as exc:
                return jsonify({"error": str(exc)}), 400
        job = manager.start(source, match_key, _runner(dict(params)))
        if request.is_json:
            return jsonify(job.to_dict(include_events=False)), 202
        return redirect(url_for("job_page", job_id=job.job_id))

    @app.post("/api/jobs/<int:job_id>/cancel")
    def api_job_cancel(job_id: int):
        job = manager.get(job_id) or abort(404)
        job.cancel_requested = True
        return jsonify(job.to_dict(include_events=False))

    @app.get("/api/jobs/<int:job_id>")
    def api_job(job_id: int):
        job = manager.get(job_id) or abort(404)
        since = request.args.get("since", 0, type=int)
        d = job.to_dict(include_events=False)
        d["events"] = job.events[since:]
        d["events_offset"] = since
        if job.status == "done":
            d["match_url"] = url_for("match_page", key=job.match_key)
        return jsonify(d)

    @app.get("/api/matches/<key>")
    def api_match(key: str):
        _KEY_RE.match(key) or abort(404)
        path = out / f"{key}.json"
        path.exists() or abort(404)
        return jsonify(json.loads(path.read_text()))

    @app.get("/api/rubric")
    def api_rubric():
        _, rubric = _load_setup(config_path)
        timing = rubric["match_timing"]
        return jsonify({name: entry["value"] for name, entry in timing.items()})

    @app.get("/files/<path:name>")
    def files(name: str):
        return send_from_directory(out.resolve(), name, as_attachment=True)

    return app

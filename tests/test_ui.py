import json
import time

import pytest

from frcscout.ui import create_app

from test_pipeline_e2e import BLUE, LINEUP, RED, match_video  # noqa: F401


@pytest.fixture
def app(tmp_path):
    app = create_app(config_path=str(tmp_path / "no-config.yaml"),
                     out_dir=str(tmp_path / "out"))
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def test_index_empty(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"Scout a match" in resp.data
    assert b"Nothing scouted yet" in resp.data


def test_scout_requires_source(client):
    resp = client.post("/api/scout", json={})
    assert resp.status_code == 400
    assert "source" in resp.get_json()["error"]


def test_scout_validates_teams(client):
    resp = client.post("/api/scout", json={
        "source": "x.mp4", "red_teams": "1690, 2630", "blue_teams": "1,2,3"})
    assert resp.status_code == 400
    assert "3 team numbers" in resp.get_json()["error"]


def test_bad_match_key_rejected(client):
    resp = client.post("/api/scout", json={"source": "x.mp4",
                                           "match_key": "../etc/passwd"})
    assert resp.status_code == 400


def test_full_job_flow(client, match_video):
    resp = client.post("/api/scout", json={
        "source": match_video,
        "match_key": "2026isde1_qm14",
        "red_teams": ", ".join(map(str, RED)),
        "blue_teams": ", ".join(map(str, BLUE)),
        "fps": "2",
    })
    assert resp.status_code == 202
    job_id = resp.get_json()["job_id"]

    deadline = time.time() + 120
    job = None
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").get_json()
        if job["status"] != "running":
            break
        time.sleep(0.5)
    assert job["status"] == "done", job.get("error")
    assert job["n_events"] > 0
    assert job["match_url"] == "/match/2026isde1_qm14"

    # incremental event fetch
    part = client.get(f"/api/jobs/{job_id}?since={job['n_events'] - 1}").get_json()
    assert len(part["events"]) == 1

    # match page + API
    page = client.get("/match/2026isde1_qm14")
    assert page.status_code == 200
    assert b"fuel-chart" in page.data and b"timeline-chart" in page.data

    record = client.get("/api/matches/2026isde1_qm14").get_json()
    assert record["alliances"]["red"]["overlay_final"] == 32
    robots = {r["team"]: r for r in record["robots"]}
    assert robots[1690]["endgame"]["climb"] == "level_2"

    # index now lists the match; downloads served
    assert b"2026isde1_qm14" in client.get("/").data
    csv = client.get("/files/2026isde1_qm14.csv")
    assert csv.status_code == 200 and b"1690" in csv.data
    report = client.get("/files/2026isde1_qm14_report.he.md")
    assert report.status_code == 200


def test_job_error_surfaces(client):
    resp = client.post("/api/scout", json={
        "source": "/nonexistent/file.mp4", "match_key": "2026x_qm1",
        "red_teams": "1,2,3", "blue_teams": "4,5,6"})
    job_id = resp.get_json()["job_id"]
    deadline = time.time() + 30
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").get_json()
        if job["status"] != "running":
            break
        time.sleep(0.2)
    assert job["status"] == "error"
    assert "could not open" in job["error"] or "IngestError" in job["error"]


def test_rubric_timing_api(client):
    timing = client.get("/api/rubric").get_json()
    assert timing["auto_s"] == 20 and timing["teleop_s"] == 140


def test_match_404(client):
    assert client.get("/match/nope_qm1").status_code == 404
    assert client.get("/api/matches/nope_qm1").status_code == 404

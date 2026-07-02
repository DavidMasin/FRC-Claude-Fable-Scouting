"""Railway/production deployment surface: wsgi entrypoint, health check,
env-var config, VOD upload."""

import importlib
import io
import time

import pytest

from frcscout.config import load_config


def test_load_config_allow_missing_uses_env(tmp_path, monkeypatch):
    monkeypatch.setenv("TBA_AUTH_KEY", "env-key")
    config = load_config(tmp_path / "absent.yaml", allow_missing=True)
    assert config["apis"]["tba"]["auth_key"] == "env-key"
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "absent.yaml")


def test_wsgi_entrypoint_reads_env(tmp_path, monkeypatch):
    monkeypatch.setenv("FRCSCOUT_OUT_DIR", str(tmp_path / "data" / "out"))
    monkeypatch.setenv("FRCSCOUT_CONFIG", str(tmp_path / "none.yaml"))
    import frcscout.ui.wsgi as wsgi

    importlib.reload(wsgi)
    assert (tmp_path / "data" / "out" / "uploads").is_dir()
    client = wsgi.app.test_client()
    assert client.get("/healthz").get_json() == {"status": "ok"}
    assert client.get("/").status_code == 200


def test_wsgi_follows_railway_volume_mount(tmp_path, monkeypatch):
    """Whatever mount path Railway allows, records land on the volume."""
    monkeypatch.delenv("FRCSCOUT_OUT_DIR", raising=False)
    monkeypatch.setenv("RAILWAY_VOLUME_MOUNT_PATH", str(tmp_path / "vol"))
    monkeypatch.setenv("FRCSCOUT_CONFIG", str(tmp_path / "none.yaml"))
    import frcscout.ui.wsgi as wsgi

    importlib.reload(wsgi)
    assert (tmp_path / "vol" / "out" / "uploads").is_dir()

    # explicit FRCSCOUT_OUT_DIR always wins over the volume default
    monkeypatch.setenv("FRCSCOUT_OUT_DIR", str(tmp_path / "explicit"))
    importlib.reload(wsgi)
    assert (tmp_path / "explicit" / "uploads").is_dir()


def test_upload_flow(tmp_path, monkeypatch):
    from frcscout.ui import create_app

    from test_pipeline_e2e import BLUE, RED

    app = create_app(config_path=str(tmp_path / "no.yaml"),
                     out_dir=str(tmp_path / "out"))
    client = app.test_client()

    # build a tiny real clip to upload
    import cv2
    import numpy as np

    clip = tmp_path / "clip.avi"
    writer = cv2.VideoWriter(str(clip), cv2.VideoWriter_fourcc(*"MJPG"), 5, (64, 48))
    for i in range(10):
        writer.write(np.full((48, 64, 3), i * 10, np.uint8))
    writer.release()

    resp = client.post("/api/scout", data={
        "match_key": "2026up_qm1",
        "red_teams": ", ".join(map(str, RED)),
        "blue_teams": ", ".join(map(str, BLUE)),
        "fps": "5",
        "video": (io.BytesIO(clip.read_bytes()), "my match!.avi"),
    }, content_type="multipart/form-data", follow_redirects=False)
    assert resp.status_code == 302  # form flow redirects to the job page

    # the upload landed (sanitized name) and the job consumed it
    uploaded = list((tmp_path / "out" / "uploads").iterdir())
    assert len(uploaded) == 1 and uploaded[0].name == "my_match_.avi"

    job_id = int(resp.headers["Location"].rstrip("/").split("/")[-1])
    deadline = time.time() + 60
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").get_json()
        if job["status"] != "running":
            break
        time.sleep(0.2)
    # a featureless clip scouts to an empty-but-valid record
    assert job["status"] == "done", job.get("error")


def test_upload_without_anything_rejected(tmp_path):
    from frcscout.ui import create_app

    app = create_app(config_path=str(tmp_path / "no.yaml"),
                     out_dir=str(tmp_path / "out"))
    resp = app.test_client().post("/api/scout", data={},
                                  content_type="multipart/form-data")
    assert resp.status_code == 400

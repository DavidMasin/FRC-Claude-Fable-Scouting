import sys
import types

import numpy as np
import pytest

from frcscout.ingest import FrameIterator, IngestError, resolve_source

FPS = 30
N_FRAMES = 90  # 3 seconds
W, H = 64, 48


@pytest.fixture(scope="session")
def synthetic_video(tmp_path_factory):
    """90-frame 30fps clip; frame i is a solid gray of intensity 2*i, so a
    frame's pixels reveal which source index it really came from."""
    import cv2

    path = tmp_path_factory.mktemp("video") / "synthetic.avi"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), FPS, (W, H))
    assert writer.isOpened()
    for i in range(N_FRAMES):
        writer.write(np.full((H, W, 3), 2 * i, np.uint8))
    writer.release()
    return str(path)


def _source_index(frame) -> float:
    return float(frame.image.mean()) / 2.0


def test_meta(synthetic_video):
    with FrameIterator(synthetic_video) as frames:
        meta = frames.meta
    assert meta.fps == pytest.approx(FPS)
    assert meta.frame_count == N_FRAMES
    assert (meta.width, meta.height) == (W, H)
    assert meta.duration_s == pytest.approx(3.0)


def test_sampling_stride_and_timestamps(synthetic_video):
    with FrameIterator(synthetic_video, sample_fps=10) as it:
        frames = list(it)
    assert len(frames) == 30  # 3s at 10fps
    assert [f.index for f in frames[:4]] == [0, 3, 6, 9]
    assert [f.sample_index for f in frames[:4]] == [0, 1, 2, 3]
    assert frames[1].t_video == pytest.approx(0.1, abs=1e-6)
    # pixel payload confirms the right source frames were kept (codec is
    # lossy, allow small drift)
    for f in frames:
        assert _source_index(f) == pytest.approx(f.index, abs=1.5)


def test_sample_fps_capped_at_source_fps(synthetic_video):
    with FrameIterator(synthetic_video, sample_fps=120) as it:
        frames = list(it)
    assert len(frames) == N_FRAMES
    assert it.stride == 1


def test_seek_and_duration_window(synthetic_video):
    with FrameIterator(synthetic_video, sample_fps=10, start_s=1.0, duration_s=1.0) as it:
        frames = list(it)
    assert [f.index for f in frames] == [30, 33, 36, 39, 42, 45, 48, 51, 54, 57]
    assert frames[0].t_video == pytest.approx(1.0)
    assert _source_index(frames[0]) == pytest.approx(30, abs=1.5)


def test_unopenable_source():
    with pytest.raises(IngestError, match="could not open"):
        FrameIterator("/nonexistent/file.mp4")


# ---- source resolution ------------------------------------------------------

def test_resolve_local_file(synthetic_video):
    src = resolve_source(synthetic_video)
    assert src.kind == "file" and not src.is_live


def test_resolve_direct_media_url():
    src = resolve_source("https://cdn.example.com/match.mp4")
    assert src.kind == "direct-url"
    assert src.location.endswith("match.mp4")


def test_resolve_garbage():
    with pytest.raises(IngestError, match="neither"):
        resolve_source("definitely-not-a-file-or-url")


def test_youtube_requires_ytdlp(monkeypatch):
    monkeypatch.setitem(sys.modules, "yt_dlp", None)  # forces ImportError
    with pytest.raises(IngestError, match="yt-dlp is required"):
        resolve_source("https://www.youtube.com/watch?v=abc123")


def _install_fake_ytdlp(monkeypatch, info):
    class FakeYDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def extract_info(self, url, download=False):
            assert download is False
            return info

    mod = types.ModuleType("yt_dlp")
    mod.YoutubeDL = FakeYDL
    monkeypatch.setitem(sys.modules, "yt_dlp", mod)


def test_youtube_live_resolution(monkeypatch):
    _install_fake_ytdlp(monkeypatch, {
        "url": "https://manifest.example/live.m3u8",
        "is_live": True,
        "title": "FRC District Event - Quals",
    })
    src = resolve_source("https://www.youtube.com/watch?v=abc123")
    assert src.kind == "youtube" and src.is_live
    assert src.location.endswith("live.m3u8")
    assert "Quals" in src.title


def test_youtube_playlist_rejected(monkeypatch):
    _install_fake_ytdlp(monkeypatch, {"_type": "playlist"})
    with pytest.raises(IngestError, match="playlist"):
        resolve_source("https://www.youtube.com/watch?v=abc&list=xyz")


def test_cli_ingest_probe_and_sample(synthetic_video, tmp_path, capsys):
    from frcscout.cli import main

    assert main(["ingest", "probe", synthetic_video]) == 0
    out = capsys.readouterr().out
    assert "64x48" in out and "3.0s" in out

    out_dir = tmp_path / "samples"
    assert main(["ingest", "sample", synthetic_video, "--fps", "2",
                 "--max", "4", "--out", str(out_dir)]) == 0
    jpgs = sorted(out_dir.glob("*.jpg"))
    assert len(jpgs) == 4
    assert jpgs[0].name.startswith("frame_0000000_t")

"""Track-lost events and the VLM frame provider."""

import json

import numpy as np
import pytest

from frcscout.pipeline import ScoutingPipeline
from frcscout.rubric.seed import seed_rubric
from frcscout.schedule.model import lineup_from_alliances

from test_vision import _field_frame, _six_robots, H, W

LINEUP = lineup_from_alliances("2026isde1_qm14", "2026isde1", "tba",
                               [1690, 2630, 3339], [5987, 1577, 4590])


def _minimal_config():
    return {"overlay": {"regions": {}}}


@pytest.fixture
def vanish_video(tmp_path):
    """6 robots; red robot 0 vanishes at t=3s and never returns."""
    import cv2

    path = tmp_path / "vanish.avi"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10, (W, H))
    for i in range(100):
        t = i / 10
        hide = {0} if t >= 3.0 else set()
        writer.write(_field_frame(_six_robots(t, hide=hide)))
    writer.release()
    return str(path)


def test_track_lost_event_emitted(vanish_video):
    pipeline = ScoutingPipeline(_minimal_config(), seed_rubric(), LINEUP)
    seen = []
    result = pipeline.run(vanish_video, sample_fps=10, on_event=seen.append)
    lost = [e for e in result.record["robots"][0]["events"]
            if e["type"] == "track_lost"] or [
        e for e in result.record["unattributed_events"] if e["type"] == "track_lost"]
    assert lost, "expected a track_lost event somewhere in the record"
    assert any(e.type == "track_lost" and e.alliance == "red" for e in seen)
    # emitted once, not every frame
    assert sum(1 for e in seen if e.type == "track_lost") == 1


def test_vlm_frame_provider_wired_and_crops():
    class DummyVlm:
        frame_provider = None

        def choose_scorer(self, candidates, context):
            return None, 0.0

    vlm = DummyVlm()
    pipeline = ScoutingPipeline(_minimal_config(), seed_rubric(), LINEUP, vlm=vlm)
    assert vlm.frame_provider is not None

    # simulate a processed frame + a live track
    pipeline._last_frame = _field_frame(_six_robots(0))
    pipeline.tracker.update(pipeline.detector.detect(pipeline._last_frame), 0.0, (H, W))
    tid = pipeline.tracker.tracks[0].track_id
    crop = vlm.frame_provider(tid, 0.0)
    assert crop is not None and crop.size > 0
    # padded beyond the raw 24x18 bumper box
    assert crop.shape[0] > 18 and crop.shape[1] > 24
    assert vlm.frame_provider(9999, 0.0) is None  # unknown track


def test_existing_frame_provider_not_overwritten():
    class ProviderVlm:
        def __init__(self):
            self.frame_provider = lambda tid, t: None

    vlm = ProviderVlm()
    original = vlm.frame_provider
    ScoutingPipeline(_minimal_config(), seed_rubric(), LINEUP, vlm=vlm)
    assert vlm.frame_provider is original

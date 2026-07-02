"""Hardening from the first real-broadcast run (2026flta_qm1 on Railway):
noisy footage spawned hundreds of junk tracks, which flooded the record with
track_lost events and made the identity solver combinatorially explode; and
long event VODs ran to end-of-file."""

import time
from types import SimpleNamespace

import numpy as np
import pytest

from frcscout.identify import TeamAssigner
from frcscout.pipeline import ScoutingPipeline
from frcscout.rubric.seed import seed_rubric
from frcscout.schedule.model import lineup_from_alliances
from frcscout.vision import ColorBlobDetector
from frcscout.vision.tracker import CONFIRMED, LOST, Track

RED = [1690, 2630, 3339]
BLUE = [5987, 1577, 4590]
LINEUP = lineup_from_alliances("2026isde1_qm14", "2026isde1", "tba", RED, BLUE)


# ---- identity solver must survive junk-track floods ----------------------------

def test_assigner_scales_to_hundreds_of_junk_tracks():
    assigner = TeamAssigner(LINEUP)
    for _ in range(4):
        assigner.add_ocr(1, "red", "1690", conf=0.9)
        assigner.add_ocr(2, "red", "2630", conf=0.9)
    # a noisy detector's junk: hundreds of tracks with a stray weak read each
    for tid in range(100, 400):
        assigner.add_ocr(tid, "red" if tid % 2 else "blue", "3339", conf=0.05)

    start = time.perf_counter()
    a = assigner.assignments()
    elapsed = time.perf_counter() - start
    assert elapsed < 1.0, f"solver took {elapsed:.2f}s with junk tracks"
    # the real evidence still wins
    assert a[1].team == 1690
    assert a[2].team == 2630


def test_assignments_cached_between_evidence():
    assigner = TeamAssigner(LINEUP)
    assigner.add_ocr(1, "red", "1690", conf=0.9)
    first = assigner.assignments()
    assert assigner.assignments() is first          # cache hit
    assigner.add_ocr(1, "red", "1690", conf=0.9)    # new evidence invalidates
    assert assigner.assignments() is not first


# ---- track_lost gating ------------------------------------------------------------

def _pipeline():
    return ScoutingPipeline({"overlay": {"regions": {}}}, seed_rubric(), LINEUP)


def _lost_track(tid, hits, alliance="red"):
    track = Track(track_id=tid, xyxy=(10, 10, 40, 30), state=LOST, hits=hits)
    track.alliance_votes[alliance] += 1
    return track


def test_short_lived_noise_tracks_dont_emit_track_lost():
    pipeline = _pipeline()
    pipeline.tracker.tracks = [_lost_track(tid, hits=3) for tid in range(1, 40)]
    frame = SimpleNamespace(t_video=50.0, index=1500)
    assert pipeline._track_lost_events(frame) == []


def test_only_identified_tracks_emit_track_lost():
    """Broadcast camera switches lose every live track constantly — only a
    robot we actually identified is worth a tracking-gap event."""
    pipeline = _pipeline()
    for _ in range(4):
        pipeline.assigner.add_ocr(7, "red", "1690", conf=0.9)
    pipeline.tracker.tracks = [
        _lost_track(5, hits=30),                 # long-lived but anonymous: silent
        _lost_track(7, hits=4),                  # identified as 1690: reported
        _lost_track(9, hits=3),                  # noise: silent
    ]
    frame = SimpleNamespace(t_video=50.0, index=1500)
    events = pipeline._track_lost_events(frame)
    assert {e.track_id for e in events} == {7}
    assert events[0].team == 1690


# ---- detector: sparse blobs are noise -----------------------------------------------

def test_sparse_red_blob_rejected():
    frame = np.full((240, 320, 3), (60, 130, 60), np.uint8)
    for i in range(0, 100, 2):                   # dotted diagonal, low fill
        frame[60 + i, 100 + i] = (30, 30, 220)
    assert ColorBlobDetector().detect(frame) == []


def test_solid_bumper_still_detected():
    frame = np.full((240, 320, 3), (60, 130, 60), np.uint8)
    frame[100:130, 100:140] = (30, 30, 220)
    (det,) = ColorBlobDetector().detect(frame)
    assert det.alliance == "red"


# ---- stop at match end ------------------------------------------------------------------

REGIONS = {
    "red_score":   [0.05, 0.03, 0.14, 0.12],
    "match_timer": [0.42, 0.03, 0.16, 0.12],
    "blue_score":  [0.80, 0.03, 0.14, 0.12],
}


@pytest.fixture
def video_with_long_tail(tmp_path):
    """Overlay-only broadcast: full match then 60s of dead post-match air."""
    import cv2

    def timer_text(t):
        if t < 20:
            return f"0:{20 - int(t):02d}"
        if t < 23:
            return "0:00"
        if t < 163:
            remaining = 140 - int(t - 23)
            return f"{remaining // 60}:{remaining % 60:02d}"
        return "0:00"

    path = tmp_path / "tail.avi"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 2, (640, 360))
    for i in range(223 * 2):  # 223s of video at 2fps
        t = i / 2
        frame = np.full((360, 640, 3), 25, np.uint8)
        frame[80:] = (60, 130, 60)
        for text, x in (("17", 40), (timer_text(t), 275), ("21", 520)):
            cv2.putText(frame, text, (x, 40), cv2.FONT_HERSHEY_SIMPLEX,
                        0.9, (240, 240, 240), 2)
        writer.write(frame)
    writer.release()
    return str(path)


def test_pipeline_stops_after_match_ends(video_with_long_tail):
    pipeline = ScoutingPipeline({"overlay": {"regions": REGIONS}},
                                seed_rubric(), LINEUP)
    result = pipeline.run(video_with_long_tail, sample_fps=2)
    # match ends ~163s + 5s confirmation; the 60s dead tail is skipped
    assert result.n_frames < 180 * 2
    assert pipeline.timeline.phase == "post_match"


def test_run_to_eof_still_available(video_with_long_tail):
    pipeline = ScoutingPipeline({"overlay": {"regions": REGIONS}},
                                seed_rubric(), LINEUP)
    result = pipeline.run(video_with_long_tail, sample_fps=2,
                          stop_at_match_end=False)
    assert result.n_frames == 223 * 2


def test_should_stop_hook(video_with_long_tail):
    pipeline = ScoutingPipeline({"overlay": {"regions": REGIONS}},
                                seed_rubric(), LINEUP)
    seen = {"n": 0}

    def stop_after_20():
        seen["n"] += 1
        return seen["n"] > 20

    result = pipeline.run(video_with_long_tail, sample_fps=2,
                          should_stop=stop_after_20)
    assert result.n_frames == 20
    assert result.record["match_key"] == "2026isde1_qm14"  # still aggregates

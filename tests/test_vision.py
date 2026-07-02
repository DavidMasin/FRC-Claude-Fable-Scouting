import numpy as np
import pytest

from frcscout.vision import ColorBlobDetector, Detection, IouTracker, iou
from frcscout.vision.tracker import CONFIRMED, LOST

W, H = 320, 240
RED_BGR = (30, 30, 220)
BLUE_BGR = (210, 90, 20)


def _field_frame(robots: list[tuple[float, float, str]]) -> np.ndarray:
    """robots: (center_x, center_y, alliance); 24x18 solid bumper rectangles
    on a green-carpet background."""
    frame = np.zeros((H, W, 3), np.uint8)
    frame[:] = (60, 130, 60)
    for cx, cy, alliance in robots:
        x0, y0 = int(cx - 12), int(cy - 9)
        frame[max(0, y0):y0 + 18, max(0, x0):x0 + 24] = \
            RED_BGR if alliance == "red" else BLUE_BGR
    return frame


def _six_robots(t: float, hide: set[int] = frozenset()) -> list[tuple[float, float, str]]:
    """3 red driving right along y=60, 3 blue driving left along y=180."""
    robots = []
    for i in range(3):
        robots.append((30 + 90 * i + 2.0 * t, 60.0, "red"))
    for i in range(3):
        robots.append((290 - 90 * i - 2.0 * t, 180.0, "blue"))
    return [r for j, r in enumerate(robots) if j not in hide]


# ---- geometry ---------------------------------------------------------------

def test_iou():
    assert iou((0, 0, 10, 10), (0, 0, 10, 10)) == pytest.approx(1.0)
    assert iou((0, 0, 10, 10), (5, 0, 15, 10)) == pytest.approx(1 / 3)
    assert iou((0, 0, 10, 10), (20, 20, 30, 30)) == 0.0


# ---- color detector ----------------------------------------------------------

def test_color_detector_finds_six_robots():
    dets = ColorBlobDetector().detect(_field_frame(_six_robots(0)))
    assert len(dets) == 6
    by_alliance = {a: sum(1 for d in dets if d.alliance == a) for a in ("red", "blue")}
    assert by_alliance == {"red": 3, "blue": 3}
    assert all(d.conf > 0.5 and d.label == "robot" for d in dets)


def test_color_detector_ignores_field_noise():
    frame = _field_frame([])
    frame[100:104, 100:104] = RED_BGR  # 16 px: below min area
    assert ColorBlobDetector().detect(frame) == []


# ---- tracker -----------------------------------------------------------------

def _run(tracker, frames_robots):
    detector = ColorBlobDetector()
    confirmed = []
    for t, robots in enumerate(frames_robots):
        dets = detector.detect(_field_frame(robots))
        confirmed = tracker.update(dets, float(t), (H, W))
    return confirmed


def test_tracker_confirms_six_stable_ids():
    tracker = IouTracker(min_hits=3)
    confirmed = _run(tracker, [_six_robots(t) for t in range(20)])
    assert len(confirmed) == 6
    assert {tr.alliance for tr in confirmed} == {"red", "blue"}
    # ids stable: same 6 ids at frame 5 and frame 20
    ids_now = {tr.track_id for tr in confirmed}
    confirmed_later = _run(tracker, [_six_robots(20 + t) for t in range(10)])
    assert {tr.track_id for tr in confirmed_later} == ids_now


def test_tracker_motion_follows_robot():
    tracker = IouTracker(min_hits=3)
    confirmed = _run(tracker, [_six_robots(t) for t in range(15)])
    red_leader = min((tr for tr in confirmed if tr.alliance == "red"),
                     key=lambda tr: tr.center[0])
    # robot 0 started at x=30 and drives right 2px/frame
    assert red_leader.center[0] == pytest.approx(30 + 2 * 14, abs=3)
    assert red_leader.velocity[0] == pytest.approx(2.0, abs=0.8)


def test_occlusion_goes_lost_then_reassociates_same_id():
    tracker = IouTracker(min_hits=3, max_missed=3, reassoc_window=60)
    _run(tracker, [_six_robots(t) for t in range(10)])
    lost_id = next(tr.track_id for tr in tracker.tracks
                   if tr.alliance == "red" and tr.center[0] < 80)

    # red robot 0 vanishes for 8 frames (occluded)
    _run(tracker, [_six_robots(10 + t, hide={0}) for t in range(8)])
    victim = next(tr for tr in tracker.tracks if tr.track_id == lost_id)
    assert victim.state == LOST
    assert len([tr for tr in tracker.tracks if tr.state == CONFIRMED]) == 5

    # it reappears roughly where it should be -> same identity, no new track
    _run(tracker, [_six_robots(18 + t) for t in range(5)])
    revived = next(tr for tr in tracker.tracks if tr.track_id == lost_id)
    assert revived.state == CONFIRMED
    assert len([tr for tr in tracker.tracks if tr.state == CONFIRMED]) == 6


def test_reassociation_respects_alliance_color():
    tracker = IouTracker(min_hits=2, max_missed=2, reassoc_dist_frac=1.0)
    # one red robot, confirmed, then gone
    _run(tracker, [[(100, 100, "red")]] * 4)
    _run(tracker, [[]] * 4)
    red_track = tracker.tracks[0]
    assert red_track.state == LOST
    # a blue robot appears exactly there: must NOT steal the red identity
    detector_frames = [[(100, 100, "blue")]] * 4
    _run(tracker, detector_frames)
    revived = [tr for tr in tracker.tracks if tr.track_id == red_track.track_id]
    assert not revived or revived[0].state == LOST
    blue_tracks = [tr for tr in tracker.tracks if tr.alliance == "blue"]
    assert blue_tracks and blue_tracks[0].track_id != red_track.track_id


def test_flicker_detection_never_confirms():
    tracker = IouTracker(min_hits=3)
    frames = [[(50, 50, "red")], [], [(200, 200, "blue")], [], [(120, 80, "red")], []]
    confirmed = _run(tracker, frames)
    assert confirmed == []


def test_low_conf_rescue():
    tracker = IouTracker(min_hits=2, high_conf=0.5, iou_threshold=0.2)
    strong = Detection(xyxy=(100, 100, 130, 120), conf=0.9, alliance="red")
    tracker.update([strong], 0.0, (H, W))
    tracker.update([strong], 1.0, (H, W))
    assert tracker.tracks[0].state == CONFIRMED
    # motion-blurred frame: only a weak detection where the robot is
    weak = Detection(xyxy=(102, 101, 132, 121), conf=0.3, alliance="red")
    confirmed = tracker.update([weak], 2.0, (H, W))
    assert confirmed and confirmed[0].time_since_update == 0
    # but a lone weak detection never births a track
    lone = Detection(xyxy=(200, 30, 230, 50), conf=0.3, alliance="blue")
    tracker.update([strong, lone], 3.0, (H, W))
    assert all(tr.alliance != "blue" for tr in tracker.tracks)


# ---- CLI + debug video ---------------------------------------------------------

def test_cli_track_with_debug_video(tmp_path, capsys):
    import cv2

    from frcscout.cli import main

    video = tmp_path / "field.avi"
    writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"MJPG"), 10, (W, H))
    for t in range(40):
        writer.write(_field_frame(_six_robots(t * 0.5)))
    writer.release()

    out_video = tmp_path / "debug.mp4"
    rc = main(["track", str(video), "--fps", "10", "--debug-video", str(out_video)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "confirmed tracks: 6 (red 3, blue 3, unknown 0)" in out
    assert "lost-track episodes: 0" in out

    cap = cv2.VideoCapture(str(out_video))
    assert cap.isOpened() and cap.get(cv2.CAP_PROP_FRAME_COUNT) == 40
    cap.release()

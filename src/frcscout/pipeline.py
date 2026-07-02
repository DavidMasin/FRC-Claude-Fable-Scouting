"""Full scouting pipeline: ingest → overlay → detect/track → identify →
field-map → events → aggregate.

One loop serves both modes: `replay` (deterministic VOD pass) and `live`
(tail the stream; the frame iterator drops frames to keep up and every stage
keys off video timestamps, so gaps are tolerated). Events stream out through
``on_event`` as they're confirmed (live JSONL) and the final per-match record
is built at the end.

Broadcast cuts/replays are a first-class problem: a scene cut pauses
detection, tracking, and attribution until the shot stabilizes (the overlay
timer also goes unreadable during replays, which keeps the phase machine
honest). Robots aren't where the last camera angle left them — better to
let tracks go LOST and re-associate than to hallucinate motion.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


class SceneGuard:
    """Cheap scene-cut detector: mean absolute difference of downscaled
    grayscale frames. A cut suspends vision stages for `cooldown` frames."""

    def __init__(self, threshold: float = 40.0, cooldown: int = 3) -> None:
        self.threshold = threshold
        self.cooldown = cooldown
        self._prev: np.ndarray | None = None
        self._hold = 0

    def stable(self, frame_bgr: np.ndarray) -> bool:
        import cv2

        small = cv2.cvtColor(cv2.resize(frame_bgr, (64, 36)), cv2.COLOR_BGR2GRAY)
        small = small.astype(np.float32)
        prev, self._prev = self._prev, small
        if prev is None:
            return True
        diff = float(np.abs(small - prev).mean())
        if diff > self.threshold:
            self._hold = self.cooldown
            return False
        if self._hold > 0:
            self._hold -= 1
            return False
        return True


@dataclass
class PipelineResult:
    record: dict
    n_frames: int
    n_unstable: int


class ScoutingPipeline:
    def __init__(self, config: dict, rubric: dict, lineup, detector=None,
                 vlm=None) -> None:
        from .events.engine import EventEngine
        from .identify.assignment import TeamAssigner
        from .overlay.ocr import get_backend
        from .overlay.timeline import OverlayTimeline
        from .vision import ColorBlobDetector, IouTracker

        self.config = config
        self.rubric = rubric
        self.lineup = lineup

        overlay_cfg = config.get("overlay") or {}
        self.regions = overlay_cfg.get("regions") or {}
        self.ocr = get_backend(overlay_cfg.get("ocr_backend", "template"))
        self.timeline = OverlayTimeline.from_rubric(rubric)
        # no configured regions -> find them from the stream itself
        self._autodetect_buf: list = []
        self._autodetect_failures = 0

        self.detector = detector or ColorBlobDetector()
        self.bumper_band = (0.0, 1.0) if detector is None else (0.55, 1.0)
        self.tracker = IouTracker()
        thresholds = config.get("thresholds") or {}
        self.assigner = TeamAssigner(
            lineup,
            min_conf=thresholds.get("assignment_min_conf", 0.6),
            reassign_margin=thresholds.get("ocr_reassign_margin", 0.25))
        self.scene_guard = SceneGuard()

        field_cfg = config.get("field") or {}
        self.fieldmap = None
        self.zonemap = None
        if (field_cfg.get("calibration") or {}).get("image_points"):
            from .field import FieldMap, ZoneMap

            self.fieldmap = FieldMap.from_config(field_cfg)
            self.zonemap = ZoneMap.from_config(field_cfg, rubric)

        field_len = (field_cfg.get("size_m") or [16.54, 8.07])[0]
        self.engine = EventEngine(rubric, vlm=vlm, field_length_m=field_len,
                                  red_on_left=field_cfg.get("red_on_left", True))
        self._seeded = False
        self._last_frame: np.ndarray | None = None
        self._lost_reported: set[int] = set()
        # a disambiguator built without a frame source gets ours
        if vlm is not None and getattr(vlm, "frame_provider", "n/a") is None:
            vlm.frame_provider = self._provide_crop

    def _provide_crop(self, track_id: int, t: float | None) -> np.ndarray | None:
        """Crop the most recent stable frame around a track (for the VLM)."""
        if self._last_frame is None:
            return None
        track = next((tr for tr in self.tracker.tracks
                      if tr.track_id == track_id), None)
        if track is None:
            return None
        h, w = self._last_frame.shape[:2]
        x0, y0, x1, y1 = track.xyxy
        pad_x, pad_y = 0.4 * (x1 - x0), 0.4 * (y1 - y0)
        x0, x1 = max(0, int(x0 - pad_x)), min(w, int(x1 + pad_x))
        y0, y1 = max(0, int(y0 - pad_y)), min(h, int(y1 + pad_y))
        if x1 <= x0 or y1 <= y0:
            return None
        return self._last_frame[y0:y1, x0:x1].copy()

    # ---- helpers -----------------------------------------------------------

    def _snapshots(self, confirmed):
        from .events.engine import TrackSnapshot

        assignments = self.assigner.assignments()
        snaps = []
        for tr in confirmed:
            field_xy = None
            zones: frozenset[str] = frozenset()
            if self.fieldmap is not None:
                field_xy = self.fieldmap.track_position(tr.xyxy)
            elif self.zonemap is not None:  # pixel-band mode: ground point in px
                x0, _, x1, y1 = tr.xyxy
                field_xy = ((x0 + x1) / 2, y1)
            if field_xy is not None and self.zonemap is not None:
                zones = frozenset(self.zonemap.zone_names_at(*field_xy))
            a = assignments.get(tr.track_id)
            snaps.append(TrackSnapshot(
                track_id=tr.track_id, alliance=tr.alliance,
                team=a.team if a else None, xyxy=tr.xyxy,
                field_xy=field_xy, zones=zones))
        return snaps

    def _maybe_autodetect_overlay(self, frame) -> None:
        """Accumulate spaced frames and locate the timer/score regions."""
        from .overlay.autodetect import autodetect_regions

        buf = self._autodetect_buf
        if buf and frame.t_video - buf[-1][0] < 1.5:
            return
        buf.append((frame.t_video, frame.image))
        if len(buf) < 5:
            return
        try:
            self.regions = autodetect_regions([f for _, f in buf], self.ocr)
            self._autodetect_buf = []
        except ValueError:
            self._autodetect_failures += 1
            buf.pop(0)  # slide the window toward live play

    def _activate_pixel_zones(self, confirmed, frame_shape) -> None:
        """No homography configured: fall back to pixel-band zones, with the
        red side inferred from where the red robots actually are."""
        from .field.autozones import infer_red_side, pixel_zone_map

        h, w = frame_shape
        self.zonemap = pixel_zone_map(w, h, infer_red_side(confirmed))
        # defense heuristics work in whatever units positions are in
        self.engine.field_length_m = float(w)
        self.engine.defense_dist_m = 0.12 * w

    def _track_lost_events(self, frame):
        from .events.model import ScoutingEvent
        from .vision.tracker import LOST

        events = []
        assignments = self.assigner.assignments()
        for tr in self.tracker.tracks:
            if tr.state == LOST and tr.track_id not in self._lost_reported:
                self._lost_reported.add(tr.track_id)
                a = assignments.get(tr.track_id)
                # only robots worth reporting: an identified track or one
                # that lived a while — short-lived noise blobs on real
                # footage would otherwise flood the record
                identified = a is not None and a.team is not None and a.confidence >= 0.3
                if not identified and tr.hits < 15:
                    continue
                events.append(ScoutingEvent(
                    t_video=frame.t_video, type="track_lost",
                    match_time_s=self.timeline.match_time(),
                    alliance=tr.alliance, track_id=tr.track_id,
                    team=a.team if a else None, conf=1.0, source="heuristic",
                    frame_index=frame.index, flags=("tracking_gap",)))
            elif tr.state != LOST:
                self._lost_reported.discard(tr.track_id)
        return events

    # ---- main loop ------------------------------------------------------------

    def run(self, source: str, sample_fps: float = 6.0, start_s: float = 0.0,
            duration_s: float | None = None, mode: str = "replay",
            on_event=None, debug_video: str | None = None,
            stop_at_match_end: bool = True, should_stop=None) -> PipelineResult:
        from .events.engine import FrameContext
        from .identify import read_bumper
        from .ingest import FrameIterator, resolve_source
        from .overlay.parse import read_overlay
        from .overlay.timeline import POST_MATCH, ScoreChange
        from .vision.debug import DebugVideoWriter, draw_tracks

        src = resolve_source(source)
        live = mode == "live" or src.is_live
        writer = None
        n_frames = 0
        n_unstable = 0
        last_t = 0.0
        post_match_since: float | None = None
        try:
            with FrameIterator(src.location, sample_fps=sample_fps, start_s=start_s,
                               duration_s=duration_s, live=live) as frames:
                for frame in frames:
                    if should_stop is not None and should_stop():
                        break
                    n_frames += 1
                    last_t = frame.t_video
                    # overlay first: it works even during replays/cuts
                    if not self.regions:
                        self._maybe_autodetect_overlay(frame)
                    score_changes = []
                    if self.regions:
                        reading = read_overlay(frame.image, frame.t_video,
                                               self.regions, self.ocr)
                        tl_events = self.timeline.add(reading)
                        score_changes = [e for e in tl_events
                                         if isinstance(e, ScoreChange)]

                    # one match scouted, stop — event VODs run for hours
                    if stop_at_match_end:
                        if self.timeline.phase == POST_MATCH:
                            post_match_since = post_match_since or frame.t_video
                            if frame.t_video - post_match_since > 5.0:
                                break
                        else:
                            post_match_since = None

                    if not self.scene_guard.stable(frame.image):
                        n_unstable += 1
                        continue  # cut/replay: no tracking, no attribution

                    self._last_frame = frame.image
                    confirmed = self.tracker.update(
                        self.detector.detect(frame.image), frame.t_video,
                        frame.image.shape[:2])

                    # a confirmed robot going LOST is itself an observation:
                    # downstream sees the gap instead of trusting silence
                    for ev in self._track_lost_events(frame):
                        self.engine.events.append(ev)
                        if on_event is not None:
                            on_event(ev)

                    if not self._seeded and len(confirmed) == 6:
                        self.assigner.seed_station_prior(confirmed)
                        if self.fieldmap is None and self.zonemap is None:
                            self._activate_pixel_zones(confirmed,
                                                       frame.image.shape[:2])
                        self._seeded = True
                    # OCR the longest-lived tracks first, capped — noisy
                    # footage can confirm dozens of junk tracks per frame
                    for tr in sorted(confirmed, key=lambda t: t.hits,
                                     reverse=True)[:12]:
                        digits, conf = read_bumper(frame.image, tr.xyxy, self.ocr,
                                                   band=self.bumper_band)
                        if digits and tr.alliance:
                            self.assigner.add_ocr(tr.track_id, tr.alliance,
                                                  digits, conf)

                    ctx = FrameContext(
                        t_video=frame.t_video, frame_index=frame.index,
                        phase=self.timeline.phase,
                        match_time_s=self.timeline.match_time(),
                        tracks=self._snapshots(confirmed),
                        score_changes=score_changes)
                    for ev in self.engine.step(ctx):
                        if on_event is not None:
                            on_event(ev)

                    if debug_video:
                        if writer is None:
                            h, w = frame.image.shape[:2]
                            writer = DebugVideoWriter(debug_video, sample_fps, (w, h))
                        writer.write(draw_tracks(frame.image, self.tracker.tracks,
                                                 self.assigner.team_labels()))
        finally:
            if writer is not None:
                writer.close()

        record = self.build_record(match_end_t=last_t)
        return PipelineResult(record=record, n_frames=n_frames, n_unstable=n_unstable)

    def build_record(self, match_end_t: float | None = None) -> dict:
        from .aggregate import build_match_record

        team_conf: dict[int, float] = {}
        for a in self.assigner.assignments().values():
            if a.team is not None:
                team_conf[a.team] = max(team_conf.get(a.team, 0.0), a.confidence)
        return build_match_record(
            match_key=self.lineup.match_key, lineup=self.lineup,
            events=self.engine.events, assignment_confidences=team_conf,
            final_scores=dict(self.timeline.scores), rubric=self.rubric,
            match_end_t=match_end_t)

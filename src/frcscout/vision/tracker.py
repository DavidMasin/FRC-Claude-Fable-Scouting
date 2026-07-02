"""ByteTrack-style IoU tracker with explicit lost-track handling.

Association is two-stage (high-confidence detections first, then
low-confidence ones rescue unmatched tracks — the ByteTrack idea), greedy on
IoU with a constant-velocity prediction. Tracks that stop matching become
LOST — visible state, no fabricated positions — and can be *re-associated*
later by alliance color + proximity (robots leave frame / get occluded and
come back). An alliance-color mismatch always vetoes a match.

This is deliberately dependency-free; swapping in BoT-SORT/ByteTrack from
ultralytics later only has to reproduce the Track interface.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from .detections import Detection, iou

TENTATIVE = "tentative"
CONFIRMED = "confirmed"
LOST = "lost"
DEAD = "dead"


@dataclass
class Track:
    track_id: int
    xyxy: tuple[float, float, float, float]
    state: str = TENTATIVE
    hits: int = 1
    time_since_update: int = 0
    velocity: tuple[float, float] = (0.0, 0.0)
    alliance_votes: Counter = field(default_factory=Counter)
    last_t: float = 0.0

    @property
    def alliance(self) -> str | None:
        if not self.alliance_votes:
            return None
        return self.alliance_votes.most_common(1)[0][0]

    @property
    def center(self) -> tuple[float, float]:
        x0, y0, x1, y1 = self.xyxy
        return ((x0 + x1) / 2, (y0 + y1) / 2)

    def predicted_box(self) -> tuple[float, float, float, float]:
        dx, dy = self.velocity
        steps = self.time_since_update + 1
        x0, y0, x1, y1 = self.xyxy
        return (x0 + dx * steps, y0 + dy * steps, x1 + dx * steps, y1 + dy * steps)

    def _apply(self, det: Detection, t: float, alpha: float = 0.6) -> None:
        old_cx, old_cy = self.center
        self.xyxy = det.xyxy
        new_cx, new_cy = self.center
        self.velocity = (
            alpha * (new_cx - old_cx) / max(1, self.time_since_update + 1)
            + (1 - alpha) * self.velocity[0],
            alpha * (new_cy - old_cy) / max(1, self.time_since_update + 1)
            + (1 - alpha) * self.velocity[1],
        )
        if det.alliance:
            self.alliance_votes[det.alliance] += 1
        self.hits += 1
        self.time_since_update = 0
        self.last_t = t


class IouTracker:
    def __init__(self, iou_threshold: float = 0.25, min_hits: int = 3,
                 max_missed: int = 12, reassoc_window: int = 120,
                 reassoc_dist_frac: float = 0.15, high_conf: float = 0.5) -> None:
        self.iou_threshold = iou_threshold
        self.min_hits = min_hits
        self.max_missed = max_missed          # missed updates before CONFIRMED -> LOST
        self.reassoc_window = reassoc_window  # missed updates before LOST -> DEAD
        self.reassoc_dist_frac = reassoc_dist_frac  # of frame diagonal
        self.high_conf = high_conf
        self.tracks: list[Track] = []
        self._next_id = 1

    # ---- helpers ------------------------------------------------------------

    def _greedy_match(self, tracks: list[Track], dets: list[Detection]
                      ) -> list[tuple[Track, Detection]]:
        pairs = []
        for track in tracks:
            box = track.predicted_box()
            for det in dets:
                if det.alliance and track.alliance and det.alliance != track.alliance:
                    continue  # color veto
                score = iou(box, det.xyxy)
                if score >= self.iou_threshold:
                    pairs.append((score, track, det))
        pairs.sort(key=lambda p: p[0], reverse=True)
        matched, used_t, used_d = [], set(), set()
        for _, track, det in pairs:
            if id(track) in used_t or id(det) in used_d:
                continue
            used_t.add(id(track))
            used_d.add(id(det))
            matched.append((track, det))
        return matched

    def _reassociate(self, dets: list[Detection], diag: float, t: float) -> list[Detection]:
        """Give LOST tracks a chance to claim unmatched detections by
        alliance + proximity to last known position."""
        remaining = list(dets)
        for track in (tr for tr in self.tracks if tr.state == LOST):
            best, best_d = None, self.reassoc_dist_frac * diag
            for det in remaining:
                if det.alliance and track.alliance and det.alliance != track.alliance:
                    continue
                cx, cy = det.center
                tx, ty = track.center
                d = ((cx - tx) ** 2 + (cy - ty) ** 2) ** 0.5
                if d < best_d:
                    best, best_d = det, d
            if best is not None:
                track._apply(best, t)
                track.state = CONFIRMED
                remaining.remove(best)
        return remaining

    # ---- public --------------------------------------------------------------

    def update(self, detections: list[Detection], t: float,
               frame_shape: tuple[int, int] | None = None) -> list[Track]:
        """Advance one sampled frame; returns currently confirmed tracks."""
        robots = [d for d in detections if d.label == "robot"]
        high = [d for d in robots if d.conf >= self.high_conf]
        low = [d for d in robots if d.conf < self.high_conf]
        diag = ((frame_shape[0] ** 2 + frame_shape[1] ** 2) ** 0.5
                if frame_shape else 800.0)

        active = [tr for tr in self.tracks if tr.state in (TENTATIVE, CONFIRMED)]

        # stage 1: high-confidence detections vs active tracks
        matched = self._greedy_match(active, high)
        matched_tracks = {id(tr) for tr, _ in matched}
        matched_dets = {id(d) for _, d in matched}
        # stage 2: leftover active tracks rescued by low-confidence detections
        leftover_tracks = [tr for tr in active if id(tr) not in matched_tracks]
        rescued = self._greedy_match(leftover_tracks, low)
        matched += rescued
        matched_tracks |= {id(tr) for tr, _ in rescued}

        for track, det in matched:
            track._apply(det, t)
            if track.state == TENTATIVE and track.hits >= self.min_hits:
                track.state = CONFIRMED

        # unmatched active tracks age out
        for track in active:
            if id(track) not in matched_tracks:
                track.time_since_update += 1
                if track.state == TENTATIVE:
                    track.state = DEAD  # never confirmed: drop quickly
                elif track.time_since_update > self.max_missed:
                    track.state = LOST

        # unmatched high-conf detections: try LOST re-association, then new tracks
        unmatched_high = [d for d in high if id(d) not in matched_dets]
        for det in self._reassociate(unmatched_high, diag, t):
            track = Track(track_id=self._next_id, xyxy=det.xyxy, last_t=t)
            if det.alliance:
                track.alliance_votes[det.alliance] += 1
            self._next_id += 1
            self.tracks.append(track)

        # LOST tracks eventually die
        for track in self.tracks:
            if track.state == LOST:
                track.time_since_update += 1
                if track.time_since_update > self.reassoc_window:
                    track.state = DEAD
        self.tracks = [tr for tr in self.tracks if tr.state != DEAD]

        return [tr for tr in self.tracks if tr.state == CONFIRMED]

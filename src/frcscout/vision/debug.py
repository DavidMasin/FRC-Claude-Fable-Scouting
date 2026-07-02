"""Debug overlay renderer: boxes, track IDs, alliance, state — the
human-verification surface every milestone ships with."""

from __future__ import annotations

import numpy as np

from .tracker import CONFIRMED, LOST, Track

_COLORS = {"red": (60, 60, 230), "blue": (230, 140, 40), None: (200, 200, 200)}


def draw_tracks(frame: np.ndarray, tracks: list[Track],
                team_labels: dict[int, str] | None = None) -> np.ndarray:
    import cv2

    out = frame.copy()
    for track in tracks:
        if track.state not in (CONFIRMED, LOST):
            continue
        color = _COLORS.get(track.alliance, _COLORS[None])
        x0, y0, x1, y1 = (int(v) for v in track.xyxy)
        if track.state == LOST:
            # dashed-ish box at last known position; make lost state obvious
            cv2.rectangle(out, (x0, y0), (x1, y1), color, 1, cv2.LINE_4)
            label = f"#{track.track_id} LOST"
        else:
            cv2.rectangle(out, (x0, y0), (x1, y1), color, 2)
            label = f"#{track.track_id}"
        if team_labels and track.track_id in team_labels:
            label += f" {team_labels[track.track_id]}"
        cv2.putText(out, label, (x0, max(12, y0 - 4)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1)
    return out


class DebugVideoWriter:
    def __init__(self, path: str, fps: float, size: tuple[int, int]) -> None:
        import cv2

        self._writer = cv2.VideoWriter(
            path, cv2.VideoWriter_fourcc(*"mp4v"), fps, size)
        if not self._writer.isOpened():
            raise RuntimeError(f"could not open video writer for {path}")

    def write(self, frame: np.ndarray) -> None:
        self._writer.write(frame)

    def close(self) -> None:
        self._writer.release()

    def __enter__(self) -> "DebugVideoWriter":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

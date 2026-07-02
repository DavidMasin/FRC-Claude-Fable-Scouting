"""Frame iteration at a reduced sampling FPS.

Detection runs at 5-10 fps and the tracker interpolates between, so the
iterator's job is to hand downstream stages evenly spaced frames stamped with
video time. Two modes:

- replay (VOD): deterministic — every Nth source frame, seekable via
  start_s/duration_s (long event VODs contain many matches).
- live: read as fast as the stream delivers, *drop* frames to hold the target
  rate rather than falling behind; gaps show up as jumps in t_video, which
  downstream stages must tolerate (they already key off timestamps, not
  frame counts).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

import numpy as np

from .errors import IngestError


@dataclass
class Frame:
    image: np.ndarray      # BGR
    index: int             # source-stream frame index
    t_video: float         # seconds since start of the *source* video
    sample_index: int      # 0,1,2,... within this iteration


@dataclass(frozen=True)
class VideoMeta:
    fps: float
    frame_count: int | None    # None when unknown (live)
    width: int
    height: int
    duration_s: float | None


class FrameIterator:
    def __init__(
        self,
        location: str,
        sample_fps: float = 6.0,
        start_s: float = 0.0,
        duration_s: float | None = None,
        live: bool = False,
    ) -> None:
        import cv2

        self._cv2 = cv2
        self.cap = cv2.VideoCapture(location)
        if not self.cap.isOpened():
            raise IngestError(f"could not open video source: {location}")

        src_fps = self.cap.get(cv2.CAP_PROP_FPS)
        # Live/HLS sources sometimes report 0 or garbage; assume broadcast 30.
        self.src_fps = src_fps if 1.0 <= src_fps <= 240.0 else 30.0
        count = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.meta = VideoMeta(
            fps=self.src_fps,
            frame_count=count if count > 0 else None,
            width=int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
            height=int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
            duration_s=count / self.src_fps if count > 0 else None,
        )

        self.sample_fps = min(sample_fps, self.src_fps)
        self.stride = max(1, round(self.src_fps / self.sample_fps))
        self.live = live
        self.start_s = start_s
        self.duration_s = duration_s

        self._start_index = int(round(start_s * self.src_fps))
        self._end_index: int | None = None
        if duration_s is not None:
            self._end_index = self._start_index + int(round(duration_s * self.src_fps))

    def __iter__(self) -> Iterator[Frame]:
        cv2 = self._cv2
        if self._start_index and not self.live:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, self._start_index)
        index = self._start_index
        next_keep = index
        sample_index = 0
        while True:
            ok, image = self.cap.read()
            if not ok:
                break  # EOF (VOD) or stream stall/end (live)
            if self._end_index is not None and index >= self._end_index:
                break
            if index >= next_keep:
                yield Frame(
                    image=image,
                    index=index,
                    t_video=index / self.src_fps,
                    sample_index=sample_index,
                )
                sample_index += 1
                # Schedule the next kept frame; in live mode intervening
                # frames are still read (and discarded) to stay at the tail.
                next_keep += self.stride
            index += 1

    def close(self) -> None:
        self.cap.release()

    def __enter__(self) -> "FrameIterator":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

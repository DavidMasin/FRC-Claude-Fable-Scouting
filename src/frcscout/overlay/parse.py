"""Turn raw OCR strings into structured overlay readings."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np

from .regions import crop_region

_TIMER_RE = re.compile(r"^(?:(\d{1,2}):)?(\d{1,3})$")


def parse_timer(text: str) -> float | None:
    """'2:07' -> 127, '0:15' -> 15, '15' -> 15. None when unparseable."""
    m = _TIMER_RE.match(text.strip())
    if not m:
        return None
    minutes = int(m.group(1)) if m.group(1) else 0
    seconds = int(m.group(2))
    if m.group(1) and seconds >= 60:
        return None
    value = minutes * 60 + seconds
    return float(value) if value <= 10 * 60 else None


def parse_score(text: str) -> int | None:
    digits = text.strip()
    if not digits.isdigit():
        return None
    value = int(digits)
    return value if value <= 999 else None


@dataclass
class OverlayReading:
    t_video: float
    timer_s: float | None
    red: int | None
    blue: int | None
    raw: dict = field(default_factory=dict)   # region -> (text, confidence)


def read_overlay(frame: np.ndarray, t_video: float, regions: dict, backend) -> OverlayReading:
    """OCR the configured overlay regions of one frame."""
    raw: dict[str, tuple[str, float]] = {}
    values: dict[str, str] = {}
    for name in ("match_timer", "red_score", "blue_score"):
        box = regions.get(name)
        if box is None:
            continue
        result = backend.read_text(crop_region(frame, box))
        raw[name] = (result.text, result.confidence)
        values[name] = result.text
    return OverlayReading(
        t_video=t_video,
        timer_s=parse_timer(values.get("match_timer", "")),
        red=parse_score(values.get("red_score", "")),
        blue=parse_score(values.get("blue_score", "")),
        raw=raw,
    )

"""Calibration-free zones, in pixel space.

Without a homography the pipeline can still reason coarsely about *where*
robots are: the broadcast game camera frames the field left-to-right, so the
frame splits into three vertical bands — each alliance's side and a neutral
middle. Which side is red is inferred from where the red robots actually are
when tracking first locks on (their own half, at match start).

Zone semantics map onto the bands: an alliance's hub and tower live on its
side (scoring/endgame roles share the band — attribution is coarser than
with a measured homography, and events carry the same confidences either
way), and its loading zone is the far side. This trades precision for zero
setup; calibrate `field.calibration` when you want real field coordinates.
"""

from __future__ import annotations

from .zones import Zone, ZoneMap

SIDE_FRAC = 0.34  # width of each alliance band


def infer_red_side(tracks) -> str:
    """'left' or 'right', from mean x of red vs blue confirmed tracks."""
    red = [tr.center[0] for tr in tracks if tr.alliance == "red"]
    blue = [tr.center[0] for tr in tracks if tr.alliance == "blue"]
    if not red or not blue:
        return "left"
    return "left" if sum(red) / len(red) <= sum(blue) / len(blue) else "right"


def pixel_zone_map(frame_w: int, frame_h: int, red_side: str = "left") -> ZoneMap:
    def band(x0: float, x1: float) -> tuple[tuple[float, float], ...]:
        return ((x0, 0.0), (x1, 0.0), (x1, float(frame_h)), (x0, float(frame_h)))

    left = band(0.0, SIDE_FRAC * frame_w)
    right = band((1 - SIDE_FRAC) * frame_w, float(frame_w))
    middle = band(SIDE_FRAC * frame_w, (1 - SIDE_FRAC) * frame_w)
    red_band, blue_band = (left, right) if red_side == "left" else (right, left)

    return ZoneMap([
        Zone("hub_zone_red", red_band, role="scoring", alliance="red"),
        Zone("tower_zone_red", red_band, role="endgame", alliance="red"),
        Zone("loading_zone_red", blue_band, role="acquisition", alliance="red"),
        Zone("hub_zone_blue", blue_band, role="scoring", alliance="blue"),
        Zone("tower_zone_blue", blue_band, role="endgame", alliance="blue"),
        Zone("loading_zone_blue", red_band, role="acquisition", alliance="blue"),
        Zone("neutral_zone", middle, role="transit", alliance=None),
    ])

"""Pixel → field-coordinate mapping.

A per-camera homography is calibrated from ≥4 point correspondences between
broadcast pixels and field coordinates (meters, origin at the red-alliance
right corner, x along the long axis — the convention used by the zone
polygons in config). Correspondences come from clicking known landmarks
(tower bases, hub corners, field perimeter marks) on one representative
frame; they live in config under ``field.calibration``.

Robots are mapped through their ground contact point — the bottom-center of
the bounding box — since the homography is only valid on the floor plane.
"""

from __future__ import annotations

import numpy as np


class CalibrationError(ValueError):
    """Bad or insufficient calibration points."""


class FieldMap:
    def __init__(self, matrix: np.ndarray, field_size: tuple[float, float]) -> None:
        self.matrix = matrix.astype(np.float64)
        self.field_size = field_size

    @classmethod
    def from_points(cls, image_points: list[list[float]],
                    field_points: list[list[float]],
                    field_size: tuple[float, float] = (16.54, 8.07)) -> "FieldMap":
        import cv2

        if len(image_points) != len(field_points):
            raise CalibrationError("image_points and field_points differ in length")
        if len(image_points) < 4:
            raise CalibrationError("need at least 4 point correspondences")
        src = np.array(image_points, np.float64)
        dst = np.array(field_points, np.float64)
        matrix, _ = cv2.findHomography(src, dst, method=0)
        if matrix is None:
            raise CalibrationError("homography estimation failed (degenerate points?)")
        return cls(matrix, field_size)

    @classmethod
    def from_config(cls, field_config: dict) -> "FieldMap":
        calib = field_config.get("calibration") or {}
        size = tuple(field_config.get("size_m", (16.54, 8.07)))
        return cls.from_points(calib.get("image_points", []),
                               calib.get("field_points", []), size)

    def to_field(self, px: float, py: float) -> tuple[float, float]:
        v = self.matrix @ np.array([px, py, 1.0])
        if abs(v[2]) < 1e-9:
            raise CalibrationError(f"point ({px}, {py}) maps to infinity")
        return (float(v[0] / v[2]), float(v[1] / v[2]))

    def track_position(self, xyxy: tuple[float, float, float, float]) -> tuple[float, float]:
        """Field position of a robot box via its ground contact point."""
        x0, _, x1, y1 = xyxy
        return self.to_field((x0 + x1) / 2, y1)

    def in_bounds(self, fx: float, fy: float, margin: float = 1.0) -> bool:
        w, h = self.field_size
        return -margin <= fx <= w + margin and -margin <= fy <= h + margin

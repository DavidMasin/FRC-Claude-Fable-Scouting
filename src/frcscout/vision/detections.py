from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Detection:
    xyxy: tuple[float, float, float, float]
    conf: float
    label: str = "robot"          # robot | fuel
    alliance: str | None = None   # red | blue | None (unknown)

    @property
    def center(self) -> tuple[float, float]:
        x0, y0, x1, y1 = self.xyxy
        return ((x0 + x1) / 2, (y0 + y1) / 2)

    @property
    def area(self) -> float:
        x0, y0, x1, y1 = self.xyxy
        return max(0.0, x1 - x0) * max(0.0, y1 - y0)


def iou(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    ix0, iy0 = max(a[0], b[0]), max(a[1], b[1])
    ix1, iy1 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
    if inter == 0.0:
        return 0.0
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    return inter / (area_a + area_b - inter)

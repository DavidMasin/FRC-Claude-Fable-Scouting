"""Field zones: named polygons in field coordinates.

Zone *names and roles* come from rubric.json (the manual owns semantics);
zone *geometry* is per-config (field drawings + how the venue laid out the
polygons). ``ZoneMap.from_config`` validates that every configured zone name
exists in the rubric's zone list, so a typo can't silently orphan zone logic.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Zone:
    name: str
    polygon: tuple[tuple[float, float], ...]  # field coords (meters)
    role: str | None = None                   # scoring | endgame | acquisition | transit
    alliance: str | None = None

    def contains(self, x: float, y: float) -> bool:
        """Ray-casting point-in-polygon (edges count as inside)."""
        inside = False
        pts = self.polygon
        n = len(pts)
        for i in range(n):
            (x0, y0), (x1, y1) = pts[i], pts[(i + 1) % n]
            # on-edge check via collinearity + bounding box
            cross = (x1 - x0) * (y - y0) - (y1 - y0) * (x - x0)
            if abs(cross) < 1e-9 and min(x0, x1) - 1e-9 <= x <= max(x0, x1) + 1e-9 \
                    and min(y0, y1) - 1e-9 <= y <= max(y0, y1) + 1e-9:
                return True
            if (y0 > y) != (y1 > y):
                t = (y - y0) / (y1 - y0)
                if x < x0 + t * (x1 - x0):
                    inside = not inside
        return inside


class ZoneMap:
    def __init__(self, zones: list[Zone]) -> None:
        self.zones = zones
        self._by_name = {z.name: z for z in zones}

    @classmethod
    def from_config(cls, field_config: dict, rubric: dict | None = None) -> "ZoneMap":
        semantic = {}
        if rubric is not None:
            semantic = {z["name"]: z for z in rubric.get("zones", [])}
        zones = []
        for name, polygon in (field_config.get("zones") or {}).items():
            if semantic and name not in semantic:
                raise ValueError(
                    f"zone {name!r} not declared in the rubric; known: {sorted(semantic)}")
            meta = semantic.get(name, {})
            zones.append(Zone(
                name=name,
                polygon=tuple((float(x), float(y)) for x, y in polygon),
                role=meta.get("role"),
                alliance=meta.get("alliance"),
            ))
        return cls(zones)

    def __getitem__(self, name: str) -> Zone:
        return self._by_name[name]

    def zones_at(self, x: float, y: float) -> list[Zone]:
        return [z for z in self.zones if z.contains(x, y)]

    def zone_names_at(self, x: float, y: float) -> set[str]:
        return {z.name for z in self.zones_at(x, y)}

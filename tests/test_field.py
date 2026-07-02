import numpy as np
import pytest

from frcscout.field import FieldMap, Zone, ZoneMap
from frcscout.field.homography import CalibrationError
from frcscout.rubric.seed import seed_rubric

FIELD_W, FIELD_H = 16.54, 8.07

# A synthetic camera: field corners land at these pixels (simple projective
# view — top edge shorter than bottom, like a real elevated broadcast cam).
IMAGE_POINTS = [[200, 100], [1080, 100], [1240, 660], [40, 660]]
FIELD_POINTS = [[0, 0], [FIELD_W, 0], [FIELD_W, FIELD_H], [0, FIELD_H]]


@pytest.fixture(scope="module")
def fmap():
    return FieldMap.from_points(IMAGE_POINTS, FIELD_POINTS)


def test_corners_roundtrip(fmap):
    for (px, py), (fx, fy) in zip(IMAGE_POINTS, FIELD_POINTS):
        got = fmap.to_field(px, py)
        assert got == pytest.approx((fx, fy), abs=1e-6)


def test_interior_point_is_inside(fmap):
    fx, fy = fmap.to_field(640, 400)
    assert 0 < fx < FIELD_W and 0 < fy < FIELD_H
    assert fmap.in_bounds(fx, fy)


def test_track_position_uses_ground_point(fmap):
    # a robot box whose bottom-center is the image bottom-center
    fx, fy = fmap.track_position((600, 500, 680, 660))
    direct = fmap.to_field(640, 660)
    assert (fx, fy) == pytest.approx(direct)


def test_calibration_validation():
    with pytest.raises(CalibrationError, match="at least 4"):
        FieldMap.from_points(IMAGE_POINTS[:3], FIELD_POINTS[:3])
    with pytest.raises(CalibrationError, match="differ in length"):
        FieldMap.from_points(IMAGE_POINTS, FIELD_POINTS[:3])


def test_from_config():
    fmap = FieldMap.from_config({
        "size_m": [FIELD_W, FIELD_H],
        "calibration": {"image_points": IMAGE_POINTS, "field_points": FIELD_POINTS},
    })
    assert fmap.to_field(200, 100) == pytest.approx((0, 0), abs=1e-6)


# ---- zones -------------------------------------------------------------------

SQUARE = Zone("test", ((0, 0), (4, 0), (4, 4), (0, 4)))


@pytest.mark.parametrize("point,inside", [
    ((2, 2), True), ((0, 0), True), ((4, 2), True),   # interior + edges
    ((5, 2), False), ((-0.1, 2), False), ((2, 4.5), False),
])
def test_zone_contains(point, inside):
    assert SQUARE.contains(*point) is inside


def test_zone_concave_polygon():
    # L-shape: the notch must be outside
    zone = Zone("L", ((0, 0), (4, 0), (4, 2), (2, 2), (2, 4), (0, 4)))
    assert zone.contains(1, 3)
    assert not zone.contains(3, 3)


def test_zonemap_from_config_with_rubric():
    field_config = {"zones": {
        "hub_zone_red": [[0, 2], [3, 2], [3, 6], [0, 6]],
        "neutral_zone": [[5.5, 0], [11, 0], [11, 8.07], [5.5, 8.07]],
    }}
    zmap = ZoneMap.from_config(field_config, seed_rubric())
    assert zmap["hub_zone_red"].role == "scoring"
    assert zmap["hub_zone_red"].alliance == "red"
    assert zmap.zone_names_at(1.0, 3.0) == {"hub_zone_red"}
    assert zmap.zone_names_at(8.0, 4.0) == {"neutral_zone"}
    assert zmap.zone_names_at(4.0, 1.0) == set()


def test_zonemap_rejects_unknown_zone_names():
    with pytest.raises(ValueError, match="not declared in the rubric"):
        ZoneMap.from_config({"zones": {"lasagna_zone": [[0, 0], [1, 0], [1, 1]]}},
                            seed_rubric())


def test_cli_field_locate(tmp_path, capsys):
    import yaml

    from frcscout.cli import main

    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump({
        "rubric_path": str(tmp_path / "absent.json"),
        "field": {
            "size_m": [FIELD_W, FIELD_H],
            "calibration": {"image_points": IMAGE_POINTS,
                            "field_points": FIELD_POINTS},
            "zones": {"neutral_zone": [[5.5, 0], [11, 0], [11, 8.07], [5.5, 8.07]]},
        },
    }))
    assert main(["field", "locate", "--config", str(config), "--pixel", "640,400"]) == 0
    out = capsys.readouterr().out
    assert "field (" in out and "neutral_zone" in out

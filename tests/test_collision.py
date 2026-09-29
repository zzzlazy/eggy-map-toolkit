import pytest

from eggy_map_api.collision import (
    VECTOR_MARKER,
    build_static_obstacle,
    quaternion_from_zxy_degrees,
)


def test_static_obstacle_uses_world_transform_and_zxy_quaternion() -> None:
    unit = {
        b"unit_id": 1_000_000_041,
        b"model": 42,
        b"position": [1.0, 2.0, 3.0],
        b"world_position": [4.0, 5.0, 6.0],
        b"model_angle": [0.0, 90.0, 0.0],
        b"scale": [9.0, 9.0, 9.0],
        b"real_scale": [2.0, 3.0, 4.0],
        b"occlusion_type": 1,
    }
    record = build_static_obstacle(unit)
    assert record[b"Position"] == [4.0, 5.0, 6.0, VECTOR_MARKER]
    assert record[b"Scale"] == [2.0, 3.0, 4.0, VECTOR_MARKER]
    assert record[b"Rotation"][:4] == pytest.approx((0.0, 2**-0.5, 0.0, 2**-0.5))
    assert record[b"CameraNoOverlap"] is True


def test_zxy_quaternion_matches_recovered_rotation_order() -> None:
    assert quaternion_from_zxy_degrees((48.5904, -49.1066, -70.8934)) == pytest.approx(
        (0.5245191467, -0.0915061701, -0.3415063161, 0.7745190263),
        abs=1e-7,
    )

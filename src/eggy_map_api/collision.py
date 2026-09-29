from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from .errors import CapabilityError

VECTOR_MARKER = b"\x11"


def _get(mapping: Mapping[Any, Any], key: str, default: Any = None) -> Any:
    return mapping.get(key, mapping.get(key.encode(), default))


def _finite_vec3(value: Any, label: str) -> tuple[float, float, float]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes))
        or len(value) < 3
        or not all(
            type(item) in (int, float) and math.isfinite(item) for item in value[:3]
        )
    ):
        raise CapabilityError(f"{label} must be a finite three-number vector")
    return tuple(float(item) for item in value[:3])  # type: ignore[return-value]


def _quaternion_multiply(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    lx, ly, lz, lw = left
    rx, ry, rz, rw = right
    return (
        lw * rx + lx * rw + ly * rz - lz * ry,
        lw * ry - lx * rz + ly * rw + lz * rx,
        lw * rz + lx * ry - ly * rx + lz * rw,
        lw * rw - lx * rx - ly * ry - lz * rz,
    )


def quaternion_from_zxy_degrees(
    angle: Sequence[float],
) -> tuple[float, float, float, float]:
    """Convert editor Euler angles using the package's Z-X-Y rotation order."""
    x, y, z = _finite_vec3(angle, "model_angle")

    def axis(value: float, index: int) -> tuple[float, float, float, float]:
        half = math.radians(value) / 2.0
        values = [0.0, 0.0, 0.0]
        values[index] = math.sin(half)
        return values[0], values[1], values[2], math.cos(half)

    # Quaternion.fromRotationZXY applies Z, then X, then Y. With column-vector
    # composition that is qY * qX * qZ.
    return _quaternion_multiply(
        _quaternion_multiply(axis(y, 1), axis(x, 0)), axis(z, 2)
    )


def build_static_obstacle(
    unit: Mapping[Any, Any], *, model_id: int | None = None
) -> dict[bytes, Any]:
    """Build the public static-obstacle record recovered from the save path.

    Custom physics shapes are intentionally rejected until their per-model
    shape payload is supplied by a matched component profile.
    """
    unit_id = _get(unit, "unit_id")
    model = model_id if model_id is not None else _get(unit, "model")
    if type(unit_id) is not int or not 0 <= unit_id <= 0xFFFFFFFF:
        raise CapabilityError("static obstacle requires a u32 unit_id")
    if type(model) is not int or model <= 0:
        raise CapabilityError("static obstacle requires a positive model ID")
    if _get(unit, "CustomPhysic", False):
        raise CapabilityError(
            "custom physics requires a resolved CustomPhysicConfig profile"
        )
    position = _finite_vec3(
        _get(unit, "world_position", _get(unit, "position", (0.0, 0.0, 0.0))),
        "world_position",
    )
    scale = _finite_vec3(_get(unit, "real_scale", _get(unit, "scale")), "scale")
    angle = _finite_vec3(_get(unit, "model_angle", (0.0, 0.0, 0.0)), "model_angle")
    rotation = quaternion_from_zxy_degrees(angle)
    return {
        b"Position": [*position, VECTOR_MARKER],
        b"model": model,
        b"Rotation": [*rotation, VECTOR_MARKER],
        b"Scale": [*scale, VECTOR_MARKER],
        b"CameraNoOverlap": _get(unit, "occlusion_type") == 1,
        b"unit_id": unit_id,
    }

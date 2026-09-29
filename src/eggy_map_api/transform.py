from __future__ import annotations

import math

from .errors import CapabilityError
from .models import CatalogEntry, TransformSpec, Vec3


def _finite_positive(values: Vec3, *, allow_zero: bool = False) -> None:
    if not all(math.isfinite(value) for value in values):
        raise CapabilityError("transform contains a non-finite value")
    if allow_zero:
        if any(value < 0 for value in values):
            raise CapabilityError("transform size cannot be negative")
    elif any(value <= 0 for value in values):
        raise CapabilityError("transform size must be positive")


def scale_for_world_aabb(entry: CatalogEntry, transform: TransformSpec) -> Vec3:
    if entry.model_cell is None:
        raise CapabilityError(f"EID {entry.eid}: model dimensions are unavailable")
    _finite_positive(transform.world_aabb.size)
    _finite_positive(entry.model_cell)
    yaw = transform.rotation_deg[1] % 180.0
    if math.isclose(yaw, 90.0, abs_tol=1e-6):
        # A quarter turn swaps the local X/Z contributions in world space.
        # The returned scale is still expressed in local model axes, so the
        # desired world X size divides local Z and world Z divides local X.
        return (
            transform.world_aabb.size[2] / entry.model_cell[0],
            transform.world_aabb.size[1] / entry.model_cell[1],
            transform.world_aabb.size[0] / entry.model_cell[2],
        )
    elif math.isclose(yaw, 0.0, abs_tol=1e-6):
        model = entry.model_cell
    else:
        raise CapabilityError(
            "AABB-to-scale conversion only supports axis-aligned 0/90-degree yaw"
        )
    return tuple(
        size / base for size, base in zip(transform.world_aabb.size, model, strict=True)
    )  # type: ignore[return-value]


def set_transform(unit_id: int, world_aabb: object, forward_axis: object) -> None:
    raise CapabilityError(
        f"unit {unit_id}: transform write requires a matched unit/public-cache/private-frame profile"
    )

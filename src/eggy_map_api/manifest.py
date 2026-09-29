from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .errors import ValidationError
from .models import ComponentSpec, CourseManifest, TransformSpec, WorldAABB


def _vec3(value: Any, field: str) -> tuple[float, float, float]:
    if (
        not isinstance(value, list)
        or len(value) != 3
        or not all(type(v) in (int, float) for v in value)
    ):
        raise ValidationError(f"{field} must be a three-number array")
    return tuple(float(v) for v in value)  # type: ignore[return-value]


def load_manifest(path: str | Path) -> CourseManifest:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if type(payload.get("schema_version")) is not int:
        raise ValidationError("manifest schema_version must be an integer")
    components: list[ComponentSpec] = []
    for index, row in enumerate(payload.get("components", [])):
        if not isinstance(row, dict):
            raise ValidationError(f"components[{index}] must be an object")
        aabb = row.get("world_aabb", {})
        color = row.get("color")
        if color is not None:
            if (
                not isinstance(color, list)
                or len(color) != 3
                or any(type(v) is not int for v in color)
            ):
                raise ValidationError(
                    f"components[{index}].color must be an RGB integer array"
                )
            color = tuple(color)
        components.append(
            ComponentSpec(
                logical_name=str(row["logical_name"]),
                eid=int(row["eid"]),
                transform=TransformSpec(
                    world_aabb=WorldAABB(
                        center=_vec3(
                            aabb.get("center"), f"components[{index}].world_aabb.center"
                        ),
                        size=_vec3(
                            aabb.get("size"), f"components[{index}].world_aabb.size"
                        ),
                    ),
                    rotation_deg=_vec3(
                        row.get("rotation_deg", [0, 0, 0]),
                        f"components[{index}].rotation_deg",
                    ),
                    forward_axis=row.get("forward_axis"),
                ),
                color=color,
                properties=dict(row.get("properties", {})),
                role=str(row.get("role", "obstacle")),
            )
        )
    return CourseManifest(
        schema_version=payload["schema_version"],
        components=tuple(components),
        map_settings=dict(payload.get("map_settings", {})),
        constraints=dict(payload.get("constraints", {})),
    )

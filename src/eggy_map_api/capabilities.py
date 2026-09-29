from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .appearance import validate_color
from .errors import CapabilityError
from .models import ComponentSpec, PackageCatalog
from .transform import scale_for_world_aabb

SUPPORTED_RUNTIME_FAMILIES = frozenset(
    {"editor_unit", "editor_decoration", "editor_trigger", "editor_virtual_point"}
)


@dataclass(frozen=True)
class RuntimeCapability:
    writable: bool
    blockers: tuple[str, ...]
    supported_properties: tuple[str, ...]
    color_supported: bool


def _property_keys(family: str) -> tuple[str, ...]:
    if family == "editor_virtual_point":
        return ("camp_id", "role_id")
    return ()


def runtime_component_capability(
    catalog: PackageCatalog, eid: int
) -> RuntimeCapability:
    entry = catalog.entries.get(eid)
    if entry is None:
        return RuntimeCapability(
            False, ("component is absent from the catalog",), (), False
        )
    blockers: list[str] = []
    if entry.kind != "unit":
        blockers.append("effects are queryable but have no runtime unit builder")
    if entry.structural_family not in SUPPORTED_RUNTIME_FAMILIES:
        blockers.append(f"unsupported structural family {entry.structural_family!r}")
    if "pass" not in entry.static_status:
        blockers.append("package static gate does not pass")
    prefab = catalog.prefab_defaults.get(eid)
    if not isinstance(prefab, Mapping):
        blockers.append("package prefab defaults are unavailable")
    model_id = entry.model_id
    if model_id is None or model_id not in catalog.model_defaults:
        blockers.append("package model defaults are unavailable")
    if entry.model_cell is None:
        blockers.append("package model dimensions are unavailable")
    if isinstance(prefab, Mapping):
        if type(prefab.get("type")) is not int:
            blockers.append("prefab runtime type is unavailable")
        if type(prefab.get("model")) is not int:
            blockers.append("prefab model binding is unavailable")
    supported = _property_keys(entry.structural_family)
    color_supported = isinstance(prefab, Mapping) and "paint_area1" in prefab
    return RuntimeCapability(not blockers, tuple(blockers), supported, color_supported)


def validate_component_spec(
    spec: ComponentSpec,
    catalog: PackageCatalog,
    *,
    require_static_gate: bool = True,
) -> RuntimeCapability:
    if not spec.logical_name or "\x00" in spec.logical_name:
        raise CapabilityError("logical_name must be non-empty and contain no NUL")
    if len(spec.logical_name.encode("utf-8")) > 255:
        raise CapabilityError("logical_name is too long for the runtime unit record")
    capability = runtime_component_capability(catalog, spec.eid)
    blockers = list(capability.blockers)
    if not require_static_gate:
        blockers = [
            row for row in blockers if row != "package static gate does not pass"
        ]
    if blockers:
        raise CapabilityError(
            f"EID {spec.eid}: " + "; ".join(blockers),
            context={"eid": spec.eid, "blockers": blockers},
        )
    unknown = sorted(set(spec.properties) - set(capability.supported_properties))
    if unknown:
        raise CapabilityError(
            f"EID {spec.eid}: unsupported properties: {', '.join(unknown)}",
            code="INVALID_PROPERTY",
            context={
                "eid": spec.eid,
                "supported_properties": list(capability.supported_properties),
            },
        )
    for key, value in spec.properties.items():
        if key in {"camp_id", "role_id"} and (
            type(value) is not int or value <= 0 or value > 2_147_483_647
        ):
            raise CapabilityError(
                f"{key} must be a positive signed 32-bit integer",
                code="INVALID_PROPERTY",
            )
    if spec.color is not None:
        validate_color(spec.color)
        if not capability.color_supported:
            raise CapabilityError(
                f"EID {spec.eid}: paint_area1 is not declared by the package prefab",
                code="INVALID_PROPERTY",
            )
    scale_for_world_aabb(catalog.entries[spec.eid], spec.transform)
    return capability


def capability_payload(catalog: PackageCatalog, eid: int) -> dict[str, Any]:
    capability = runtime_component_capability(catalog, eid)
    return {
        "writable": capability.writable,
        "blockers": list(capability.blockers),
        "supported_properties": list(capability.supported_properties),
        "color_supported": capability.color_supported,
    }

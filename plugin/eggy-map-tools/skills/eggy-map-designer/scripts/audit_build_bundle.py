#!/usr/bin/env python3
"""Cross-check an Eggy design ledger against its explicit assembly expansion.

The individual auditors prove that each artifact is internally consistent. This
gate proves that the design promise, generated instances, and optional density
ledger describe the same build instead of three independently valid builds. A
final build also proves its declared spatial envelope, zone coverage, visible
construction share, completion layers, spatial design-role minima, and
non-padding repetition policy.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
import math
from pathlib import Path
import sys
from typing import Any

from audit_density_plan import PlanError, validate_plan as validate_density_plan
from audit_design_plan import DesignPlanError, validate_design_plan
from expand_assembly_plan import (
    DESIGN_ROLES,
    VISIBLE_DESIGN_ROLES,
    ExpansionError,
    expand_plan,
)


class BundleError(ValueError):
    pass


CONSTRUCTION_MODES = {"asset_led", "hybrid", "primitive_led"}
PROFILE_MIN_WORLD_VISIBLE_SHARE = {
    "micro_space": 0.20,
    "themed_short": 0.35,
    "multi_scene": 0.40,
    "long_world": 0.45,
}
WORLD_VISIBLE_LAYERS = {"MASS", "MID", "PROP", "ROUTE"}
WORLD_CONSTRUCTION_KINDS = {"BASIC_PRIMITIVE", "THEME_ASSET"}
COMPLETION_LAYERS = {"MASS", "MID", "PROP", "ROUTE", "FX"}
SPATIAL_CONSTRUCTION_KINDS = {
    "BASIC_PRIMITIVE",
    "COLLISION_PROXY",
    "FX_LIGHT_AUDIO",
    "GAMEPLAY_DEVICE",
    "THEME_ASSET",
}


def _mapping(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BundleError(f"{path} must be an object")
    return value


def _list(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise BundleError(f"{path} must be an array")
    return value


def _string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BundleError(f"{path} must be a non-empty string")
    return value.strip()


def _number(
    value: Any,
    path: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BundleError(f"{path} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise BundleError(f"{path} must be a finite number")
    if minimum is not None and result < minimum:
        raise BundleError(f"{path} must be >= {minimum}")
    if maximum is not None and result > maximum:
        raise BundleError(f"{path} must be <= {maximum}")
    return result


def _integer(
    value: Any,
    path: str,
    *,
    minimum: int | None = None,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise BundleError(f"{path} must be an integer")
    if minimum is not None and value < minimum:
        raise BundleError(f"{path} must be >= {minimum}")
    return value


def _vector(value: Any, path: str) -> tuple[float, float, float]:
    raw = _list(value, path)
    if len(raw) != 3:
        raise BundleError(f"{path} must contain exactly 3 numbers")
    return tuple(_number(part, f"{path}[{index}]") for index, part in enumerate(raw))  # type: ignore[return-value]


def _bounds(
    value: Any,
    path: str,
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    raw = _mapping(value, path)
    minimum = _vector(raw.get("min"), f"{path}.min")
    maximum = _vector(raw.get("max"), f"{path}.max")
    for axis, (low, high) in enumerate(zip(minimum, maximum)):
        if low >= high:
            raise BundleError(f"{path} axis {axis} must satisfy min < max")
    return minimum, maximum


def _basis_vectors(
    value: Any,
    path: str,
) -> tuple[tuple[float, float, float], ...]:
    raw = _mapping(value, path)
    return tuple(_vector(raw.get(name), f"{path}.{name}") for name in ("u", "v", "f"))


def _instance_aabb(
    instance: dict[str, Any],
    path: str,
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    position = _vector(instance.get("world_position"), f"{path}.world_position")
    size = _vector(instance.get("target_size_local"), f"{path}.target_size_local")
    basis = _basis_vectors(instance.get("world_basis"), f"{path}.world_basis")
    half_extent = tuple(
        sum(abs(basis[local_axis][world_axis]) * size[local_axis] * 0.5 for local_axis in range(3))
        for world_axis in range(3)
    )
    return (
        tuple(position[axis] - half_extent[axis] for axis in range(3)),  # type: ignore[return-value]
        tuple(position[axis] + half_extent[axis] for axis in range(3)),  # type: ignore[return-value]
    )


def _merge_bounds(
    items: list[tuple[tuple[float, float, float], tuple[float, float, float]]],
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    if not items:
        raise BundleError("cannot compute bounds for an empty spatial set")
    return (
        tuple(min(item[0][axis] for item in items) for axis in range(3)),  # type: ignore[return-value]
        tuple(max(item[1][axis] for item in items) for axis in range(3)),  # type: ignore[return-value]
    )


def _extent(
    value: tuple[tuple[float, float, float], tuple[float, float, float]],
) -> tuple[float, float, float]:
    return tuple(value[1][axis] - value[0][axis] for axis in range(3))  # type: ignore[return-value]


def _bounds_json(
    value: tuple[tuple[float, float, float], tuple[float, float, float]],
) -> dict[str, list[float]]:
    return {
        "min": [round(number, 6) for number in value[0]],
        "max": [round(number, 6) for number in value[1]],
    }


def _contains_bounds(
    outer: tuple[tuple[float, float, float], tuple[float, float, float]],
    inner: tuple[tuple[float, float, float], tuple[float, float, float]],
    *,
    epsilon: float = 1e-6,
) -> bool:
    return all(
        inner[0][axis] >= outer[0][axis] - epsilon
        and inner[1][axis] <= outer[1][axis] + epsilon
        for axis in range(3)
    )


def _string_list(value: Any, path: str) -> list[str]:
    raw = _list(value, path)
    result = [_string(item, f"{path}[{index}]") for index, item in enumerate(raw)]
    if len(result) != len(set(result)):
        raise BundleError(f"{path} contains duplicates")
    return result


def _minimum_design_role_counts(
    value: Any,
    path: str,
    required_roles: list[str],
) -> dict[str, int]:
    raw = _mapping(value, path)
    expected = set(required_roles)
    missing = sorted(expected - set(raw))
    extra = sorted(set(raw) - expected)
    if missing or extra:
        raise BundleError(
            f"{path} keys must exactly match required_design_roles "
            f"(missing={missing}, extra={extra})"
        )
    return {
        role: _integer(raw[role], f"{path}.{role}", minimum=1)
        for role in sorted(expected)
    }


def _compare_counts(
    promised: dict[str, int],
    expanded: dict[str, int],
    path: str,
) -> None:
    if promised == expanded:
        return
    keys = sorted(set(promised) | set(expanded))
    differences = [
        f"{key}: promised={promised.get(key, 0)}, expanded={expanded.get(key, 0)}"
        for key in keys
        if promised.get(key, 0) != expanded.get(key, 0)
    ]
    raise BundleError(f"{path} mismatch ({'; '.join(differences)})")


def _validate_quality_contract(
    value: Any,
    *,
    stage: str,
    maturity: str,
    density_profile: str,
    instances: list[Any],
    actual_total: int,
    placements_by_family: dict[str, set[str]],
    variants_by_family: dict[str, set[str]],
) -> tuple[dict[str, Any], list[str]]:
    path = "assembly_plan.quality_contract"
    contract = _mapping(value, path)
    required_fields = {
        "build_bounds",
        "minimum_world_visible_share",
        "required_completion_layers",
        "required_design_roles",
        "minimum_design_role_counts",
        "zone_targets",
        "uniform_family_exceptions",
        "rationale",
    }
    missing = sorted(required_fields - set(contract))
    if missing:
        raise BundleError(f"{path} is missing: {', '.join(missing)}")

    build_bounds = _bounds(contract["build_bounds"], f"{path}.build_bounds")
    minimum_world_visible_share = _number(
        contract["minimum_world_visible_share"],
        f"{path}.minimum_world_visible_share",
        minimum=0,
        maximum=1,
    )
    profile_share_floor = PROFILE_MIN_WORLD_VISIBLE_SHARE[density_profile]
    if maturity == "final" and minimum_world_visible_share < profile_share_floor:
        raise BundleError(
            f"{path}.minimum_world_visible_share must be >= {profile_share_floor:.2f} "
            f"for final {density_profile} builds"
        )
    required_completion_layers = _string_list(
        contract["required_completion_layers"],
        f"{path}.required_completion_layers",
    )
    if not required_completion_layers:
        raise BundleError(f"{path}.required_completion_layers cannot be empty")
    unknown_layers = sorted(set(required_completion_layers) - COMPLETION_LAYERS)
    if unknown_layers:
        raise BundleError(
            f"{path}.required_completion_layers contains unknown layers: "
            + ", ".join(unknown_layers)
        )
    if maturity == "final" and not {"MASS", "MID"}.issubset(required_completion_layers):
        raise BundleError(
            f"{path}.required_completion_layers must include MASS and MID for final builds"
        )
    required_design_roles = _string_list(
        contract["required_design_roles"], f"{path}.required_design_roles"
    )
    if not required_design_roles:
        raise BundleError(f"{path}.required_design_roles cannot be empty")
    unknown_design_roles = sorted(set(required_design_roles) - DESIGN_ROLES)
    if unknown_design_roles:
        raise BundleError(
            f"{path}.required_design_roles contains unknown roles: "
            + ", ".join(unknown_design_roles)
        )
    nonvisual_design_roles = sorted(
        set(required_design_roles) - VISIBLE_DESIGN_ROLES
    )
    if nonvisual_design_roles:
        raise BundleError(
            f"{path}.required_design_roles is a spatial quality contract and cannot "
            "use nonvisual-only roles: " + ", ".join(nonvisual_design_roles)
        )
    if maturity == "final" and not {
        "NAVIGATION",
        "SILHOUETTE",
        "STRUCTURE",
    }.issubset(required_design_roles):
        raise BundleError(
            f"{path}.required_design_roles must include SILHOUETTE, STRUCTURE, "
            "and NAVIGATION for final builds"
        )
    minimum_design_role_counts = _minimum_design_role_counts(
        contract["minimum_design_role_counts"],
        f"{path}.minimum_design_role_counts",
        required_design_roles,
    )
    _string(contract["rationale"], f"{path}.rationale")

    spatial: list[dict[str, Any]] = []
    world_visible: list[dict[str, Any]] = []
    exact_geometry: dict[tuple[Any, ...], list[str]] = defaultdict(list)
    all_layers: Counter[str] = Counter()
    all_design_roles: Counter[str] = Counter()
    spatial_design_roles: Counter[str] = Counter()
    for index, raw_instance in enumerate(instances):
        instance_path = f"expanded.instances[{index}]"
        instance = _mapping(raw_instance, instance_path)
        construction_kind = _string(
            instance.get("construction_kind"), f"{instance_path}.construction_kind"
        )
        layer = _string(instance.get("layer"), f"{instance_path}.layer")
        all_layers[layer] += 1
        instance_design_roles = _string_list(
            instance.get("design_roles"), f"{instance_path}.design_roles"
        )
        bad_instance_roles = sorted(set(instance_design_roles) - DESIGN_ROLES)
        if bad_instance_roles:
            raise BundleError(
                f"{instance_path}.design_roles contains unknown roles: "
                + ", ".join(bad_instance_roles)
            )
        for design_role in instance_design_roles:
            all_design_roles[design_role] += 1
        if construction_kind in SPATIAL_CONSTRUCTION_KINDS:
            bounds = _instance_aabb(instance, instance_path)
            enriched = dict(instance)
            enriched["_bounds"] = bounds
            spatial.append(enriched)
            for design_role in instance_design_roles:
                spatial_design_roles[design_role] += 1
            if not _contains_bounds(build_bounds, bounds):
                raise BundleError(
                    f"{instance_path} ({instance.get('name')}) exceeds quality_contract build_bounds"
                )
            position = _vector(
                instance.get("world_position"), f"{instance_path}.world_position"
            )
            size = _vector(
                instance.get("target_size_local"), f"{instance_path}.target_size_local"
            )
            basis = _basis_vectors(
                instance.get("world_basis"), f"{instance_path}.world_basis"
            )
            geometry_key = (
                construction_kind,
                *(round(number, 6) for number in position),
                *(round(number, 6) for axis in basis for number in axis),
                *(round(number, 6) for number in size),
            )
            exact_geometry[geometry_key].append(
                _string(instance.get("name"), f"{instance_path}.name")
            )
        if (
            layer in WORLD_VISIBLE_LAYERS
            and construction_kind in WORLD_CONSTRUCTION_KINDS
        ):
            world_visible.append(instance)

    if not spatial:
        raise BundleError(f"{path} cannot validate a build with no spatial instances")
    duplicate_groups = [names for names in exact_geometry.values() if len(names) > 1]
    if duplicate_groups:
        duplicate_instances = sum(len(names) - 1 for names in duplicate_groups)
        examples = "; ".join(" / ".join(names[:3]) for names in duplicate_groups[:3])
        raise BundleError(
            "exact duplicate spatial geometry detected "
            f"({duplicate_instances} redundant instances; examples: {examples})"
        )

    visible_share = len(world_visible) / actual_total if actual_total else 0.0
    if visible_share + 1e-12 < minimum_world_visible_share:
        raise BundleError(
            "world-visible construction share is below quality contract "
            f"(actual={visible_share:.4f}, target={minimum_world_visible_share:.4f})"
        )
    missing_layers = sorted(
        layer for layer in required_completion_layers if all_layers.get(layer, 0) == 0
    )
    if missing_layers:
        raise BundleError(
            "required completion layers have no expanded instances: "
            + ", ".join(missing_layers)
        )
    missing_design_roles = sorted(
        role for role in required_design_roles if spatial_design_roles.get(role, 0) == 0
    )
    if missing_design_roles:
        raise BundleError(
            "required design roles have no expanded instances: "
            + ", ".join(missing_design_roles)
        )
    for role, target_count in minimum_design_role_counts.items():
        actual_count = spatial_design_roles.get(role, 0)
        if actual_count < target_count:
            raise BundleError(
                f"design role {role} has {actual_count} spatial instances, "
                f"below target {target_count}"
            )

    exceptions: dict[str, str] = {}
    for index, raw_exception in enumerate(
        _list(contract["uniform_family_exceptions"], f"{path}.uniform_family_exceptions")
    ):
        exception_path = f"{path}.uniform_family_exceptions[{index}]"
        exception = _mapping(raw_exception, exception_path)
        family = _string(exception.get("family"), f"{exception_path}.family")
        reason = _string(exception.get("reason"), f"{exception_path}.reason")
        if family in exceptions:
            raise BundleError(f"duplicate uniform-family exception for {family}")
        if family not in placements_by_family:
            raise BundleError(f"uniform-family exception references unused family {family}")
        placement_count = len(placements_by_family[family])
        used_variant_count = len(variants_by_family[family])
        if placement_count < 4 or used_variant_count >= 2:
            raise BundleError(
                f"uniform-family exception for {family} is stale or unnecessary"
            )
        exceptions[family] = reason

    warnings: list[str] = []
    for family in sorted(placements_by_family):
        placement_count = len(placements_by_family[family])
        used_variant_count = len(variants_by_family[family])
        if placement_count >= 4 and used_variant_count < 2 and family not in exceptions:
            message = (
                f"family {family} repeats {placement_count} placements with one used variant "
                "and no uniform-family exception"
            )
            if maturity == "final":
                raise BundleError(message)
            warnings.append(message)

    zone_targets_raw = _mapping(contract["zone_targets"], f"{path}.zone_targets")
    if not zone_targets_raw:
        raise BundleError(f"{path}.zone_targets cannot be empty")
    spatial_by_zone: dict[str, list[dict[str, Any]]] = defaultdict(list)
    visible_by_zone: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in spatial:
        zone = _string(item.get("zone"), "expanded spatial instance.zone")
        spatial_by_zone[zone].append(item)
    for item in world_visible:
        zone = _string(item.get("zone"), "expanded visible instance.zone")
        visible_by_zone[zone].append(item)

    declared_zones = set(zone_targets_raw)
    actual_visible_zones = set(visible_by_zone)
    unknown_zones = sorted(declared_zones - set(spatial_by_zone))
    if unknown_zones:
        raise BundleError(
            f"{path}.zone_targets references zones with no spatial instances: "
            + ", ".join(unknown_zones)
        )
    if maturity == "final":
        untargeted = sorted(actual_visible_zones - declared_zones)
        if untargeted:
            raise BundleError(
                "final quality contract omits world-visible zones: "
                + ", ".join(untargeted)
            )

    zone_report: dict[str, Any] = {}
    for zone in sorted(zone_targets_raw):
        zone_path = f"{path}.zone_targets.{zone}"
        target = _mapping(zone_targets_raw[zone], zone_path)
        required_zone_fields = {
            "bounds",
            "minimum_world_visible_instances",
            "minimum_family_count",
            "minimum_extent",
            "required_design_roles",
            "minimum_design_role_counts",
        }
        missing_zone_fields = sorted(required_zone_fields - set(target))
        if missing_zone_fields:
            raise BundleError(
                f"{zone_path} is missing: {', '.join(missing_zone_fields)}"
            )
        target_bounds = _bounds(target["bounds"], f"{zone_path}.bounds")
        if not _contains_bounds(build_bounds, target_bounds):
            raise BundleError(f"{zone_path}.bounds must fit inside build_bounds")
        minimum_visible = _integer(
            target["minimum_world_visible_instances"],
            f"{zone_path}.minimum_world_visible_instances",
            minimum=1,
        )
        minimum_family_count = _integer(
            target["minimum_family_count"],
            f"{zone_path}.minimum_family_count",
            minimum=1,
        )
        minimum_extent = _vector(target["minimum_extent"], f"{zone_path}.minimum_extent")
        if any(number < 0 for number in minimum_extent):
            raise BundleError(f"{zone_path}.minimum_extent values must be >= 0")
        zone_spatial = spatial_by_zone[zone]
        zone_visible = visible_by_zone.get(zone, [])
        actual_zone_bounds = _merge_bounds([item["_bounds"] for item in zone_spatial])
        if not _contains_bounds(target_bounds, actual_zone_bounds):
            raise BundleError(f"zone {zone} instances exceed their declared zone bounds")
        if len(zone_visible) < minimum_visible:
            raise BundleError(
                f"zone {zone} has {len(zone_visible)} world-visible instances, "
                f"below target {minimum_visible}"
            )
        family_count = len(
            {_string(item.get("family"), "expanded visible instance.family") for item in zone_visible}
        )
        if family_count < minimum_family_count:
            raise BundleError(
                f"zone {zone} uses {family_count} world-visible families, "
                f"below target {minimum_family_count}"
            )
        actual_extent = _extent(actual_zone_bounds)
        for axis, (actual, target_minimum) in enumerate(zip(actual_extent, minimum_extent)):
            if actual + 1e-6 < target_minimum:
                raise BundleError(
                    f"zone {zone} extent axis {axis} is {actual:.4f}, "
                    f"below target {target_minimum:.4f}"
                )
        required_zone_layers = _string_list(
            target.get("required_layers", []), f"{zone_path}.required_layers"
        )
        bad_zone_layers = sorted(set(required_zone_layers) - COMPLETION_LAYERS)
        if bad_zone_layers:
            raise BundleError(
                f"{zone_path}.required_layers contains unknown layers: "
                + ", ".join(bad_zone_layers)
            )
        actual_zone_layers = Counter(
            _string(item.get("layer"), "expanded zone instance.layer") for item in zone_spatial
        )
        absent_zone_layers = sorted(
            layer for layer in required_zone_layers if actual_zone_layers.get(layer, 0) == 0
        )
        if absent_zone_layers:
            raise BundleError(
                f"zone {zone} is missing required layers: " + ", ".join(absent_zone_layers)
            )
        required_zone_design_roles = _string_list(
            target["required_design_roles"], f"{zone_path}.required_design_roles"
        )
        if not required_zone_design_roles:
            raise BundleError(f"{zone_path}.required_design_roles cannot be empty")
        bad_zone_design_roles = sorted(set(required_zone_design_roles) - DESIGN_ROLES)
        if bad_zone_design_roles:
            raise BundleError(
                f"{zone_path}.required_design_roles contains unknown roles: "
                + ", ".join(bad_zone_design_roles)
            )
        nonvisual_zone_design_roles = sorted(
            set(required_zone_design_roles) - VISIBLE_DESIGN_ROLES
        )
        if nonvisual_zone_design_roles:
            raise BundleError(
                f"{zone_path}.required_design_roles cannot use nonvisual-only roles: "
                + ", ".join(nonvisual_zone_design_roles)
            )
        minimum_zone_design_role_counts = _minimum_design_role_counts(
            target["minimum_design_role_counts"],
            f"{zone_path}.minimum_design_role_counts",
            required_zone_design_roles,
        )
        actual_zone_design_roles: Counter[str] = Counter()
        for item in zone_spatial:
            for design_role in _string_list(
                item.get("design_roles"), "expanded zone instance.design_roles"
            ):
                actual_zone_design_roles[design_role] += 1
        absent_zone_design_roles = sorted(
            role
            for role in required_zone_design_roles
            if actual_zone_design_roles.get(role, 0) == 0
        )
        if absent_zone_design_roles:
            raise BundleError(
                f"zone {zone} is missing required design roles: "
                + ", ".join(absent_zone_design_roles)
            )
        for role, target_count in minimum_zone_design_role_counts.items():
            actual_count = actual_zone_design_roles.get(role, 0)
            if actual_count < target_count:
                raise BundleError(
                    f"zone {zone} design role {role} has {actual_count} spatial "
                    f"instances, below target {target_count}"
                )
        zone_report[zone] = {
            "spatial_instance_count": len(zone_spatial),
            "world_visible_instance_count": len(zone_visible),
            "world_visible_family_count": family_count,
            "actual_bounds": _bounds_json(actual_zone_bounds),
            "actual_extent": [round(number, 6) for number in actual_extent],
            "layers": dict(sorted(actual_zone_layers.items())),
            "design_roles": dict(sorted(actual_zone_design_roles.items())),
            "minimum_design_role_counts": minimum_zone_design_role_counts,
        }

    actual_build_bounds = _merge_bounds([item["_bounds"] for item in spatial])
    return {
        "spatial_instance_count": len(spatial),
        "world_visible_instance_count": len(world_visible),
        "world_visible_share": round(visible_share, 6),
        "density_profile_world_visible_share_floor": profile_share_floor,
        "exact_duplicate_spatial_instances": 0,
        "declared_build_bounds": _bounds_json(build_bounds),
        "actual_build_bounds": _bounds_json(actual_build_bounds),
        "actual_build_extent": [round(number, 6) for number in _extent(actual_build_bounds)],
        "required_completion_layers": required_completion_layers,
        "required_design_roles": required_design_roles,
        "minimum_design_role_counts": minimum_design_role_counts,
        "design_roles": dict(sorted(all_design_roles.items())),
        "spatial_design_roles": dict(sorted(spatial_design_roles.items())),
        "uniform_family_exceptions": dict(sorted(exceptions.items())),
        "zones": zone_report,
        "predeploy_ready": stage == "predeploy" and maturity == "final",
    }, warnings


def validate_bundle(
    design_plan: Any,
    assembly_plan: Any,
    density_plan: Any | None = None,
) -> dict[str, Any]:
    design_root = _mapping(design_plan, "design_plan")
    assembly_root = _mapping(assembly_plan, "assembly_plan")
    design = validate_design_plan(design_root)
    expanded = expand_plan(assembly_root)
    expanded_summary = _mapping(expanded.get("summary"), "expanded.summary")
    instances = _list(expanded.get("instances"), "expanded.instances")

    promised_total = design["assembly"]["expanded_total"]
    actual_total = expanded_summary["expanded_total"]
    if promised_total != actual_total:
        raise BundleError(
            "expanded_total mismatch "
            f"(design={promised_total}, assembly={actual_total})"
        )
    _compare_counts(
        design["assembly"]["layers"],
        expanded_summary["layers"],
        "design assembly layers",
    )

    maturity = design["maturity"]
    stage = design["stage"]
    if maturity == "final" and "expected_total" not in assembly_root:
        raise BundleError("final assembly_plan must declare expected_total")

    family_defs = _list(assembly_root.get("families"), "assembly_plan.families")
    declared_families: dict[str, set[str]] = {}
    for index, raw_family in enumerate(family_defs):
        path = f"assembly_plan.families[{index}]"
        family = _mapping(raw_family, path)
        name = _string(family.get("name"), f"{path}.name")
        raw_variants = family.get("variants", ["A"])
        variants = {
            _string(value, f"{path}.variants[{variant_index}]")
            for variant_index, value in enumerate(_list(raw_variants, f"{path}.variants"))
        }
        declared_families[name] = variants

    used_families = set(expanded_summary["families"])
    unused_families = sorted(set(declared_families) - used_families)
    if maturity == "final" and unused_families:
        raise BundleError(
            "final assembly_plan contains unused families: "
            + ", ".join(unused_families)
        )

    promised_families = set(
        _string_list(
            design_root["theme"]["assembly_families"],
            "design_plan.theme.assembly_families",
        )
    )
    if maturity == "final":
        missing_promised_families = sorted(promised_families - used_families)
        if missing_promised_families:
            raise BundleError(
                "theme promises assembly families absent from the final expansion: "
                + ", ".join(missing_promised_families)
            )

    placements_by_family: dict[str, set[str]] = defaultdict(set)
    variants_by_family: dict[str, set[str]] = defaultdict(set)
    component_roles: set[str] = set()
    recomputed_layers: Counter[str] = Counter()
    recomputed_zones: Counter[str] = Counter()
    recomputed_cost_roles: Counter[str] = Counter()
    recomputed_construction_kinds: Counter[str] = Counter()
    recomputed_design_roles: Counter[str] = Counter()
    world_construction_kinds: Counter[str] = Counter()
    names: set[str] = set()
    for index, raw_instance in enumerate(instances):
        path = f"expanded.instances[{index}]"
        instance = _mapping(raw_instance, path)
        name = _string(instance.get("name"), f"{path}.name")
        if name in names:
            raise BundleError(f"duplicate expanded instance name: {name}")
        names.add(name)
        family = _string(instance.get("family"), f"{path}.family")
        placement = _string(instance.get("placement"), f"{path}.placement")
        variant = _string(instance.get("variant"), f"{path}.variant")
        layer = _string(instance.get("layer"), f"{path}.layer")
        zone = _string(instance.get("zone"), f"{path}.zone")
        cost_role = _string(instance.get("cost_role"), f"{path}.cost_role")
        construction_kind = _string(
            instance.get("construction_kind"), f"{path}.construction_kind"
        )
        component_role = _string(
            instance.get("component_role"), f"{path}.component_role"
        )
        design_roles = _string_list(
            instance.get("design_roles"), f"{path}.design_roles"
        )
        unknown_design_roles = sorted(set(design_roles) - DESIGN_ROLES)
        if unknown_design_roles:
            raise BundleError(
                f"{path}.design_roles contains unknown roles: "
                + ", ".join(unknown_design_roles)
            )
        placements_by_family[family].add(placement)
        variants_by_family[family].add(variant)
        component_roles.add(component_role)
        recomputed_layers[layer] += 1
        recomputed_zones[zone] += 1
        recomputed_cost_roles[cost_role] += 1
        recomputed_construction_kinds[construction_kind] += 1
        for design_role in design_roles:
            recomputed_design_roles[design_role] += 1
        if (
            layer in WORLD_VISIBLE_LAYERS
            and construction_kind in WORLD_CONSTRUCTION_KINDS
        ):
            world_construction_kinds[construction_kind] += 1

    _compare_counts(
        dict(sorted(recomputed_layers.items())),
        expanded_summary["layers"],
        "expanded instance layers",
    )
    _compare_counts(
        dict(sorted(recomputed_zones.items())),
        expanded_summary["zones"],
        "expanded instance zones",
    )
    _compare_counts(
        dict(sorted(recomputed_cost_roles.items())),
        expanded_summary["cost_roles"],
        "expanded instance cost roles",
    )
    _compare_counts(
        dict(sorted(recomputed_construction_kinds.items())),
        expanded_summary["construction_kinds"],
        "expanded instance construction kinds",
    )
    _compare_counts(
        dict(sorted(recomputed_design_roles.items())),
        expanded_summary["design_roles"],
        "expanded instance design roles",
    )

    strategy_raw = assembly_root.get("construction_strategy")
    if strategy_raw is None and maturity == "final":
        raise BundleError("final assembly_plan requires construction_strategy")
    strategy: dict[str, Any] | None = None
    if strategy_raw is not None:
        strategy_obj = _mapping(strategy_raw, "assembly_plan.construction_strategy")
        mode = _string(
            strategy_obj.get("mode"), "assembly_plan.construction_strategy.mode"
        )
        if mode not in CONSTRUCTION_MODES:
            raise BundleError(
                "assembly_plan.construction_strategy.mode must be one of "
                + ", ".join(sorted(CONSTRUCTION_MODES))
            )
        target = _number(
            strategy_obj.get("primitive_visible_share_min"),
            "assembly_plan.construction_strategy.primitive_visible_share_min",
            minimum=0,
            maximum=1,
        )
        rationale = _string(
            strategy_obj.get("rationale"),
            "assembly_plan.construction_strategy.rationale",
        )
        if mode == "primitive_led" and target < 0.5:
            raise BundleError(
                "primitive_led construction must target at least 0.5 primitive visible share"
            )
        world_total = sum(world_construction_kinds.values())
        if maturity == "final" and world_total == 0:
            raise BundleError(
                "final assembly has no MASS/MID/PROP/ROUTE basic primitives or theme assets"
            )
        primitive_share = (
            world_construction_kinds.get("BASIC_PRIMITIVE", 0) / world_total
            if world_total
            else 0.0
        )
        if primitive_share + 1e-12 < target:
            raise BundleError(
                "primitive visible share is below construction strategy target "
                f"(actual={primitive_share:.4f}, target={target:.4f})"
            )
        strategy = {
            "mode": mode,
            "primitive_visible_share_min": target,
            "primitive_visible_share_actual": round(primitive_share, 6),
            "world_visible_construction_count": world_total,
            "world_visible_share_of_all_instances": round(
                world_total / actual_total if actual_total else 0.0,
                6,
            ),
            "world_visible_construction_kinds": dict(
                sorted(world_construction_kinds.items())
            ),
            "rationale": rationale,
        }

    warnings: list[str] = []
    if (
        maturity == "final"
        and strategy is not None
        and strategy["world_visible_share_of_all_instances"] < 0.2
    ):
        warnings.append(
            "fewer than 20% of expanded instances are visible world construction; "
            "verify that devices, collision, FX, or logic are not standing in for scene completion"
        )
    low_count_exception = design["assembly"]["low_count_exception"]
    if (
        low_count_exception is not None
        and low_count_exception["mode"] == "large_asset_led"
        and strategy is not None
        and strategy["mode"] != "asset_led"
    ):
        raise BundleError(
            "large_asset_led low-count exception requires "
            "assembly_plan.construction_strategy.mode='asset_led'"
        )
    quality_summary: dict[str, Any] | None = None
    quality_raw = assembly_root.get("quality_contract")
    if quality_raw is None:
        if maturity == "final":
            raise BundleError("final assembly_plan requires quality_contract")
        for family in sorted(used_families):
            placement_count = len(placements_by_family[family])
            declared_variant_count = len(declared_families.get(family, set()))
            used_variant_count = len(variants_by_family[family])
            if placement_count >= 4 and declared_variant_count < 2:
                warnings.append(
                    f"family {family} repeats {placement_count} placements with one declared variant"
                )
            elif placement_count >= 4 and used_variant_count < 2:
                warnings.append(
                    f"family {family} declares variants but repeats {placement_count} placements with one used variant"
                )
    else:
        quality_summary, quality_warnings = _validate_quality_contract(
            quality_raw,
            stage=stage,
            maturity=maturity,
            density_profile=design["assembly"]["density_profile"],
            instances=instances,
            actual_total=actual_total,
            placements_by_family=placements_by_family,
            variants_by_family=variants_by_family,
        )
        warnings.extend(quality_warnings)

    shell_zone_links: dict[str, list[str]] = {}
    shell_family_links: dict[str, list[str]] = {}
    shell_zone_names: set[str] = set()
    for index, raw_shell in enumerate(
        _list(design_root["theme"]["world_shells"], "design_plan.theme.world_shells")
    ):
        shell_path = f"design_plan.theme.world_shells[{index}]"
        shell = _mapping(raw_shell, shell_path)
        shell_name = _string(shell.get("name"), f"{shell_path}.name")
        zones = _string_list(shell.get("assembly_zones"), f"{shell_path}.assembly_zones")
        families = _string_list(
            shell.get("assembly_families"), f"{shell_path}.assembly_families"
        )
        shell_zone_links[shell_name] = zones
        shell_family_links[shell_name] = families
        shell_zone_names.update(zones)
    if quality_summary is not None:
        quality_zones = set(quality_summary["zones"])
        missing_quality_zones = sorted(shell_zone_names - quality_zones)
        if missing_quality_zones:
            raise BundleError(
                "world shells reference assembly zones absent from quality_contract: "
                + ", ".join(missing_quality_zones)
            )
        if maturity == "final":
            unassigned_quality_zones = sorted(quality_zones - shell_zone_names)
            if unassigned_quality_zones:
                raise BundleError(
                    "final quality_contract zones are not assigned to any world shell: "
                    + ", ".join(unassigned_quality_zones)
                )
        if maturity == "final":
            visible_families_by_zone: dict[str, set[str]] = defaultdict(set)
            for index, raw_instance in enumerate(instances):
                instance_path = f"expanded.instances[{index}]"
                instance = _mapping(raw_instance, instance_path)
                layer = _string(instance.get("layer"), f"{instance_path}.layer")
                construction_kind = _string(
                    instance.get("construction_kind"),
                    f"{instance_path}.construction_kind",
                )
                if (
                    layer in WORLD_VISIBLE_LAYERS
                    and construction_kind in WORLD_CONSTRUCTION_KINDS
                ):
                    zone = _string(instance.get("zone"), f"{instance_path}.zone")
                    family = _string(instance.get("family"), f"{instance_path}.family")
                    visible_families_by_zone[zone].add(family)
            for shell_name, zones in shell_zone_links.items():
                actual_shell_families: set[str] = set()
                for zone in zones:
                    actual_shell_families.update(visible_families_by_zone.get(zone, set()))
                missing_shell_families = sorted(
                    set(shell_family_links[shell_name]) - actual_shell_families
                )
                if missing_shell_families:
                    raise BundleError(
                        f"world shell {shell_name} promises visible assembly families "
                        "absent from its assembly_zones: "
                        + ", ".join(missing_shell_families)
                    )

    density_summary: dict[str, Any] | None = None
    if density_plan is not None:
        density_summary = validate_density_plan(density_plan)
        if maturity == "final" and density_summary["stage"] != "final":
            raise BundleError("final build requires density_plan.stage='final'")
        if density_summary["expanded_total"] != actual_total:
            raise BundleError(
                "density expanded_total mismatch "
                f"(density={density_summary['expanded_total']}, assembly={actual_total})"
            )
        if density_summary["graybox_total"] != design["assembly"]["graybox_total"]:
            raise BundleError(
                "graybox_total mismatch "
                f"(design={design['assembly']['graybox_total']}, "
                f"density={density_summary['graybox_total']})"
            )
        if (
            density_summary["asset_vocabulary_count"]
            != design["assembly"]["asset_vocabulary_count"]
        ):
            raise BundleError(
                "asset_vocabulary_count mismatch "
                f"(design={design['assembly']['asset_vocabulary_count']}, "
                f"density={density_summary['asset_vocabulary_count']})"
            )
        if density_summary["density_profile"] != design["assembly"]["density_profile"]:
            raise BundleError(
                "density_profile mismatch "
                f"(design={design['assembly']['density_profile']}, "
                f"density={density_summary['density_profile']})"
            )
        if (
            density_summary["density_profile_evidence"]
            != design["assembly"]["density_profile_evidence"]
        ):
            raise BundleError(
                "density_profile_evidence mismatch between design and density ledgers"
            )
        _compare_counts(
            density_summary["layers"],
            expanded_summary["layers"],
            "density layers",
        )
        _compare_counts(
            density_summary["zones"],
            expanded_summary["zones"],
            "density zones",
        )
        if density_summary["low_count_exception"] != low_count_exception:
            raise BundleError(
                "low_count_exception mismatch between design and density ledgers"
            )
    elif stage == "predeploy":
        raise BundleError("predeploy build requires density_plan at every instance count")
    elif maturity == "final":
        warnings.append("final build has no cross-checked density_plan yet")

    family_report = {
        family: {
            "instance_count": expanded_summary["families"][family],
            "placement_count": len(placements_by_family[family]),
            "declared_variant_count": len(declared_families.get(family, set())),
            "used_variant_count": len(variants_by_family[family]),
        }
        for family in sorted(used_families)
    }
    return {
        "schema_version": 1,
        "stage": stage,
        "maturity": maturity,
        "primary_type": design["primary_type"],
        "secondary_type": design["secondary_type"],
        "expanded_total": actual_total,
        "graybox_total": design["assembly"]["graybox_total"],
        "density_profile": design["assembly"]["density_profile"],
        "density_floor": design["assembly"]["density_floor"],
        "density_profile_evidence": design["assembly"]["density_profile_evidence"],
        "zone_count": len(expanded_summary["zones"]),
        "family_count": len(used_families),
        "component_role_count": len(component_roles),
        "layers": expanded_summary["layers"],
        "cost_roles": expanded_summary["cost_roles"],
        "construction_kinds": expanded_summary["construction_kinds"],
        "design_roles": expanded_summary["design_roles"],
        "construction_strategy": strategy,
        "quality_contract": quality_summary,
        "quality_cross_checked": quality_summary is not None,
        "world_shell_zone_links": shell_zone_links,
        "world_shell_family_links": shell_family_links,
        "world_shell_zones_cross_checked": quality_summary is not None,
        "families": family_report,
        "density_cross_checked": density_summary is not None,
        "warnings": warnings,
    }


def _expect_invalid(
    design_plan: dict[str, Any],
    assembly_plan: dict[str, Any],
    needle: str,
) -> None:
    try:
        validate_bundle(design_plan, assembly_plan)
    except (BundleError, DesignPlanError, ExpansionError, PlanError) as exc:
        if needle not in str(exc):
            raise AssertionError(f"expected {needle!r} in error, got: {exc}") from exc
    else:
        raise AssertionError("invalid build bundle was accepted")


def _self_test() -> None:
    from audit_design_plan import design_template_plan, example_plan as design_example
    from expand_assembly_plan import example_plan

    assembly = example_plan()
    design = design_template_plan("short_race")
    design["theme"]["assembly_families"] = ["WALL_BAY", "WALL_TRIM"]
    for shell in design["theme"]["world_shells"]:
        shell["assembly_families"] = ["WALL_BAY", "WALL_TRIM"]
        shell["assembly_zones"] = ["RUN"]
    design["assembly_budget"] = {
        "density_profile": "micro_space",
        "density_profile_evidence": "one bounded concept room",
        "graybox_total": 4,
        "expanded_total": 10,
        "asset_vocabulary_count": 3,
        "layers": {"MASS": 4, "MID": 4, "ROUTE": 2},
    }
    design["complexity_budget"]["visual"] = {
        "visible_peak": 10,
        "collision_peak": 0,
        "shadow_peak": 2,
        "dynamic_peak": 0,
        "transparent_layer_peak": 0,
        "switch_load_peak": 10,
    }
    result = validate_bundle(design, assembly)
    if result["expanded_total"] != 10 or result["family_count"] != 1:
        raise AssertionError("valid bundle summary mismatch")
    if not result["world_shell_zones_cross_checked"]:
        raise AssertionError("world-shell assembly zones were not cross-checked")

    missing_world_shell_zone = json.loads(json.dumps(design))
    missing_world_shell_zone["theme"]["world_shells"][0]["assembly_zones"] = [
        "UNBUILT"
    ]
    _expect_invalid(
        missing_world_shell_zone,
        assembly,
        "world shells reference assembly zones absent from quality_contract",
    )

    wrong_total = json.loads(json.dumps(design))
    wrong_total["assembly_budget"]["expanded_total"] = 11
    wrong_total["assembly_budget"]["layers"]["MID"] = 5
    _expect_invalid(wrong_total, assembly, "expanded_total mismatch")

    wrong_layers = json.loads(json.dumps(design))
    wrong_layers["assembly_budget"]["layers"] = {"MASS": 4, "MID": 3, "ROUTE": 3}
    _expect_invalid(wrong_layers, assembly, "assembly layers mismatch")

    out_of_bounds = json.loads(json.dumps(assembly))
    out_of_bounds["quality_contract"]["build_bounds"]["max"][2] = 24
    _expect_invalid(design, out_of_bounds, "exceeds quality_contract build_bounds")

    missing_completion_layer = json.loads(json.dumps(assembly))
    missing_completion_layer["quality_contract"]["required_completion_layers"].append("FX")
    _expect_invalid(
        design,
        missing_completion_layer,
        "required completion layers have no expanded instances",
    )

    incomplete_role_budget = json.loads(json.dumps(assembly))
    incomplete_role_budget["quality_contract"]["minimum_design_role_counts"].pop(
        "NAVIGATION"
    )
    _expect_invalid(
        design,
        incomplete_role_budget,
        "keys must exactly match required_design_roles",
    )

    padded_role_budget = json.loads(json.dumps(assembly))
    padded_role_budget["quality_contract"]["zone_targets"]["RUN"][
        "minimum_design_role_counts"
    ]["STRUCTURE"] = 9
    _expect_invalid(
        design,
        padded_role_budget,
        "zone RUN design role STRUCTURE has 8 spatial instances, below target 9",
    )

    stale_zone_contract = json.loads(json.dumps(assembly))
    stale_zone_contract["placements"][0]["zone"] = "ALT"
    _expect_invalid(
        design,
        stale_zone_contract,
        "references zones with no spatial instances",
    )

    large_assembly = example_plan()
    large_assembly["expected_total"] = 250
    large_assembly["placements"][0]["count"] = 98
    second_family = json.loads(json.dumps(large_assembly["families"][0]))
    second_family["name"] = "WALL_TRIM"
    large_assembly["families"].append(second_family)
    second_placement = json.loads(json.dumps(large_assembly["placements"][0]))
    second_placement["name"] = "CORRIDOR_TRIM"
    second_placement["family"] = "WALL_TRIM"
    second_placement["origin"] = [0, 0, 784]
    second_placement["count"] = 2
    large_assembly["placements"].append(second_placement)
    large_assembly["quality_contract"]["build_bounds"]["max"][2] = 800
    large_assembly["quality_contract"]["zone_targets"]["RUN"]["bounds"]["max"][2] = 800
    large_assembly["quality_contract"]["zone_targets"]["RUN"][
        "minimum_world_visible_instances"
    ] = 250
    large_assembly["quality_contract"]["zone_targets"]["RUN"][
        "minimum_family_count"
    ] = 2
    large_assembly["quality_contract"]["zone_targets"]["RUN"][
        "minimum_extent"
    ][2] = 700
    large_design = design_example("short_race")
    large_design["theme"]["assembly_families"] = ["WALL_BAY", "WALL_TRIM"]
    for shell in large_design["theme"]["world_shells"]:
        shell["assembly_families"] = ["WALL_BAY", "WALL_TRIM"]
        shell["assembly_zones"] = ["RUN"]
    large_design["assembly_budget"] = {
        "density_profile": "themed_short",
        "density_profile_evidence": "one continuous themed route with a complete world shell",
        "graybox_total": 20,
        "expanded_total": 250,
        "asset_vocabulary_count": 3,
        "layers": {"MASS": 100, "MID": 100, "ROUTE": 50},
    }
    large_design["complexity_budget"]["visual"] = {
        "visible_peak": 250,
        "collision_peak": 0,
        "shadow_peak": 50,
        "dynamic_peak": 0,
        "transparent_layer_peak": 0,
        "switch_load_peak": 250,
    }
    low_visible_contract = json.loads(json.dumps(large_assembly))
    low_visible_contract["quality_contract"]["minimum_world_visible_share"] = 0.2
    low_count_exception = {
        "mode": "deliberate_minimalism",
        "scope_evidence": "one continuous themed route whose shell is visible from both review views",
        "layer_coverage": [
            {"layer": "MASS", "handled_by": "the enclosing route shell"},
            {"layer": "MID", "handled_by": "the repeated wall-bay frame"},
        ],
        "visual_review_views": ["spawn first screen", "finish return view"],
        "tradeoff": "sparse props preserve the route silhouette while retaining macro and mid layers",
    }
    large_design["assembly_budget"]["low_count_exception"] = low_count_exception
    _expect_invalid(
        large_design,
        low_visible_contract,
        "minimum_world_visible_share must be >= 0.35",
    )
    _expect_invalid(
        large_design,
        large_assembly,
        "requires density_plan",
    )
    density = {
        "schema_version": 1,
        "stage": "final",
        "density_profile": "themed_short",
        "density_profile_evidence": "one continuous themed route with a complete world shell",
        "graybox_total": 20,
        "asset_vocabulary_count": 3,
        "assemblies": [
            {
                "name": "WALL_BAY",
                "pieces_per_instance": 250,
                "placements": 1,
                "adjustment": 0,
                "zones": {"RUN": 250},
                "layers": {"MASS": 100, "MID": 100, "ROUTE": 50},
            }
        ],
        "independent": [],
        "declared": {
            "expanded_total": 250,
            "zones": {"RUN": 250},
            "layers": {"MASS": 100, "MID": 100, "ROUTE": 50},
        },
        "low_count_exception": low_count_exception,
    }
    large_result = validate_bundle(large_design, large_assembly, density)
    if not large_result["density_cross_checked"]:
        raise AssertionError("matching density ledger was not cross-checked")
    if (
        large_result["quality_contract"] is None
        or large_result["quality_contract"]["exact_duplicate_spatial_instances"] != 0
    ):
        raise AssertionError("spatial quality contract was not cross-checked")

    missing_promised_family = json.loads(json.dumps(large_design))
    missing_promised_family["theme"]["assembly_families"] = [
        "WALL_BAY",
        "UNBUILT_FAMILY",
    ]
    missing_promised_family["theme"]["world_shells"][0][
        "assembly_families"
    ] = ["WALL_BAY", "UNBUILT_FAMILY"]
    _expect_invalid(
        missing_promised_family,
        large_assembly,
        "theme promises assembly families absent from the final expansion",
    )

    graybox_density = json.loads(json.dumps(density))
    graybox_density["stage"] = "graybox"
    graybox_density.pop("low_count_exception")
    try:
        validate_bundle(large_design, large_assembly, graybox_density)
    except BundleError as exc:
        if "requires density_plan.stage='final'" not in str(exc):
            raise AssertionError(f"unexpected density stage error: {exc}") from exc
    else:
        raise AssertionError("final build accepted a graybox density ledger")

    mismatched_profile = json.loads(json.dumps(density))
    mismatched_profile["density_profile"] = "multi_scene"
    try:
        validate_bundle(large_design, large_assembly, mismatched_profile)
    except BundleError as exc:
        if "density_profile mismatch" not in str(exc):
            raise AssertionError(f"unexpected density profile error: {exc}") from exc
    else:
        raise AssertionError("mismatched density profiles were accepted")

    mismatched_profile_evidence = json.loads(json.dumps(density))
    mismatched_profile_evidence["density_profile_evidence"] = (
        "a different scope claim must not silently pass"
    )
    try:
        validate_bundle(large_design, large_assembly, mismatched_profile_evidence)
    except BundleError as exc:
        if "density_profile_evidence mismatch" not in str(exc):
            raise AssertionError(
                f"unexpected density profile evidence error: {exc}"
            ) from exc
    else:
        raise AssertionError("mismatched density profile evidence was accepted")

    mismatched_low_count = json.loads(json.dumps(density))
    mismatched_low_count["low_count_exception"]["tradeoff"] = (
        "a different exception must not silently pass"
    )
    try:
        validate_bundle(large_design, large_assembly, mismatched_low_count)
    except BundleError as exc:
        if "low_count_exception mismatch" not in str(exc):
            raise AssertionError(f"unexpected low-count mismatch error: {exc}") from exc
    else:
        raise AssertionError("mismatched low-count exceptions were accepted")

    missing_quality = json.loads(json.dumps(large_assembly))
    missing_quality.pop("quality_contract")
    try:
        validate_bundle(large_design, missing_quality, density)
    except BundleError as exc:
        if "requires quality_contract" not in str(exc):
            raise AssertionError(f"unexpected missing quality error: {exc}") from exc
    else:
        raise AssertionError("final build without quality_contract was accepted")

    duplicate_expanded = expand_plan(example_plan())
    duplicate_instances = json.loads(json.dumps(duplicate_expanded["instances"]))
    duplicate = json.loads(json.dumps(duplicate_instances[0]))
    duplicate["name"] = duplicate["name"] + "_DUPLICATE"
    duplicate_instances.append(duplicate)
    try:
        _validate_quality_contract(
            example_plan()["quality_contract"],
            stage="design",
            maturity="concept",
            density_profile="micro_space",
            instances=duplicate_instances,
            actual_total=len(duplicate_instances),
            placements_by_family={
                "WALL_BAY": {item["placement"] for item in duplicate_instances}
            },
            variants_by_family={
                "WALL_BAY": {item["variant"] for item in duplicate_instances}
            },
        )
    except BundleError as exc:
        if "exact duplicate spatial geometry" not in str(exc):
            raise AssertionError(f"unexpected duplicate geometry error: {exc}") from exc
    else:
        raise AssertionError("exact duplicate spatial geometry was accepted")

    uniform = example_plan()
    uniform["expected_total"] = 8
    uniform["placements"][0]["variant_sequence"] = ["A"]
    uniform["families"][0]["pieces"][1]["design_roles"].append("NAVIGATION")
    uniform["quality_contract"]["required_completion_layers"] = ["MASS", "MID"]
    uniform["quality_contract"]["zone_targets"]["RUN"][
        "minimum_world_visible_instances"
    ] = 8
    uniform["quality_contract"]["zone_targets"]["RUN"]["required_layers"] = [
        "MASS",
        "MID",
    ]
    uniform_expanded = expand_plan(uniform)
    try:
        _validate_quality_contract(
            uniform["quality_contract"],
            stage="design",
            maturity="final",
            density_profile="micro_space",
            instances=uniform_expanded["instances"],
            actual_total=uniform_expanded["summary"]["expanded_total"],
            placements_by_family={
                "WALL_BAY": {item["placement"] for item in uniform_expanded["instances"]}
            },
            variants_by_family={
                "WALL_BAY": {item["variant"] for item in uniform_expanded["instances"]}
            },
        )
    except BundleError as exc:
        if "no uniform-family exception" not in str(exc):
            raise AssertionError(f"unexpected uniform repetition error: {exc}") from exc
    else:
        raise AssertionError("unexplained uniform repeated family was accepted")

    impossible_primitive_share = json.loads(json.dumps(large_assembly))
    impossible_primitive_share["construction_strategy"][
        "primitive_visible_share_min"
    ] = 0.9
    try:
        validate_bundle(large_design, impossible_primitive_share, density)
    except BundleError as exc:
        if "primitive visible share" not in str(exc):
            raise AssertionError(f"unexpected construction strategy error: {exc}") from exc
    else:
        raise AssertionError("impossible primitive share target was accepted")


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Cross-check a design ledger, parametric assembly plan, and optional "
            "density ledger, including final spatial-quality gates, before deployment."
        )
    )
    parser.add_argument("design_plan", nargs="?", type=Path)
    parser.add_argument("assembly_plan", nargs="?", type=Path)
    parser.add_argument("--density-plan", type=Path)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--json", action="store_true", help="emit the summary as JSON")
    args = parser.parse_args()

    if args.self_test:
        _self_test()
        print("self-test passed")
        return 0
    if args.design_plan is None or args.assembly_plan is None:
        parser.error("design_plan and assembly_plan are required unless --self-test is used")

    try:
        design_plan = _read_json(args.design_plan)
        assembly_plan = _read_json(args.assembly_plan)
        density_plan = (
            _read_json(args.density_plan) if args.density_plan is not None else None
        )
        summary = validate_bundle(design_plan, assembly_plan, density_plan)
    except (
        OSError,
        json.JSONDecodeError,
        BundleError,
        DesignPlanError,
        ExpansionError,
        PlanError,
    ) as exc:
        print(f"invalid build bundle: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(
            "build bundle valid: "
            f"density_profile={summary['density_profile']}, "
            f"expanded={summary['expanded_total']}, "
            f"families={summary['family_count']}, "
            f"zones={summary['zone_count']}, "
            f"quality_cross_checked={summary['quality_cross_checked']}, "
            f"density_cross_checked={summary['density_cross_checked']}"
        )
        for warning in summary["warnings"]:
            print(f"warning: {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

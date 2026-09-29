from __future__ import annotations

import math
import struct
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from .appearance import validate_color
from .collision import build_static_obstacle
from .errors import CapabilityError, ValidationError
from .graph import build_reference_graph
from .models import (
    CourseManifest,
    MapSnapshot,
    OutputClosureProfile,
    PackageCatalog,
    PatchPlan,
    WorldAABB,
)
from .native_tasks import inventory_native_tasks
from .transform import scale_for_world_aabb


@dataclass(frozen=True)
class ValidationReport:
    checks: tuple[str, ...]
    warnings: tuple[str, ...] = ()


def _get(mapping: Mapping[Any, Any], key: str, default: Any = None) -> Any:
    return mapping.get(key, mapping.get(key.encode(), default))


def _table(value: Any, key: str, label: str) -> dict[Any, Any]:
    result = _get(value, key) if isinstance(value, Mapping) else None
    if not isinstance(result, dict):
        raise ValidationError(f"{label} is not a map")
    return result


def _expected_ids(
    unit_eids: Mapping[int, int], rules: Mapping[int, bool], label: str
) -> set[int]:
    missing = sorted(set(unit_eids.values()) - set(rules))
    if missing:
        raise ValidationError(f"{label} has no resolved membership rule for {missing}")
    return {unit_id for unit_id, eid in unit_eids.items() if rules[eid]}


def _assert_exact_ids(actual: Any, expected: set[int], label: str) -> None:
    if not isinstance(actual, Mapping) or any(type(key) is not int for key in actual):
        raise ValidationError(f"{label} is not an integer-keyed map")
    if set(actual) != expected:
        raise ValidationError(
            f"{label} unit membership mismatch: expected {sorted(expected)}, "
            f"got {sorted(actual)}"
        )


def _decode_name(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return None
    return None


def _native_material_vec(task: Any, name: bytes) -> tuple[float, ...] | None:
    matches: list[tuple[float, ...]] = []
    for param in task.params:
        if param.opcode != 24:
            continue
        string_index = struct.unpack_from("<Q", param.data, 0)[0]
        value_type = struct.unpack_from("<I", param.data, 16)[0]
        if string_index >= len(task.strings) or task.strings[string_index] != name:
            continue
        if value_type != 4:
            raise ValidationError(
                f"task {task.task_id}: color material {name!r} is not a float array"
            )
        array_index = struct.unpack_from("<Q", param.data, 24)[0]
        if array_index >= len(task.array_pools[0]):
            raise ValidationError(
                f"task {task.task_id}: color material array index is out of range"
            )
        raw = task.array_pools[0][array_index]
        if len(raw) % 4:
            raise ValidationError(
                f"task {task.task_id}: color material array width is invalid"
            )
        matches.append(struct.unpack(f"<{len(raw) // 4}f", raw))
    if len(matches) > 1:
        raise ValidationError(
            f"task {task.task_id}: color material {name!r} is not unique"
        )
    return matches[0] if matches else None


def validate_manifest(
    manifest: CourseManifest, catalog: PackageCatalog | None = None
) -> ValidationReport:
    """Validate the generic manifest contract without imposing a map genre."""
    checks: list[str] = []
    if manifest.schema_version != 1:
        raise ValidationError(f"unsupported manifest schema {manifest.schema_version}")
    names = [component.logical_name for component in manifest.components]
    if len(names) != len(set(names)):
        raise ValidationError("logical component names must be globally unique")
    if any(not name or "\x00" in name for name in names):
        raise ValidationError(
            "logical component names must be non-empty and contain no NUL"
        )
    for component in manifest.components:
        center = component.transform.world_aabb.center
        size = component.transform.world_aabb.size
        if not all(
            math.isfinite(v)
            for v in (*center, *size, *component.transform.rotation_deg)
        ):
            raise ValidationError(
                f"{component.logical_name}: transform contains non-finite values"
            )
        if any(v <= 0 for v in size):
            raise ValidationError(
                f"{component.logical_name}: AABB size must be positive"
            )
        if component.color is not None:
            validate_color(component.color)
        if catalog is not None:
            entry = catalog.entries.get(component.eid)
            if entry is None:
                raise ValidationError(
                    f"{component.logical_name}: EID {component.eid} is absent from catalog"
                )
            scale_for_world_aabb(entry, component.transform)
    checks.extend(
        (
            "manifest-schema",
            "logical-name-uniqueness",
            "finite-positive-transforms",
            "catalog-model-scales",
        )
    )

    expected_total = manifest.constraints.get("expected_component_count")
    if expected_total is not None:
        if type(expected_total) is not int or expected_total < 0:
            raise ValidationError(
                "expected_component_count must be a non-negative integer"
            )
        if len(manifest.components) != expected_total:
            raise ValidationError(
                f"expected {expected_total} components, got {len(manifest.components)}"
            )
        checks.append("expected-component-count")
    expected_eid_counts = manifest.constraints.get("expected_eid_counts")
    if expected_eid_counts is not None:
        if not isinstance(expected_eid_counts, dict):
            raise ValidationError("expected_eid_counts must be an object")
        actual_counts = Counter(component.eid for component in manifest.components)
        normalized: dict[int, int] = {}
        for raw_eid, raw_count in expected_eid_counts.items():
            try:
                eid = int(raw_eid)
            except (TypeError, ValueError) as exc:
                raise ValidationError(
                    "expected_eid_counts contains an invalid EID"
                ) from exc
            if type(raw_count) is not int or raw_count < 0:
                raise ValidationError(
                    f"expected_eid_counts[{raw_eid!r}] must be a non-negative integer"
                )
            normalized[eid] = raw_count
        if actual_counts != Counter(normalized):
            raise ValidationError(
                f"declared EID counts do not match manifest: expected {normalized}, "
                f"got {dict(actual_counts)}"
            )
        checks.append("expected-eid-counts")

    return ValidationReport(tuple(checks))


def validate_course_manifest(
    manifest: CourseManifest, catalog: PackageCatalog | None = None
) -> ValidationReport:
    """Apply the optional racing-course preset used by course-specific callers."""
    checks = list(validate_manifest(manifest, catalog).checks)
    roles: dict[str, list[WorldAABB]] = {}
    for component in manifest.components:
        roles.setdefault(component.role, []).append(component.transform.world_aabb)
    destroy = roles.get("destroy", [])
    protected = (
        roles.get("spawn", []) + roles.get("checkpoint", []) + roles.get("victory", [])
    )
    if len(destroy) != 1:
        raise ValidationError("manifest must contain exactly one destroy region")
    if any(destroy[0].intersects(box, touching=True) for box in protected):
        raise ValidationError(
            "destroy region intersects spawn/checkpoint/victory region"
        )
    checks.append("trigger-region-separation")
    if manifest.map_settings.get("map_recommend_play_num") != 8:
        raise ValidationError("recommended player count must be 8")
    if (
        manifest.map_settings.get("min_play_num") != 1
        or manifest.map_settings.get("min_play_num_new") != 1
    ):
        raise ValidationError("minimum player count must remain 1")
    if manifest.map_settings.get("max_game_time") != 180:
        raise ValidationError("maximum game time must remain 180 seconds")
    checks.append("map-settings")
    return ValidationReport(tuple(checks))


def validate_output_snapshot(
    snapshot: MapSnapshot,
    manifest: CourseManifest,
    catalog: PackageCatalog,
    closure: OutputClosureProfile,
) -> ValidationReport:
    """Validate a generated map against an explicit derived-container profile."""
    checks = list(validate_manifest(manifest, catalog).checks)
    graph = build_reference_graph(snapshot)
    units = _table(snapshot.decoded("unit.mm"), "unit", "unit.mm.unit")
    if len(units) != len(manifest.components):
        raise ValidationError(
            f"unit count mismatch: expected {len(manifest.components)}, got {len(units)}"
        )
    expected_pairs = Counter(
        (component.logical_name, component.eid) for component in manifest.components
    )
    actual_pairs = Counter(
        (_decode_name(_get(unit, "name")), graph.unit_eids[unit_id])
        for unit_id, unit in units.items()
    )
    if actual_pairs != expected_pairs:
        raise ValidationError("unit logical-name/EID inventory does not match manifest")
    if any(
        graph.parents[unit_id] or graph.children[unit_id] for unit_id in graph.unit_ids
    ):
        raise ValidationError("every generated course component must remain top-level")
    checks.append("unit-inventory-and-flat-hierarchy")

    unit_editor = snapshot.decoded("uniteditor.mm")
    _assert_exact_ids(unit_editor, set(graph.unit_ids), "uniteditor.mm")

    cache = snapshot.decoded("editingcachewithlevel.mm")
    preload_cache = _table(
        cache,
        "preload_unit_material_content",
        "editingcachewithlevel.mm.preload_unit_material_content",
    )
    loader_content = _table(
        cache, "loader_content", "editingcachewithlevel.mm.loader_content"
    )
    unit_display = _table(
        cache, "unit_display_data", "editingcachewithlevel.mm.unit_display_data"
    )
    _assert_exact_ids(
        preload_cache,
        _expected_ids(graph.unit_eids, closure.preload_cache_by_eid, "preload cache"),
        "editingcachewithlevel.mm.preload_unit_material_content",
    )
    _assert_exact_ids(
        loader_content,
        _expected_ids(graph.unit_eids, closure.loader_content_by_eid, "loader content"),
        "editingcachewithlevel.mm.loader_content",
    )
    _assert_exact_ids(
        unit_display,
        _expected_ids(graph.unit_eids, closure.unit_display_by_eid, "unit display"),
        "editingcachewithlevel.mm.unit_display_data",
    )

    new_preload = snapshot.decoded("newpreloadres.mm")
    batch_loader = _table(
        new_preload, "batch_loader_data", "newpreloadres.mm.batch_loader_data"
    )
    batch_units = _table(
        batch_loader, "batch_unit_data", "newpreloadres.mm.batch_unit_data"
    )
    expected_tasks = _expected_ids(
        graph.unit_eids, closure.batch_task_by_eid, "batch/native task"
    )
    _assert_exact_ids(batch_units, expected_tasks, "newpreloadres.mm.batch_unit_data")
    native = inventory_native_tasks(new_preload, loader_version=closure.loader_version)
    task_ids = [task.task_id for task in native.tasks]
    if task_ids != list(batch_units):
        raise ValidationError(
            "public batch-unit order and private native-task order differ"
        )
    if set(task_ids) != expected_tasks:
        raise ValidationError("private native-task membership differs from profile")
    tasks = {task.task_id: task for task in native.tasks}
    checks.append("public-private-batch-bijection")

    preload = snapshot.decoded("preloadres.mm")
    preload_material = _table(
        preload, "preload_unit_material", "preloadres.mm.preload_unit_material"
    )
    _assert_exact_ids(
        preload_material,
        _expected_ids(
            graph.unit_eids, closure.preload_material_by_eid, "preload material"
        ),
        "preloadres.mm.preload_unit_material",
    )

    static_rows = snapshot.decoded("staticobstacle.mm")
    if not isinstance(static_rows, list) or any(
        not isinstance(row, Mapping) for row in static_rows
    ):
        raise ValidationError("staticobstacle.mm must be a list of maps")
    static_by_id: dict[int, Mapping[Any, Any]] = {}
    for row in static_rows:
        unit_id = _get(row, "unit_id")
        if type(unit_id) is not int or unit_id in static_by_id:
            raise ValidationError("static obstacle IDs must be unique integers")
        static_by_id[unit_id] = row
    expected_static = _expected_ids(
        graph.unit_eids, closure.static_obstacle_by_eid, "static obstacle"
    )
    if set(static_by_id) != expected_static:
        raise ValidationError("static-obstacle membership differs from profile")
    for unit_id, row in static_by_id.items():
        expected = build_static_obstacle(units[unit_id])
        for key in (b"model", b"CameraNoOverlap", b"unit_id"):
            if _get(row, key.decode()) != expected[key]:
                raise ValidationError(
                    f"static obstacle {unit_id}: {key!r} differs from unit source"
                )
        for key in (b"Position", b"Rotation", b"Scale"):
            actual_vec = _get(row, key.decode())
            expected_vec = expected[key]
            if (
                not isinstance(actual_vec, list)
                or len(actual_vec) != len(expected_vec)
                or any(
                    not math.isclose(float(a), float(b), abs_tol=1e-6)
                    for a, b in zip(
                        actual_vec[: len(expected_vec) - 1], expected_vec[:-1]
                    )
                )
                or actual_vec[-1] != expected_vec[-1]
            ):
                raise ValidationError(
                    f"static obstacle {unit_id}: {key!r} differs from unit transform"
                )
    checks.append("static-obstacle-source-consistency")

    desc = snapshot.decoded("desc.mm")
    if not isinstance(desc, Mapping):
        raise ValidationError("desc.mm root is not a map")
    for key, expected in manifest.map_settings.items():
        if _get(desc, key) != expected:
            raise ValidationError(f"desc.mm setting {key!r} differs from manifest")

    components_by_key = {
        (component.logical_name, component.eid): component
        for component in manifest.components
    }
    for unit_id, unit in units.items():
        eid = graph.unit_eids[unit_id]
        name = _decode_name(_get(unit, "name"))
        component = components_by_key[(name, eid)]
        if component.color is None:
            continue
        unit_color = _get(unit, "paint_area1")
        if not isinstance(unit_color, list) or tuple(unit_color[:3]) != component.color:
            raise ValidationError(f"unit {unit_id}: paint_area1 differs from manifest")
        color_var = closure.color_var_by_eid.get(eid)
        if eid not in closure.color_var_by_eid:
            raise ValidationError(f"color slot has no resolved rule for EID {eid}")
        if unit_id in tasks:
            if color_var is None:
                raise ValidationError(
                    f"unit {unit_id}: native color slot is unresolved"
                )
            vector = _native_material_vec(tasks[unit_id], color_var)
            expected_rgb = tuple(channel / 255.0 for channel in component.color)
            if (
                vector is None
                or len(vector) < 4
                or any(
                    not math.isclose(actual, expected, abs_tol=1e-6)
                    for actual, expected in zip(vector[:3], expected_rgb, strict=True)
                )
            ):
                raise ValidationError(f"unit {unit_id}: native color slot differs")
        elif color_var is not None:
            raise ValidationError(
                f"unit {unit_id}: color profile requires a missing native task"
            )
    checks.extend(("map-settings-output", "color-public-private-closure"))
    return ValidationReport(tuple(checks))


def validate(
    plan: PatchPlan, level: Literal["strict-local"] = "strict-local"
) -> ValidationReport:
    if level != "strict-local":
        raise ValidationError("only strict-local validation is implemented")
    report = validate_manifest(plan.manifest, plan.catalog)
    if plan.blockers:
        raise CapabilityError(
            "plan is not deployable:\n- " + "\n- ".join(plan.blockers)
        )
    expected = Counter(component.eid for component in plan.manifest.components)
    if sum(expected.values()) != len(plan.manifest.components):
        raise ValidationError("manifest count invariant failed")
    return ValidationReport(
        report.checks + ("capability-closure", "declared-component-counts"),
        report.warnings,
    )


def validate_snapshot_integrity(snapshot: MapSnapshot) -> ValidationReport:
    """Validate generic, discoverable invariants without assuming a map genre."""
    checks = ["strict-mm-decode"]
    graph = build_reference_graph(snapshot)
    checks.append("unit-hierarchy")
    if "uniteditor.mm" in snapshot.files:
        editor = snapshot.decoded("uniteditor.mm")
        if not isinstance(editor, Mapping) or set(editor) != set(graph.unit_ids):
            raise ValidationError("uniteditor membership differs from unit inventory")
        checks.append("uniteditor-membership")
    if "editingcachewithlevel.mm" in snapshot.files:
        cache = snapshot.decoded("editingcachewithlevel.mm")
        if not isinstance(cache, Mapping):
            raise ValidationError("editingcachewithlevel.mm root is not a map")
        for key in (
            "preload_unit_material_content",
            "loader_content",
            "unit_display_data",
        ):
            value = _get(cache, key)
            if value is not None and (
                not isinstance(value, Mapping)
                or not set(value).issubset(graph.unit_ids)
            ):
                raise ValidationError(f"{key} contains a non-existent unit")
        checks.append("public-cache-subsets")
    if "newpreloadres.mm" in snapshot.files:
        new_preload = snapshot.decoded("newpreloadres.mm")
        batch = (
            _get(new_preload, "batch_loader_data")
            if isinstance(new_preload, Mapping)
            else None
        )
        public = _get(batch, "batch_unit_data") if isinstance(batch, Mapping) else None
        if public is not None:
            if not isinstance(public, Mapping) or not set(public).issubset(
                graph.unit_ids
            ):
                raise ValidationError("batch_unit_data contains a non-existent unit")
            native = inventory_native_tasks(new_preload, loader_version=1)
            if list(public) != [task.task_id for task in native.tasks]:
                raise ValidationError("public/private batch task order differs")
            checks.append("public-private-batch-bijection")
    if "staticobstacle.mm" in snapshot.files:
        rows = snapshot.decoded("staticobstacle.mm")
        if not isinstance(rows, list):
            raise ValidationError("staticobstacle.mm root is not a list")
        ids = [_get(row, "unit_id") for row in rows if isinstance(row, Mapping)]
        if len(ids) != len(rows) or any(type(value) is not int for value in ids):
            raise ValidationError("static obstacle IDs are malformed")
        if len(ids) != len(set(ids)) or not set(ids).issubset(graph.unit_ids):
            raise ValidationError("static obstacle membership is not closed over units")
        checks.append("static-obstacle-membership")
    return ValidationReport(tuple(checks))

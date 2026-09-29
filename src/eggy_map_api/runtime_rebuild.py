from __future__ import annotations

import base64
import copy
import hashlib
import json
import random
import shutil
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .allocator import InstanceAllocator
from .capabilities import validate_component_spec
from .codec import encode_mm
from .errors import CapabilityError, ValidationError
from .graph import build_reference_graph
from .models import ApplyResult, ComponentSpec, MapSnapshot, PatchPlan
from .native_tasks import (
    NativeTaskContainer,
    encode_task_container,
    inventory_native_tasks,
)
from .snapshot import open_snapshot
from .transform import scale_for_world_aabb

_MARKER = b"\x11"
_LOGIC_FILES = (
    "triggereditor.mm",
    "globaltrigger.mm",
    "triggereditorruntime.mm",
    "customevent.mm",
    "ecapath.mm",
    "eui.mm",
    "dialog.mm",
    "eggimon.mm",
)
_VECTOR_FIELDS = frozenset(
    {
        "AngularVelocity",
        "LinearVelocity",
        "LocalCenterOfMass",
        "default_model_angle",
        "floating_plat_normal_color",
        "floating_plat_shake_color",
        "pattern_color",
        "save_point",
        "save_use_unit_offset",
        "sound_pos",
        "trans_tape_speed",
    }
)


def _get(mapping: Mapping[Any, Any], key: str, default: Any = None) -> Any:
    return mapping.get(key, mapping.get(key.encode(), default))


def _set(mapping: dict[Any, Any], key: str, value: Any) -> None:
    encoded = key.encode()
    mapping[encoded if encoded in mapping or key not in mapping else key] = value


def _contains_unit_id(value: Any, unit_ids: set[int]) -> bool:
    if type(value) is int:
        return value in unit_ids
    if isinstance(value, Mapping):
        return any(
            _contains_unit_id(key, unit_ids) or _contains_unit_id(item, unit_ids)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_unit_id(item, unit_ids) for item in value)
    return False


def _wire_value(value: Any, field: str | None = None) -> Any:
    if isinstance(value, str):
        return value.encode("utf-8")
    if isinstance(value, bytes) or value is None or type(value) in (bool, int, float):
        return value
    if isinstance(value, Mapping):
        return {
            (key.encode("utf-8") if isinstance(key, str) else key): _wire_value(
                item, str(key)
            )
            for key, item in value.items()
        }
    if isinstance(value, (tuple, list)):
        result = [_wire_value(item) for item in value]
        if field in _VECTOR_FIELDS and len(result) in (3, 4) and result[-1] != _MARKER:
            result.append(_MARKER)
        return result
    raise CapabilityError(f"unsupported prefab value type: {type(value).__name__}")


def _angle_for(
    spec: ComponentSpec, prefab: Mapping[str, Any]
) -> tuple[float, float, float]:
    explicit = tuple(float(value) for value in spec.transform.rotation_deg)
    if (
        any(abs(value) > 1e-9 for value in explicit)
        or spec.transform.forward_axis is None
    ):
        return explicit
    default_angle = prefab.get("default_model_angle")
    if default_angle is not None and spec.transform.forward_axis == "-x":
        values = tuple(float(value) for value in default_angle)
        if len(values) == 3:
            return values  # type: ignore[return-value]
    source: tuple[float, float] | None = None
    tape = prefab.get("trans_tape_speed")
    if isinstance(tape, (list, tuple)) and len(tape) == 3:
        source = (float(tape[0]), float(tape[2]))
    if source is None:
        motors = prefab.get("MotorList")
        if isinstance(motors, (list, tuple)):
            for motor in motors:
                if not isinstance(motor, Mapping):
                    continue
                velocity = motor.get("LinearVelocity")
                if isinstance(velocity, (list, tuple)) and len(velocity) == 3:
                    source = (float(velocity[0]), float(velocity[2]))
                    break
    # Most directional editor models use local +Z as their visual forward axis.
    source = source or (0.0, 1.0)
    source_heading = math_degrees_atan2(source[0], source[1])
    desired_heading = {"+z": 0.0, "+x": 90.0, "-z": 180.0, "-x": -90.0}[
        spec.transform.forward_axis
    ]
    yaw = desired_heading - source_heading
    while yaw <= -180.0:
        yaw += 360.0
    while yaw > 180.0:
        yaw -= 360.0
    return (0.0, yaw, 0.0)


def math_degrees_atan2(x: float, z: float) -> float:
    import math

    if abs(x) < 1e-12 and abs(z) < 1e-12:
        raise CapabilityError("directional prefab has a zero forward vector")
    return math.degrees(math.atan2(x, z))


def _deterministic_uuid(unit_ids: list[int], manifest_payload: bytes) -> bytes:
    digest = hashlib.sha256(
        manifest_payload + b"\0" + b",".join(str(value).encode() for value in unit_ids)
    ).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=")[:22]


def _base_unit(
    spec: ComponentSpec,
    unit_id: int,
    create_index: int,
    plan: PatchPlan,
) -> tuple[dict[bytes, Any], Mapping[str, Any]]:
    entry = plan.catalog.entries[spec.eid]
    prefab = plan.catalog.prefab_defaults[spec.eid]
    model_id = entry.model_id
    if model_id is None:
        raise CapabilityError(f"EID {spec.eid}: model ID is unavailable")
    model = plan.catalog.model_defaults.get(model_id)
    if model is None:
        raise CapabilityError(f"EID {spec.eid}: model defaults are unavailable")
    angle = _angle_for(spec, prefab)
    transform = copy.copy(spec.transform)
    object.__setattr__(transform, "rotation_deg", angle)
    editor_scale = scale_for_world_aabb(entry, transform)
    model_scale_raw = model.get("scale", (1.0, 1.0, 1.0))
    if not isinstance(model_scale_raw, (tuple, list)) or len(model_scale_raw) != 3:
        raise CapabilityError(f"EID {spec.eid}: invalid package model scale")
    real_scale = tuple(
        float(scale) * float(base)
        for scale, base in zip(editor_scale, model_scale_raw, strict=True)
    )
    center = [float(value) for value in spec.transform.world_aabb.center]
    type_id = prefab.get("type")
    if type(type_id) is not int:
        raise CapabilityError(f"EID {spec.eid}: prefab type is unavailable")
    unit: dict[bytes, Any] = {
        b"position": center.copy(),
        b"world_position": center.copy(),
        b"model_angle": [float(value) for value in angle],
        b"scale": [float(value) for value in editor_scale],
        b"real_scale": [float(value) for value in real_scale],
        b"create_op": 0,
        b"unit_id": unit_id,
        b"name": spec.logical_name.encode("utf-8"),
        b"type": type_id,
        b"unit_type": type_id,
        b"eid": spec.eid,
        b"parent_unit_id": 0,
        b"children_unit_id": [],
        b"expression_device_list": [],
    }
    return unit, prefab


def _components() -> dict[bytes, Any]:
    return {b"kv": [[], {}, _MARKER]}


def _build_obstacle(
    spec: ComponentSpec, unit_id: int, create_index: int, plan: PatchPlan
) -> dict[bytes, Any]:
    unit, prefab = _base_unit(spec, unit_id, create_index, plan)
    motors = prefab.get("MotorList", ())
    special = int(prefab.get("special_comp", 0) or 0)
    has_motion = bool(motors) or special != 0
    physic_enable = bool(prefab.get("physic_enable", True))
    is_static = (
        physic_enable and not has_motion and not bool(prefab.get("ForcedType", False))
    )
    body_type = 0 if is_static else int(prefab.get("BodyType", 1))
    unit.update(
        {
            b"interacts": {b"enable": False},
            b"new_interact_enable": False,
            b"link_parent_id_list": [],
            b"owner_camp_role_id": -1,
            b"create_probability": 1.0,
            b"model_center_pos": [0, 0, 0, _MARKER],
            b"model_center_angle": [0, 0, 0, _MARKER],
        }
    )
    if spec.color is not None:
        unit[b"paint_area1"] = [*spec.color, _MARKER]
    elif "paint_area1" in prefab:
        color = list(prefab["paint_area1"][:3])
        unit[b"paint_area1"] = [*color, _MARKER]
    unit.update(
        {
            b"model_alpha": float(prefab.get("model_alpha", 1.0)),
            b"CollisionExtraForce": int(prefab.get("CollisionExtraForce", 0)),
            b"Bounciness": float(prefab.get("Bounciness", 0.0)),
            b"physic_enable": physic_enable,
            b"occlusion_type": int(prefab.get("occlusion_type", 0)),
            b"ForcedType": bool(prefab.get("ForcedType", False)),
            b"sel_skin": int(prefab.get("sel_skin", 0)),
            b"extra_special_comp": 0,
            b"FrictionCoefficient": float(prefab.get("FrictionCoefficient", 0.3)),
            b"RollingResistance": float(prefab.get("RollingResistance", 0.1)),
            b"close_cast_shadow": bool(prefab.get("close_cast_shadow", False)),
            b"fix_destroy_time": -1,
            b"LocalCenterOfMass": _wire_value(
                prefab.get("LocalCenterOfMass", (0.0, 0.5, 0.0)),
                "LocalCenterOfMass",
            ),
            b"touch_enable": bool(prefab.get("touch_enable", False)),
            b"isDynamicMechanism": has_motion,
            b"char_contact_param": False,
            b"MotorOpti": bool(prefab.get("MotorOpti", True)),
            b"AIAvoidType": 0,
            b"MotorList": _wire_value(motors, "MotorList"),
            b"physic_lod": b"default",
            b"custom_physics_category": b"_default",
            b"enable_hp": False,
            b"ob_max_hp": 0,
        }
    )
    optional = (
        "AcceptRoomLighting",
        "AngularDamping",
        "LinearDamping",
        "Mass",
        "MassCenterType",
        "MassDensity",
        "Sound",
        "Sound2",
        "Sound_Type",
        "bounce_board_recover_time",
        "close_accept_other_bake",
        "close_bake_to_other",
        "floating_plat_normal_color",
        "floating_plat_shake_color",
        "pattern_alpha",
        "pattern_color",
        "sound_pos",
        "special_comp",
        "trans_tape_speed",
        "use_static_shadow",
    )
    for key in optional:
        if key in prefab:
            unit[key.encode()] = _wire_value(prefab[key], key)
    unit.update(
        {
            b"ugc_wind_force_enable": False,
            b"enable_climbed": False,
            b"only_collide_char": False,
        }
    )
    if is_static:
        unit[b"is_static_obstacle"] = True
    unit[b"BodyType"] = body_type
    unit[b"ugc_death_drops"] = [_MARKER]
    unit[b"unit_merge_info"] = {}
    unit[b"model"] = int(prefab["model"])
    unit[b"components"] = _components()
    return unit


def _build_trigger(
    spec: ComponentSpec, unit_id: int, create_index: int, plan: PatchPlan
) -> dict[bytes, Any]:
    unit, prefab = _base_unit(spec, unit_id, create_index, plan)
    effect_type = int(prefab.get("effect_type", 99))
    unit.update(
        {
            b"interacts": {b"enable": False},
            b"new_interact_enable": False,
            b"owner_camp_role_id": -1,
            b"model_center_pos": [0, 0, 0, _MARKER],
            b"model_center_angle": [0, 0, 0, _MARKER],
            b"model_visible": bool(prefab.get("model_visible", effect_type != 99)),
            b"model_alpha": float(prefab.get("model_alpha", 0.5)),
            b"sel_skin": int(prefab.get("sel_skin", 0)),
            b"model": int(prefab["model"]),
            b"close_cast_shadow": bool(prefab.get("close_cast_shadow", False)),
            b"effect_type": effect_type,
            b"simple_trigger": False,
            b"enter_expression_list": [_MARKER],
            b"leave_expression_list": [_MARKER],
            b"collision_type": [0],
            b"disable_navmesh": 0,
            b"AIRegisterTag": b"",
            b"material_enable_tiling": False,
            b"intensity_g": 0.5,
            b"intensity_b": 0.0,
            b"intensity_a": 0.0,
            b"emissive_color": [0, 0, 0, 255, _MARKER],
            b"collision_char_camps_mask": [_MARKER],
            b"collision_mask": int(prefab.get("collision_mask", 4)),
            b"exert_collision_mask": 0,
            b"MotorList": [],
        }
    )
    if spec.color is not None:
        unit[b"paint_area1"] = [*spec.color, _MARKER]
    elif "paint_area1" in prefab:
        unit[b"paint_area1"] = [*list(prefab["paint_area1"][:3]), _MARKER]
    for key in (
        "model_alpha_type",
        "save_as_check_point",
        "save_point",
        "save_use_unit",
        "save_use_unit_offset",
        "save_y_angle",
    ):
        if key in prefab:
            unit[key.encode()] = _wire_value(prefab[key], key)
    unit[b"components"] = _components()
    return unit


def _build_virtual_point(
    spec: ComponentSpec, unit_id: int, create_index: int, plan: PatchPlan
) -> dict[bytes, Any]:
    unit, prefab = _base_unit(spec, unit_id, create_index, plan)
    props = dict(spec.properties)
    unit.update(
        {
            b"group_eid": 0,
            b"group_type": 0,
            b"sel_skin": int(prefab.get("sel_skin", 0)),
            b"virtual_point_type": int(prefab.get("virtual_point_type", 0)),
            b"camp_id": int(props.get("camp_id", 1)),
            b"role_id": int(props.get("role_id", 1)),
            b"use_camp_color": bool(prefab.get("use_camp_color", True)),
            b"ability2_id": 0,
            b"ability3_id": 0,
            b"ability4_id": 0,
            b"ability5_id": 0,
            b"vehicle_id": 0,
            b"auto_ability1_id": 0,
            b"auto_ability2_id": 0,
            b"auto_ability3_id": 0,
            b"auto_ability4_id": 0,
            b"auto_ability5_id": 0,
            b"modifier_list": [_MARKER],
            b"char_key": create_index,
            b"components": _components(),
        }
    )
    if spec.color is not None:
        unit[b"paint_area1"] = [*spec.color, _MARKER]
    unit[b"model"] = int(prefab["model"])
    return unit


def build_runtime_rebuild_unit(
    spec: ComponentSpec,
    *,
    unit_id: int,
    create_index: int,
    plan: PatchPlan,
) -> dict[bytes, Any]:
    validate_component_spec(spec, plan.catalog)
    family = plan.catalog.entries[spec.eid].structural_family
    if family in {"editor_unit", "editor_decoration"}:
        unit = _build_obstacle(spec, unit_id, create_index, plan)
        if family == "editor_decoration":
            unit[b"physic_enable"] = False
            unit.pop(b"is_static_obstacle", None)
        return unit
    if family == "editor_trigger":
        return _build_trigger(spec, unit_id, create_index, plan)
    if family == "editor_virtual_point":
        return _build_virtual_point(spec, unit_id, create_index, plan)
    raise CapabilityError(
        f"EID {spec.eid}: unsupported runtime-rebuild family {family!r}"
    )


def _unit_name(unit: Mapping[Any, Any]) -> str | None:
    value = _get(unit, "name")
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return None
    return value if isinstance(value, str) else None


def _write_mm(path: Path, value: Any, level: int) -> None:
    path.write_bytes(encode_mm(value, compression_level=level))


def _hash_tree(root: Path) -> dict[str, tuple[str, str]]:
    hashes: dict[str, tuple[str, str]] = {}
    for item in sorted(root.rglob("*")):
        if item.is_file():
            raw = item.read_bytes()
            hashes[item.relative_to(root).as_posix()] = (
                hashlib.sha256(raw).hexdigest(),
                hashlib.blake2b(raw).hexdigest(),
            )
    return hashes


def _manifest_bytes(plan: PatchPlan) -> bytes:
    payload = [
        {
            "name": spec.logical_name,
            "eid": spec.eid,
            "center": spec.transform.world_aabb.center,
            "size": spec.transform.world_aabb.size,
            "rotation": spec.transform.rotation_deg,
            "forward": spec.transform.forward_axis,
            "color": spec.color,
            "properties": dict(spec.properties),
        }
        for spec in plan.manifest.components
    ]
    return json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")


def apply_runtime_rebuild(plan: PatchPlan, output: Path) -> ApplyResult:
    if plan.cache_strategy != "runtime-rebuild":
        raise CapabilityError(
            "runtime-rebuild apply requires the matching plan strategy"
        )
    if output.exists():
        raise ValidationError(f"fresh output directory already exists: {output}")
    shutil.copytree(plan.snapshot.root, output, copy_function=shutil.copy2)

    source_unit = copy.deepcopy(plan.snapshot.decoded("unit.mm"))
    source_units = _get(source_unit, "unit")
    source_indices = _get(source_unit, "_unit_create_index")
    if not isinstance(source_units, dict) or not isinstance(source_indices, dict):
        raise ValidationError("unit.mm identity tables are malformed")
    existing: dict[tuple[str, int], list[int]] = {}
    for unit_id, row in source_units.items():
        if not isinstance(row, Mapping):
            continue
        name, eid = _unit_name(row), _get(row, "eid")
        if name is not None and type(eid) is int:
            existing.setdefault((name, eid), []).append(unit_id)
    deleted_ids: set[int] = set()
    for action in plan.actions:
        if action.kind == "logic-prune":
            deleted_ids.update(action.details.get("deleted_unit_ids", ()))
    bindings = _get(source_unit, "unit_bind_infos10", {})
    if _contains_unit_id(bindings, deleted_ids):
        raise CapabilityError(
            "unit bindings reference a deleted component and have no generic rewrite profile"
        )
    seed = int.from_bytes(
        hashlib.sha256(
            plan.snapshot.files["unit.mm"].raw + _manifest_bytes(plan)
        ).digest()[:16],
        "big",
    )
    allocator = InstanceAllocator(
        create_indices=dict(source_indices),
        used_unit_ids=set(source_units),
        algorithm="package-randint-positive-i31",
        random_source=random.Random(seed),
    )
    replaced_ids = {
        min(existing[(spec.logical_name, spec.eid)])
        for spec in plan.manifest.components
        if existing.get((spec.logical_name, spec.eid))
    }
    units: dict[int, dict[Any, Any]] = {
        unit_id: copy.deepcopy(row)
        for unit_id, row in source_units.items()
        if unit_id not in deleted_ids and unit_id not in replaced_ids
    }
    for spec in plan.manifest.components:
        matches = sorted(existing.get((spec.logical_name, spec.eid), ()))
        if matches:
            unit_id = matches[0]
            create_index = allocator.create_indices.get(spec.eid, 1)
        else:
            unit_id, create_index = allocator.allocate(spec.eid)
        units[unit_id] = build_runtime_rebuild_unit(
            spec, unit_id=unit_id, create_index=create_index, plan=plan
        )
    _set(source_unit, "unit", units)
    _set(source_unit, "_unit_create_index", allocator.create_indices)
    _set(source_unit, "del_parent_unit_list", [])
    _set(
        source_unit,
        "save_version_uuid",
        _deterministic_uuid(list(units), _manifest_bytes(plan)),
    )
    _write_mm(output / "unit.mm", source_unit, plan.compression_level)

    desc = copy.deepcopy(plan.snapshot.decoded("desc.mm"))
    if not isinstance(desc, dict):
        raise ValidationError("desc.mm root is not a map")
    for key, value in plan.manifest.map_settings.items():
        _set(desc, key, value)
    _write_mm(output / "desc.mm", desc, plan.compression_level)

    source_editor = plan.snapshot.decoded("uniteditor.mm")
    if not isinstance(source_editor, dict):
        raise ValidationError("uniteditor.mm root is not a map")
    desired_ids = set(units) - (set(source_units) - deleted_ids - replaced_ids)
    unit_editor: dict[int, dict[Any, Any]] = {
        unit_id: copy.deepcopy(source_editor[unit_id])
        for unit_id in units
        if unit_id not in desired_ids and unit_id in source_editor
    }
    spawn_ids: list[int] = []
    character_start: list[dict[bytes, Any]] = []
    for unit_id, unit in units.items():
        type_id = unit[b"unit_type"]
        if unit_id in desired_ids:
            editor_row: dict[bytes, Any] = {
                b"in_lock": False,
                b"filter_visible": True,
                b"children_unit_id_order": [],
            }
            if type_id in (256, 1024):
                editor_row[b"unit_auto_opti"] = bool(unit.get(b"MotorOpti", False))
            elif type_id == 512:
                editor_row[b"navmesh_include_layer"] = [_MARKER]
            elif type_id == 16384:
                editor_row[b"group_center_lock"] = False
            unit_editor[unit_id] = editor_row
        elif unit_id not in unit_editor:
            raise ValidationError(f"uniteditor.mm is missing preserved unit {unit_id}")
        if type_id == 16384:
            spawn_ids.append(unit_id)
            character_start.append(
                {
                    b"role_id": int(unit.get(b"role_id", 1)),
                    b"type": 128,
                    b"radius": 0.75,
                    b"height": 0.25,
                    b"position": copy.deepcopy(unit[b"world_position"]),
                    b"model_angle": copy.deepcopy(unit[b"model_angle"]),
                }
            )
    _write_mm(output / "uniteditor.mm", unit_editor, plan.compression_level)
    _write_mm(output / "characterstart.mm", character_start, plan.compression_level)

    editing_cache = copy.deepcopy(plan.snapshot.decoded("editingcache.mm"))
    editing_cache[b"level_info"] = {
        b"level_order_list": [],
        b"level_infos": {},
    }
    editing_cache[b"story_dialog"] = {}
    editing_cache[b"born_point"] = spawn_ids
    editing_cache[b"lua_info"] = {b"custom_file": []}
    _write_mm(output / "editingcache.mm", editing_cache, plan.compression_level)

    cache = copy.deepcopy(plan.snapshot.decoded("editingcachewithlevel.mm"))
    cache[b"preload_unit_material_content"] = {}
    cache[b"loader_content"] = {}
    cache[b"unit_display_data"] = {}
    # Preserve the old cache UUID so it cannot claim to match the rewritten unit file.
    _write_mm(output / "editingcachewithlevel.mm", cache, plan.compression_level)

    preload = copy.deepcopy(plan.snapshot.decoded("preloadres.mm"))
    preload[b"preload_trigger"] = {}
    preload[b"preload_unit_material"] = {}
    preload[b"preload_collect_res"] = {b"model_sfx_list": [], b"graph_set": []}
    _write_mm(output / "preloadres.mm", preload, plan.compression_level)

    source_new_preload = plan.snapshot.decoded("newpreloadres.mm")
    container = inventory_native_tasks(source_new_preload, loader_version=1)
    empty_container = NativeTaskContainer(1, container.compressed, 0, ())
    new_preload = {
        b"batch_loader_data": {
            b"batch_unit_data": {},
            b"batch_task_data": encode_task_container(
                empty_container, compression_level=plan.compression_level
            ),
            b"dynamic_mesh_paths": {},
            b"batch_merge_model_idmap": {},
        }
    }
    _write_mm(output / "newpreloadres.mm", new_preload, plan.compression_level)
    _write_mm(output / "staticobstacle.mm", [], plan.compression_level)

    source_l10n = plan.snapshot.decoded("commonl10ndata.mm")
    if not isinstance(source_l10n, dict):
        raise ValidationError("commonl10ndata.mm root is not a map")
    l10n: dict[Any, Any] = copy.deepcopy(source_l10n)
    current_eids = {_get(unit, "eid") for unit in units.values()}
    deleted_eids = {
        _get(unit, "eid")
        for unit_id, unit in source_units.items()
        if unit_id in deleted_ids
    }
    for eid in deleted_eids - current_eids:
        l10n.pop(f"SJZJ_NAME_{eid}", None)
        l10n.pop(f"SJZJ_NAME_{eid}".encode(), None)
    for eid in current_eids:
        entry = plan.catalog.entries.get(eid)
        if entry is not None:
            key = f"SJZJ_NAME_{eid}".encode()
            l10n.setdefault(key, entry.name.encode("utf-8"))
    _write_mm(output / "commonl10ndata.mm", l10n, plan.compression_level)

    generated = open_snapshot(output)
    validate_runtime_rebuild_output(generated, plan)
    return ApplyResult(plan=plan, output=output, hashes=_hash_tree(output))


def _walk_ints(value: Any) -> list[int]:
    result: list[int] = []
    if type(value) is int:
        result.append(value)
    elif isinstance(value, Mapping):
        for key, item in value.items():
            result.extend(_walk_ints(key))
            result.extend(_walk_ints(item))
    elif isinstance(value, (list, tuple)):
        for item in value:
            result.extend(_walk_ints(item))
    return result


def validate_runtime_rebuild_output(snapshot: MapSnapshot, plan: PatchPlan) -> None:
    if set(snapshot.files) != set(plan.snapshot.files):
        raise ValidationError("runtime rebuild changed the map file inventory")
    graph = build_reference_graph(snapshot)
    units = _get(snapshot.decoded("unit.mm"), "unit")
    if not isinstance(units, dict):
        raise ValidationError("generated unit table is malformed")
    expected = Counter(
        (spec.logical_name, spec.eid) for spec in plan.manifest.components
    )
    actual = Counter(
        (_unit_name(unit), graph.unit_eids[unit_id]) for unit_id, unit in units.items()
    )
    if plan.cleanup_policy == "whitelist" and actual != expected:
        raise ValidationError(
            "generated unit inventory differs from whitelist manifest"
        )
    if any(actual[key] != count for key, count in expected.items()):
        raise ValidationError(
            "generated map does not contain each declared component exactly once"
        )
    for spec in plan.manifest.components:
        unit = next(
            row
            for row in units.values()
            if _unit_name(row) == spec.logical_name and _get(row, "eid") == spec.eid
        )
        if (
            spec.color is not None
            and tuple(_get(unit, "paint_area1")[:3]) != spec.color
        ):
            raise ValidationError(f"{spec.logical_name}: public color differs")
    desc = snapshot.decoded("desc.mm")
    for key, value in plan.manifest.map_settings.items():
        if _get(desc, key) != value:
            raise ValidationError(f"desc.mm setting {key!r} differs")
    uniteditor = snapshot.decoded("uniteditor.mm")
    if not isinstance(uniteditor, dict) or set(uniteditor) != set(units):
        raise ValidationError("uniteditor membership differs from unit inventory")
    cache = snapshot.decoded("editingcachewithlevel.mm")
    for key in (
        "preload_unit_material_content",
        "loader_content",
        "unit_display_data",
    ):
        if _get(cache, key) != {}:
            raise ValidationError(f"derived cache {key} was not invalidated")
    if _get(cache, "save_version_uuid") == _get(
        snapshot.decoded("unit.mm"), "save_version_uuid"
    ):
        raise ValidationError("derived cache UUID still matches rewritten unit data")
    preload = snapshot.decoded("preloadres.mm")
    if _get(preload, "preload_unit_material") != {}:
        raise ValidationError("preload material cache was not invalidated")
    native = inventory_native_tasks(
        snapshot.decoded("newpreloadres.mm"), loader_version=1
    )
    if native.tasks:
        raise ValidationError("native batch task cache was not invalidated")
    batch = _get(snapshot.decoded("newpreloadres.mm"), "batch_loader_data")
    if _get(batch, "batch_unit_data") != {}:
        raise ValidationError("public batch cache was not invalidated")
    if snapshot.decoded("staticobstacle.mm") != []:
        raise ValidationError("static collision cache was not invalidated")
    born = _get(snapshot.decoded("editingcache.mm"), "born_point")
    spawn_ids = [
        unit_id for unit_id, unit in units.items() if _get(unit, "unit_type") == 16384
    ]
    if born != spawn_ids or len(snapshot.decoded("characterstart.mm")) != len(
        spawn_ids
    ):
        raise ValidationError("spawn cache does not match the generated spawn units")
    deleted_ids = set(_get(plan.snapshot.decoded("unit.mm"), "unit")) - set(units)
    for name, record in snapshot.files.items():
        if record.decoded is None or name == "unit.mm":
            continue
        stale = deleted_ids.intersection(_walk_ints(record.decoded))
        if stale:
            raise ValidationError(f"{name}: stale deleted-unit references remain")
    for name in _LOGIC_FILES:
        if (
            name in plan.snapshot.files
            and snapshot.files[name].raw != plan.snapshot.files[name].raw
        ):
            raise ValidationError(
                f"{name}: logic file changed during generic reconciliation"
            )

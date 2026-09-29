from __future__ import annotations

import base64
import copy
import hashlib
import json
import random
import shutil
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from .allocator import InstanceAllocator
from .capabilities import validate_component_spec
from .codec import encode_mm
from .errors import CapabilityError
from .graph import build_reference_graph
from .models import ComponentProfile, ComponentSpec, MapSnapshot, PackageCatalog
from .native_tasks import (
    NativeTaskContainer,
    encode_task_container,
    inventory_native_tasks,
)
from .snapshot import open_snapshot

_BUILDERS: dict[str, Any] = {}


def create_component(
    eid: int,
    logical_name: str,
    transform: Any,
    properties: Mapping[str, Any],
    *,
    catalog: PackageCatalog,
    profile: ComponentProfile,
    allocator: InstanceAllocator,
) -> dict[bytes, Any]:
    if not all(
        (
            profile.prefab_complete,
            profile.public_cache_complete,
            profile.native_create_complete,
        )
    ):
        raise CapabilityError(f"EID {eid}: byte-complete creation profile required")
    if eid not in catalog.entries:
        raise CapabilityError(f"EID {eid}: missing from package catalog")
    builder = _BUILDERS.get(profile.package_fingerprint)
    if builder is None:
        raise CapabilityError(
            "no byte-complete component constructor is registered for the matched profile"
        )
    unit_id, create_index = allocator.allocate(eid)
    return builder(
        eid=eid,
        unit_id=unit_id,
        create_index=create_index,
        logical_name=logical_name,
        transform=transform,
        properties=properties,
        catalog=catalog,
        profile=profile,
    )


def spec_to_request(spec: ComponentSpec) -> dict[str, Any]:
    return {
        "eid": spec.eid,
        "logical_name": spec.logical_name,
        "transform": spec.transform,
        "properties": dict(spec.properties),
    }


def _get(mapping: Mapping[Any, Any], key: str, default: Any = None) -> Any:
    return mapping.get(key, mapping.get(key.encode(), default))


def _set(mapping: dict[Any, Any], key: str, value: Any) -> None:
    encoded = key.encode()
    mapping[encoded if encoded in mapping or key not in mapping else key] = value


def _spec_payload(spec: ComponentSpec) -> bytes:
    return json.dumps(
        {
            "name": spec.logical_name,
            "eid": spec.eid,
            "center": spec.transform.world_aabb.center,
            "size": spec.transform.world_aabb.size,
            "rotation": spec.transform.rotation_deg,
            "forward": spec.transform.forward_axis,
            "color": spec.color,
            "properties": dict(spec.properties),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _source_uuid(unit_ids: list[int], payload: bytes) -> bytes:
    digest = hashlib.sha256(
        payload + b"\0" + b",".join(str(value).encode() for value in unit_ids)
    ).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=")[:22]


def apply_component_addition_with_runtime_rebuild(
    snapshot: MapSnapshot,
    spec: ComponentSpec,
    *,
    catalog: PackageCatalog,
    output: str | Path,
    compression_level: int = 3,
) -> tuple[Path, int]:
    """Add one top-level component and invalidate only derived runtime caches.

    Existing source units and logic remain byte-semantically unchanged. The first
    editor open is part of the transaction and must rebuild the emptied caches.
    """
    if not 1 <= compression_level <= 22:
        raise CapabilityError("compression level must be in 1..22")
    destination = Path(output).expanduser().resolve()
    if destination.exists():
        raise CapabilityError(f"fresh addition output already exists: {destination}")
    validate_component_spec(spec, catalog)

    graph = build_reference_graph(snapshot)
    unit_root = copy.deepcopy(snapshot.decoded("unit.mm"))
    units = _get(unit_root, "unit")
    indices = _get(unit_root, "_unit_create_index")
    if not isinstance(units, dict) or not isinstance(indices, dict):
        raise CapabilityError("unit.mm identity tables are malformed")
    for unit in units.values():
        if not isinstance(unit, Mapping):
            raise CapabilityError("unit.mm contains a malformed unit")
        name = _get(unit, "name")
        if isinstance(name, bytes):
            name = name.decode("utf-8")
        if name == spec.logical_name and _get(unit, "eid") == spec.eid:
            raise CapabilityError("logical name and EID already identify a component")

    payload = _spec_payload(spec)
    seed = int.from_bytes(
        hashlib.sha256(snapshot.files["unit.mm"].raw + payload).digest()[:16], "big"
    )
    allocator = InstanceAllocator(
        create_indices=dict(indices),
        used_unit_ids=set(graph.unit_ids),
        algorithm="package-randint-positive-i31",
        random_source=random.Random(seed),
    )
    unit_id, create_index = allocator.allocate(spec.eid)
    from .runtime_rebuild import build_runtime_rebuild_unit

    unit = build_runtime_rebuild_unit(
        spec,
        unit_id=unit_id,
        create_index=create_index,
        plan=SimpleNamespace(catalog=catalog),
    )
    units[unit_id] = unit
    _set(unit_root, "_unit_create_index", allocator.create_indices)
    _set(unit_root, "save_version_uuid", _source_uuid(list(units), payload))

    required_caches = {
        "characterstart.mm",
        "editingcache.mm",
        "editingcachewithlevel.mm",
        "preloadres.mm",
        "newpreloadres.mm",
        "staticobstacle.mm",
        "commonl10ndata.mm",
    }
    missing = sorted(required_caches - set(snapshot.files))
    if missing:
        raise CapabilityError(
            "runtime-rebuild addition requires existing cache containers: "
            + ", ".join(missing)
        )
    shutil.copytree(snapshot.root, destination, copy_function=shutil.copy2)

    (destination / "unit.mm").write_bytes(
        encode_mm(unit_root, compression_level=compression_level)
    )
    editor = copy.deepcopy(snapshot.decoded("uniteditor.mm"))
    if not isinstance(editor, dict) or set(editor) != set(graph.unit_ids):
        raise CapabilityError("uniteditor membership differs from the source units")
    editor_row: dict[bytes, Any] = {
        b"in_lock": False,
        b"filter_visible": True,
        b"children_unit_id_order": [],
    }
    if unit[b"unit_type"] in (256, 1024):
        editor_row[b"unit_auto_opti"] = bool(unit.get(b"MotorOpti", False))
    elif unit[b"unit_type"] == 16384:
        editor_row[b"group_center_lock"] = False
    editor[unit_id] = editor_row
    (destination / "uniteditor.mm").write_bytes(
        encode_mm(editor, compression_level=compression_level)
    )

    if unit[b"unit_type"] == 16384:
        editing = copy.deepcopy(snapshot.decoded("editingcache.mm"))
        if not isinstance(editing, dict):
            raise CapabilityError("editingcache.mm root is not a map")
        born = _get(editing, "born_point")
        if not isinstance(born, list) or any(type(value) is not int for value in born):
            raise CapabilityError("editingcache.mm born_point is not an integer list")
        _set(editing, "born_point", [*born, unit_id])
        (destination / "editingcache.mm").write_bytes(
            encode_mm(editing, compression_level=compression_level)
        )
        starts = copy.deepcopy(snapshot.decoded("characterstart.mm"))
        if not isinstance(starts, list):
            raise CapabilityError("characterstart.mm root is not a list")
        starts.append(
            {
                b"role_id": int(unit.get(b"role_id", 1)),
                b"type": 128,
                b"radius": 0.75,
                b"height": 0.25,
                b"position": copy.deepcopy(unit[b"world_position"]),
                b"model_angle": copy.deepcopy(unit[b"model_angle"]),
            }
        )
        (destination / "characterstart.mm").write_bytes(
            encode_mm(starts, compression_level=compression_level)
        )

    cache = copy.deepcopy(snapshot.decoded("editingcachewithlevel.mm"))
    if not isinstance(cache, dict):
        raise CapabilityError("editingcachewithlevel.mm root is not a map")
    for key in (
        "preload_unit_material_content",
        "loader_content",
        "unit_display_data",
    ):
        _set(cache, key, {})
    (destination / "editingcachewithlevel.mm").write_bytes(
        encode_mm(cache, compression_level=compression_level)
    )

    preload = copy.deepcopy(snapshot.decoded("preloadres.mm"))
    if not isinstance(preload, dict):
        raise CapabilityError("preloadres.mm root is not a map")
    _set(preload, "preload_trigger", {})
    _set(preload, "preload_unit_material", {})
    _set(preload, "preload_collect_res", {b"model_sfx_list": [], b"graph_set": []})
    (destination / "preloadres.mm").write_bytes(
        encode_mm(preload, compression_level=compression_level)
    )

    source_new_preload = snapshot.decoded("newpreloadres.mm")
    native = inventory_native_tasks(source_new_preload, loader_version=1)
    empty_native = NativeTaskContainer(1, native.compressed, 0, ())
    new_preload = {
        b"batch_loader_data": {
            b"batch_unit_data": {},
            b"batch_task_data": encode_task_container(
                empty_native, compression_level=compression_level
            ),
            b"dynamic_mesh_paths": {},
            b"batch_merge_model_idmap": {},
        }
    }
    (destination / "newpreloadres.mm").write_bytes(
        encode_mm(new_preload, compression_level=compression_level)
    )
    (destination / "staticobstacle.mm").write_bytes(
        encode_mm([], compression_level=compression_level)
    )

    l10n = copy.deepcopy(snapshot.decoded("commonl10ndata.mm"))
    if not isinstance(l10n, dict):
        raise CapabilityError("commonl10ndata.mm root is not a map")
    l10n_key = f"SJZJ_NAME_{spec.eid}".encode()
    l10n.setdefault(l10n_key, catalog.entries[spec.eid].name.encode("utf-8"))
    (destination / "commonl10ndata.mm").write_bytes(
        encode_mm(l10n, compression_level=compression_level)
    )

    result = open_snapshot(destination)
    result_graph = build_reference_graph(result)
    if result_graph.unit_ids != graph.unit_ids | {unit_id}:
        raise CapabilityError(
            "post-add unit inventory differs from the planned addition"
        )
    if set(result.decoded("uniteditor.mm")) != set(result_graph.unit_ids):
        raise CapabilityError("post-add uniteditor membership differs from units")
    result_cache = result.decoded("editingcachewithlevel.mm")
    if any(
        _get(result_cache, key) != {}
        for key in (
            "preload_unit_material_content",
            "loader_content",
            "unit_display_data",
        )
    ):
        raise CapabilityError("post-add derived editor caches were not invalidated")
    if inventory_native_tasks(
        result.decoded("newpreloadres.mm"), loader_version=1
    ).tasks:
        raise CapabilityError("post-add private native cache was not invalidated")
    return destination, unit_id

from __future__ import annotations

import copy
import shutil
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, Literal

from .codec import encode_mm
from .errors import CapabilityError
from .graph import ReferenceGraph, build_reference_graph, deletion_closure
from .models import MapSnapshot
from .native_tasks import (
    NativeTaskContainer,
    encode_task_container,
    inventory_native_tasks,
)
from .snapshot import open_snapshot


def delete_component(
    unit_id: int, *, graph: ReferenceGraph, closure: str = "full"
) -> frozenset[int]:
    if closure != "full":
        raise CapabilityError("only full deletion closure is accepted")
    targets = deletion_closure(graph, [unit_id])
    unknown = [ref for ref in graph.unknown_references if ref.unit_id in targets]
    if unknown:
        locations = ", ".join(f"{ref.file}:{ref.path}" for ref in unknown[:8])
        raise CapabilityError(
            f"unit deletion has unclassified reverse references: {locations}"
        )
    return targets


def _get(mapping: Mapping[Any, Any], key: str, default: Any = None) -> Any:
    return mapping.get(key, mapping.get(key.encode(), default))


def _table(mapping: Mapping[Any, Any], key: str) -> dict[Any, Any] | None:
    value = _get(mapping, key)
    if value is None:
        return None
    if not isinstance(value, dict):
        raise CapabilityError(f"{key} is not a map")
    return value


def _contains_deleted_id(value: Any, deleted: frozenset[int]) -> bool:
    if type(value) is int:
        return value in deleted
    if isinstance(value, Mapping):
        return any(
            _contains_deleted_id(key, deleted) or _contains_deleted_id(item, deleted)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_deleted_id(item, deleted) for item in value)
    return False


def apply_component_deletions(
    snapshot: MapSnapshot,
    unit_ids: Iterable[int],
    *,
    output: str | Path,
    loader_version: Literal[1, 2] = 1,
    compression_level: int = 3,
) -> Path:
    """Delete a complete unit closure and every resolved derived reference.

    Derived caches are invalidated for first-open rebuilding. Spawn points and
    every unclassified reverse-reference container remain fail-closed.
    """
    requested = frozenset(unit_ids)
    if not requested or any(type(unit_id) is not int for unit_id in requested):
        raise CapabilityError("one or more integer unit IDs are required")
    if not 1 <= compression_level <= 22:
        raise CapabilityError("compression level must be in 1..22")
    destination = Path(output).expanduser().resolve()
    if destination.exists():
        raise CapabilityError(f"fresh deletion output already exists: {destination}")

    graph = build_reference_graph(snapshot)
    missing = requested - graph.unit_ids
    if missing:
        raise CapabilityError(f"cannot delete missing unit IDs: {sorted(missing)}")
    units = _table(snapshot.decoded("unit.mm"), "unit")
    if units is None:
        raise CapabilityError("unit.mm has no unit table")
    deleted = deletion_closure(graph, requested)
    if any(_get(units[unit_id], "unit_type") == 16384 for unit_id in deleted):
        raise CapabilityError(
            "spawn deletion requires a character-start projection Profile"
        )
    unknown = [ref for ref in graph.unknown_references if ref.unit_id in deleted]
    if unknown:
        locations = ", ".join(f"{ref.file}:{ref.path}" for ref in unknown[:8])
        raise CapabilityError(
            f"deletion has unclassified reverse references: {locations}"
        )

    shutil.copytree(snapshot.root, destination, copy_function=shutil.copy2)
    rewritten: dict[str, Any] = {}

    unit_root = copy.deepcopy(snapshot.decoded("unit.mm"))
    unit_table = _table(unit_root, "unit")
    assert unit_table is not None
    for unit_id in deleted:
        unit_table.pop(unit_id)
    rewritten["unit.mm"] = unit_root

    editor = copy.deepcopy(snapshot.decoded("uniteditor.mm"))
    if not isinstance(editor, dict):
        raise CapabilityError("uniteditor.mm root is not a map")
    for unit_id in deleted:
        if unit_id not in editor:
            raise CapabilityError(f"uniteditor is missing deleted unit {unit_id}")
        editor.pop(unit_id)
    rewritten["uniteditor.mm"] = editor

    if "editingcachewithlevel.mm" in snapshot.files:
        cache = copy.deepcopy(snapshot.decoded("editingcachewithlevel.mm"))
        if not isinstance(cache, dict):
            raise CapabilityError("editingcachewithlevel.mm root is not a map")
        for key in (
            "preload_unit_material_content",
            "loader_content",
            "unit_display_data",
        ):
            encoded = key.encode()
            cache[encoded if encoded in cache or key not in cache else key] = {}
        rewritten["editingcachewithlevel.mm"] = cache

    if "editingcache.mm" in snapshot.files:
        editing = copy.deepcopy(snapshot.decoded("editingcache.mm"))
        if not isinstance(editing, dict):
            raise CapabilityError("editingcache.mm root is not a map")
        for key, value in (
            ("level_info", {b"level_order_list": [], b"level_infos": {}}),
            ("story_dialog", {}),
            ("lua_info", {b"custom_file": []}),
        ):
            encoded = key.encode()
            editing[encoded if encoded in editing or key not in editing else key] = (
                value
            )
        rewritten["editingcache.mm"] = editing

    if "preloadres.mm" in snapshot.files:
        preload = copy.deepcopy(snapshot.decoded("preloadres.mm"))
        if not isinstance(preload, dict):
            raise CapabilityError("preloadres.mm root is not a map")
        for key, value in (
            ("preload_trigger", {}),
            ("preload_unit_material", {}),
            ("preload_collect_res", {b"model_sfx_list": [], b"graph_set": []}),
        ):
            encoded = key.encode()
            preload[encoded if encoded in preload or key not in preload else key] = (
                value
            )
        rewritten["preloadres.mm"] = preload

    if "newpreloadres.mm" in snapshot.files:
        new_preload = copy.deepcopy(snapshot.decoded("newpreloadres.mm"))
        if not isinstance(new_preload, dict):
            raise CapabilityError("newpreloadres.mm root is not a map")
        batch = _table(new_preload, "batch_loader_data")
        if batch is None:
            raise CapabilityError("newpreloadres.mm has no batch loader table")
        public = _table(batch, "batch_unit_data")
        if public is None:
            raise CapabilityError("newpreloadres.mm has no public batch-unit table")
        native = inventory_native_tasks(new_preload, loader_version=loader_version)
        public_ids = list(public)
        native_ids = [task.task_id for task in native.tasks]
        if public_ids != native_ids:
            raise CapabilityError(
                "public/private batch task order differs before deletion"
            )
        public.clear()
        batch_key = (
            b"batch_task_data" if b"batch_task_data" in batch else "batch_task_data"
        )
        batch[batch_key] = encode_task_container(
            NativeTaskContainer(loader_version, native.compressed, 0, ()),
            compression_level=compression_level,
        )
        for key in ("dynamic_mesh_paths", "batch_merge_model_idmap"):
            encoded = key.encode()
            batch[encoded if encoded in batch or key not in batch else key] = {}
        rewritten["newpreloadres.mm"] = new_preload

    if "staticobstacle.mm" in snapshot.files:
        static_rows = copy.deepcopy(snapshot.decoded("staticobstacle.mm"))
        if not isinstance(static_rows, list):
            raise CapabilityError("staticobstacle.mm root is not a list")
        rewritten["staticobstacle.mm"] = []

    if "commonl10ndata.mm" in snapshot.files:
        l10n = copy.deepcopy(snapshot.decoded("commonl10ndata.mm"))
        if not isinstance(l10n, dict):
            raise CapabilityError("commonl10ndata.mm root is not a map")
        remaining_eids = {
            _get(unit, "eid")
            for unit_id, unit in units.items()
            if unit_id not in deleted
        }
        deleted_eids = {_get(units[unit_id], "eid") for unit_id in deleted}
        for eid in deleted_eids - remaining_eids:
            l10n.pop(f"SJZJ_NAME_{eid}", None)
            l10n.pop(f"SJZJ_NAME_{eid}".encode(), None)
        rewritten["commonl10ndata.mm"] = l10n

    for name, value in rewritten.items():
        (destination / name).write_bytes(
            encode_mm(value, compression_level=compression_level)
        )

    result = open_snapshot(destination)
    if set(result.files) != set(snapshot.files):
        raise CapabilityError("deletion changed the map file inventory")
    result_graph = build_reference_graph(result)
    if result_graph.unit_ids != graph.unit_ids - deleted:
        raise CapabilityError(
            "post-delete unit inventory differs from requested closure"
        )
    for name, record in result.files.items():
        if record.decoded is not None and _contains_deleted_id(record.decoded, deleted):
            raise CapabilityError(f"{name} still contains a deleted unit ID")
    if "newpreloadres.mm" in result.files:
        new_preload = result.decoded("newpreloadres.mm")
        batch = _table(new_preload, "batch_loader_data")
        assert batch is not None
        public = _table(batch, "batch_unit_data")
        assert public is not None
        native = inventory_native_tasks(new_preload, loader_version=loader_version)
        if list(public) != [task.task_id for task in native.tasks]:
            raise CapabilityError(
                "public/private batch task order differs after deletion"
            )
    return destination

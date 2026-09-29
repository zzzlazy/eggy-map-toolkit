from pathlib import Path

from eggy_map_api.apply import apply
from eggy_map_api.codec import encode_mm
from eggy_map_api.models import (
    CatalogEntry,
    ComponentSpec,
    CourseManifest,
    PackageCatalog,
    TransformSpec,
    WorldAABB,
)
from eggy_map_api.native_tasks import NativeTaskContainer, encode_task_container
from eggy_map_api.planner import plan_reconcile
from eggy_map_api.profiles import ProfileRegistry, ResolvedProfile
from eggy_map_api.snapshot import open_snapshot
from eggy_map_api.validate import validate, validate_snapshot_integrity


def write_mm(root: Path, name: str, value: object) -> None:
    (root / name).write_bytes(encode_mm(value, compression_level=3))


def existing_unit(unit_id: int, *, name: bytes = b"existing") -> dict[bytes, object]:
    return {
        b"unit_id": unit_id,
        b"name": name,
        b"eid": 71,
        b"unit_type": 256,
        b"parent_unit_id": 0,
        b"children_unit_id": [],
    }


def synthetic_snapshot(tmp_path: Path, *, duplicate: bool = False):
    source = tmp_path / "source"
    source.mkdir()
    (source / "header.map").write_bytes(b"synthetic")
    units = {5001: existing_unit(5001)}
    if duplicate:
        units[5002] = existing_unit(5002, name=b"managed")
        units[5001] = existing_unit(5001, name=b"managed")
    write_mm(
        source,
        "unit.mm",
        {
            b"unit": units,
            b"_unit_create_index": {71: len(units), 72: 0},
            b"save_version_uuid": b"source",
        },
    )
    write_mm(source, "desc.mm", {b"max_game_time": 90})
    write_mm(source, "uniteditor.mm", {unit_id: {} for unit_id in units})
    write_mm(source, "editingcache.mm", {b"born_point": [], b"other": 1})
    write_mm(source, "characterstart.mm", [])
    write_mm(
        source,
        "editingcachewithlevel.mm",
        {
            b"preload_unit_material_content": {unit_id: {} for unit_id in units},
            b"loader_content": {},
            b"unit_display_data": {},
            b"save_version_uuid": b"old-cache",
        },
    )
    write_mm(
        source,
        "preloadres.mm",
        {
            b"preload_trigger": {},
            b"preload_unit_material": {},
            b"preload_collect_res": {b"model_sfx_list": [], b"graph_set": []},
        },
    )
    write_mm(
        source,
        "newpreloadres.mm",
        {
            b"batch_loader_data": {
                b"batch_unit_data": {},
                b"batch_task_data": encode_task_container(
                    NativeTaskContainer(1, False, 0, ())
                ),
            }
        },
    )
    write_mm(source, "staticobstacle.mm", [])
    write_mm(source, "commonl10ndata.mm", {})
    write_mm(source, "globaltrigger.mm", {b"events": []})
    return open_snapshot(source)


def synthetic_catalog() -> PackageCatalog:
    entries = {
        eid: CatalogEntry(
            eid=eid,
            name=f"Synthetic {eid}",
            structural_family="editor_unit",
            asset_type="unit",
            model_id=eid + 100,
            model_path=f"synthetic/{eid}.gim",
            model_cell=(2.0, 1.0, 2.0),
            property_keys=(),
            static_status="pass",
            evidence="synthetic",
        )
        for eid in (71, 72)
    }
    return PackageCatalog(
        root=Path("."),
        entries=entries,
        fingerprint="synthetic",
        prefab_defaults={
            eid: {
                "type": 256,
                "model": eid + 100,
                "paint_area1": (1, 2, 3),
            }
            for eid in entries
        },
        model_defaults={eid + 100: {"scale": (1.0, 1.0, 1.0)} for eid in entries},
    )


def component(name: str, eid: int = 72) -> ComponentSpec:
    return ComponentSpec(
        logical_name=name,
        eid=eid,
        transform=TransformSpec(WorldAABB((10.0, 2.0, 3.0), (4.0, 1.0, 2.0))),
        color=(12, 34, 56),
    )


def profile() -> ResolvedProfile:
    return ResolvedProfile(
        catalog=synthetic_catalog(),
        components=ProfileRegistry(),
        allocator_complete=True,
        desc_write_complete=True,
        cache_strategy="runtime-rebuild",
    )


def file_hashes(root: Path) -> dict[str, tuple[str, str]]:
    snapshot = open_snapshot(root)
    return {
        name: (record.sha256, record.blake2b) for name, record in snapshot.files.items()
    }


def test_managed_reconcile_preserves_unmanaged_and_is_byte_idempotent(
    tmp_path: Path,
) -> None:
    source = synthetic_snapshot(tmp_path)
    manifest = CourseManifest(1, (component("free-form logical name"),), {}, {})
    first_plan = plan_reconcile(
        snapshot=source,
        manifest=manifest,
        profile=profile(),
        cleanup_policy="managed_only",
    )
    validate(first_plan)
    first = apply(first_plan, output=tmp_path / "first")
    first_snapshot = open_snapshot(first.output)
    units = first_snapshot.decoded("unit.mm")[b"unit"]
    assert 5001 in units
    assert sum(row[b"name"] == b"free-form logical name" for row in units.values()) == 1
    assert (
        first_snapshot.files["globaltrigger.mm"].raw
        == source.files["globaltrigger.mm"].raw
    )
    validate_snapshot_integrity(first_snapshot)

    second_plan = plan_reconcile(
        snapshot=first_snapshot,
        manifest=manifest,
        profile=profile(),
        cleanup_policy="managed_only",
    )
    second = apply(second_plan, output=tmp_path / "second")
    assert file_hashes(first.output) == file_hashes(second.output)


def test_whitelist_removes_unmanaged_top_level_units(tmp_path: Path) -> None:
    source = synthetic_snapshot(tmp_path)
    manifest = CourseManifest(1, (component("only declared"),), {}, {})
    plan = plan_reconcile(
        snapshot=source,
        manifest=manifest,
        profile=profile(),
        cleanup_policy="whitelist",
    )
    result = apply(plan, output=tmp_path / "result")
    units = open_snapshot(result.output).decoded("unit.mm")[b"unit"]
    assert [row[b"name"] for row in units.values()] == [b"only declared"]


def test_duplicate_reconcile_keeps_lowest_closed_instance(tmp_path: Path) -> None:
    source = synthetic_snapshot(tmp_path, duplicate=True)
    manifest = CourseManifest(1, (component("managed", eid=71),), {}, {})
    plan = plan_reconcile(
        snapshot=source,
        manifest=manifest,
        profile=profile(),
        cleanup_policy="managed_only",
    )
    result = apply(plan, output=tmp_path / "result")
    units = open_snapshot(result.output).decoded("unit.mm")[b"unit"]
    assert list(units) == [5001]

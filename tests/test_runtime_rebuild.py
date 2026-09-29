from pathlib import Path
from types import SimpleNamespace

from eggy_map_api.codec import encode_mm
from eggy_map_api.component_builder import (
    apply_component_addition_with_runtime_rebuild,
)
from eggy_map_api.models import (
    CatalogEntry,
    ComponentSpec,
    PackageCatalog,
    TransformSpec,
    WorldAABB,
)
from eggy_map_api.native_tasks import NativeTaskContainer, encode_task_container
from eggy_map_api.runtime_rebuild import build_runtime_rebuild_unit
from eggy_map_api.snapshot import open_snapshot


def component(*, forward_axis=None) -> ComponentSpec:
    return ComponentSpec(
        logical_name="赛道_合成组件",
        eid=7,
        transform=TransformSpec(
            WorldAABB((1.0, 2.0, 3.0), (8.0, 1.0, 4.0)),
            forward_axis=forward_axis,
        ),
        color=(10, 20, 30),
    )


def catalog(prefab) -> PackageCatalog:
    entry = CatalogEntry(
        eid=7,
        name="合成组件",
        structural_family="editor_unit",
        asset_type="unit",
        model_id=9,
        model_path="synthetic/model.gim",
        model_cell=(8.0, 1.0, 4.0),
        property_keys=(),
        static_status="pass",
        evidence="synthetic",
    )
    return PackageCatalog(
        root=Path("."),
        entries={7: entry},
        fingerprint="synthetic",
        prefab_defaults={7: prefab},
        model_defaults={9: {}},
    )


def test_runtime_rebuild_staticizes_motionless_obstacle() -> None:
    plan = SimpleNamespace(
        catalog=catalog(
            {
                "type": 256,
                "model": 9,
                "BodyType": 1,
                "MotorOpti": True,
                "paint_area1": (1, 2, 3),
            }
        )
    )
    unit = build_runtime_rebuild_unit(
        component(), unit_id=77, create_index=1, plan=plan
    )
    assert unit[b"BodyType"] == 0
    assert unit[b"is_static_obstacle"] is True
    assert unit[b"scale"] == [1.0, 1.0, 1.0]
    assert unit[b"paint_area1"] == [10, 20, 30, b"\x11"]


def test_runtime_rebuild_rotates_local_positive_z_toward_negative_x() -> None:
    plan = SimpleNamespace(
        catalog=catalog(
            {
                "type": 256,
                "model": 9,
                "BodyType": 1,
                "MotorList": ({"LinearVelocity": (0.0, 0.0, 5.0)},),
                "paint_area1": (1, 2, 3),
            }
        )
    )
    unit = build_runtime_rebuild_unit(
        component(forward_axis="-x"), unit_id=78, create_index=1, plan=plan
    )
    assert unit[b"model_angle"] == [0.0, -90.0, 0.0]
    assert unit[b"scale"] == [0.5, 1.0, 2.0]
    assert unit[b"real_scale"] == [0.5, 1.0, 2.0]
    assert b"is_static_obstacle" not in unit
    assert unit[b"MotorList"][0][b"LinearVelocity"] == [0.0, 0.0, 5.0, b"\x11"]


def test_addition_preserves_units_and_invalidates_runtime_caches(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "header.map").write_bytes(b"synthetic")

    def write(name: str, value: object) -> None:
        (source / name).write_bytes(encode_mm(value, compression_level=3))

    keeper = {
        b"unit_id": 101,
        b"name": b"keeper",
        b"eid": 8,
        b"unit_type": 256,
        b"parent_unit_id": 0,
        b"children_unit_id": [],
    }
    write(
        "unit.mm",
        {
            b"unit": {101: keeper},
            b"_unit_create_index": {7: 2, 8: 1},
            b"save_version_uuid": b"source",
        },
    )
    write("desc.mm", {})
    write("uniteditor.mm", {101: {b"in_lock": False}})
    write("editingcache.mm", {b"born_point": []})
    write("characterstart.mm", [])
    write(
        "editingcachewithlevel.mm",
        {
            b"preload_unit_material_content": {101: {}},
            b"loader_content": {101: {}},
            b"unit_display_data": {101: {}},
            b"save_version_uuid": b"cache",
        },
    )
    write(
        "preloadres.mm",
        {
            b"preload_trigger": {101: {}},
            b"preload_unit_material": {101: {}},
            b"preload_collect_res": {b"model_sfx_list": [1], b"graph_set": [2]},
        },
    )
    write(
        "newpreloadres.mm",
        {
            b"batch_loader_data": {
                b"batch_unit_data": {101: {}},
                b"batch_task_data": encode_task_container(
                    NativeTaskContainer(1, False, 0, ())
                ),
            }
        },
    )
    write("staticobstacle.mm", [{b"unit_id": 101}])
    write("commonl10ndata.mm", {})

    result, added_id = apply_component_addition_with_runtime_rebuild(
        open_snapshot(source),
        component(),
        catalog=catalog(
            {
                "type": 256,
                "model": 9,
                "BodyType": 1,
                "MotorOpti": True,
                "paint_area1": (1, 2, 3),
            }
        ),
        output=tmp_path / "result",
    )
    generated = open_snapshot(result)
    root = generated.decoded("unit.mm")
    assert root[b"unit"][101] == keeper
    assert set(root[b"unit"]) == {101, added_id}
    assert root[b"unit"][added_id][b"name"] == "赛道_合成组件".encode()
    assert root[b"_unit_create_index"][7] == 3
    assert set(generated.decoded("uniteditor.mm")) == {101, added_id}
    cache = generated.decoded("editingcachewithlevel.mm")
    assert cache[b"loader_content"] == {}
    assert cache[b"unit_display_data"] == {}
    assert cache[b"preload_unit_material_content"] == {}
    assert generated.decoded("staticobstacle.mm") == []


def test_virtual_point_addition_updates_spawn_projection(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "header.map").write_bytes(b"synthetic")

    def write(name: str, value: object) -> None:
        (source / name).write_bytes(encode_mm(value, compression_level=3))

    write(
        "unit.mm",
        {
            b"unit": {},
            b"_unit_create_index": {14: 0},
            b"save_version_uuid": b"source",
        },
    )
    write("desc.mm", {})
    write("uniteditor.mm", {})
    write("editingcache.mm", {b"born_point": []})
    write("characterstart.mm", [])
    write(
        "editingcachewithlevel.mm",
        {
            b"preload_unit_material_content": {},
            b"loader_content": {},
            b"unit_display_data": {},
            b"save_version_uuid": b"cache",
        },
    )
    write(
        "preloadres.mm",
        {
            b"preload_trigger": {},
            b"preload_unit_material": {},
            b"preload_collect_res": {b"model_sfx_list": [], b"graph_set": []},
        },
    )
    write(
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
    write("staticobstacle.mm", [])
    write("commonl10ndata.mm", {})
    virtual_catalog = PackageCatalog(
        root=Path("."),
        entries={
            14: CatalogEntry(
                eid=14,
                name="Synthetic spawn",
                structural_family="editor_virtual_point",
                asset_type="unit",
                model_id=114,
                model_path="synthetic/spawn.gim",
                model_cell=(1.0, 1.0, 1.0),
                property_keys=(),
                static_status="pass",
                evidence="synthetic",
            )
        },
        fingerprint="synthetic",
        prefab_defaults={14: {"type": 16384, "model": 114}},
        model_defaults={114: {"scale": (1.0, 1.0, 1.0)}},
    )
    virtual_spec = ComponentSpec(
        logical_name="synthetic spawn",
        eid=14,
        transform=TransformSpec(WorldAABB((1.0, 2.0, 3.0), (1.0, 1.0, 1.0))),
        properties={"camp_id": 2, "role_id": 3},
    )
    result, added_id = apply_component_addition_with_runtime_rebuild(
        open_snapshot(source),
        virtual_spec,
        catalog=virtual_catalog,
        output=tmp_path / "result",
    )
    generated = open_snapshot(result)
    assert generated.decoded("editingcache.mm")[b"born_point"] == [added_id]
    assert generated.decoded("characterstart.mm")[0][b"role_id"] == 3
    assert generated.decoded("uniteditor.mm")[added_id][b"group_center_lock"] is False

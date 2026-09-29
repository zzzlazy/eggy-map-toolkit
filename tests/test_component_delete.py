from pathlib import Path

from eggy_map_api.codec import encode_mm
from eggy_map_api.component_delete import apply_component_deletions
from eggy_map_api.native_tasks import (
    NativeTaskContainer,
    NativeTaskV1Builder,
    encode_task_container,
    inventory_native_tasks,
)
from eggy_map_api.snapshot import open_snapshot


def write_mm(path: Path, value: object) -> None:
    path.write_bytes(encode_mm(value, compression_level=3))


def unit(unit_id: int, name: bytes) -> dict[bytes, object]:
    return {
        b"unit_id": unit_id,
        b"name": name,
        b"eid": 7,
        b"unit_type": 256,
        b"parent_unit_id": 0,
        b"children_unit_id": [],
    }


def test_delete_component_closes_public_and_private_batch_records(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "header.map").write_bytes(b"synthetic")
    write_mm(
        source / "unit.mm",
        {b"unit": {101: unit(101, b"delete"), 202: unit(202, b"keep")}},
    )
    write_mm(source / "desc.mm", {})
    write_mm(source / "uniteditor.mm", {101: {}, 202: {}})
    native = NativeTaskContainer(
        1,
        False,
        0,
        (
            NativeTaskV1Builder(101, b"delete.gim").finish(),
            NativeTaskV1Builder(202, b"keep.gim").finish(),
        ),
    )
    write_mm(
        source / "newpreloadres.mm",
        {
            b"batch_loader_data": {
                b"batch_unit_data": {101: {}, 202: {}},
                b"batch_task_data": encode_task_container(native),
            }
        },
    )

    result = apply_component_deletions(
        open_snapshot(source), [101], output=tmp_path / "result"
    )
    snapshot = open_snapshot(result)
    assert set(snapshot.decoded("unit.mm")[b"unit"]) == {202}
    assert set(snapshot.decoded("uniteditor.mm")) == {202}
    batch = snapshot.decoded("newpreloadres.mm")[b"batch_loader_data"]
    assert list(batch[b"batch_unit_data"]) == []
    assert [
        task.task_id
        for task in inventory_native_tasks(
            snapshot.decoded("newpreloadres.mm"), loader_version=1
        ).tasks
    ] == []

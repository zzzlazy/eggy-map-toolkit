import struct
from dataclasses import replace

import pytest

from eggy_map_api.errors import SnapshotError
from eggy_map_api.native_tasks import (
    GroupSwitch,
    NativeParam,
    NativeTask,
    NativeTaskContainer,
    decode_task_container,
    encode_task_container,
    remove_owned_tasks,
    validate_task_container,
)


def task(task_id: int, version: int = 1) -> NativeTask:
    return NativeTask(
        task_id=task_id,
        loader_version=version,
        header=struct.pack("<I", 1),
        optional_kind_word=None,
        source=b"source",
        resource=b"asset",
        params=(NativeParam(3, b"\x01" + b"\0" * 31),),
        strings=(b"group",),
        vectors=(b"\0" * 12,),
        array_pools=((b"\0" * 16,), (), (), ()),
    )


def test_v1_roundtrip_is_exact_for_plain_container() -> None:
    original = NativeTaskContainer(1, False, 0, (task(7), task(9)))
    encoded = encode_task_container(original)
    assert encode_task_container(decode_task_container(encoded, 1)) == encoded


def test_v2_group_switch_roundtrip() -> None:
    v2 = replace(task(7, 2), header=struct.pack("<HH", 0, 4))
    original = NativeTaskContainer(2, False, 0, (GroupSwitch(4), v2))
    encoded = encode_task_container(original)
    assert decode_task_container(encoded, 2) == original


def test_remove_requires_exact_ownership_count() -> None:
    original = NativeTaskContainer(1, False, 0, (task(7), task(9)))
    result = remove_owned_tasks(original, {7}, expected_count=1)
    assert [item.task_id for item in result.tasks] == [9]


def test_recovered_pool_reference_must_be_in_range() -> None:
    invalid = replace(
        task(7),
        params=(NativeParam(16, struct.pack("<Q", 1) + bytes(24)),),
        strings=(b"Unit",),
    )
    with pytest.raises(SnapshotError, match="string index 1 is out of range"):
        validate_task_container(NativeTaskContainer(1, False, 0, (invalid,)))

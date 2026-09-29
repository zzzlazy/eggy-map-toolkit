from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from typing import Any, Literal, Self

import zstandard

from .errors import CapabilityError, SnapshotError
from .hashing import engine_string_hash


@dataclass(frozen=True)
class NativeLimits:
    max_uncompressed: int = 64 * 1024 * 1024
    max_tasks: int = 200_000
    max_params: int = 10_000
    max_pool_items: int = 100_000
    max_string_bytes: int = 16 * 1024 * 1024


@dataclass(frozen=True)
class NativeParam:
    opcode: int
    data: bytes


@dataclass(frozen=True)
class NativeTask:
    task_id: int
    loader_version: Literal[1, 2]
    header: bytes
    optional_kind_word: bytes | None
    source: bytes
    resource: bytes
    params: tuple[NativeParam, ...]
    strings: tuple[bytes, ...]
    vectors: tuple[bytes, ...]
    array_pools: tuple[tuple[bytes, ...], ...]

    @property
    def flags(self) -> int | None:
        return (
            struct.unpack_from("<H", self.header)[0]
            if self.loader_version == 2
            else None
        )

    @property
    def task_kind(self) -> int:
        return ((self.flags or 0) >> 8) & 3


@dataclass(frozen=True)
class GroupSwitch:
    group: int


@dataclass(frozen=True)
class NativeTaskContainer:
    loader_version: Literal[1, 2]
    compressed: bool
    declared_uncompressed_size: int
    entries: tuple[NativeTask | GroupSwitch, ...]

    @property
    def tasks(self) -> tuple[NativeTask, ...]:
        return tuple(entry for entry in self.entries if isinstance(entry, NativeTask))


@dataclass(frozen=True)
class NativeMaterialVar:
    name: str | bytes
    hash_argument: int | None
    value: bool | int | float | tuple[float, ...]


@dataclass(frozen=True)
class NativeAudioAttrs:
    max_distance: float
    local_position: tuple[float, float, float]
    diff_tag: tuple[bool, bool, bool]


@dataclass(frozen=True)
class NativeModelTaskV1Spec:
    """Complete, profile-resolved input for one loader-v1 model task.

    Optional values mean that the matched component profile proved the matching
    loader call is absent. Callers must not use ``None`` as an unknown value.
    """

    task_id: int
    source: str | bytes
    scale: tuple[float, float, float]
    angle: tuple[float, float, float]
    position: tuple[float, float, float]
    primary_group: str | bytes
    pickable: bool
    scene_flag: int
    cast_shadow: bool
    receive_shadow: bool
    visible: bool
    animation: str | bytes | None
    post_animation_groups: tuple[str | bytes, ...]
    audio: NativeAudioAttrs | None
    material_dither: bool
    material_alpha: int
    material_vars: tuple[NativeMaterialVar, ...]
    material_macros: tuple[tuple[str | bytes, str | bytes], ...]


class NativeTaskV1Builder:
    """Build a loader-v1 native task from the recovered ABI.

    The builder deliberately exposes semantic operations instead of raw offsets.
    Component profiles remain responsible for deciding which operations belong to
    a particular display family and in what order they must be emitted.
    """

    def __init__(self, task_id: int, source: str | bytes) -> None:
        self.task_id = task_id
        self.source = source.encode() if isinstance(source, str) else source
        self.params: list[NativeParam] = []
        self.strings: list[bytes] = []
        self.float_arrays: list[bytes] = []

    @staticmethod
    def _data() -> bytearray:
        return bytearray(32)

    def _append(self, opcode: int, data: bytearray) -> Self:
        if type(opcode) is not int or not 0 <= opcode <= 0xFFFFFFFF:
            raise CapabilityError(f"opcode is outside u32 range: {opcode!r}")
        self.params.append(NativeParam(opcode, bytes(data)))
        return self

    def _string_index(self, value: str | bytes) -> int:
        encoded = value.encode() if isinstance(value, str) else value
        try:
            return self.strings.index(encoded)
        except ValueError:
            self.strings.append(encoded)
            return len(self.strings) - 1

    def _float_array_index(self, values: tuple[float, ...]) -> int:
        if not values or not all(
            type(value) is float and math.isfinite(value) for value in values
        ):
            raise CapabilityError("material float-array must be non-empty and finite")
        encoded = struct.pack(f"<{len(values)}f", *values)
        try:
            return self.float_arrays.index(encoded)
        except ValueError:
            self.float_arrays.append(encoded)
            return len(self.float_arrays) - 1

    def u32(self, opcode: int, value: int, *, offset: int = 0) -> Self:
        if type(value) is not int or not 0 <= value <= 0xFFFFFFFF:
            raise CapabilityError(f"value is outside u32 range: {value!r}")
        if type(offset) is not int or not 0 <= offset <= 28:
            raise CapabilityError(f"u32 offset is invalid: {offset!r}")
        data = self._data()
        struct.pack_into("<I", data, offset, value)
        return self._append(opcode, data)

    def u64(self, opcode: int, value: int, *, offset: int = 0) -> Self:
        if type(value) is not int or not 0 <= value <= 0xFFFFFFFFFFFFFFFF:
            raise CapabilityError(f"value is outside u64 range: {value!r}")
        if type(offset) is not int or not 0 <= offset <= 24:
            raise CapabilityError(f"u64 offset is invalid: {offset!r}")
        data = self._data()
        struct.pack_into("<Q", data, offset, value)
        return self._append(opcode, data)

    def boolean(self, opcode: int, value: bool, *, offset: int = 0) -> Self:
        if type(value) is not bool:
            raise CapabilityError(f"boolean value required: {value!r}")
        if type(offset) is not int or not 0 <= offset <= 31:
            raise CapabilityError(f"boolean offset is invalid: {offset!r}")
        data = self._data()
        data[offset] = int(value)
        return self._append(opcode, data)

    def float32(self, opcode: int, value: float, *, offset: int = 0) -> Self:
        if type(value) is not float or not math.isfinite(value):
            raise CapabilityError(f"finite float value required: {value!r}")
        if type(offset) is not int or not 0 <= offset <= 28:
            raise CapabilityError(f"float32 offset is invalid: {offset!r}")
        data = self._data()
        struct.pack_into("<f", data, offset, value)
        return self._append(opcode, data)

    def vec3_slots(self, opcode: int, value: tuple[float, float, float]) -> Self:
        if (
            not isinstance(value, tuple)
            or len(value) != 3
            or not all(
                type(component) is float and math.isfinite(component)
                for component in value
            )
        ):
            raise CapabilityError(f"finite float vec3 required: {value!r}")
        data = self._data()
        for offset, component in zip((0, 8, 16), value, strict=True):
            struct.pack_into("<f", data, offset, component)
        return self._append(opcode, data)

    def set_model_uid(self, unit_id: int) -> Self:
        return self.u32(1, unit_id)

    def set_local_scale(self, value: tuple[float, float, float]) -> Self:
        return self.vec3_slots(10, value)

    def set_local_angle(self, value: tuple[float, float, float]) -> Self:
        return self.vec3_slots(12, value)

    def scene_add_object(self) -> Self:
        return self._append(14, self._data())

    def set_local_position(self, value: tuple[float, float, float]) -> Self:
        return self.vec3_slots(11, value)

    def add_to_group(self, group: str | bytes) -> Self:
        return self.u64(16, self._string_index(group))

    def set_pickable(self, value: bool) -> Self:
        return self.boolean(18, value)

    def set_scene_flag(self, value: int) -> Self:
        return self.u64(2, value, offset=8)

    def set_cast_shadow(self, value: bool) -> Self:
        return self.boolean(3, value)

    def set_receive_shadow(self, value: bool) -> Self:
        return self.boolean(4, value)

    def set_visible(self, value: bool) -> Self:
        return self.boolean(5, value)

    def set_animation(self, name: str | bytes) -> Self:
        return self.u64(30, self._string_index(name))

    def set_audio_max_distance(self, value: float) -> Self:
        return self.float32(7, value)

    def set_local_sound_position(self, value: tuple[float, float, float]) -> Self:
        return self.vec3_slots(8, value)

    def set_diff_audio_tag(self, values: tuple[bool, bool, bool]) -> Self:
        data = self._data()
        for offset, component in zip((0, 8, 16), values, strict=True):
            data[offset] = int(component)
        return self._append(9, data)

    def set_all_material_dither(self, value: bool) -> Self:
        return self.boolean(26, value)

    def set_all_material_alpha(self, value: int) -> Self:
        if type(value) is not int or not 0 <= value <= 255:
            raise CapabilityError(f"material alpha must be in [0, 255]: {value!r}")
        return self.u32(27, value)

    def set_all_material_var(
        self,
        name: str | bytes,
        value: bool | int | float | tuple[float, ...],  # noqa: PYI041
        *,
        hash_argument: int,
    ) -> Self:
        data = self._data()
        struct.pack_into("<Q", data, 0, self._string_index(name))
        struct.pack_into("<I", data, 8, hash_argument)
        if type(value) is bool:
            struct.pack_into("<I", data, 16, 1)
            data[24] = int(value)
        elif type(value) is int:
            struct.pack_into("<I", data, 16, 2)
            struct.pack_into("<i", data, 24, value)
        elif type(value) is float:
            struct.pack_into("<I", data, 16, 3)
            struct.pack_into("<f", data, 24, value)
        elif (
            isinstance(value, tuple)
            and value
            and all(type(component) is float for component in value)
        ):
            struct.pack_into("<I", data, 16, 4)
            struct.pack_into("<Q", data, 24, self._float_array_index(value))
        else:
            raise CapabilityError(f"unsupported material value: {value!r}")
        return self._append(24, data)

    def set_all_material_macro(self, name: str | bytes, value: str | bytes) -> Self:
        data = self._data()
        struct.pack_into("<Q", data, 0, self._string_index(name))
        struct.pack_into("<Q", data, 8, self._string_index(value))
        return self._append(33, data)

    def finish(self) -> NativeTask:
        return NativeTask(
            task_id=self.task_id,
            loader_version=1,
            header=struct.pack("<I", 1),
            optional_kind_word=None,
            source=self.source,
            resource=b"",
            params=tuple(self.params),
            strings=tuple(self.strings),
            vectors=(),
            array_pools=(tuple(self.float_arrays), (), (), ()),
        )


def build_model_task_v1(spec: NativeModelTaskV1Spec) -> NativeTask:
    """Compose the exact recovered ``begin_model_loader`` operation order.

    This function does not infer component defaults. The caller must first
    resolve a byte-complete family profile and supply every emitted or omitted
    loader field explicitly.
    """
    if not spec.source:
        raise CapabilityError("model task source path must not be empty")
    builder = (
        NativeTaskV1Builder(spec.task_id, spec.source)
        .set_model_uid(spec.task_id)
        .set_local_scale(spec.scale)
        .set_local_angle(spec.angle)
        .scene_add_object()
        .set_local_position(spec.position)
        .add_to_group(spec.primary_group)
        .set_pickable(spec.pickable)
        .set_scene_flag(spec.scene_flag)
        .set_cast_shadow(spec.cast_shadow)
        .set_receive_shadow(spec.receive_shadow)
        .set_visible(spec.visible)
    )
    if spec.animation is not None:
        builder.set_animation(spec.animation)
    for group in spec.post_animation_groups:
        builder.add_to_group(group)
    if spec.audio is not None:
        builder.set_audio_max_distance(spec.audio.max_distance)
        builder.set_local_sound_position(spec.audio.local_position)
        builder.set_diff_audio_tag(spec.audio.diff_tag)
    builder.set_all_material_dither(spec.material_dither)
    builder.set_all_material_alpha(spec.material_alpha)
    for material in spec.material_vars:
        expected_hash = engine_string_hash(material.name)
        if (
            material.hash_argument is not None
            and material.hash_argument != expected_hash
        ):
            raise CapabilityError(
                f"material hash does not match engine ABI for {material.name!r}"
            )
        builder.set_all_material_var(
            material.name,
            material.value,
            hash_argument=expected_hash,
        )
    for name, value in spec.material_macros:
        builder.set_all_material_macro(name, value)
    task = builder.finish()
    validate_task_container(NativeTaskContainer(1, False, 0, (task,)))
    return task


class _Reader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.offset = 0

    @property
    def remaining(self) -> int:
        return len(self.data) - self.offset

    def take(self, count: int, label: str) -> bytes:
        if count < 0 or count > self.remaining:
            raise SnapshotError(f"truncated native task payload while reading {label}")
        result = self.data[self.offset : self.offset + count]
        self.offset += count
        return result

    def u32(self, label: str) -> int:
        return struct.unpack("<I", self.take(4, label))[0]

    def string(self, limits: NativeLimits, label: str) -> bytes:
        length = self.u32(label + " length")
        if length > limits.max_string_bytes:
            raise SnapshotError(f"native string exceeds limit in {label}")
        return self.take(length, label)


def _count(reader: _Reader, limit: int, label: str) -> int:
    value = reader.u32(label)
    if value > limit:
        raise SnapshotError(f"native {label} exceeds configured limit")
    return value


def _decode_payload(
    task_id: int, payload: bytes, loader_version: Literal[1, 2], limits: NativeLimits
) -> NativeTask:
    reader = _Reader(payload)
    header = reader.take(4, "task header")
    optional: bytes | None = None
    if loader_version == 2:
        flags = struct.unpack_from("<H", header)[0]
        if flags & ~0xF3FF:
            raise SnapshotError(
                f"task {task_id}: unsupported v2 flag bits 0x{flags & ~0xF3FF:x}"
            )
        if flags & 0x300:
            optional = reader.take(4, "v2 task-kind word")
    source = reader.string(limits, "source string")
    resource = reader.string(limits, "resource string")
    params = tuple(
        NativeParam(reader.u32("opcode"), reader.take(32, "parameter data"))
        for _ in range(_count(reader, limits.max_params, "parameter count"))
    )
    strings = tuple(
        reader.string(limits, "string-pool item")
        for _ in range(_count(reader, limits.max_pool_items, "string-pool count"))
    )
    vectors = tuple(
        reader.take(12, "vector-pool item")
        for _ in range(_count(reader, limits.max_pool_items, "vector-pool count"))
    )
    pools: list[tuple[bytes, ...]] = []
    for pool_index, width in enumerate((4, 8, 8, 8)):
        rows: list[bytes] = []
        for _ in range(
            _count(reader, limits.max_pool_items, f"array-pool-{pool_index} count")
        ):
            item_count = _count(
                reader, limits.max_pool_items, f"array-pool-{pool_index} item count"
            )
            rows.append(
                reader.take(item_count * width, f"array-pool-{pool_index} item")
            )
        pools.append(tuple(rows))
    if reader.remaining:
        raise SnapshotError(
            f"task {task_id}: {reader.remaining} trailing payload bytes"
        )
    return NativeTask(
        task_id,
        loader_version,
        header,
        optional,
        source,
        resource,
        params,
        strings,
        vectors,
        tuple(pools),
    )


def decode_task_container(
    blob: bytes, loader_version: Literal[1, 2], limits: NativeLimits | None = None
) -> NativeTaskContainer:
    limits = limits or NativeLimits()
    outer = _Reader(blob)
    declared = outer.u32("uncompressed-size prefix")
    if declared > limits.max_uncompressed:
        raise SnapshotError("native task container exceeds uncompressed-size limit")
    if declared:
        try:
            body = zstandard.ZstdDecompressor().decompress(
                outer.take(outer.remaining, "compressed body"), max_output_size=declared
            )
        except zstandard.ZstdError as exc:
            raise SnapshotError(f"invalid native task Zstandard body: {exc}") from exc
        if len(body) != declared:
            raise SnapshotError(
                f"native task declared size {declared} does not match {len(body)}"
            )
    else:
        body = outer.take(outer.remaining, "plain body")
    reader = _Reader(body)
    task_count = _count(reader, limits.max_tasks, "task count")
    entries: list[NativeTask | GroupSwitch] = []
    parsed_tasks = 0
    while parsed_tasks < task_count:
        task_id = reader.u32("task ID")
        if loader_version == 2 and task_id == 0xFFFFFFFF:
            group = reader.u32("group switch")
            if group > 0xFFFF:
                raise SnapshotError("v2 group switch exceeds u16 range")
            entries.append(GroupSwitch(group))
            continue
        payload_length = reader.u32("task payload length")
        entries.append(
            _decode_payload(
                task_id,
                reader.take(payload_length, "task payload"),
                loader_version,
                limits,
            )
        )
        parsed_tasks += 1
    if reader.remaining:
        raise SnapshotError(
            f"native task container has {reader.remaining} trailing bytes"
        )
    container = NativeTaskContainer(
        loader_version, bool(declared), declared, tuple(entries)
    )
    validate_task_container(container)
    return container


def _u32(value: int) -> bytes:
    if type(value) is not int or not 0 <= value <= 0xFFFFFFFF:
        raise CapabilityError(f"value is outside u32 range: {value!r}")
    return struct.pack("<I", value)


def _string(value: bytes) -> bytes:
    return _u32(len(value)) + value


def _encode_payload(task: NativeTask) -> bytes:
    parts = [task.header]
    if task.loader_version == 2 and (task.flags or 0) & 0x300:
        if task.optional_kind_word is None or len(task.optional_kind_word) != 4:
            raise CapabilityError(f"task {task.task_id}: missing v2 task-kind word")
        parts.append(task.optional_kind_word)
    elif task.optional_kind_word is not None:
        raise CapabilityError(f"task {task.task_id}: unexpected optional task word")
    parts.extend((_string(task.source), _string(task.resource), _u32(len(task.params))))
    for param in task.params:
        if len(param.data) != 32:
            raise CapabilityError(
                f"task {task.task_id}: parameter data must be 32 bytes"
            )
        parts.extend((_u32(param.opcode), param.data))
    parts.append(_u32(len(task.strings)))
    parts.extend(_string(value) for value in task.strings)
    parts.append(_u32(len(task.vectors)))
    for vector in task.vectors:
        if len(vector) != 12:
            raise CapabilityError(
                f"task {task.task_id}: vector pool item must be 12 bytes"
            )
        parts.append(vector)
    if len(task.array_pools) != 4:
        raise CapabilityError(
            f"task {task.task_id}: exactly four array pools are required"
        )
    for width, pool in zip((4, 8, 8, 8), task.array_pools, strict=True):
        parts.append(_u32(len(pool)))
        for item in pool:
            if len(item) % width:
                raise CapabilityError(
                    f"task {task.task_id}: array-pool item has invalid width"
                )
            parts.extend((_u32(len(item) // width), item))
    return b"".join(parts)


def encode_task_container(
    container: NativeTaskContainer, *, compression_level: int = 3
) -> bytes:
    parts = [_u32(len(container.tasks))]
    for entry in container.entries:
        if isinstance(entry, GroupSwitch):
            if container.loader_version != 2:
                raise CapabilityError("group switches are only valid for loader v2")
            if not 0 <= entry.group <= 0xFFFF:
                raise CapabilityError("v2 group switch exceeds u16 range")
            parts.extend((_u32(0xFFFFFFFF), _u32(entry.group)))
            continue
        if entry.loader_version != container.loader_version:
            raise CapabilityError("task/container loader-version mismatch")
        payload = _encode_payload(entry)
        parts.extend((_u32(entry.task_id), _u32(len(payload)), payload))
    body = b"".join(parts)
    if container.compressed:
        return _u32(len(body)) + zstandard.ZstdCompressor(
            level=compression_level
        ).compress(body)
    return _u32(0) + body


def remove_owned_tasks(
    container: NativeTaskContainer, task_ids: set[int], *, expected_count: int
) -> NativeTaskContainer:
    found = [task for task in container.tasks if task.task_id in task_ids]
    if len(found) != expected_count:
        raise CapabilityError(
            f"native task ownership mismatch: expected {expected_count}, found {len(found)}"
        )
    entries = tuple(
        entry
        for entry in container.entries
        if not isinstance(entry, NativeTask) or entry.task_id not in task_ids
    )
    return NativeTaskContainer(
        container.loader_version,
        container.compressed,
        container.declared_uncompressed_size,
        entries,
    )


def validate_task_container(container: NativeTaskContainer) -> None:
    """Validate identity and every recovered pool reference.

    Unknown opcodes are structurally preserved. Known opcodes are checked
    against the exact pool slot consumed by the recovered loader ABI.
    """
    task_ids = [task.task_id for task in container.tasks]
    if len(task_ids) != len(set(task_ids)):
        raise SnapshotError("native task container contains duplicate task IDs")

    def string_index(task: NativeTask, param: NativeParam, offset: int) -> int:
        index = struct.unpack_from("<Q", param.data, offset)[0]
        if index >= len(task.strings):
            raise SnapshotError(
                f"task {task.task_id}: opcode {param.opcode} string index "
                f"{index} is out of range"
            )
        return index

    for task in container.tasks:
        for param in task.params:
            if param.opcode in {16, 22, 23, 24, 30, 32, 33, 74, 76}:
                string_index(task, param, 0)
            if param.opcode in {32, 33, 76}:
                string_index(task, param, 8)
            if param.opcode in {23, 24, 74}:
                value_type = struct.unpack_from("<I", param.data, 16)[0]
                if value_type == 4:
                    index = struct.unpack_from("<Q", param.data, 24)[0]
                    if index >= len(task.array_pools[0]):
                        raise SnapshotError(
                            f"task {task.task_id}: opcode {param.opcode} float-array "
                            f"index {index} is out of range"
                        )
                elif value_type == 5:
                    string_index(task, param, 24)


def inventory_native_tasks(
    decoded_newpreload: Any, *, loader_version: Literal[1, 2]
) -> NativeTaskContainer:
    if not isinstance(decoded_newpreload, dict):
        raise SnapshotError("newpreloadres.mm root is not a map")
    batch = decoded_newpreload.get(
        b"batch_loader_data", decoded_newpreload.get("batch_loader_data")
    )
    if not isinstance(batch, dict):
        raise SnapshotError("newpreloadres.mm has no batch_loader_data map")
    blob = batch.get(b"batch_task_data", batch.get("batch_task_data"))
    if not isinstance(blob, bytes):
        raise SnapshotError("newpreloadres.mm has no binary batch_task_data")
    return decode_task_container(blob, loader_version)


def build_native_create_task(*_args: Any, **_kwargs: Any) -> bytes:
    raise CapabilityError(
        "native batch-task creation is unavailable without a matched opcode/pool/frame profile"
    )

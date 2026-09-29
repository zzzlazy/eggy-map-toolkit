from __future__ import annotations

import math
import struct
from collections.abc import Iterable
from typing import Any

import msgpack
import zstandard

from .errors import SnapshotError


class _WireReader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.offset = 0

    def take(self, size: int) -> bytes:
        if size < 0 or self.offset + size > len(self.data):
            raise SnapshotError("truncated MessagePack wire value")
        value = self.data[self.offset : self.offset + size]
        self.offset += size
        return value

    def byte(self) -> int:
        return self.take(1)[0]


def _wire_length(reader: _WireReader, width: int) -> int:
    return int.from_bytes(reader.take(width), "big")


def _scan_wire_value(reader: _WireReader) -> None:
    code = reader.byte()
    if code <= 0x7F or code >= 0xE0 or code in (0xC0, 0xC2, 0xC3):
        return
    if 0x80 <= code <= 0x8F:
        for _ in range(code & 0x0F):
            _scan_wire_value(reader)
            _scan_wire_value(reader)
        return
    if 0x90 <= code <= 0x9F:
        for _ in range(code & 0x0F):
            _scan_wire_value(reader)
        return
    if 0xA0 <= code <= 0xBF:
        reader.take(code & 0x1F)
        return
    if code == 0xC1:
        raise SnapshotError("reserved MessagePack opcode 0xc1")
    if code in (0xC4, 0xC5, 0xC6):
        width = {0xC4: 1, 0xC5: 2, 0xC6: 4}[code]
        reader.take(_wire_length(reader, width))
        return
    if code in (0xC7, 0xC8, 0xC9):
        width = {0xC7: 1, 0xC8: 2, 0xC9: 4}[code]
        reader.take(1 + _wire_length(reader, width))
        return
    if code == 0xCA:
        value = struct.unpack(">f", reader.take(4))[0]
        if not math.isfinite(value):
            raise SnapshotError("illegal non-finite float32 in MessagePack wire data")
        return
    if code == 0xCB:
        value = struct.unpack(">d", reader.take(8))[0]
        if not math.isfinite(value):
            raise SnapshotError("illegal non-finite float64 in MessagePack wire data")
        return
    if code in (0xCC, 0xCD, 0xCE, 0xCF):
        width = {0xCC: 1, 0xCD: 2, 0xCE: 4, 0xCF: 8}[code]
        value = _wire_length(reader, width)
        minimum = {1: 0x80, 2: 0x100, 4: 0x10000, 8: 0x100000000}[width]
        if value < minimum:
            raise SnapshotError(f"non-canonical uint{width * 8} MessagePack integer")
        return
    if code in (0xD0, 0xD1, 0xD2, 0xD3):
        width = {0xD0: 1, 0xD1: 2, 0xD2: 4, 0xD3: 8}[code]
        value = int.from_bytes(reader.take(width), "big", signed=True)
        minimum = {1: -0x80, 2: -0x8000, 4: -0x80000000, 8: -0x8000000000000000}[width]
        previous = {1: -0x20, 2: -0x80, 4: -0x8000, 8: -0x80000000}[width]
        if value >= previous or value < minimum:
            raise SnapshotError(f"non-canonical int{width * 8} MessagePack integer")
        return
    if code in (0xD4, 0xD5, 0xD6, 0xD7, 0xD8):
        size = {0xD4: 1, 0xD5: 2, 0xD6: 4, 0xD7: 8, 0xD8: 16}[code]
        reader.take(1 + size)
        return
    if code in (0xD9, 0xDA, 0xDB):
        width = {0xD9: 1, 0xDA: 2, 0xDB: 4}[code]
        reader.take(_wire_length(reader, width))
        return
    if code in (0xDC, 0xDD):
        count = _wire_length(reader, 2 if code == 0xDC else 4)
        for _ in range(count):
            _scan_wire_value(reader)
        return
    if code in (0xDE, 0xDF):
        count = _wire_length(reader, 2 if code == 0xDE else 4)
        for _ in range(count):
            _scan_wire_value(reader)
            _scan_wire_value(reader)
        return
    raise SnapshotError(f"unsupported MessagePack opcode 0x{code:02x}")


def validate_messagepack_wire(data: bytes) -> None:
    reader = _WireReader(data)
    _scan_wire_value(reader)
    if reader.offset != len(data):
        raise SnapshotError(
            f"MessagePack payload has {len(data) - reader.offset} trailing bytes"
        )


def _key_fingerprint(key: Any) -> tuple[Any, ...]:
    if key is None:
        return ("none",)
    if type(key) is bool:
        return ("bool", key)
    if type(key) is int:
        return ("int", key)
    if type(key) is float:
        return ("float", struct.pack(">d", key))
    if type(key) is str:
        return ("text", key)
    if type(key) is bytes:
        return ("binary", key)
    if isinstance(key, msgpack.ExtType):
        return ("ext", key.code, key.data)
    raise SnapshotError(f"unsupported MessagePack map key type: {type(key).__name__}")


def _reject_ambiguous_pairs(pairs: Iterable[tuple[Any, Any]]) -> dict[Any, Any]:
    result: dict[Any, Any] = {}
    exact: set[tuple[Any, ...]] = set()
    semantic_text: set[str] = set()
    for index, (key, value) in enumerate(pairs):
        fingerprint = _key_fingerprint(key)
        if fingerprint in exact:
            raise SnapshotError(f"duplicate MessagePack key at pair {index}")
        text_key: str | None = None
        if type(key) is str:
            text_key = key
        elif type(key) is bytes:
            try:
                text_key = key.decode("utf-8")
            except UnicodeDecodeError:
                pass
        if text_key is not None and text_key in semantic_text:
            raise SnapshotError(f"binary/text key alias at pair {index}: {text_key!r}")
        try:
            if key in result:
                raise SnapshotError(f"Python-equality key alias at pair {index}")
        except TypeError as exc:
            raise SnapshotError(f"unhashable MessagePack key at pair {index}") from exc
        exact.add(fingerprint)
        if text_key is not None:
            semantic_text.add(text_key)
        result[key] = value
    return result


def _reject_nonfinite(value: Any, path: str = "$") -> None:
    if type(value) is float and not math.isfinite(value):
        raise SnapshotError(f"illegal non-finite float at {path}")
    if isinstance(value, dict):
        for key, item in value.items():
            _reject_nonfinite(key, f"{path}.<key>")
            _reject_nonfinite(item, f"{path}.{key!r}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_nonfinite(item, f"{path}[{index}]")


def decode_mm(raw: bytes) -> Any:
    try:
        unpacked = zstandard.ZstdDecompressor().decompress(raw)
    except zstandard.ZstdError as exc:
        raise SnapshotError(f"invalid Zstandard frame: {exc}") from exc
    validate_messagepack_wire(unpacked)
    try:
        value = msgpack.unpackb(
            unpacked,
            raw=False,
            strict_map_key=False,
            object_pairs_hook=_reject_ambiguous_pairs,
        )
    except (msgpack.UnpackException, ValueError) as exc:
        if isinstance(exc, SnapshotError):
            raise
        raise SnapshotError(f"invalid MessagePack payload: {exc}") from exc
    _reject_nonfinite(value)
    return value


def encode_mm(value: Any, *, compression_level: int) -> bytes:
    """Encode only under an explicit matched serializer profile.

    Callers are responsible for preserving field order and numeric-width rules.
    Generic planning never calls this helper.
    """
    _reject_nonfinite(value)
    payload = msgpack.packb(value, use_bin_type=True, strict_types=True)
    return zstandard.ZstdCompressor(level=compression_level).compress(payload)

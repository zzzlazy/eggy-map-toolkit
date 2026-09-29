#!/usr/bin/env python3
"""Decode a Bindict byte-string constant from an extracted NeoX module."""

from __future__ import annotations

import argparse
import importlib.util
import json
import struct
from pathlib import Path
from typing import Any


def load_parser_class(neoxtractor_root: Path) -> type:
    path = neoxtractor_root / "core" / "bindict" / "parser.py"
    spec = importlib.util.spec_from_file_location("neox_bindict_parser", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.BindictParser


def find_largest_blob(module_json: dict[str, Any]) -> tuple[int, bytes]:
    constants = module_json["marshal"]["__code__"]["consts"]["__tuple__"]
    blobs = []
    for index, value in enumerate(constants):
        if isinstance(value, dict) and "__bytes_hex__" in value:
            blobs.append((index, bytes.fromhex(value["__bytes_hex__"])))
    if not blobs:
        raise ValueError("module has no byte-string constants")
    return max(blobs, key=lambda item: len(item[1]))


def initialize_string_pool(parser: Any, data: bytes) -> tuple[int, int]:
    if len(data) < 8:
        raise ValueError("Bindict blob is too short")
    string_count, padding = struct.unpack_from("<II", data, 0)
    ends = [struct.unpack_from("<I", data, 8 + index * 4)[0] for index in range(string_count)]
    offset = 8 + string_count * 4
    previous = 0
    strings = []
    for end in ends:
        raw = data[offset : offset + end - previous]
        strings.append(raw.decode("utf-8"))
        offset += end - previous
        previous = end
    parser.has_string_pool = bool(string_count)
    parser.strings = strings
    parser.jump_base = offset
    return string_count, padding


def parse_hash_items(parser: Any, data: bytes) -> list[tuple[Any, Any, int, int]]:
    jump_base = parser.jump_base
    hash_offset = struct.unpack_from("<I", data, jump_base)[0]
    offset = jump_base + hash_offset
    marker = data[offset]
    offset += 1

    if marker == 0x56:
        key_type = data[offset]
        offset += 1
        value_type = None
    elif marker == 0x66:
        value_type = data[offset]
        offset += 1
        key_type = None
    elif marker == 0x76:
        key_type, value_type = data[offset : offset + 2]
        offset += 2
    else:
        raise ValueError(f"unsupported hash marker 0x{marker:02x}")

    count, offset = parser._read_varint(data, offset)
    if count is None:
        raise ValueError("missing hash item count")
    locations = []
    for _ in range(count):
        hash_value, relative_offset = struct.unpack_from("<II", data, offset)
        offset += 8
        locations.append((hash_value, relative_offset))

    result = []
    for hash_value, relative_offset in locations:
        item_offset = jump_base + relative_offset
        if marker == 0x56:
            key, item_offset, _ = parser._read_value_by_type(
                data, item_offset, key_type
            )
            item_value_type = data[item_offset]
            value, _, _ = parser._read_value_by_type(
                data, item_offset + 1, item_value_type
            )
        elif marker == 0x66:
            item_key_type = data[item_offset]
            key, item_offset, _ = parser._read_value_by_type(
                data, item_offset + 1, item_key_type
            )
            value, _, _ = parser._read_value_by_type(
                data, item_offset, value_type
            )
        else:
            key, item_offset, _ = parser._read_value_by_type(
                data, item_offset, key_type
            )
            value, _, _ = parser._read_value_by_type(
                data, item_offset, value_type
            )
        result.append((key, value, hash_value, relative_offset))
    return result


def safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {"__dict_pairs__": [[safe(key), safe(item)] for key, item in value.items()]}
    if isinstance(value, tuple):
        return {"__tuple__": [safe(item) for item in value]}
    if isinstance(value, list):
        return [safe(item) for item in value]
    if isinstance(value, set):
        return {"__set__": [safe(item) for item in value]}
    if isinstance(value, bytes):
        try:
            return {"__bytes_utf8__": value.decode("utf-8")}
        except UnicodeDecodeError:
            return {"__bytes_hex__": value.hex()}
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("module_json", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--neoxtractor-root", required=True, type=Path)
    args = parser.parse_args()

    module_json = json.loads(args.module_json.read_text())
    constant_index, blob = find_largest_blob(module_json)
    bindict_parser = load_parser_class(args.neoxtractor_root)(debug=True)
    string_count, padding = initialize_string_pool(bindict_parser, blob)
    items = parse_hash_items(bindict_parser, blob)
    result = {
        "source_module": module_json["marshal"]["__code__"]["filename"],
        "source_signature": module_json["entry"]["signature"],
        "constant_index": constant_index,
        "blob_length": len(blob),
        "string_count": string_count,
        "padding": padding,
        "jump_base": bindict_parser.jump_base,
        "entry_count": len(items),
        "data": {
            "__dict_pairs__": [[safe(key), safe(value)] for key, value, _, _ in items]
        },
        "hash_index": [
            {"hash": f"0x{hash_value:08x}", "relative_offset": relative_offset}
            for _, _, hash_value, relative_offset in items
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(f"decoded {len(items)} entries to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

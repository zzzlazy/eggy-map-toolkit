#!/usr/bin/env python3
"""Extract and inspect one legacy NeoX Python module from an Eggy NPK.

Index mode 3 and the rotor wrapper are decoded with functions from a checked-out
NeoXtractor tree supplied by the caller.  The extracted marshal object is
represented as JSON-friendly code-object records; it is never executed.
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class LegacyCode:
    argcount: int
    nlocals: int
    stacksize: int
    flags: int
    code: Any
    consts: Any
    names: Any
    varnames: Any
    freevars: Any
    cellvars: Any
    filename: Any
    name: Any
    firstlineno: int
    lnotab: Any


class _Null:
    pass


MARSHAL_NULL = _Null()


class LegacyMarshalReader:
    def __init__(self, data: bytes):
        self.data = data
        self.offset = 0
        self.string_table: list[Any] = []

    def read(self, size: int) -> bytes:
        value = self.data[self.offset : self.offset + size]
        if len(value) != size:
            raise EOFError(f"marshal read past end at {self.offset}")
        self.offset += size
        return value

    def int32(self) -> int:
        return struct.unpack("<i", self.read(4))[0]

    def int64(self) -> int:
        return struct.unpack("<q", self.read(8))[0]

    def load(self) -> Any:
        start = self.offset
        kind = self.read(1)
        if kind == b"0":
            return MARSHAL_NULL
        if kind == b"N":
            return None
        if kind == b"F":
            return False
        if kind == b"T":
            return True
        if kind == b"S":
            return "StopIteration"
        if kind == b".":
            return "Ellipsis"
        if kind == b"i":
            return self.int32()
        if kind == b"I":
            return self.int64()
        if kind == b"l":
            size = self.int32()
            sign = -1 if size < 0 else 1
            result = 0
            for index in range(abs(size)):
                result |= struct.unpack("<h", self.read(2))[0] << (15 * index)
            return sign * result
        if kind == b"f":
            return float(self.read(self.read(1)[0]))
        if kind == b"g":
            return struct.unpack("<d", self.read(8))[0]
        if kind == b"x":
            real = float(self.read(self.read(1)[0]))
            imaginary = float(self.read(self.read(1)[0]))
            return {"__complex__": [real, imaginary]}
        if kind == b"y":
            return {"__complex__": list(struct.unpack("<dd", self.read(16)))}
        if kind in (b"s", b"t", b"u"):
            raw = self.read(self.int32())
            try:
                value: Any = raw.decode("utf-8")
            except UnicodeDecodeError:
                value = raw
            if kind == b"t":
                self.string_table.append(value)
            return value
        if kind == b"R":
            return self.string_table[self.int32()]
        if kind in (b"(", b"[", b"<", b">"):
            values = [self.load() for _ in range(self.int32())]
            if kind == b"(":
                return tuple(values)
            if kind == b"[":
                return values
            return {"__set__": values, "frozen": kind == b">"}
        if kind == b"{":
            pairs = []
            while True:
                key = self.load()
                if key is MARSHAL_NULL:
                    return {"__dict_pairs__": pairs}
                pairs.append((key, self.load()))
        if kind == b"c":
            argcount, nlocals, stacksize, flags = (self.int32() for _ in range(4))
            code, consts, names, varnames, freevars, cellvars, filename, name = (
                self.load() for _ in range(8)
            )
            firstlineno = self.int32()
            lnotab = self.load()
            return LegacyCode(
                argcount,
                nlocals,
                stacksize,
                flags,
                code,
                consts,
                names,
                varnames,
                freevars,
                cellvars,
                filename,
                name,
                firstlineno,
                lnotab,
            )
        raise ValueError(
            f"unsupported marshal code {kind!r} at {start}; "
            f"next={self.data[start:start + 20].hex()}"
        )


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_round_keys(decryption_path: Path) -> list[int]:
    tree = ast.parse(decryption_path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "round_keys"
            for target in node.targets
        ):
            value = ast.literal_eval(node.value)
            if isinstance(value, list):
                return value
    raise ValueError("round_keys assignment not found")


def decrypt_mode3_index(data: bytes, eggy_codes: Any, keys: list[int]) -> bytes:
    result = bytearray(data)
    for block_index in range(len(result) // 16):
        offset = block_index * 16
        block = bytes(result[offset : offset + 16])
        result[offset : offset + 16] = eggy_codes.decrypt_mode3_block(block, keys)
    return bytes(result)


def rotor_key() -> str:
    part_a = "j2h56ogodh3se"
    part_b = "=dziaq."
    part_c = '|os=5v7!"-234'
    return (
        part_a * 4
        + (part_b + part_a + part_c) * 5
        + "!"
        + "#"
        + part_b * 7
        + part_c * 2
        + "*"
        + "&"
        + "'"
    )


def unwrap_rotor(data: bytes, rotor_module: Any) -> bytes:
    rotor = rotor_module.Rotor(rotor_key())
    # Some NeoXtractor revisions declare this attribute but do not initialize it.
    rotor.positions = [None, None]
    size, rotor_count, rotors, positions = rotor.get_rotors(True)
    decrypted = bytearray(len(data))
    for output_index, byte in enumerate(data):
        for rotor_index in range(rotor_count - 1, -1, -1):
            byte = positions[rotor_index] ^ rotors[rotor_index][byte]
        decrypted[output_index] = byte
        carry = 0
        for rotor_index in range(rotor_count):
            carry = (
                (positions[rotor_index] + (carry >= size)) & 0xFF
            ) + rotors[rotor_index][size]
            positions[rotor_index] = carry % size
    unpacked = zlib.decompress(decrypted)
    first = [byte ^ 154 for byte in unpacked[:128]]
    return bytes(reversed(first + list(unpacked[128:])))


def extract_entry(
    npk_path: Path, signature: int, neoxtractor_root: Path
) -> tuple[bytes, dict[str, Any]]:
    eggy_codes = load_module(
        "neox_eggyparty_codes",
        neoxtractor_root / "core" / "npk" / "eggyparty_codes.py",
    )
    rotor_module = load_module("neox_rotor", neoxtractor_root / "core" / "rotor.py")
    round_keys = load_round_keys(neoxtractor_root / "core" / "npk" / "decryption.py")

    archive = npk_path.read_bytes()
    magic, count, variant, encrypt_mode, hash_mode, index_offset = struct.unpack_from(
        "<4sIIIII", archive, 0
    )
    if magic != b"NXPK":
        raise ValueError(f"unsupported archive magic {magic!r}")
    info_size = 32 if variant == 1 else (len(archive) - index_offset) // count
    actual_index_offset = len(archive) - info_size * count if variant == 1 else index_offset
    index_data = archive[actual_index_offset : actual_index_offset + count * info_size]
    if encrypt_mode == 3:
        index_data = decrypt_mode3_index(index_data, eggy_codes, round_keys)

    for index in range(count):
        if info_size == 28:
            values = struct.unpack_from("<6I2H", index_data, index * info_size)
            entry_signature, file_offset, length, original_length, zcrc, crc, zip_flag, entry_encrypt = values
        elif info_size == 32:
            values = struct.unpack_from("<Q5I2H", index_data, index * info_size)
            entry_signature, file_offset, length, original_length, zcrc, crc, zip_flag, entry_encrypt = values
        else:
            raise ValueError(f"unsupported NPK index size {info_size}")
        if entry_signature != signature:
            continue
        data = archive[file_offset : file_offset + length]
        if entry_encrypt:
            raise ValueError(f"entry encryption flag {entry_encrypt} is not implemented")
        if zip_flag == 1:
            data = zlib.decompress(data)
        elif zip_flag not in (0,):
            raise ValueError(f"entry compression flag {zip_flag} is not implemented")
        wrappers = []
        if data[:2] in (b"\x1d\x04", b"\x15\x23"):
            data = unwrap_rotor(data, rotor_module)
            wrappers.append("rotor-zlib-reverse")
        return data, {
            "archive_magic": magic.decode("ascii"),
            "archive_entry_count": count,
            "archive_encrypt_mode": encrypt_mode,
            "archive_hash_mode": hash_mode,
            "index": index,
            "signature": f"0x{signature:08x}",
            "stored_length": length,
            "original_length": original_length,
            "decoded_length": len(data),
            "zip_flag": zip_flag,
            "entry_encrypt_flag": entry_encrypt,
            "wrappers": wrappers,
            "zcrc": f"0x{zcrc:08x}",
            "crc": f"0x{crc:08x}",
        }
    raise KeyError(f"signature 0x{signature:08x} not found")


def safe(value: Any) -> Any:
    if isinstance(value, LegacyCode):
        return {
            "__code__": {
                "argcount": value.argcount,
                "nlocals": value.nlocals,
                "stacksize": value.stacksize,
                "flags": value.flags,
                "code": safe(value.code),
                "consts": safe(value.consts),
                "names": safe(value.names),
                "varnames": safe(value.varnames),
                "freevars": safe(value.freevars),
                "cellvars": safe(value.cellvars),
                "filename": safe(value.filename),
                "name": safe(value.name),
                "firstlineno": value.firstlineno,
                "lnotab": safe(value.lnotab),
            }
        }
    if isinstance(value, bytes):
        try:
            return {"__bytes_utf8__": value.decode("utf-8")}
        except UnicodeDecodeError:
            return {"__bytes_hex__": value.hex()}
    if isinstance(value, tuple):
        return {"__tuple__": [safe(item) for item in value]}
    if isinstance(value, list):
        return [safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): safe(item) for key, item in value.items()}
    return value


def parse_signature(value: str) -> int:
    return int(value, 0)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("npk", type=Path)
    parser.add_argument("signature", type=parse_signature)
    parser.add_argument("output", type=Path)
    parser.add_argument("--neoxtractor-root", required=True, type=Path)
    args = parser.parse_args()

    data, metadata = extract_entry(args.npk, args.signature, args.neoxtractor_root)
    reader = LegacyMarshalReader(data)
    code = reader.load()
    if reader.offset != len(data):
        raise ValueError(f"marshal trailing bytes: {len(data) - reader.offset}")
    result = {"entry": metadata, "marshal": safe(code)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(f"wrote {metadata['signature']} to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

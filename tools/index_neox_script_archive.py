#!/usr/bin/env python3
"""Recover module filenames from every entry in a legacy NeoX script NPK."""

from __future__ import annotations

import argparse
import csv
import struct
import zlib
from pathlib import Path

from extract_neox_script_module import (
    LegacyCode,
    LegacyMarshalReader,
    decrypt_mode3_index,
    load_module,
    load_round_keys,
    unwrap_rotor,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("npk", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--neoxtractor-root", required=True, type=Path)
    parser.add_argument("--start-index", type=int, default=0)
    parser.add_argument("--end-index", type=int)
    args = parser.parse_args()

    eggy_codes = load_module(
        "neox_eggyparty_codes_index",
        args.neoxtractor_root / "core" / "npk" / "eggyparty_codes.py",
    )
    rotor_module = load_module(
        "neox_rotor_index", args.neoxtractor_root / "core" / "rotor.py"
    )
    round_keys = load_round_keys(
        args.neoxtractor_root / "core" / "npk" / "decryption.py"
    )

    archive = args.npk.read_bytes()
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

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(
            [
                "archive",
                "index",
                "signature",
                "stored_length",
                "decoded_length",
                "filename",
                "status",
            ]
        )
        start_index = max(0, args.start_index)
        end_index = min(count, args.end_index if args.end_index is not None else count)
        if start_index > end_index:
            raise ValueError("start index is greater than end index")
        for index in range(start_index, end_index):
            if info_size == 28:
                values = struct.unpack_from("<6I2H", index_data, index * info_size)
            elif info_size == 32:
                values = struct.unpack_from("<Q5I2H", index_data, index * info_size)
            else:
                raise ValueError(f"unsupported NPK index size {info_size}")
            signature, file_offset, length, original_length, _, _, zip_flag, entry_encrypt = values
            decoded_length = ""
            filename = ""
            status = "ok"
            try:
                if entry_encrypt:
                    raise ValueError(f"entry-encrypt-{entry_encrypt}")
                data = archive[file_offset : file_offset + length]
                if zip_flag == 1:
                    data = zlib.decompress(data)
                elif zip_flag != 0:
                    raise ValueError(f"compression-{zip_flag}")
                if data[:2] in (b"\x1d\x04", b"\x15\x23"):
                    data = unwrap_rotor(data, rotor_module)
                decoded_length = len(data)
                reader = LegacyMarshalReader(data)
                code = reader.load()
                if not isinstance(code, LegacyCode):
                    raise ValueError("marshal-root-is-not-code")
                if reader.offset != len(data):
                    raise ValueError(f"marshal-trailing-{len(data) - reader.offset}")
                filename = str(code.filename)
            except Exception as exc:  # inventory must retain failures as evidence
                status = f"error:{type(exc).__name__}:{exc}"
            writer.writerow(
                [
                    args.npk.name,
                    index,
                    f"0x{signature:08x}",
                    length,
                    decoded_length,
                    filename,
                    status,
                ]
            )
    print(f"indexed {end_index - start_index} entries to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

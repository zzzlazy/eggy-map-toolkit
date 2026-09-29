from __future__ import annotations

from .errors import CapabilityError


def engine_string_hash(value: str | bytes) -> int:
    """Return the package engine's 32-bit string hash.

    Static disassembly identifies MurmurHash3 x86_32 with the engine seed
    ``0x9747B28C``. Text inputs are encoded as UTF-8, matching the native
    Python binding's string conversion path.
    """
    if isinstance(value, str):
        data = value.encode("utf-8")
    elif isinstance(value, bytes):
        data = value
    else:
        raise CapabilityError("engine string hash requires str or bytes")

    result = 0x9747B28C
    block_end = len(data) & ~3
    for offset in range(0, block_end, 4):
        block = int.from_bytes(data[offset : offset + 4], "little")
        block = (block * 0xCC9E2D51) & 0xFFFFFFFF
        block = ((block << 15) | (block >> 17)) & 0xFFFFFFFF
        block = (block * 0x1B873593) & 0xFFFFFFFF
        result ^= block
        result = ((result << 13) | (result >> 19)) & 0xFFFFFFFF
        result = (result * 5 + 0xE6546B64) & 0xFFFFFFFF

    tail = data[block_end:]
    block = 0
    if len(tail) == 3:
        block ^= tail[2] << 16
    if len(tail) >= 2:
        block ^= tail[1] << 8
    if tail:
        block ^= tail[0]
        block = (block * 0xCC9E2D51) & 0xFFFFFFFF
        block = ((block << 15) | (block >> 17)) & 0xFFFFFFFF
        block = (block * 0x1B873593) & 0xFFFFFFFF
        result ^= block

    result ^= len(data)
    result ^= result >> 16
    result = (result * 0x85EBCA6B) & 0xFFFFFFFF
    result ^= result >> 13
    result = (result * 0xC2B2AE35) & 0xFFFFFFFF
    result ^= result >> 16
    return result

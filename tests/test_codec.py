import msgpack
import pytest
import zstandard

from eggy_map_api.codec import decode_mm
from eggy_map_api.errors import SnapshotError


def wrap(payload: bytes) -> bytes:
    return zstandard.ZstdCompressor().compress(payload)


def test_strict_decode_accepts_canonical_payload() -> None:
    raw = msgpack.packb({b"value": [1, 2.5]}, use_bin_type=True)
    assert decode_mm(wrap(raw)) == {b"value": [1, 2.5]}


def test_strict_decode_rejects_duplicate_keys() -> None:
    # fixmap(2), "a":1, "a":2
    with pytest.raises(SnapshotError, match="duplicate"):
        decode_mm(wrap(b"\x82\xa1a\x01\xa1a\x02"))


def test_strict_decode_rejects_noncanonical_integer() -> None:
    # uint8(1) must have been encoded as a positive fixint.
    with pytest.raises(SnapshotError, match="non-canonical"):
        decode_mm(wrap(b"\xcc\x01"))

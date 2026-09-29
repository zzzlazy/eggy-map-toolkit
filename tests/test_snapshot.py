import msgpack
import zstandard

from eggy_map_api.snapshot import open_snapshot


def mm(value):
    return zstandard.ZstdCompressor().compress(msgpack.packb(value, use_bin_type=True))


def test_snapshot_requires_and_decodes_editable_inventory(tmp_path) -> None:
    (tmp_path / "header.map").write_bytes(b"header")
    (tmp_path / "unit.mm").write_bytes(mm({b"unit": {}, b"_unit_create_index": {}}))
    (tmp_path / "desc.mm").write_bytes(mm({b"map_recommend_play_num": 1}))
    (tmp_path / "uniteditor.mm").write_bytes(mm({}))
    (tmp_path / "editingcachewithlevel.mm").write_bytes(mm({}))
    snapshot = open_snapshot(tmp_path)
    assert snapshot.decoded("unit.mm")[b"unit"] == {}
    assert len(snapshot.files) == 5

import hashlib
import json
from pathlib import Path

import pytest

from eggy_map_api.device import DeviceContext, MapLocation
from eggy_map_api.errors import DeploymentError, StateError
from eggy_map_api.state import StateStore
from eggy_map_api.transaction import TransactionCoordinator


def synthetic_device() -> DeviceContext:
    return DeviceContext(
        serial="synthetic-device",
        package="synthetic.package",
        maps_root="/synthetic/device/application/files/editor_maps",
        version_code=1,
        version_name="synthetic",
        apk_path="/synthetic/device/application/base.apk",
        apk_sha256="0" * 64,
        pid="123",
        root_available=True,
        profile_match=True,
    )


def synthetic_location(suffix: str = "one") -> MapLocation:
    root = "/synthetic/device/application/files/editor_maps"
    return MapLocation(
        map_id=f"synthetic-{suffix}",
        name=f"Synthetic {suffix}",
        save_time=1,
        map_directory=f"{root}/synthetic-{suffix}",
        archive_path=f"{root}/synthetic-{suffix}.gmp",
        index_path=f"{root}/index.conf",
    )


def test_opaque_refs_are_snapshot_and_map_bound(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state")
    device = synthetic_device()
    first = store.register_map(device, synthetic_location("one"), "revision-one")
    second = store.register_map(device, synthetic_location("two"), "revision-two")
    unit_ref = store.register_unit(first, 101, "revision-one")
    assert store.resolve_unit(unit_ref, map_ref=first).unit_id == 101
    with pytest.raises(StateError) as caught:
        store.resolve_unit(unit_ref, map_ref=second)
    assert caught.value.error_code == "UNIT_REF_INVALID"
    assert "/" not in first and "/" not in unit_ref


def test_mutation_requires_editor_closed_before_reference_resolution(
    tmp_path: Path,
) -> None:
    coordinator = TransactionCoordinator(
        adb=object(), store=StateStore(tmp_path / "state"), catalog=object()
    )
    with pytest.raises(DeploymentError) as caught:
        coordinator.execute(
            map_ref="unknown",
            operation="add",
            editor_closed_confirmed=False,
            builder=lambda _snapshot, _output: None,
        )
    assert caught.value.error_code == "EDITOR_NOT_CONFIRMED_CLOSED"


def test_backup_manifest_requires_both_hashes(tmp_path: Path) -> None:
    backup = tmp_path / "backup"
    backup.mkdir()
    payload = b"synthetic payload"
    (backup / "map.gmp").write_bytes(payload)
    capture = {
        "schema_version": 1,
        "capture_complete": True,
        "device": {},
        "map": {},
        "hashes": {},
        "permissions": {},
        "directories": [],
        "local_hashes": {
            "map.gmp": {
                "sha256": hashlib.sha256(payload).hexdigest(),
                "blake2b": hashlib.blake2b(payload).hexdigest(),
            }
        },
    }
    for relative in (
        "map/header.map",
        "map/unit.mm",
        "map/desc.mm",
        "map/uniteditor.mm",
        "index.conf",
    ):
        target = backup / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        capture["local_hashes"][relative] = {
            "sha256": hashlib.sha256(payload).hexdigest(),
            "blake2b": hashlib.blake2b(payload).hexdigest(),
        }
    (backup / "capture.json").write_text(json.dumps(capture), encoding="utf-8")
    assert TransactionCoordinator._load_capture(backup)["capture_complete"]
    capture["local_hashes"]["map.gmp"]["blake2b"] = "0" * 128
    (backup / "capture.json").write_text(json.dumps(capture), encoding="utf-8")
    with pytest.raises(StateError, match="bytes changed"):
        TransactionCoordinator._load_capture(backup)


def test_rollback_index_rejects_duplicate_keys(tmp_path: Path) -> None:
    path = tmp_path / "index.conf"
    path.write_text('{"map_conf":{"synthetic":{}},"map_conf":{}}', encoding="utf-8")
    with pytest.raises(StateError, match="duplicate"):
        TransactionCoordinator._index_without_target(path, "synthetic")

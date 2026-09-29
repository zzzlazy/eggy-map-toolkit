import hashlib
import json
import shutil
from pathlib import Path

import eggy_map_api.transaction as transaction_module
from eggy_map_api.codec import encode_mm
from eggy_map_api.device import DeviceContext, FrozenTriplet, MapLocation, RemoteState
from eggy_map_api.state import StateStore
from eggy_map_api.transaction import TransactionCoordinator


def digest(path: Path) -> tuple[str, str]:
    raw = path.read_bytes()
    return hashlib.sha256(raw).hexdigest(), hashlib.blake2b(raw).hexdigest()


def test_full_triplet_rollback_records_new_reference(
    tmp_path: Path, monkeypatch
) -> None:
    remote_root = "/synthetic/application/files/editor_maps"
    location = MapLocation(
        map_id="synthetic-map",
        name="Synthetic",
        save_time=1,
        map_directory=f"{remote_root}/synthetic-map",
        archive_path=f"{remote_root}/synthetic-map.gmp",
        index_path=f"{remote_root}/index.conf",
    )
    device = DeviceContext(
        serial="synthetic",
        package="synthetic.package",
        maps_root=remote_root,
        version_code=1,
        version_name="synthetic",
        apk_path="/synthetic/application/base.apk",
        apk_sha256="0" * 64,
        pid="456",
        root_available=True,
        profile_match=True,
    )
    backup = tmp_path / "original-backup"
    map_dir = backup / "map"
    map_dir.mkdir(parents=True)
    (map_dir / "header.map").write_bytes(b"synthetic")
    for name, value in (
        ("unit.mm", {b"unit": {}}),
        ("desc.mm", {}),
        ("uniteditor.mm", {}),
    ):
        (map_dir / name).write_bytes(encode_mm(value, compression_level=3))
    (backup / "map.gmp").write_bytes(b"original archive")
    index = {
        "map_conf": {
            location.map_id: {
                "name": location.name,
                "save_time": 1,
            }
        }
    }
    (backup / "index.conf").write_text(json.dumps(index), encoding="utf-8")

    local_files = [path for path in backup.rglob("*") if path.is_file()]
    local_hashes = {
        path.relative_to(backup).as_posix(): {
            "sha256": digest(path)[0],
            "blake2b": digest(path)[1],
        }
        for path in local_files
    }
    remote_hashes = {
        str(Path(location.map_directory) / path.relative_to(map_dir)): digest(path)[0]
        for path in map_dir.iterdir()
    }
    remote_hashes[location.archive_path] = digest(backup / "map.gmp")[0]
    remote_hashes[location.index_path] = digest(backup / "index.conf")[0]
    permissions = {
        location.map_directory: {
            "type": "directory",
            "uid": 1,
            "gid": 1,
            "mode": 0o700,
        }
    }
    for remote in remote_hashes:
        permissions[remote] = {
            "type": "regular file",
            "uid": 1,
            "gid": 1,
            "mode": 0o600,
        }
    original_state = RemoteState(
        "original",
        remote_hashes,
        permissions,
        (location.map_directory,),
        device.pid,
    )
    capture = {
        "schema_version": 1,
        "capture_complete": True,
        "device": {
            "serial": device.serial,
            "package": device.package,
            "maps_root": device.maps_root,
            "version_code": device.version_code,
            "version_name": device.version_name,
        },
        "map": {
            "map_id": location.map_id,
            "name": location.name,
            "map_directory": location.map_directory,
            "archive_path": location.archive_path,
            "index_path": location.index_path,
        },
        "hashes": remote_hashes,
        "permissions": permissions,
        "directories": [location.map_directory],
        "local_hashes": local_hashes,
    }
    (backup / "capture.json").write_text(json.dumps(capture), encoding="utf-8")

    current_state = RemoteState(
        "current",
        {key: "f" * 64 for key in remote_hashes},
        permissions,
        (location.map_directory,),
        device.pid,
    )
    store = StateStore(tmp_path / "state")
    current_ref = store.register_map(device, location, current_state.revision)
    deployed_id = store.record_deployment(
        operation="add",
        map_ref=current_ref,
        backup_path=backup,
        work_path=tmp_path / "prior-work",
        input_revision=original_state.revision,
        output_revision=current_state.revision,
        changed_files=("unit.mm",),
        validation_checks=("synthetic",),
        status="deployed",
        remote_rollback=f"{location.map_directory}.prior",
    )

    class FakeAdb:
        def __init__(self) -> None:
            self.pushed: list[str] = []

        def push(self, _serial: str, _local: Path, remote: str) -> None:
            self.pushed.append(remote)

    adb = FakeAdb()
    coordinator = TransactionCoordinator(adb=adb, store=store, catalog=object())
    monkeypatch.setattr(coordinator, "_resolve_writable", lambda _stored: device)
    monkeypatch.setattr(coordinator, "_remote_absent", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        coordinator,
        "_upload_map",
        lambda **_kwargs: {path.name: digest(path)[0] for path in map_dir.iterdir()},
    )
    staged_hashes = iter(
        (digest(backup / "map.gmp")[0], digest(backup / "index.conf")[0])
    )

    def root(_device, command: str) -> str:
        if command.startswith("sha256sum "):
            return next(staged_hashes) + "  synthetic\n"
        return ""

    monkeypatch.setattr(coordinator, "_root", root)

    def freeze(_adb, _device, _location, destination: Path) -> FrozenTriplet:
        shutil.copytree(map_dir, destination / "map")
        shutil.copy2(backup / "map.gmp", destination / "map.gmp")
        shutil.copy2(backup / "index.conf", destination / "index.conf")
        return FrozenTriplet(destination, location, device, current_state, {})

    monkeypatch.setattr(transaction_module, "freeze_device_triplet", freeze)
    states = iter((current_state, current_state, original_state))
    monkeypatch.setattr(
        transaction_module, "read_remote_state", lambda *_args: next(states)
    )

    receipt, retained = coordinator.rollback(
        deployment_id=deployed_id,
        editor_closed_confirmed=True,
    )
    assert receipt.status == "rolled_back"
    assert receipt.output_revision == original_state.revision
    assert retained.endswith(receipt.deployment_id.rsplit("_", 1)[-1][:16])
    assert store.resolve_map(receipt.map_ref).revision == original_state.revision
    assert store.get_deployment(deployed_id).status == "rolled_back"
    assert store.get_deployment(receipt.deployment_id).map_ref == receipt.map_ref
    assert len(adb.pushed) == 2

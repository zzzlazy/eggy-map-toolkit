import hashlib
import json
from pathlib import Path

import pytest

import eggy_map_api.transaction as transaction_module
from eggy_map_api.device import DeviceContext, FrozenTriplet, MapLocation, RemoteState
from eggy_map_api.errors import DeploymentError, DeviceError, StateError
from eggy_map_api.state import StateStore
from eggy_map_api.transaction import TransactionCoordinator


def device() -> DeviceContext:
    return DeviceContext(
        serial="synthetic",
        package="synthetic.package",
        maps_root="/synthetic/application/files/editor_maps",
        version_code=1,
        version_name="synthetic",
        apk_path="/synthetic/application/base.apk",
        apk_sha256="0" * 64,
        pid="321",
        root_available=True,
        profile_match=True,
    )


def location() -> MapLocation:
    root = device().maps_root
    return MapLocation(
        map_id="synthetic-map",
        name="Synthetic",
        save_time=1,
        map_directory=f"{root}/synthetic-map",
        archive_path=f"{root}/synthetic-map.gmp",
        index_path=f"{root}/index.conf",
    )


def remote_state(revision: str = "source", *, index_hash: str = "c" * 64) -> RemoteState:
    loc = location()
    permissions = {
        loc.map_directory: {"type": "directory", "uid": 1, "gid": 1, "mode": 0o700},
        f"{loc.map_directory}/unit.mm": {
            "type": "regular file",
            "uid": 1,
            "gid": 1,
            "mode": 0o600,
        },
        loc.archive_path: {"type": "regular file", "uid": 1, "gid": 1, "mode": 0o600},
        loc.index_path: {"type": "regular file", "uid": 1, "gid": 1, "mode": 0o600},
    }
    return RemoteState(
        revision,
        {
            f"{loc.map_directory}/unit.mm": "a" * 64,
            loc.archive_path: "b" * 64,
            loc.index_path: index_hash,
        },
        permissions,
        (loc.map_directory,),
        device().pid,
    )


def index_document(flag: bool) -> dict:
    return {
        "schema": 1,
        "map_conf": {
            location().map_id: {
                "name": location().name,
                "save_time": 1,
                "map_upload_fail_tag": flag,
                "custom": {"preserved": True},
            },
            "another-map": {
                "name": "Another",
                "map_upload_fail_tag": True,
            },
        },
    }


class PushAdb:
    def __init__(self) -> None:
        self.pushes: list[tuple[Path, str]] = []
        self.pushed_hash = ""

    def push(self, _serial: str, local: Path, remote: str) -> None:
        self.pushes.append((local, remote))
        self.pushed_hash = hashlib.sha256(local.read_bytes()).hexdigest()


def coordinator(tmp_path: Path, adb: PushAdb) -> TransactionCoordinator:
    return TransactionCoordinator(
        adb=adb,
        store=StateStore(tmp_path / "state"),
        catalog=object(),
    )


def install_capture(monkeypatch, tmp_path: Path, tx: TransactionCoordinator, flag: bool):
    source = remote_state()
    target_device = device()
    target_location = location()
    map_ref = tx.store.register_map(target_device, target_location, source.revision)
    monkeypatch.setattr(tx, "_resolve_writable", lambda _stored: target_device)
    monkeypatch.setattr(tx, "_remote_absent", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(transaction_module, "open_snapshot", lambda _path: object())
    monkeypatch.setattr(
        transaction_module, "validate_snapshot_integrity", lambda _snapshot: None
    )

    def freeze(_adb, _device, _location, destination: Path) -> FrozenTriplet:
        (destination / "map").mkdir(parents=True)
        (destination / "map.gmp").write_bytes(b"archive")
        (destination / "index.conf").write_text(
            json.dumps(index_document(flag), ensure_ascii=False), encoding="utf-8"
        )
        return FrozenTriplet(destination, target_location, target_device, source, {})

    monkeypatch.setattr(transaction_module, "freeze_device_triplet", freeze)
    return map_ref, source


def test_reset_requires_editor_closed_before_reference_resolution(tmp_path: Path) -> None:
    tx = coordinator(tmp_path, PushAdb())
    with pytest.raises(DeploymentError) as caught:
        tx.reset_map_upload_failure(
            map_ref="unknown", editor_closed_confirmed=False
        )
    assert caught.value.error_code == "EDITOR_NOT_CONFIRMED_CLOSED"


def test_reset_changes_only_target_index_flag_and_records_deployment(
    tmp_path: Path, monkeypatch
) -> None:
    adb = PushAdb()
    tx = coordinator(tmp_path, adb)
    map_ref, source = install_capture(monkeypatch, tmp_path, tx, True)
    commands: list[str] = []

    def root(_device, command: str) -> str:
        commands.append(command)
        if command.startswith("sha256sum "):
            return f"{adb.pushed_hash}  staged-index\n"
        return ""

    monkeypatch.setattr(tx, "_root", root)
    reads = 0

    def read_state(*_args):
        nonlocal reads
        reads += 1
        if reads < 3:
            return source
        return remote_state("output", index_hash=adb.pushed_hash)

    monkeypatch.setattr(transaction_module, "read_remote_state", read_state)
    receipt = tx.reset_map_upload_failure(
        map_ref=map_ref, editor_closed_confirmed=True
    )

    assert receipt.operation == "reset_upload_failure"
    assert receipt.changed_files == ("index.conf",)
    assert tx.store.resolve_map(receipt.map_ref).revision == "output"
    deployed = tx.store.get_deployment(receipt.deployment_id)
    assert deployed.operation == "reset_upload_failure"
    assert deployed.status == "deployed"
    output = json.loads(adb.pushes[0][0].read_text(encoding="utf-8"))
    expected = index_document(True)
    expected["map_conf"][location().map_id]["map_upload_fail_tag"] = False
    assert output == expected
    assert len(adb.pushes) == 1
    assert ".eggy-stage-" in adb.pushes[0][1]
    assert len([command for command in commands if command.startswith("mv ")]) == 2


def test_reset_rejects_an_unset_flag_without_device_write(
    tmp_path: Path, monkeypatch
) -> None:
    adb = PushAdb()
    tx = coordinator(tmp_path, adb)
    map_ref, source = install_capture(monkeypatch, tmp_path, tx, False)
    monkeypatch.setattr(
        transaction_module, "read_remote_state", lambda *_args: source
    )
    commands: list[str] = []
    monkeypatch.setattr(tx, "_root", lambda _device, command: commands.append(command) or "")

    with pytest.raises(StateError) as caught:
        tx.reset_map_upload_failure(
            map_ref=map_ref, editor_closed_confirmed=True
        )
    assert caught.value.error_code == "UPLOAD_FAILURE_NOT_SET"
    assert adb.pushes == []
    assert not any(command.startswith("mv ") for command in commands)


def test_atomic_index_swap_failure_restores_original(
    tmp_path: Path, monkeypatch
) -> None:
    adb = PushAdb()
    tx = coordinator(tmp_path, adb)
    source_file = tmp_path / "index.conf"
    source_file.write_text(json.dumps(index_document(False)), encoding="utf-8")
    source = remote_state()
    frozen = FrozenTriplet(tmp_path / "capture", location(), device(), source, {})
    monkeypatch.setattr(tx, "_remote_absent", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        transaction_module, "read_remote_state", lambda *_args: source
    )
    commands: list[str] = []
    moves = 0

    def root(_device, command: str) -> str:
        nonlocal moves
        commands.append(command)
        if command.startswith("sha256sum "):
            return f"{adb.pushed_hash}  staged-index\n"
        if command.startswith("mv "):
            moves += 1
            if moves == 2:
                raise DeviceError("synthetic swap failure")
        return ""

    monkeypatch.setattr(tx, "_root", root)
    with pytest.raises(DeploymentError) as caught:
        tx._deploy_index(
            device=device(),
            location=location(),
            frozen=frozen,
            source=source_file,
            deployment_id="deployment_synthetic",
        )
    assert caught.value.error_code == "ATOMIC_SWAP_FAILED"
    move_commands = [command for command in commands if command.startswith("mv ")]
    assert len(move_commands) == 3
    assert ".eggy-rollback-" in move_commands[-1]

from pathlib import Path

import pytest

import eggy_map_api.device as device_module
import eggy_map_api.transaction as transaction_module
from eggy_map_api.codec import encode_mm
from eggy_map_api.device import (
    DeviceContext,
    FrozenTriplet,
    MapLocation,
    RemoteState,
    freeze_device_triplet,
)
from eggy_map_api.errors import DeploymentError, DeviceError, SnapshotError
from eggy_map_api.state import StateStore
from eggy_map_api.transaction import TransactionCoordinator


def context() -> DeviceContext:
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
    root = "/synthetic/application/files/editor_maps"
    return MapLocation(
        map_id="synthetic-map",
        name="Synthetic",
        save_time=1,
        map_directory=f"{root}/synthetic-map",
        archive_path=f"{root}/synthetic-map.gmp",
        index_path=f"{root}/index.conf",
    )


def state(revision: str = "source", *, permissions=None) -> RemoteState:
    loc = location()
    hashes = {
        f"{loc.map_directory}/unit.mm": "a" * 64,
        loc.archive_path: "b" * 64,
        loc.index_path: "c" * 64,
    }
    default_permissions = {
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
        hashes,
        permissions or default_permissions,
        (loc.map_directory,),
        "321",
    )


class LoggingAdb:
    def __init__(self) -> None:
        self.commands: list[str] = []

    def shell(self, _serial: str, command: str, *, root: bool = False) -> str:
        self.commands.append(command)
        return "0\n"


def coordinator(tmp_path: Path, adb: LoggingAdb) -> TransactionCoordinator:
    return TransactionCoordinator(
        adb=adb,
        store=StateStore(tmp_path / "state"),
        catalog=object(),
    )


def frozen(tmp_path: Path) -> FrozenTriplet:
    return FrozenTriplet(tmp_path / "backup", location(), context(), state(), {})


def test_change_after_staging_prevents_swap(tmp_path: Path, monkeypatch) -> None:
    adb = LoggingAdb()
    tx = coordinator(tmp_path, adb)
    monkeypatch.setattr(tx, "_remote_absent", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        tx,
        "_upload_map",
        lambda **_kwargs: {"unit.mm": "d" * 64},
    )
    monkeypatch.setattr(
        transaction_module,
        "read_remote_state",
        lambda *_args, **_kwargs: state("changed"),
    )
    with pytest.raises(DeploymentError) as caught:
        tx._deploy_map(
            device=context(),
            location=location(),
            frozen=frozen(tmp_path),
            output=tmp_path / "output",
            deployment_id="deployment_synthetic",
        )
    assert caught.value.error_code == "CONCURRENT_SAVE"
    assert not any(command.startswith("mv ") for command in adb.commands)


def test_atomic_swap_failure_attempts_immediate_restore(
    tmp_path: Path, monkeypatch
) -> None:
    adb = LoggingAdb()
    tx = coordinator(tmp_path, adb)
    monkeypatch.setattr(tx, "_remote_absent", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(tx, "_upload_map", lambda **_kwargs: {"unit.mm": "d" * 64})
    monkeypatch.setattr(transaction_module, "read_remote_state", lambda *_args: state())
    calls = 0

    def root(_device, command):
        nonlocal calls
        adb.commands.append(command)
        if command.startswith("mv "):
            calls += 1
            if calls == 2:
                raise DeviceError("synthetic swap failure")
        return "0\n"

    monkeypatch.setattr(tx, "_root", root)
    with pytest.raises(DeploymentError) as caught:
        tx._deploy_map(
            device=context(),
            location=location(),
            frozen=frozen(tmp_path),
            output=tmp_path / "output",
            deployment_id="deployment_synthetic",
        )
    assert caught.value.error_code == "ATOMIC_SWAP_FAILED"
    assert calls == 3
    assert ".eggy-rollback-" in adb.commands[-1]


def test_permission_mismatch_restores_original_and_fails(
    tmp_path: Path, monkeypatch
) -> None:
    adb = LoggingAdb()
    tx = coordinator(tmp_path, adb)
    source = state()
    altered_permissions = dict(source.permissions)
    altered_permissions[location().map_directory] = {
        "type": "directory",
        "uid": 9,
        "gid": 9,
        "mode": 0o700,
    }
    after = RemoteState(
        "output",
        {
            f"{location().map_directory}/unit.mm": "d" * 64,
            location().archive_path: "b" * 64,
            location().index_path: "c" * 64,
        },
        altered_permissions,
        source.directories,
        source.pid,
    )
    states = iter((source, after, source))
    monkeypatch.setattr(tx, "_remote_absent", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(tx, "_upload_map", lambda **_kwargs: {"unit.mm": "d" * 64})
    monkeypatch.setattr(
        transaction_module, "read_remote_state", lambda *_args: next(states)
    )
    with pytest.raises(DeploymentError) as caught:
        tx._deploy_map(
            device=context(),
            location=location(),
            frozen=frozen(tmp_path),
            output=tmp_path / "output",
            deployment_id="deployment_synthetic",
        )
    assert caught.value.error_code == "DEVICE_HASH_MISMATCH"
    assert any(".eggy-failed-" in command for command in adb.commands)


def test_post_swap_read_failure_restores_original(tmp_path: Path, monkeypatch) -> None:
    adb = LoggingAdb()
    tx = coordinator(tmp_path, adb)
    responses = iter((state(), DeviceError("synthetic read failure"), state()))

    def read(*_args):
        value = next(responses)
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(tx, "_remote_absent", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(tx, "_upload_map", lambda **_kwargs: {"unit.mm": "d" * 64})
    monkeypatch.setattr(transaction_module, "read_remote_state", read)
    with pytest.raises(DeploymentError) as caught:
        tx._deploy_map(
            device=context(),
            location=location(),
            frozen=frozen(tmp_path),
            output=tmp_path / "output",
            deployment_id="deployment_synthetic",
        )
    assert caught.value.error_code == "DEVICE_HASH_MISMATCH"
    assert any(".eggy-failed-" in command for command in adb.commands)


def test_capture_detects_change_during_backup(tmp_path: Path, monkeypatch) -> None:
    remote_root = tmp_path / "remote"
    map_root = remote_root / "map"
    map_root.mkdir(parents=True)
    (map_root / "header.map").write_bytes(b"synthetic")
    for name, value in (
        ("unit.mm", {b"unit": {}}),
        ("desc.mm", {}),
        ("uniteditor.mm", {}),
    ):
        (map_root / name).write_bytes(encode_mm(value, compression_level=3))
    (remote_root / "map.gmp").write_bytes(b"archive")
    (remote_root / "index.conf").write_bytes(b"{}")

    loc = location()
    sources = {f"{loc.map_directory}/{path.name}": path for path in map_root.iterdir()}
    sources[loc.archive_path] = remote_root / "map.gmp"
    sources[loc.index_path] = remote_root / "index.conf"

    class PullAdb:
        def pull(self, _serial: str, remote: str, local: Path) -> None:
            local.parent.mkdir(parents=True, exist_ok=True)
            local.write_bytes(sources[remote].read_bytes())

    snapshots = iter((state("before"), state("during")))
    monkeypatch.setattr(
        device_module, "read_remote_state", lambda *_args: next(snapshots)
    )
    with pytest.raises(SnapshotError) as caught:
        freeze_device_triplet(PullAdb(), context(), loc, tmp_path / "capture")
    assert caught.value.error_code == "CONCURRENT_SAVE"
    assert (tmp_path / "capture" / "INCOMPLETE").is_file()


def test_change_between_reference_check_and_backup_never_builds(
    tmp_path: Path, monkeypatch
) -> None:
    adb = LoggingAdb()
    tx = coordinator(tmp_path, adb)
    device = context()
    map_ref = tx.store.register_map(device, location(), "source")
    monkeypatch.setattr(tx, "_resolve_writable", lambda _stored: device)
    monkeypatch.setattr(
        transaction_module, "read_remote_state", lambda *_args: state("source")
    )
    captured = FrozenTriplet(
        tmp_path / "captured",
        location(),
        device,
        state("newer"),
        {},
    )
    monkeypatch.setattr(
        transaction_module, "freeze_device_triplet", lambda *_args: captured
    )
    built = False

    def builder(_snapshot, _output):
        nonlocal built
        built = True

    with pytest.raises(DeploymentError) as caught:
        tx.execute(
            map_ref=map_ref,
            operation="add",
            editor_closed_confirmed=True,
            builder=builder,
        )
    assert caught.value.error_code == "CONCURRENT_SAVE"
    assert built is False

from __future__ import annotations

import fcntl
import hashlib
import json
import shlex
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .catalog_bundle import CompiledCatalog
from .device import (
    AdbClient,
    DeviceContext,
    FrozenTriplet,
    MapLocation,
    RemoteState,
    discover_device,
    freeze_device_triplet,
    read_remote_state,
)
from .errors import DeploymentError, EggyMapError, StateError
from .models import DeploymentReceipt, MapSnapshot
from .snapshot import open_snapshot
from .state import StateStore, StoredMapRef
from .validate import validate_snapshot_integrity


@dataclass(frozen=True)
class BuildResult:
    output: Path
    checks: tuple[str, ...]


Builder = Callable[[MapSnapshot, Path], BuildResult]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _blake2b(path: Path) -> str:
    digest = hashlib.blake2b()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tree_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): _sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


class TransactionCoordinator:
    def __init__(
        self,
        *,
        adb: AdbClient,
        store: StateStore,
        catalog: CompiledCatalog,
    ) -> None:
        self.adb = adb
        self.store = store
        self.catalog = catalog

    @contextmanager
    def _lock(self, stored: StoredMapRef):
        digest = hashlib.sha256(
            f"{stored.serial}\0{stored.location.map_directory}".encode()
        ).hexdigest()
        path = self.store.root / f"map-{digest}.lock"
        with path.open("a+b") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise StateError(
                    "another mutation is already active for this map",
                    code="MAP_LOCKED",
                ) from exc
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def _resolve_writable(self, stored: StoredMapRef) -> DeviceContext:
        device = discover_device(
            self.adb, game_profile=self.catalog.game_profile, verify_apk=True
        )
        if (
            device.serial != stored.serial
            or device.package != stored.package
            or device.maps_root != stored.maps_root
        ):
            raise StateError(
                "map_ref belongs to another device or package", code="MAP_REF_INVALID"
            )
        if not device.root_available:
            raise DeploymentError("root access is required", code="ROOT_REQUIRED")
        if not device.pid:
            raise DeploymentError(
                "the game process is not running", code="GAME_NOT_RUNNING"
            )
        if not device.profile_match:
            raise DeploymentError(
                "device package does not match the writable catalog profile",
                code="PROFILE_MISMATCH",
            )
        return device

    @staticmethod
    def _assert_fresh(stored: StoredMapRef, state: RemoteState) -> None:
        if state.revision != stored.revision:
            raise StateError(
                "map_ref no longer identifies the current map bytes",
                code="STALE_MAP_REF",
            )

    def _root(self, device: DeviceContext, command: str) -> str:
        return self.adb.shell(device.serial, command, root=True)

    def _remote_absent(self, device: DeviceContext, paths: tuple[str, ...]) -> None:
        for path in paths:
            AdbClient.validate_remote_path(path)
            status = self._root(
                device, f"test ! -e {shlex.quote(path)}; echo $?"
            ).strip()
            if status != "0":
                raise DeploymentError(
                    "a transaction staging path already exists",
                    code="ATOMIC_SWAP_FAILED",
                )

    def _upload_map(
        self,
        *,
        device: DeviceContext,
        location: MapLocation,
        source: Path,
        stage: str,
        permissions: dict[str, dict[str, Any]],
    ) -> dict[str, str]:
        self._root(device, f"mkdir {shlex.quote(stage)}")
        source_hashes = _tree_hashes(source)
        source_root = PurePosixPath(location.map_directory)
        for relative in source_hashes:
            remote = stage + "/" + relative
            parent = str(PurePosixPath(remote).parent)
            self._root(device, f"mkdir -p {shlex.quote(parent)}")
            self.adb.push(device.serial, source / relative, remote)
            original = str(source_root / PurePosixPath(relative))
            metadata = permissions.get(original)
            if not metadata or metadata.get("type") == "directory":
                raise DeploymentError("source file permission profile is incomplete")
            self._root(
                device,
                f"chown {metadata['uid']}:{metadata['gid']} {shlex.quote(remote)} && "
                f"chmod {metadata['mode']:o} {shlex.quote(remote)}",
            )
        for original, metadata in sorted(
            permissions.items(), key=lambda row: row[0].count("/")
        ):
            if metadata.get("type") != "directory":
                continue
            pure = PurePosixPath(original)
            if original == location.map_directory:
                remote = stage
            elif source_root in pure.parents:
                remote = stage + "/" + pure.relative_to(source_root).as_posix()
            else:
                continue
            self._root(device, f"mkdir -p {shlex.quote(remote)}")
            self._root(
                device,
                f"chown {metadata['uid']}:{metadata['gid']} {shlex.quote(remote)} && "
                f"chmod {metadata['mode']:o} {shlex.quote(remote)}",
            )
        stage_rows = self._root(
            device,
            f"find {shlex.quote(stage)} -type f -exec sha256sum {{}} \\;",
        ).splitlines()
        actual: dict[str, str] = {}
        for row in stage_rows:
            digest, path = row.split(maxsplit=1)
            actual[PurePosixPath(path).relative_to(PurePosixPath(stage)).as_posix()] = (
                digest
            )
        if actual != source_hashes:
            raise DeploymentError(
                "staged map hash mismatch", code="DEVICE_HASH_MISMATCH"
            )
        return source_hashes

    def _deploy_map(
        self,
        *,
        device: DeviceContext,
        location: MapLocation,
        frozen: FrozenTriplet,
        output: Path,
        deployment_id: str,
    ) -> tuple[RemoteState, str]:
        suffix = deployment_id.rsplit("_", 1)[-1][:16]
        stage = location.map_directory + f".eggy-stage-{suffix}"
        rollback = location.map_directory + f".eggy-rollback-{suffix}"
        failed = location.map_directory + f".eggy-failed-{suffix}"
        self._remote_absent(device, (stage, rollback, failed))
        output_hashes = self._upload_map(
            device=device,
            location=location,
            source=output,
            stage=stage,
            permissions=frozen.state.permissions,
        )
        live = read_remote_state(self.adb, device, location)
        if live != frozen.state:
            raise DeploymentError(
                "map changed before atomic swap", code="CONCURRENT_SAVE"
            )
        moved_old = False
        try:
            self._root(
                device,
                f"mv {shlex.quote(location.map_directory)} {shlex.quote(rollback)}",
            )
            moved_old = True
            self._root(
                device,
                f"mv {shlex.quote(stage)} {shlex.quote(location.map_directory)}",
            )
        except EggyMapError as exc:
            if moved_old:
                try:
                    self._root(
                        device,
                        f"mv {shlex.quote(rollback)} {shlex.quote(location.map_directory)}",
                    )
                except EggyMapError as restore_error:
                    raise DeploymentError(
                        "atomic swap and automatic restoration both failed",
                        code="ROLLBACK_FAILED",
                    ) from restore_error
            raise DeploymentError(
                "atomic map swap failed", code="ATOMIC_SWAP_FAILED"
            ) from exc
        try:
            after = read_remote_state(self.adb, device, location)
        except EggyMapError as verify_error:
            try:
                self._root(
                    device,
                    f"mv {shlex.quote(location.map_directory)} {shlex.quote(failed)} && "
                    f"mv {shlex.quote(rollback)} {shlex.quote(location.map_directory)}",
                )
                restored = read_remote_state(self.adb, device, location)
            except EggyMapError as restore_error:
                raise DeploymentError(
                    "post-swap state could not be read and automatic restoration failed",
                    code="ROLLBACK_FAILED",
                ) from restore_error
            if restored != frozen.state:
                raise DeploymentError(
                    "post-swap state could not be read and the restored source did not verify",
                    code="ROLLBACK_FAILED",
                )
            raise DeploymentError(
                "post-swap state could not be read; original map was restored",
                code="DEVICE_HASH_MISMATCH",
            ) from verify_error
        expected_hashes = dict(frozen.state.hashes)
        for remote in list(expected_hashes):
            pure = PurePosixPath(remote)
            root = PurePosixPath(location.map_directory)
            if root in pure.parents:
                expected_hashes.pop(remote)
        expected_hashes.update(
            {
                str(
                    PurePosixPath(location.map_directory) / PurePosixPath(relative)
                ): digest
                for relative, digest in output_hashes.items()
            }
        )
        if (
            after.hashes != expected_hashes
            or after.permissions != frozen.state.permissions
            or after.directories != frozen.state.directories
            or after.pid != frozen.state.pid
        ):
            try:
                self._root(
                    device,
                    f"mv {shlex.quote(location.map_directory)} {shlex.quote(failed)} && "
                    f"mv {shlex.quote(rollback)} {shlex.quote(location.map_directory)}",
                )
            except EggyMapError as exc:
                raise DeploymentError(
                    "post-swap verification failed and restoration was incomplete",
                    code="ROLLBACK_FAILED",
                ) from exc
            restored = read_remote_state(self.adb, device, location)
            if restored != frozen.state:
                raise DeploymentError(
                    "post-swap verification failed and the restored source did not verify",
                    code="ROLLBACK_FAILED",
                )
            raise DeploymentError(
                "post-swap verification failed; original map was restored",
                code="DEVICE_HASH_MISMATCH",
            )
        return after, rollback

    def _deploy_index(
        self,
        *,
        device: DeviceContext,
        location: MapLocation,
        frozen: FrozenTriplet,
        source: Path,
        deployment_id: str,
    ) -> tuple[RemoteState, str]:
        suffix = deployment_id.rsplit("_", 1)[-1][:16]
        stage = location.index_path + f".eggy-stage-{suffix}"
        rollback = location.index_path + f".eggy-rollback-{suffix}"
        failed = location.index_path + f".eggy-failed-{suffix}"
        self._remote_absent(device, (stage, rollback, failed))
        self.adb.push(device.serial, source, stage)
        metadata = frozen.state.permissions.get(location.index_path)
        if not metadata or metadata.get("type") == "directory":
            raise DeploymentError("index permission profile is incomplete")
        self._root(
            device,
            f"chown {metadata['uid']}:{metadata['gid']} {shlex.quote(stage)} && "
            f"chmod {metadata['mode']:o} {shlex.quote(stage)}",
        )
        source_hash = _sha256(source)
        remote_hash = self._root(
            device, f"sha256sum {shlex.quote(stage)}"
        ).split(maxsplit=1)[0]
        if remote_hash != source_hash:
            raise DeploymentError(
                "staged index hash mismatch", code="DEVICE_HASH_MISMATCH"
            )
        live = read_remote_state(self.adb, device, location)
        if live != frozen.state:
            raise DeploymentError(
                "map changed before atomic index swap", code="CONCURRENT_SAVE"
            )
        moved_old = False
        try:
            self._root(
                device,
                f"mv {shlex.quote(location.index_path)} {shlex.quote(rollback)}",
            )
            moved_old = True
            self._root(
                device,
                f"mv {shlex.quote(stage)} {shlex.quote(location.index_path)}",
            )
        except EggyMapError as exc:
            if moved_old:
                try:
                    self._root(
                        device,
                        f"mv {shlex.quote(rollback)} {shlex.quote(location.index_path)}",
                    )
                except EggyMapError as restore_error:
                    raise DeploymentError(
                        "atomic index swap and automatic restoration both failed",
                        code="ROLLBACK_FAILED",
                    ) from restore_error
            raise DeploymentError(
                "atomic index swap failed", code="ATOMIC_SWAP_FAILED"
            ) from exc
        try:
            after = read_remote_state(self.adb, device, location)
        except EggyMapError as verify_error:
            try:
                self._root(
                    device,
                    f"mv {shlex.quote(location.index_path)} {shlex.quote(failed)} && "
                    f"mv {shlex.quote(rollback)} {shlex.quote(location.index_path)}",
                )
                restored = read_remote_state(self.adb, device, location)
            except EggyMapError as restore_error:
                raise DeploymentError(
                    "post-swap index state could not be read and restoration failed",
                    code="ROLLBACK_FAILED",
                ) from restore_error
            if restored != frozen.state:
                raise DeploymentError(
                    "post-swap index state could not be read and source did not restore",
                    code="ROLLBACK_FAILED",
                )
            raise DeploymentError(
                "post-swap index state could not be read; original index was restored",
                code="DEVICE_HASH_MISMATCH",
            ) from verify_error
        expected_hashes = dict(frozen.state.hashes)
        expected_hashes[location.index_path] = source_hash
        if (
            after.hashes != expected_hashes
            or after.permissions != frozen.state.permissions
            or after.directories != frozen.state.directories
            or after.pid != frozen.state.pid
        ):
            try:
                self._root(
                    device,
                    f"mv {shlex.quote(location.index_path)} {shlex.quote(failed)} && "
                    f"mv {shlex.quote(rollback)} {shlex.quote(location.index_path)}",
                )
            except EggyMapError as exc:
                raise DeploymentError(
                    "index verification and automatic restoration both failed",
                    code="ROLLBACK_FAILED",
                ) from exc
            if read_remote_state(self.adb, device, location) != frozen.state:
                raise DeploymentError(
                    "index verification failed and source did not restore",
                    code="ROLLBACK_FAILED",
                )
            raise DeploymentError(
                "index verification failed; original index was restored",
                code="DEVICE_HASH_MISMATCH",
            )
        return after, rollback

    def execute(
        self,
        *,
        map_ref: str,
        operation: str,
        editor_closed_confirmed: bool,
        builder: Builder,
    ) -> tuple[DeploymentReceipt, str]:
        if not editor_closed_confirmed:
            raise DeploymentError(
                "confirm that the editor is closed and the game is on the map list",
                code="EDITOR_NOT_CONFIRMED_CLOSED",
            )
        stored = self.store.resolve_map(map_ref)
        deployment_id = f"deployment_{uuid.uuid4().hex}"
        backup = self.store.backups / deployment_id
        work = self.store.work / deployment_id
        work.mkdir(mode=0o700)
        with self._lock(stored):
            device = self._resolve_writable(stored)
            first = read_remote_state(self.adb, device, stored.location)
            self._assert_fresh(stored, first)
            frozen: FrozenTriplet | None = None
            try:
                frozen = freeze_device_triplet(
                    self.adb, device, stored.location, backup
                )
                if frozen.state != first:
                    raise DeploymentError(
                        "map changed between reference check and backup",
                        code="CONCURRENT_SAVE",
                    )
                input_snapshot = open_snapshot(backup / "map")
                validate_snapshot_integrity(input_snapshot)
                build = builder(input_snapshot, work / "output")
                output_snapshot = open_snapshot(build.output)
                validate_snapshot_integrity(output_snapshot)
                if set(output_snapshot.files) != set(input_snapshot.files):
                    raise DeploymentError(
                        "output changed the editable map file inventory"
                    )
                before_hashes = _tree_hashes(backup / "map")
                after_hashes = _tree_hashes(build.output)
                changed = tuple(
                    name
                    for name in sorted(before_hashes)
                    if before_hashes[name] != after_hashes[name]
                )
                after, remote_rollback = self._deploy_map(
                    device=device,
                    location=stored.location,
                    frozen=frozen,
                    output=build.output,
                    deployment_id=deployment_id,
                )
                checks = tuple(
                    dict.fromkeys(
                        (
                            "input-snapshot-integrity",
                            *build.checks,
                            "output-snapshot-integrity",
                            "device-source-stability",
                            "device-stage-hashes",
                            "permissions-restored",
                            "pid-unchanged",
                        )
                    )
                )
                new_ref = self.store.register_map(
                    device, stored.location, after.revision
                )
                self.store.record_deployment(
                    operation=operation,
                    map_ref=new_ref,
                    backup_path=backup,
                    work_path=work,
                    input_revision=frozen.state.revision,
                    output_revision=after.revision,
                    changed_files=changed,
                    validation_checks=checks,
                    status="deployed",
                    remote_rollback=remote_rollback,
                    deployment_id=deployment_id,
                )
                return (
                    DeploymentReceipt(
                        deployment_id=deployment_id,
                        operation=operation,  # type: ignore[arg-type]
                        map_ref=new_ref,
                        backup_id=backup.name,
                        input_revision=frozen.state.revision,
                        output_revision=after.revision,
                        changed_files=changed,
                        validation_checks=checks,
                        status="deployed",
                    ),
                    remote_rollback,
                )
            except Exception as exc:
                if frozen is not None:
                    try:
                        self.store.record_deployment(
                            operation=operation,
                            map_ref=map_ref,
                            backup_path=backup,
                            work_path=work,
                            input_revision=frozen.state.revision,
                            output_revision=frozen.state.revision,
                            changed_files=(),
                            validation_checks=(),
                            status="failed",
                            remote_rollback=None,
                            deployment_id=deployment_id,
                            details={
                                "error_code": getattr(
                                    exc, "error_code", type(exc).__name__
                                )
                            },
                        )
                    except Exception as state_error:  # noqa: BLE001
                        exc.add_note(
                            f"failed to persist failed deployment state: {type(state_error).__name__}"
                        )
                if isinstance(exc, EggyMapError):
                    exc.context.setdefault("deployment_id", deployment_id)
                    raise
                raise DeploymentError(
                    "unexpected transaction failure",
                    context={"deployment_id": deployment_id},
                ) from exc

    @staticmethod
    def _load_capture(path: Path) -> dict[str, Any]:
        try:
            capture = json.loads((path / "capture.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise StateError("deployment backup manifest is unreadable") from exc
        if (
            not isinstance(capture, dict)
            or capture.get("schema_version") != 1
            or capture.get("capture_complete") is not True
            or not isinstance(capture.get("device"), dict)
            or not isinstance(capture.get("map"), dict)
            or not isinstance(capture.get("hashes"), dict)
            or not isinstance(capture.get("permissions"), dict)
            or not isinstance(capture.get("directories"), list)
            or not isinstance(capture.get("local_hashes"), dict)
        ):
            raise StateError("deployment backup is incomplete")
        for relative, hashes in capture.get("local_hashes", {}).items():
            pure = PurePosixPath(relative) if isinstance(relative, str) else None
            if (
                pure is None
                or pure.is_absolute()
                or ".." in pure.parts
                or str(pure) != relative
                or not isinstance(hashes, dict)
            ):
                raise StateError("deployment backup manifest has an unsafe file entry")
            target = path.joinpath(*pure.parts)
            if (
                not target.is_file()
                or _sha256(target) != hashes.get("sha256")
                or _blake2b(target) != hashes.get("blake2b")
            ):
                raise StateError("deployment backup bytes changed")
        required = {
            "map.gmp",
            "index.conf",
            "map/header.map",
            "map/unit.mm",
            "map/desc.mm",
            "map/uniteditor.mm",
        }
        if not required.issubset(capture["local_hashes"]):
            raise StateError("deployment backup triplet is incomplete")
        return capture

    @staticmethod
    def _assert_capture_identity(
        capture: dict[str, Any], device: DeviceContext, location: MapLocation
    ) -> None:
        recorded_device = capture["device"]
        recorded_map = capture["map"]
        if (
            recorded_device.get("serial") != device.serial
            or recorded_device.get("package") != device.package
            or recorded_device.get("maps_root") != device.maps_root
            or recorded_device.get("version_code") != device.version_code
            or recorded_device.get("version_name") != device.version_name
            or recorded_map.get("map_id") != location.map_id
            or recorded_map.get("map_directory") != location.map_directory
            or recorded_map.get("archive_path") != location.archive_path
            or recorded_map.get("index_path") != location.index_path
        ):
            raise StateError("deployment backup identity does not match the target map")

    @staticmethod
    def _read_index(path: Path) -> dict[str, Any]:
        def unique_pairs(pairs: list[tuple[Any, Any]]) -> dict[Any, Any]:
            result: dict[Any, Any] = {}
            for key, value in pairs:
                if key in result:
                    raise StateError("map index contains a duplicate JSON key")
                result[key] = value
            return result

        try:
            document = json.loads(
                path.read_text(encoding="utf-8"), object_pairs_hook=unique_pairs
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise StateError("map index is unreadable") from exc
        if not isinstance(document, dict):
            raise StateError("map index root is malformed")
        return document

    @classmethod
    def _index_without_target(cls, path: Path, map_id: str) -> tuple[Any, Any]:
        document = cls._read_index(path)
        rows = document.get("map_conf") if isinstance(document, dict) else None
        if not isinstance(rows, dict) or map_id not in rows:
            raise StateError("target map is absent from the map index")
        target = rows.pop(map_id)
        return document, target

    def reset_map_upload_failure(
        self,
        *,
        map_ref: str,
        editor_closed_confirmed: bool,
    ) -> DeploymentReceipt:
        if not editor_closed_confirmed:
            raise DeploymentError(
                "confirm that the editor is closed and the game is on the map list",
                code="EDITOR_NOT_CONFIRMED_CLOSED",
            )
        stored = self.store.resolve_map(map_ref)
        deployment_id = f"deployment_{uuid.uuid4().hex}"
        backup = self.store.backups / deployment_id
        work = self.store.work / deployment_id
        work.mkdir(mode=0o700)
        with self._lock(stored):
            device = self._resolve_writable(stored)
            first = read_remote_state(self.adb, device, stored.location)
            self._assert_fresh(stored, first)
            frozen: FrozenTriplet | None = None
            try:
                frozen = freeze_device_triplet(
                    self.adb, device, stored.location, backup
                )
                if frozen.state != first:
                    raise DeploymentError(
                        "map changed between reference check and backup",
                        code="CONCURRENT_SAVE",
                    )
                validate_snapshot_integrity(open_snapshot(backup / "map"))
                document = self._read_index(backup / "index.conf")
                rows = document.get("map_conf")
                if not isinstance(rows, dict) or stored.location.map_id not in rows:
                    raise StateError(
                        "target map is absent from the current index",
                        code="INDEX_INVALID",
                    )
                target = rows[stored.location.map_id]
                if (
                    not isinstance(target, dict)
                    or target.get("name") != stored.location.name
                ):
                    raise StateError(
                        "target map identity does not match the current index",
                        code="MAP_REF_INVALID",
                    )
                if target.get("del_time") not in (None, 0, "0", ""):
                    raise StateError(
                        "archived maps cannot reset upload failure state",
                        code="MAP_ARCHIVED",
                    )
                if target.get("map_upload_fail_tag") is not True:
                    raise StateError(
                        "map upload failure flag is not set",
                        code="UPLOAD_FAILURE_NOT_SET",
                    )
                target["map_upload_fail_tag"] = False
                output = work / "index.conf"
                output.write_text(
                    json.dumps(document, ensure_ascii=False, separators=(",", ":")),
                    encoding="utf-8",
                )
                old_other, old_target = self._index_without_target(
                    backup / "index.conf", stored.location.map_id
                )
                new_other, new_target = self._index_without_target(
                    output, stored.location.map_id
                )
                expected_target = dict(old_target)
                expected_target["map_upload_fail_tag"] = False
                if old_other != new_other or new_target != expected_target:
                    raise DeploymentError(
                        "upload failure reset changed fields outside its whitelist",
                        code="VALIDATION_FAILED",
                    )
                after, remote_rollback = self._deploy_index(
                    device=device,
                    location=stored.location,
                    frozen=frozen,
                    source=output,
                    deployment_id=deployment_id,
                )
                checks = (
                    "input-snapshot-integrity",
                    "target-index-only-semantic-diff",
                    "device-source-stability",
                    "device-stage-hash",
                    "permissions-restored",
                    "pid-unchanged",
                    "upload-failure-flag-false",
                )
                new_ref = self.store.register_map(
                    device, stored.location, after.revision
                )
                self.store.record_deployment(
                    operation="reset_upload_failure",
                    map_ref=new_ref,
                    backup_path=backup,
                    work_path=work,
                    input_revision=frozen.state.revision,
                    output_revision=after.revision,
                    changed_files=("index.conf",),
                    validation_checks=checks,
                    status="deployed",
                    remote_rollback=remote_rollback,
                    deployment_id=deployment_id,
                )
                return DeploymentReceipt(
                    deployment_id=deployment_id,
                    operation="reset_upload_failure",
                    map_ref=new_ref,
                    backup_id=backup.name,
                    input_revision=frozen.state.revision,
                    output_revision=after.revision,
                    changed_files=("index.conf",),
                    validation_checks=checks,
                    status="deployed",
                )
            except Exception as exc:
                if frozen is not None:
                    try:
                        self.store.record_deployment(
                            operation="reset_upload_failure",
                            map_ref=map_ref,
                            backup_path=backup,
                            work_path=work,
                            input_revision=frozen.state.revision,
                            output_revision=frozen.state.revision,
                            changed_files=(),
                            validation_checks=(),
                            status="failed",
                            remote_rollback=None,
                            deployment_id=deployment_id,
                            details={
                                "error_code": getattr(
                                    exc, "error_code", type(exc).__name__
                                )
                            },
                        )
                    except Exception as state_error:  # noqa: BLE001
                        exc.add_note(
                            "failed to persist failed deployment state: "
                            f"{type(state_error).__name__}"
                        )
                if isinstance(exc, EggyMapError):
                    exc.context.setdefault("deployment_id", deployment_id)
                    raise
                raise DeploymentError(
                    "unexpected upload failure reset error",
                    context={"deployment_id": deployment_id},
                ) from exc

    def rollback(
        self,
        *,
        deployment_id: str,
        editor_closed_confirmed: bool,
    ) -> tuple[DeploymentReceipt, str]:
        if not editor_closed_confirmed:
            raise DeploymentError(
                "confirm that the editor is closed and the game is on the map list",
                code="EDITOR_NOT_CONFIRMED_CLOSED",
            )
        deployed = self.store.get_deployment(deployment_id)
        if deployed.status != "deployed":
            raise StateError("only a deployed transaction can be rolled back")
        stored = self.store.resolve_map(deployed.map_ref)
        original = self._load_capture(deployed.backup_path)
        rollback_id = f"deployment_{uuid.uuid4().hex}"
        current_backup = self.store.backups / rollback_id
        work = self.store.work / rollback_id
        work.mkdir(mode=0o700)
        with self._lock(stored):
            device = self._resolve_writable(stored)
            self._assert_capture_identity(original, device, stored.location)
            current_state = read_remote_state(self.adb, device, stored.location)
            current = freeze_device_triplet(
                self.adb, device, stored.location, current_backup
            )
            old_other, old_target = self._index_without_target(
                deployed.backup_path / "index.conf", stored.location.map_id
            )
            new_other, new_target = self._index_without_target(
                current_backup / "index.conf", stored.location.map_id
            )
            if old_other != new_other or old_target.get("name") != new_target.get(
                "name"
            ):
                raise DeploymentError(
                    "index state outside the selected map changed; rollback is unsafe",
                    code="CONCURRENT_SAVE",
                )
            suffix = rollback_id.rsplit("_", 1)[-1][:16]
            stage_map = stored.location.map_directory + f".eggy-restore-stage-{suffix}"
            stage_archive = stored.location.archive_path + f".eggy-stage-{suffix}"
            stage_index = stored.location.index_path + f".eggy-stage-{suffix}"
            current_map = stored.location.map_directory + f".eggy-current-{suffix}"
            current_archive = stored.location.archive_path + f".eggy-current-{suffix}"
            current_index = stored.location.index_path + f".eggy-current-{suffix}"
            self._remote_absent(
                device,
                (
                    stage_map,
                    stage_archive,
                    stage_index,
                    current_map,
                    current_archive,
                    current_index,
                ),
            )
            permissions = original["permissions"]
            self._upload_map(
                device=device,
                location=stored.location,
                source=deployed.backup_path / "map",
                stage=stage_map,
                permissions=permissions,
            )
            for local_name, remote, original_path in (
                ("map.gmp", stage_archive, stored.location.archive_path),
                ("index.conf", stage_index, stored.location.index_path),
            ):
                self.adb.push(device.serial, deployed.backup_path / local_name, remote)
                metadata = permissions[original_path]
                self._root(
                    device,
                    f"chown {metadata['uid']}:{metadata['gid']} {shlex.quote(remote)} && "
                    f"chmod {int(metadata['mode']):o} {shlex.quote(remote)}",
                )
                remote_hash = self._root(
                    device, f"sha256sum {shlex.quote(remote)}"
                ).split(maxsplit=1)[0]
                if remote_hash != _sha256(deployed.backup_path / local_name):
                    raise DeploymentError(
                        "staged rollback triplet hash mismatch",
                        code="DEVICE_HASH_MISMATCH",
                    )
            if read_remote_state(self.adb, device, stored.location) != current_state:
                raise DeploymentError(
                    "map changed before rollback", code="CONCURRENT_SAVE"
                )
            moved: list[tuple[str, str]] = []
            pairs = (
                (stored.location.map_directory, current_map),
                (stored.location.archive_path, current_archive),
                (stored.location.index_path, current_index),
                (stage_map, stored.location.map_directory),
                (stage_archive, stored.location.archive_path),
                (stage_index, stored.location.index_path),
            )
            try:
                for source, target in pairs:
                    self._root(
                        device, f"mv {shlex.quote(source)} {shlex.quote(target)}"
                    )
                    moved.append((source, target))
            except EggyMapError as exc:
                for source, target in reversed(moved):
                    try:
                        exists = self._root(
                            device, f"test -e {shlex.quote(target)}; echo $?"
                        ).strip()
                        missing_source = self._root(
                            device, f"test ! -e {shlex.quote(source)}; echo $?"
                        ).strip()
                        if exists == "0" and missing_source == "0":
                            self._root(
                                device,
                                f"mv {shlex.quote(target)} {shlex.quote(source)}",
                            )
                    except EggyMapError:
                        pass
                raise DeploymentError(
                    "rollback swap failed", code="ROLLBACK_FAILED"
                ) from exc
            after = read_remote_state(self.adb, device, stored.location)
            expected_permissions = original.get("permissions")
            expected_directories = tuple(original.get("directories", ()))
            if (
                after.hashes != original["hashes"]
                or after.permissions != expected_permissions
                or after.directories != expected_directories
                or after.pid != current.state.pid
            ):
                try:
                    for restored, staged in (
                        (stored.location.map_directory, stage_map),
                        (stored.location.archive_path, stage_archive),
                        (stored.location.index_path, stage_index),
                    ):
                        self._root(
                            device,
                            f"mv {shlex.quote(restored)} {shlex.quote(staged)}",
                        )
                    for preserved, target in (
                        (current_map, stored.location.map_directory),
                        (current_archive, stored.location.archive_path),
                        (current_index, stored.location.index_path),
                    ):
                        self._root(
                            device,
                            f"mv {shlex.quote(preserved)} {shlex.quote(target)}",
                        )
                except EggyMapError as exc:
                    raise DeploymentError(
                        "rollback verification and automatic restoration both failed",
                        code="ROLLBACK_FAILED",
                    ) from exc
                if (
                    read_remote_state(self.adb, device, stored.location)
                    != current.state
                ):
                    raise DeploymentError(
                        "rollback verification failed and current state did not restore",
                        code="ROLLBACK_FAILED",
                    )
                raise DeploymentError(
                    "rollback verification failed; current state was restored",
                    code="ROLLBACK_FAILED",
                )
            checks = (
                "backup-double-hash",
                "non-target-index-invariant",
                "rollback-device-hashes",
                "rollback-permissions",
                "pid-unchanged",
            )
            new_ref = self.store.register_map(device, stored.location, after.revision)
            self.store.record_deployment(
                operation="rollback",
                map_ref=new_ref,
                backup_path=current_backup,
                work_path=work,
                input_revision=current.state.revision,
                output_revision=after.revision,
                changed_files=tuple(sorted(_tree_hashes(deployed.backup_path / "map"))),
                validation_checks=checks,
                status="rolled_back",
                remote_rollback=current_map,
                deployment_id=rollback_id,
                details={"restored_deployment_id": deployment_id},
            )
            self.store.update_deployment_status(deployment_id, "rolled_back")
            return (
                DeploymentReceipt(
                    deployment_id=rollback_id,
                    operation="rollback",
                    map_ref=new_ref,
                    backup_id=current_backup.name,
                    input_revision=current.state.revision,
                    output_revision=after.revision,
                    changed_files=tuple(
                        sorted(_tree_hashes(deployed.backup_path / "map"))
                    ),
                    validation_checks=checks,
                    status="rolled_back",
                ),
                current_map,
            )

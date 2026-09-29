from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .errors import DeviceError, SnapshotError
from .snapshot import open_snapshot

_PACKAGE = re.compile(r"^[A-Za-z0-9_.]+$")
_REMOTE = re.compile(r"^/[A-Za-z0-9_./=+:~-]+$")
_MAPS_SUFFIX = "/files/NeoX/Documents/etc/editor_maps"


def _strict_json_pairs(pairs: list[tuple[Any, Any]]) -> dict[Any, Any]:
    result: dict[Any, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DeviceError(
                "index contains a duplicate JSON key", code="INDEX_INVALID"
            )
        result[key] = value
    return result


@dataclass(frozen=True)
class DeviceContext:
    serial: str
    package: str
    maps_root: str
    version_code: int
    version_name: str
    apk_path: str
    apk_sha256: str | None
    pid: str
    root_available: bool
    profile_match: bool

    @property
    def writable(self) -> bool:
        return self.root_available and self.profile_match and bool(self.pid)


@dataclass(frozen=True)
class MapLocation:
    map_id: str
    name: str
    save_time: Any
    map_directory: str
    archive_path: str
    index_path: str


@dataclass(frozen=True)
class RemoteState:
    revision: str
    hashes: dict[str, str]
    permissions: dict[str, dict[str, Any]]
    directories: tuple[str, ...]
    pid: str


@dataclass(frozen=True)
class FrozenTriplet:
    root: Path
    map_location: MapLocation
    device: DeviceContext
    state: RemoteState
    local_hashes: dict[str, tuple[str, str]]


class AdbClient:
    def __init__(self, executable: str | Path | None = None) -> None:
        candidate = (
            str(executable) if executable is not None else os.getenv("EGGY_ADB_PATH")
        )
        resolved = shutil.which(candidate or "adb")
        if not resolved:
            raise DeviceError("adb executable is unavailable", code="ADB_NOT_FOUND")
        self.executable = resolved

    def run(
        self,
        *args: str,
        serial: str | None = None,
        timeout: int = 60,
        check: bool = True,
    ) -> bytes:
        command = [self.executable]
        if serial:
            command.extend(("-s", serial))
        command.extend(args)
        completed = subprocess.run(
            command, capture_output=True, check=False, timeout=timeout
        )
        if check and completed.returncode:
            message = completed.stderr.decode("utf-8", errors="replace").strip()
            raise DeviceError(
                message or f"adb command failed with code {completed.returncode}",
                code="ADB_COMMAND_FAILED",
            )
        return completed.stdout

    def shell(self, serial: str, command: str, *, root: bool = False) -> str:
        if root:
            identity = self.run("shell", "id -u", serial=serial).strip()
            if identity != b"0":
                command = "su 0 sh -c " + shlex.quote(command)
        return self.run("shell", command, serial=serial).decode(
            "utf-8", errors="strict"
        )

    def pull(self, serial: str, remote: str, local: Path) -> None:
        local.parent.mkdir(parents=True, exist_ok=True)
        self.run("pull", remote, str(local), serial=serial, timeout=120)

    def push(self, serial: str, local: Path, remote: str) -> None:
        self.run("push", str(local), remote, serial=serial, timeout=120)

    @staticmethod
    def validate_remote_path(path: str, *, minimum_parts: int = 5) -> str:
        pure = PurePosixPath(path)
        if (
            not pure.is_absolute()
            or len(pure.parts) < minimum_parts
            or ".." in pure.parts
            or str(pure) != path
            or not _REMOTE.fullmatch(path)
        ):
            raise DeviceError("unsafe or non-canonical remote path", code="UNSAFE_PATH")
        return path


def _device_serials(adb: AdbClient) -> list[str]:
    rows = adb.run("devices", "-l").decode("utf-8", errors="replace").splitlines()[1:]
    return [
        row.split()[0]
        for row in rows
        if len(row.split()) >= 2 and row.split()[1] == "device"
    ]


def discover_device(
    adb: AdbClient,
    *,
    game_profile: dict[str, Any],
    verify_apk: bool = True,
) -> DeviceContext:
    serials = _device_serials(adb)
    if len(serials) != 1:
        raise DeviceError(
            "exactly one online ADB device is required",
            code="DEVICE_NOT_UNIQUE",
            context={"device_count": len(serials)},
        )
    serial = serials[0]
    roots = [
        row.strip()
        for row in adb.shell(
            serial,
            "for d in /sdcard/Android/data/*/files/NeoX/Documents/etc/editor_maps; "
            'do [ -d "$d" ] && echo "$d"; done',
        ).splitlines()
        if row.strip()
    ]
    if len(roots) != 1:
        raise DeviceError(
            "exactly one editable-map package root is required",
            code="PACKAGE_NOT_UNIQUE",
            context={"candidate_count": len(roots)},
        )
    maps_root = AdbClient.validate_remote_path(roots[0])
    marker = "/Android/data/"
    if marker not in maps_root or not maps_root.endswith(_MAPS_SUFFIX):
        raise DeviceError("map root does not match the supported MuMu layout")
    package = maps_root.split(marker, 1)[1].split("/", 1)[0]
    if not _PACKAGE.fullmatch(package):
        raise DeviceError("discovered package name is invalid")
    dump = adb.shell(serial, f"dumpsys package {shlex.quote(package)}")
    version_code_match = re.search(r"\bversionCode=(\d+)", dump)
    version_name_match = re.search(r"\bversionName=([^\s]+)", dump)
    if not version_code_match or not version_name_match:
        raise DeviceError(
            "game package version is unavailable", code="PROFILE_MISMATCH"
        )
    version_code = int(version_code_match.group(1))
    version_name = version_name_match.group(1)
    package_paths = [
        row.removeprefix("package:").strip()
        for row in adb.shell(serial, f"pm path {shlex.quote(package)}").splitlines()
        if row.startswith("package:")
    ]
    base_paths = [path for path in package_paths if path.endswith("/base.apk")]
    if len(base_paths) != 1:
        raise DeviceError(
            "unique base.apk path is unavailable", code="PROFILE_MISMATCH"
        )
    apk_path = AdbClient.validate_remote_path(base_paths[0])
    root_available = False
    try:
        root_available = adb.shell(serial, "id -u", root=True).strip() == "0"
    except DeviceError:
        root_available = False
    apk_sha256: str | None = None
    if verify_apk and root_available:
        row = adb.shell(serial, f"sha256sum {shlex.quote(apk_path)}", root=True).strip()
        digest = row.split(maxsplit=1)[0] if row else ""
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise DeviceError(
                "base.apk SHA-256 is unavailable", code="PROFILE_MISMATCH"
            )
        apk_sha256 = digest
    pid = adb.shell(serial, f"pidof {shlex.quote(package)}").strip()
    expected_hash = game_profile.get("apk_sha256")
    profile_match = (
        version_code == int(game_profile.get("version_code", -1))
        and version_name == str(game_profile.get("version_name", ""))
        and (not verify_apk or apk_sha256 == expected_hash)
    )
    return DeviceContext(
        serial=serial,
        package=package,
        maps_root=maps_root,
        version_code=version_code,
        version_name=version_name,
        apk_path=apk_path,
        apk_sha256=apk_sha256,
        pid=pid,
        root_available=root_available,
        profile_match=profile_match,
    )


def list_device_maps(
    adb: AdbClient,
    device: DeviceContext,
    *,
    exact_name: str | None = None,
    include_archived: bool = False,
) -> list[MapLocation]:
    root = shlex.quote(device.maps_root)
    conf_paths = sorted(
        row.strip()
        for row in adb.shell(
            device.serial,
            f'find {root} -maxdepth 1 -type f -name "*.conf" -print',
            root=True,
        ).splitlines()
        if row.strip()
    )
    if not conf_paths:
        raise DeviceError("no editable-map index was found", code="INDEX_INVALID")
    result: list[MapLocation] = []
    seen: set[tuple[str, str]] = set()
    for conf_path in conf_paths:
        AdbClient.validate_remote_path(conf_path)
        raw = adb.run("exec-out", "cat", conf_path, serial=device.serial)
        try:
            document = json.loads(raw, object_pairs_hook=_strict_json_pairs)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DeviceError(
                "editable-map index is invalid JSON", code="INDEX_INVALID"
            ) from exc
        rows = document.get("map_conf") if isinstance(document, dict) else None
        if not isinstance(rows, dict):
            raise DeviceError(
                "editable-map index has no map_conf object", code="INDEX_INVALID"
            )
        for map_id, entry in rows.items():
            if not isinstance(map_id, str) or not isinstance(entry, dict):
                raise DeviceError(
                    "editable-map index entry is malformed", code="INDEX_INVALID"
                )
            name = entry.get("name")
            if not isinstance(name, str) or not name:
                raise DeviceError(
                    "editable-map index name is malformed", code="INDEX_INVALID"
                )
            if exact_name is not None and name != exact_name:
                continue
            if not include_archived and entry.get("del_time") not in (None, 0, "0", ""):
                continue
            map_directory = AdbClient.validate_remote_path(
                f"{device.maps_root}/{map_id}"
            )
            archive = AdbClient.validate_remote_path(map_directory + ".gmp")
            identity = (map_id, conf_path)
            if identity in seen:
                continue
            exists = adb.shell(
                device.serial,
                f"test -d {shlex.quote(map_directory)} -a -f {shlex.quote(archive)}; echo $?",
                root=True,
            ).strip()
            if exists != "0":
                continue
            seen.add(identity)
            result.append(
                MapLocation(
                    map_id=map_id,
                    name=name,
                    save_time=entry.get("save_time"),
                    map_directory=map_directory,
                    archive_path=archive,
                    index_path=conf_path,
                )
            )
    return result


def _parse_hashes(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for row in text.splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})\s+(.+)", row)
        if not match or match.group(2) in result:
            raise SnapshotError("device hash inventory is malformed")
        result[match.group(2)] = match.group(1)
    return result


def _parse_permissions(text: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in text.splitlines():
        fields = row.split("|", 4)
        if len(fields) != 5:
            raise SnapshotError("device permission inventory is malformed")
        kind, uid, gid, mode, path = fields
        if (
            kind not in {"directory", "regular file", "regular empty file"}
            or not uid.isdecimal()
            or not gid.isdecimal()
            or not re.fullmatch(r"[0-7]{3,4}", mode)
            or path in result
        ):
            raise SnapshotError("device permission row is invalid")
        result[path] = {
            "type": kind,
            "uid": int(uid),
            "gid": int(gid),
            "mode": int(mode, 8),
        }
    return result


def read_remote_state(
    adb: AdbClient, device: DeviceContext, location: MapLocation
) -> RemoteState:
    quoted_map = shlex.quote(location.map_directory)
    outer = " ".join(
        shlex.quote(path) for path in (location.archive_path, location.index_path)
    )
    hashes = _parse_hashes(
        adb.shell(
            device.serial,
            f"find {quoted_map} -type f -exec sha256sum {{}} \\; && sha256sum {outer}",
            root=True,
        )
    )
    permissions = _parse_permissions(
        adb.shell(
            device.serial,
            f"find {quoted_map} -exec stat -c '%F|%u|%g|%a|%n' {{}} \\; "
            f"&& stat -c '%F|%u|%g|%a|%n' {outer}",
            root=True,
        )
    )
    directories = tuple(
        sorted(
            row.strip()
            for row in adb.shell(
                device.serial, f"find {quoted_map} -type d -print", root=True
            ).splitlines()
            if row.strip()
        )
    )
    pid = adb.shell(device.serial, f"pidof {shlex.quote(device.package)}").strip()
    payload = json.dumps(sorted(hashes.items()), separators=(",", ":")).encode()
    revision = hashlib.sha256(payload).hexdigest()
    return RemoteState(revision, hashes, permissions, directories, pid)


def _local_key(location: MapLocation, remote: str) -> str:
    root = PurePosixPath(location.map_directory)
    path = PurePosixPath(remote)
    if remote == location.archive_path:
        return "map.gmp"
    if remote == location.index_path:
        return "index.conf"
    if root in path.parents:
        return "map/" + path.relative_to(root).as_posix()
    raise SnapshotError("device file lies outside the selected map triplet")


def freeze_device_triplet(
    adb: AdbClient,
    device: DeviceContext,
    location: MapLocation,
    output: str | Path,
) -> FrozenTriplet:
    destination = Path(output).expanduser().resolve()
    if destination.exists():
        raise SnapshotError(f"capture output already exists: {destination}")
    destination.mkdir(parents=True, mode=0o700)
    first = read_remote_state(adb, device, location)
    if first.pid != device.pid or not first.pid:
        raise SnapshotError(
            "game process changed before capture", code="CONCURRENT_SAVE"
        )
    try:
        for remote in sorted(first.hashes):
            local = destination / _local_key(location, remote)
            adb.pull(device.serial, remote, local)
        second = read_remote_state(adb, device, location)
        if first != second:
            raise SnapshotError("map changed during capture", code="CONCURRENT_SAVE")
        snapshot = open_snapshot(destination / "map")
        local_hashes: dict[str, tuple[str, str]] = {}
        for path in sorted(destination.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(destination).as_posix()
            raw = path.read_bytes()
            local_hashes[relative] = (
                hashlib.sha256(raw).hexdigest(),
                hashlib.blake2b(raw).hexdigest(),
            )
        expected = {
            _local_key(location, remote): digest
            for remote, digest in first.hashes.items()
        }
        if {key: value[0] for key, value in local_hashes.items()} != expected:
            raise SnapshotError("local capture differs from the device hash inventory")
        if set(snapshot.files) != {
            key.removeprefix("map/") for key in expected if key.startswith("map/")
        }:
            raise SnapshotError("editable map inventory differs after strict decoding")
        capture = {
            "schema_version": 1,
            "device": {
                "serial": device.serial,
                "package": device.package,
                "maps_root": device.maps_root,
                "version_code": device.version_code,
                "version_name": device.version_name,
                "pid": device.pid,
            },
            "map": {
                "map_id": location.map_id,
                "name": location.name,
                "save_time": location.save_time,
                "map_directory": location.map_directory,
                "archive_path": location.archive_path,
                "index_path": location.index_path,
            },
            "revision": first.revision,
            "hashes": first.hashes,
            "local_hashes": {
                key: {"sha256": value[0], "blake2b": value[1]}
                for key, value in local_hashes.items()
            },
            "permissions": first.permissions,
            "directories": list(first.directories),
            "capture_complete": True,
        }
        (destination / "capture.json").write_text(
            json.dumps(capture, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return FrozenTriplet(destination, location, device, first, local_hashes)
    except Exception:
        (destination / "INCOMPLETE").write_text("capture failed\n", encoding="utf-8")
        raise

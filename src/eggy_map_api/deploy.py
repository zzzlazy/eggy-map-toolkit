from __future__ import annotations

import hashlib
import json
import re
import shlex
import subprocess

from .errors import DeploymentError
from .models import ApplyResult, DeploymentTarget


def _adb(
    serial: str, *args: str, input_bytes: bytes | None = None
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["adb", "-s", serial, *args],
        input=input_bytes,
        capture_output=True,
        check=False,
    )


def _root_shell(serial: str, *args: str) -> subprocess.CompletedProcess[bytes]:
    identity = _adb(serial, "shell", "id", "-u")
    if identity.returncode == 0 and identity.stdout.strip() == b"0":
        return _adb(serial, "shell", *args)
    command = shlex.join(args)
    return _adb(serial, "shell", "su 0 sh -c " + shlex.quote(command))


def deploy(result: ApplyResult, *, target: DeploymentTarget) -> None:
    if not result.plan.deployable:
        raise DeploymentError("refusing to deploy a blocked plan")
    if not target.backup_directory.is_dir():
        raise DeploymentError(
            "verified local backup directory is required before deployment"
        )
    if not target.atomic_swap_complete or not target.remote_rollback_directory:
        raise DeploymentError(
            "matched atomic directory-swap profile and remote rollback path are required"
        )
    safe_remote = re.compile(r"^/[A-Za-z0-9_./=+:-]+$")
    for path in (target.map_directory, target.remote_rollback_directory):
        if not safe_remote.fullmatch(path):
            raise DeploymentError(f"unsafe remote path: {path!r}")
    if target.remote_rollback_directory == target.map_directory:
        raise DeploymentError("rollback and target directories must differ")
    state = _adb(target.serial, "get-state")
    if state.returncode or state.stdout.strip() != b"device":
        raise DeploymentError("target ADB device is not online")
    remote_stage = target.map_directory + ".codex-stage"
    for path in (remote_stage, target.remote_rollback_directory):
        probe = _adb(target.serial, "shell", "test", "!", "-e", path)
        if probe.returncode:
            raise DeploymentError(f"remote deployment path already exists: {path}")
    mkdir = _adb(target.serial, "shell", "mkdir", "-p", remote_stage)
    if mkdir.returncode:
        raise DeploymentError(mkdir.stderr.decode(errors="replace"))
    for relative in sorted(result.hashes):
        local = result.output / relative
        remote = remote_stage + "/" + relative
        parent = remote.rsplit("/", 1)[0]
        if _adb(target.serial, "shell", "mkdir", "-p", parent).returncode:
            raise DeploymentError(f"failed to create remote directory for {relative}")
        pushed = _adb(target.serial, "push", str(local), remote)
        if pushed.returncode:
            raise DeploymentError(
                f"failed to push {relative}: {pushed.stderr.decode(errors='replace')}"
            )
        mode = target.file_modes.get(relative, 0o600)
        if _root_shell(target.serial, "chmod", f"{mode:o}", remote).returncode:
            raise DeploymentError(f"failed to restore mode for {relative}")
        if _root_shell(
            target.serial, "chown", f"{target.uid}:{target.gid}", remote
        ).returncode:
            raise DeploymentError(f"failed to restore ownership for {relative}")
        digest = _root_shell(target.serial, "sha256sum", remote)
        if (
            digest.returncode
            or digest.stdout.split(maxsplit=1)[0].decode() != result.hashes[relative][0]
        ):
            raise DeploymentError(f"remote hash mismatch for {relative}")
    marker = {
        "profile": result.plan.profile_fingerprint,
        "output_sha256": hashlib.sha256(
            json.dumps(result.hashes, sort_keys=True).encode()
        ).hexdigest(),
    }
    if _root_shell(
        target.serial, "chmod", f"{target.directory_mode:o}", remote_stage
    ).returncode:
        raise DeploymentError("failed to restore staging-directory mode")
    if _root_shell(
        target.serial, "chown", f"{target.uid}:{target.gid}", remote_stage
    ).returncode:
        raise DeploymentError("failed to restore staging-directory ownership")
    moved_old = _root_shell(
        target.serial,
        "mv",
        target.map_directory,
        target.remote_rollback_directory,
    )
    if moved_old.returncode:
        raise DeploymentError(
            f"failed to move target to rollback path; stage retained; marker {marker['output_sha256']}"
        )
    moved_new = _root_shell(target.serial, "mv", remote_stage, target.map_directory)
    if moved_new.returncode:
        restored = _root_shell(
            target.serial,
            "mv",
            target.remote_rollback_directory,
            target.map_directory,
        )
        if restored.returncode:
            raise DeploymentError(
                "atomic swap failed and automatic restoration also failed"
            )
        raise DeploymentError("atomic swap failed; original target was restored")
    mismatches: list[str] = []
    for relative, expected in sorted(result.hashes.items()):
        remote = target.map_directory + "/" + relative
        digest = _root_shell(target.serial, "sha256sum", remote)
        if (
            digest.returncode
            or digest.stdout.split(maxsplit=1)[0].decode(errors="replace")
            != expected[0]
        ):
            mismatches.append(relative)
    if mismatches:
        failed_output = target.map_directory + ".codex-failed"
        moved_failed = _root_shell(
            target.serial, "mv", target.map_directory, failed_output
        )
        restored = _root_shell(
            target.serial,
            "mv",
            target.remote_rollback_directory,
            target.map_directory,
        )
        if moved_failed.returncode or restored.returncode:
            raise DeploymentError(
                "post-swap hash verification failed and automatic restoration was incomplete"
            )
        raise DeploymentError(
            "post-swap hash verification failed; original target was restored: "
            + ", ".join(mismatches[:8])
        )

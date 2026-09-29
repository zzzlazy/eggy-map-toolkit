from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from .codec import decode_mm
from .errors import SnapshotError
from .models import FileRecord, MapSnapshot

REQUIRED_EDITABLE_FILES = frozenset(
    {"header.map", "unit.mm", "desc.mm", "uniteditor.mm"}
)


def _digest(raw: bytes) -> tuple[str, str]:
    return hashlib.sha256(raw).hexdigest(), hashlib.blake2b(raw).hexdigest()


def open_snapshot(path: str | Path) -> MapSnapshot:
    root = Path(path).expanduser().resolve()
    if not root.is_dir():
        raise SnapshotError(f"editable map directory does not exist: {root}")
    names = {p.name for p in root.iterdir() if p.is_file()}
    missing = sorted(REQUIRED_EDITABLE_FILES - names)
    if missing:
        raise SnapshotError(f"incomplete editable map directory; missing {missing}")
    files: dict[str, FileRecord] = {}
    fingerprint_rows: list[dict[str, object]] = []
    for item in sorted(root.rglob("*")):
        if not item.is_file():
            continue
        relative = item.relative_to(root).as_posix()
        raw = item.read_bytes()
        stat = item.stat()
        sha256, blake2b = _digest(raw)
        decoded = decode_mm(raw) if item.suffix == ".mm" else None
        files[relative] = FileRecord(
            relative_path=relative,
            size=len(raw),
            sha256=sha256,
            blake2b=blake2b,
            mode=stat.st_mode & 0o7777,
            uid=stat.st_uid,
            gid=stat.st_gid,
            raw=raw,
            decoded=decoded,
        )
        fingerprint_rows.append(
            {
                "path": relative,
                "kind": "mm" if item.suffix == ".mm" else item.suffix,
                "decoded_type": type(decoded).__name__ if decoded is not None else None,
            }
        )
    fingerprint = hashlib.sha256(
        json.dumps(fingerprint_rows, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()
    return MapSnapshot(root=root, files=files, format_fingerprint=fingerprint)


def freeze_snapshot(snapshot: MapSnapshot, output: str | Path) -> Path:
    """Write an immutable local evidence copy without changing source metadata."""
    destination = Path(output).expanduser().resolve()
    if destination.exists():
        raise SnapshotError(f"freeze output already exists: {destination}")
    destination.mkdir(parents=True, mode=0o700)
    for relative, record in snapshot.files.items():
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(record.raw)
        os.chmod(target, record.mode)
    manifest = {
        "format_fingerprint": snapshot.format_fingerprint,
        "files": {
            name: {
                "size": rec.size,
                "sha256": rec.sha256,
                "blake2b": rec.blake2b,
                "mode": rec.mode,
                "uid": rec.uid,
                "gid": rec.gid,
            }
            for name, rec in snapshot.files.items()
        },
    }
    (destination / "snapshot-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return destination

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .device import DeviceContext, MapLocation
from .errors import StateError


@dataclass(frozen=True)
class StoredMapRef:
    map_ref: str
    serial: str
    package: str
    maps_root: str
    location: MapLocation
    revision: str
    version_code: int
    version_name: str


@dataclass(frozen=True)
class StoredUnitRef:
    unit_ref: str
    map_ref: str
    unit_id: int
    revision: str


@dataclass(frozen=True)
class StoredDeployment:
    deployment_id: str
    operation: str
    map_ref: str
    backup_id: str
    backup_path: Path
    work_path: Path
    input_revision: str
    output_revision: str
    changed_files: tuple[str, ...]
    validation_checks: tuple[str, ...]
    status: str
    remote_rollback: str | None
    details: dict[str, Any]


class StateStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.backups = self.root / "backups"
        self.work = self.root / "work"
        self.catalog = self.root / "catalog"
        for directory in (self.backups, self.work, self.catalog):
            directory.mkdir(exist_ok=True, mode=0o700)
        self.database = self.root / "state.sqlite3"
        with self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS map_refs (
                    map_ref TEXT PRIMARY KEY,
                    serial TEXT NOT NULL,
                    package TEXT NOT NULL,
                    maps_root TEXT NOT NULL,
                    map_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    save_time_json TEXT NOT NULL,
                    map_directory TEXT NOT NULL,
                    archive_path TEXT NOT NULL,
                    index_path TEXT NOT NULL,
                    revision TEXT NOT NULL,
                    version_code INTEGER NOT NULL,
                    version_name TEXT NOT NULL,
                    created REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS unit_refs (
                    unit_ref TEXT PRIMARY KEY,
                    map_ref TEXT NOT NULL REFERENCES map_refs(map_ref),
                    unit_id INTEGER NOT NULL,
                    revision TEXT NOT NULL,
                    created REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS deployments (
                    deployment_id TEXT PRIMARY KEY,
                    operation TEXT NOT NULL,
                    map_ref TEXT NOT NULL,
                    backup_id TEXT NOT NULL,
                    backup_path TEXT NOT NULL,
                    work_path TEXT NOT NULL,
                    input_revision TEXT NOT NULL,
                    output_revision TEXT NOT NULL,
                    changed_files_json TEXT NOT NULL,
                    validation_checks_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    remote_rollback TEXT,
                    details_json TEXT NOT NULL,
                    created REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS deployments_map_ref
                    ON deployments(map_ref, created DESC);
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _token(prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex}"

    def register_map(
        self, device: DeviceContext, location: MapLocation, revision: str
    ) -> str:
        map_ref = self._token("map")
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO map_refs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    map_ref,
                    device.serial,
                    device.package,
                    device.maps_root,
                    location.map_id,
                    location.name,
                    json.dumps(location.save_time, ensure_ascii=False),
                    location.map_directory,
                    location.archive_path,
                    location.index_path,
                    revision,
                    device.version_code,
                    device.version_name,
                    time.time(),
                ),
            )
        return map_ref

    def resolve_map(self, map_ref: str) -> StoredMapRef:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM map_refs WHERE map_ref=?", (map_ref,)
            ).fetchone()
        if row is None:
            raise StateError("map_ref is unknown", code="MAP_REF_INVALID")
        return StoredMapRef(
            map_ref=row["map_ref"],
            serial=row["serial"],
            package=row["package"],
            maps_root=row["maps_root"],
            location=MapLocation(
                map_id=row["map_id"],
                name=row["name"],
                save_time=json.loads(row["save_time_json"]),
                map_directory=row["map_directory"],
                archive_path=row["archive_path"],
                index_path=row["index_path"],
            ),
            revision=row["revision"],
            version_code=row["version_code"],
            version_name=row["version_name"],
        )

    def register_unit(self, map_ref: str, unit_id: int, revision: str) -> str:
        unit_ref = self._token("unit")
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO unit_refs VALUES(?,?,?,?,?)",
                (unit_ref, map_ref, unit_id, revision, time.time()),
            )
        return unit_ref

    def resolve_unit(self, unit_ref: str, *, map_ref: str) -> StoredUnitRef:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM unit_refs WHERE unit_ref=?", (unit_ref,)
            ).fetchone()
        if row is None or row["map_ref"] != map_ref:
            raise StateError(
                "unit_ref is unknown for this map", code="UNIT_REF_INVALID"
            )
        return StoredUnitRef(
            unit_ref=row["unit_ref"],
            map_ref=row["map_ref"],
            unit_id=row["unit_id"],
            revision=row["revision"],
        )

    def record_deployment(
        self,
        *,
        operation: str,
        map_ref: str,
        backup_path: Path,
        work_path: Path,
        input_revision: str,
        output_revision: str,
        changed_files: tuple[str, ...],
        validation_checks: tuple[str, ...],
        status: str,
        remote_rollback: str | None,
        details: dict[str, Any] | None = None,
        deployment_id: str | None = None,
        backup_id: str | None = None,
    ) -> str:
        deployment_id = deployment_id or self._token("deployment")
        backup_id = backup_id or backup_path.name
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO deployments VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    deployment_id,
                    operation,
                    map_ref,
                    backup_id,
                    str(backup_path),
                    str(work_path),
                    input_revision,
                    output_revision,
                    json.dumps(changed_files),
                    json.dumps(validation_checks),
                    status,
                    remote_rollback,
                    json.dumps(details or {}, ensure_ascii=False, sort_keys=True),
                    time.time(),
                ),
            )
        return deployment_id

    @staticmethod
    def _deployment(row: sqlite3.Row) -> StoredDeployment:
        return StoredDeployment(
            deployment_id=row["deployment_id"],
            operation=row["operation"],
            map_ref=row["map_ref"],
            backup_id=row["backup_id"],
            backup_path=Path(row["backup_path"]),
            work_path=Path(row["work_path"]),
            input_revision=row["input_revision"],
            output_revision=row["output_revision"],
            changed_files=tuple(json.loads(row["changed_files_json"])),
            validation_checks=tuple(json.loads(row["validation_checks_json"])),
            status=row["status"],
            remote_rollback=row["remote_rollback"],
            details=json.loads(row["details_json"]),
        )

    def get_deployment(self, deployment_id: str) -> StoredDeployment:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM deployments WHERE deployment_id=?", (deployment_id,)
            ).fetchone()
        if row is None:
            raise StateError("deployment_id is unknown", code="DEPLOYMENT_NOT_FOUND")
        return self._deployment(row)

    def list_deployments(self, map_ref: str | None = None) -> list[StoredDeployment]:
        with self._connect() as connection:
            if map_ref:
                rows = connection.execute(
                    "SELECT * FROM deployments WHERE map_ref=? ORDER BY created DESC",
                    (map_ref,),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM deployments ORDER BY created DESC LIMIT 100"
                ).fetchall()
        return [self._deployment(row) for row in rows]

    def update_deployment_status(self, deployment_id: str, status: str) -> None:
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE deployments SET status=? WHERE deployment_id=?",
                (status, deployment_id),
            )
            if cursor.rowcount != 1:
                raise StateError(
                    "deployment_id is unknown", code="DEPLOYMENT_NOT_FOUND"
                )

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import json
import os
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

import msgpack
import zstandard

from .capabilities import runtime_component_capability
from .catalog import open_package_catalog
from .errors import CatalogError
from .models import CatalogEntry, PackageCatalog

SCHEMA_VERSION = 1


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _pack(value: Any) -> bytes:
    return msgpack.packb(value, use_bin_type=True)


def _unpack(value: bytes) -> Any:
    return msgpack.unpackb(value, raw=False, strict_map_key=False)


def _component_ref(fingerprint: str, kind: str, eid: int) -> str:
    return f"component:{fingerprint[:16]}:{kind}:{eid}"


def build_catalog_bundle(
    *,
    catalog_directory: str | Path,
    decoded_bindicts: str | Path,
    output: str | Path,
    version_code: int,
    version_name: str,
    apk_sha256: str,
) -> Path:
    source = Path(catalog_directory).expanduser().resolve()
    decoded = Path(decoded_bindicts).expanduser().resolve()
    destination = Path(output).expanduser().resolve()
    if destination.exists():
        raise CatalogError(f"catalog bundle output already exists: {destination}")
    if version_code <= 0 or not version_name:
        raise CatalogError(
            "a positive version code and non-empty version name are required"
        )
    if len(apk_sha256) != 64 or any(ch not in "0123456789abcdef" for ch in apk_sha256):
        raise CatalogError("apk_sha256 must be a lower-case SHA-256 digest")
    catalog = open_package_catalog(source, decoded_bindicts=decoded)
    effect_path = source / "effect-components.csv"
    if not effect_path.is_file():
        raise CatalogError("effect-components.csv is required")

    destination.mkdir(parents=True, mode=0o700)
    database = destination / "catalog.sqlite3"
    connection = sqlite3.connect(database)
    connection.executescript(
        """
        PRAGMA journal_mode=OFF;
        PRAGMA synchronous=OFF;
        PRAGMA temp_store=MEMORY;
        CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE components (
            component_ref TEXT PRIMARY KEY,
            kind TEXT NOT NULL CHECK(kind IN ('unit','effect')),
            eid INTEGER NOT NULL,
            name TEXT NOT NULL,
            structural_family TEXT NOT NULL,
            asset_type TEXT NOT NULL,
            model_id INTEGER,
            model_path TEXT,
            property_keys_json TEXT NOT NULL,
            static_status TEXT NOT NULL,
            evidence TEXT NOT NULL,
            writable INTEGER NOT NULL CHECK(writable IN (0,1)),
            write_blockers_json TEXT NOT NULL,
            supported_properties_json TEXT NOT NULL,
            color_supported INTEGER NOT NULL CHECK(color_supported IN (0,1))
        );
        CREATE UNIQUE INDEX components_kind_eid ON components(kind, eid);
        CREATE INDEX components_name ON components(name);
        CREATE INDEX components_family ON components(structural_family);
        CREATE INDEX components_status ON components(static_status, writable);
        CREATE TABLE prefabs (
            component_ref TEXT PRIMARY KEY REFERENCES components(component_ref),
            payload BLOB NOT NULL
        );
        CREATE TABLE models (
            model_id INTEGER PRIMARY KEY,
            payload BLOB NOT NULL,
            model_cell_json TEXT NOT NULL
        );
        """
    )
    connection.executemany(
        "INSERT INTO metadata(key,value) VALUES(?,?)",
        (
            ("schema_version", str(SCHEMA_VERSION)),
            ("catalog_fingerprint", catalog.fingerprint),
            ("version_code", str(version_code)),
            ("version_name", version_name),
            ("apk_sha256", apk_sha256),
        ),
    )

    writable_refs: list[tuple[str, int]] = []
    component_rows: list[tuple[Any, ...]] = []
    for eid, entry in sorted(catalog.entries.items()):
        capability = runtime_component_capability(catalog, eid)
        ref = _component_ref(catalog.fingerprint, "unit", eid)
        component_rows.append(
            (
                ref,
                "unit",
                eid,
                entry.name,
                entry.structural_family,
                entry.asset_type,
                entry.model_id,
                entry.model_path,
                _json(entry.property_keys),
                entry.static_status,
                entry.evidence,
                int(capability.writable),
                _json(capability.blockers),
                _json(capability.supported_properties),
                int(capability.color_supported),
            )
        )
        if capability.writable:
            writable_refs.append((ref, eid))

    with effect_path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            try:
                eid = int(row["effect_eid"])
            except (KeyError, TypeError, ValueError) as exc:
                raise CatalogError("invalid effect_eid in effect catalog") from exc
            model_id_text = (row.get("model_id") or "").strip()
            component_rows.append(
                (
                    _component_ref(catalog.fingerprint, "effect", eid),
                    "effect",
                    eid,
                    row.get("effect_name") or "",
                    "effect",
                    row.get("effect_type") or "effect",
                    int(model_id_text) if model_id_text else None,
                    row.get("effect_path") or None,
                    "[]",
                    row.get("static_filter_status") or "",
                    row.get("evidence_scope") or "package-static-declared",
                    0,
                    _json(("effects have no runtime unit builder",)),
                    "[]",
                    0,
                )
            )
    connection.executemany(
        "INSERT INTO components VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        component_rows,
    )
    used_models: set[int] = set()
    for ref, eid in writable_refs:
        connection.execute(
            "INSERT INTO prefabs(component_ref,payload) VALUES(?,?)",
            (ref, sqlite3.Binary(_pack(catalog.prefab_defaults[eid]))),
        )
        model_id = catalog.entries[eid].model_id
        if model_id is not None:
            used_models.add(model_id)
    for model_id in sorted(used_models):
        cell = catalog.entries[
            next(
                eid
                for _, eid in writable_refs
                if catalog.entries[eid].model_id == model_id
            )
        ].model_cell
        connection.execute(
            "INSERT INTO models(model_id,payload,model_cell_json) VALUES(?,?,?)",
            (
                model_id,
                sqlite3.Binary(_pack(catalog.model_defaults[model_id])),
                _json(cell),
            ),
        )
    connection.commit()
    connection.execute("VACUUM")
    connection.close()

    database_sha256 = _sha256(database)
    compressed = destination / "catalog.sqlite3.zst"
    with database.open("rb") as source_handle, compressed.open("wb") as target_handle:
        compressor = zstandard.ZstdCompressor(level=19)
        compressor.copy_stream(source_handle, target_handle)
    compressed_sha256 = _sha256(compressed)
    database.unlink()
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "catalog_fingerprint": catalog.fingerprint,
        "database": {
            "file": compressed.name,
            "compression": "zstd",
            "sha256": compressed_sha256,
            "uncompressed_sha256": database_sha256,
        },
        "game_profile": {
            "version_code": version_code,
            "version_name": version_name,
            "apk_sha256": apk_sha256,
        },
        "counts": {
            "components": len(component_rows),
            "units": len(catalog.entries),
            "effects": len(component_rows) - len(catalog.entries),
            "writable_units": len(writable_refs),
        },
    }
    (destination / "catalog-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return destination


class CompiledCatalog:
    def __init__(
        self, manifest_path: str | Path, *, data_directory: str | Path
    ) -> None:
        self.manifest_path = Path(manifest_path).expanduser().resolve()
        self.data_directory = Path(data_directory).expanduser().resolve()
        try:
            self.manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CatalogError("cannot read compiled catalog manifest") from exc
        if self.manifest.get("schema_version") != SCHEMA_VERSION:
            raise CatalogError("unsupported compiled catalog schema")
        database_info = self.manifest.get("database")
        if not isinstance(database_info, dict):
            raise CatalogError("compiled catalog has no database descriptor")
        compressed = self.manifest_path.parent / str(database_info.get("file"))
        if not compressed.is_file() or _sha256(compressed) != database_info.get(
            "sha256"
        ):
            raise CatalogError("compiled catalog compressed hash mismatch")
        self.data_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        fingerprint = str(self.manifest["catalog_fingerprint"])
        self.database = self.data_directory / f"catalog-{fingerprint[:24]}.sqlite3"
        if not self.database.is_file() or _sha256(self.database) != database_info.get(
            "uncompressed_sha256"
        ):
            fd, temporary_name = tempfile.mkstemp(
                prefix="catalog-", suffix=".sqlite3.tmp", dir=self.data_directory
            )
            os.close(fd)
            temporary = Path(temporary_name)
            try:
                with compressed.open("rb") as source, temporary.open("wb") as target:
                    zstandard.ZstdDecompressor().copy_stream(source, target)
                if _sha256(temporary) != database_info.get("uncompressed_sha256"):
                    raise CatalogError("compiled catalog database hash mismatch")
                os.chmod(temporary, 0o600)
                os.replace(temporary, self.database)
            finally:
                temporary.unlink(missing_ok=True)
        self.fingerprint = fingerprint

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            f"file:{self.database.as_posix()}?mode=ro&immutable=1", uri=True
        )
        connection.row_factory = sqlite3.Row
        return connection

    @property
    def game_profile(self) -> dict[str, Any]:
        return dict(self.manifest["game_profile"])

    @property
    def counts(self) -> dict[str, int]:
        return {key: int(value) for key, value in self.manifest["counts"].items()}

    def _encode_cursor(self, offset: int) -> str:
        raw = _json({"f": self.fingerprint[:16], "o": offset}).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    def _decode_cursor(self, cursor: str | None) -> int:
        if not cursor:
            return 0
        try:
            raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
            payload = json.loads(raw)
            if payload != {"f": self.fingerprint[:16], "o": payload.get("o")}:
                raise ValueError
            offset = payload["o"]
            if type(offset) is not int or offset < 0:
                raise ValueError
            return offset
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            raise CatalogError("invalid component-search cursor") from exc

    @staticmethod
    def _row_payload(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "component_ref": row["component_ref"],
            "kind": row["kind"],
            "eid": row["eid"],
            "name": row["name"],
            "structural_family": row["structural_family"],
            "asset_type": row["asset_type"],
            "model_id": row["model_id"],
            "model_path": row["model_path"],
            "property_keys": json.loads(row["property_keys_json"]),
            "static_status": row["static_status"],
            "evidence": row["evidence"],
            "evidence_level": "static-derived",
            "write_capability": {
                "writable": bool(row["writable"]),
                "blockers": json.loads(row["write_blockers_json"]),
                "supported_properties": json.loads(row["supported_properties_json"]),
                "color_supported": bool(row["color_supported"]),
            },
        }

    def search(
        self,
        query: str = "",
        *,
        kind: str | None = None,
        family: str | None = None,
        static_status: str | None = None,
        writable_only: bool = False,
        limit: int = 50,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        if not 1 <= limit <= 200:
            raise CatalogError("search limit must be in 1..200")
        if kind not in {None, "unit", "effect"}:
            raise CatalogError("kind must be unit or effect")
        offset = self._decode_cursor(cursor)
        clauses = ["1=1"]
        params: list[Any] = []
        if query:
            clauses.append("(name LIKE ? OR CAST(eid AS TEXT)=? OR model_path LIKE ?)")
            token = f"%{query}%"
            params.extend((token, query, token))
        if kind:
            clauses.append("kind=?")
            params.append(kind)
        if family:
            clauses.append("structural_family=?")
            params.append(family)
        if static_status:
            clauses.append("static_status=?")
            params.append(static_status)
        if writable_only:
            clauses.append("writable=1")
        where = " AND ".join(clauses)
        with self._connect() as connection:
            total = connection.execute(
                f"SELECT COUNT(*) FROM components WHERE {where}", params
            ).fetchone()[0]
            rows = connection.execute(
                f"SELECT * FROM components WHERE {where} "
                "ORDER BY kind DESC, eid LIMIT ? OFFSET ?",
                (*params, limit, offset),
            ).fetchall()
        next_offset = offset + len(rows)
        return {
            "items": [self._row_payload(row) for row in rows],
            "total": total,
            "next_cursor": self._encode_cursor(next_offset)
            if next_offset < total
            else None,
            "catalog_fingerprint": self.fingerprint,
        }

    def get(
        self, component_ref: str | None = None, *, eid: int | None = None
    ) -> dict[str, Any]:
        if bool(component_ref) == (eid is not None):
            raise CatalogError("provide exactly one of component_ref or eid")
        with self._connect() as connection:
            if component_ref:
                row = connection.execute(
                    "SELECT * FROM components WHERE component_ref=?", (component_ref,)
                ).fetchone()
            else:
                row = connection.execute(
                    "SELECT * FROM components WHERE kind='unit' AND eid=?", (eid,)
                ).fetchone()
        if row is None:
            raise CatalogError("component is not present in this catalog version")
        result = self._row_payload(row)
        result["model"] = {
            "id": row["model_id"],
            "path": row["model_path"],
            "cell": None,
        }
        result["prefab"] = {
            "packaged": False,
            "runtime_type": None,
            "model_binding": None,
            "default_keys": [],
        }
        result["accepted_parameters"] = None
        if result["write_capability"]["writable"]:
            result["accepted_parameters"] = {
                "logical_name": "non-empty UTF-8 string up to 255 bytes",
                "transform": {
                    "center": "finite numeric triple",
                    "size": "positive numeric triple",
                    "rotation_deg": "finite triple; AABB scale supports axis-aligned 0/90-degree yaw",
                    "forward_axis": [None, "+x", "-x", "+z", "-z"],
                },
                "color": "RGB integer triple in 0..255"
                if result["write_capability"]["color_supported"]
                else None,
                "properties": {
                    key: "positive signed 32-bit integer"
                    for key in result["write_capability"]["supported_properties"]
                },
            }
        with self._connect() as connection:
            details = connection.execute(
                "SELECT p.payload,m.model_cell_json FROM prefabs p "
                "JOIN components c USING(component_ref) "
                "JOIN models m ON m.model_id=c.model_id WHERE p.component_ref=?",
                (row["component_ref"],),
            ).fetchone()
        if details is not None:
            prefab = _unpack(details["payload"])
            if not isinstance(prefab, dict):
                raise CatalogError("compiled prefab payload is malformed")
            result["model"]["cell"] = json.loads(details["model_cell_json"])
            result["prefab"] = {
                "packaged": True,
                "runtime_type": prefab.get("type"),
                "model_binding": prefab.get("model"),
                "default_keys": sorted(str(key) for key in prefab),
            }
            property_defaults: dict[str, Any] = {}
            for key in result["write_capability"]["supported_properties"]:
                value = prefab.get(key)
                if value is None or type(value) in (bool, int, float, str):
                    property_defaults[key] = value
            result["prefab"]["supported_property_defaults"] = property_defaults
            paint = prefab.get("paint_area1")
            if isinstance(paint, (list, tuple)) and len(paint) >= 3:
                result["prefab"]["default_color"] = list(paint[:3])
        return result

    def package_catalog(self) -> PackageCatalog:
        entries: dict[int, CatalogEntry] = {}
        prefabs: dict[int, dict[str, Any]] = {}
        models: dict[int, dict[str, Any]] = {}
        with self._connect() as connection:
            for row in connection.execute("SELECT * FROM components WHERE kind='unit'"):
                entries[row["eid"]] = CatalogEntry(
                    eid=row["eid"],
                    name=row["name"],
                    structural_family=row["structural_family"],
                    asset_type=row["asset_type"],
                    model_id=row["model_id"],
                    model_path=row["model_path"],
                    model_cell=None,
                    property_keys=tuple(json.loads(row["property_keys_json"])),
                    static_status=row["static_status"],
                    evidence=row["evidence"],
                    write_capability=bool(row["writable"]),
                    write_blockers=tuple(json.loads(row["write_blockers_json"])),
                    supported_properties=tuple(
                        json.loads(row["supported_properties_json"])
                    ),
                    color_supported=bool(row["color_supported"]),
                )
            for row in connection.execute(
                "SELECT p.component_ref,p.payload,c.eid,c.model_id,m.payload AS model_payload,"
                "m.model_cell_json FROM prefabs p JOIN components c USING(component_ref) "
                "JOIN models m ON m.model_id=c.model_id"
            ):
                eid = row["eid"]
                prefabs[eid] = _unpack(row["payload"])
                model_id = row["model_id"]
                models.setdefault(model_id, _unpack(row["model_payload"]))
                cell = json.loads(row["model_cell_json"])
                entry = entries[eid]
                entries[eid] = CatalogEntry(
                    **{**vars(entry), "model_cell": tuple(float(v) for v in cell)}
                )
        return PackageCatalog(
            root=self.manifest_path.parent,
            entries=entries,
            fingerprint=self.fingerprint,
            prefab_defaults=prefabs,
            model_defaults=models,
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a compact, versioned component catalog"
    )
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--decoded-bindicts", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--version-code", required=True, type=int)
    parser.add_argument("--version-name", required=True)
    parser.add_argument("--apk-sha256", required=True)
    args = parser.parse_args()
    result = build_catalog_bundle(
        catalog_directory=args.catalog,
        decoded_bindicts=args.decoded_bindicts,
        output=args.output,
        version_code=args.version_code,
        version_name=args.version_name,
        apk_sha256=args.apk_sha256,
    )
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

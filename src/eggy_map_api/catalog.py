from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from .errors import CatalogError
from .models import CatalogEntry, PackageCatalog, Vec3


def _pairs(value: Any) -> dict[Any, Any] | None:
    if not isinstance(value, dict):
        return None
    for marker in ("__dict__", "__dict_pairs__"):
        rows = value.get(marker)
        if isinstance(rows, list) and all(
            isinstance(row, list) and len(row) == 2 for row in rows
        ):
            return dict(rows)
    return None


def _tuple(value: Any) -> list[Any] | None:
    if isinstance(value, list):
        return value
    if isinstance(value, dict) and isinstance(value.get("__tuple__"), list):
        return value["__tuple__"]
    return None


def _hashable(value: Any) -> Any:
    if isinstance(value, list):
        return tuple(_hashable(item) for item in value)
    if isinstance(value, dict):
        return tuple(
            sorted(
                ((_hashable(key), _hashable(item)) for key, item in value.items()),
                key=repr,
            )
        )
    return value


def _decode_safe_json(value: Any) -> Any:
    if isinstance(value, list):
        return [_decode_safe_json(item) for item in value]
    if not isinstance(value, dict):
        return value
    if "__dict_pairs__" in value or "__dict__" in value:
        rows = value.get("__dict_pairs__", value.get("__dict__"))
        if not isinstance(rows, list):
            raise CatalogError("malformed encoded dictionary")
        result: dict[Any, Any] = {}
        for raw_key, raw_item in rows:
            key = _hashable(_decode_safe_json(raw_key))
            if key in result:
                raise CatalogError(f"duplicate decoded package-table key {key!r}")
            result[key] = _decode_safe_json(raw_item)
        return result
    if "__tuple__" in value:
        return tuple(_decode_safe_json(item) for item in value["__tuple__"])
    if "__set__" in value:
        return tuple(_decode_safe_json(item) for item in value["__set__"])
    if "__bytes_utf8__" in value:
        return value["__bytes_utf8__"].encode("utf-8")
    if "__bytes_hex__" in value:
        return bytes.fromhex(value["__bytes_hex__"])
    return {key: _decode_safe_json(item) for key, item in value.items()}


def _load_standard_table(directory: Path, stem: str) -> dict[Any, Any]:
    path = directory / f"{stem}.json"
    envelope = json.loads(path.read_text(encoding="utf-8"))
    bindicts = envelope.get("bindicts", [])
    if len(bindicts) != 1:
        raise CatalogError(f"{path.name}: expected exactly one Bindict")
    parsed = _decode_safe_json(bindicts[0]["parsed"])
    data = parsed.get("data") if isinstance(parsed, dict) else None
    if not isinstance(data, dict):
        raise CatalogError(f"{path.name}: decoded data is not a map")
    return data


def _load_full_table(directory: Path, stem: str) -> dict[Any, Any]:
    path = directory / f"{stem}.full.json"
    envelope = json.loads(path.read_text(encoding="utf-8"))
    data = _decode_safe_json(envelope.get("data"))
    if not isinstance(data, dict):
        raise CatalogError(f"{path.name}: decoded data is not a map")
    return data


def _load_package_defaults(
    directory: Path,
) -> tuple[dict[int, dict[str, Any]], dict[int, dict[str, Any]], list[Path]]:
    table_specs = (
        ("editor_unit", False),
        ("editor_trigger", False),
        ("editor_virtual_point", True),
        ("editor_decoration", True),
    )
    prefabs: dict[int, dict[str, Any]] = {}
    sources: list[Path] = []
    for stem, full in table_specs:
        path = directory / f"{stem}{'.full' if full else ''}.json"
        if not path.is_file():
            raise CatalogError(f"missing decoded package table: {path.name}")
        table = (
            _load_full_table(directory, stem)
            if full
            else _load_standard_table(directory, stem)
        )
        sources.append(path)
        for eid, row in table.items():
            if type(eid) is not int or not isinstance(row, dict):
                continue
            if eid in prefabs:
                raise CatalogError(f"duplicate prefab EID across package tables: {eid}")
            prefabs[eid] = row
    model_path = directory / "editor_model.json"
    if not model_path.is_file():
        raise CatalogError("missing decoded package table: editor_model.json")
    models = {
        model_id: row
        for model_id, row in _load_standard_table(directory, "editor_model").items()
        if type(model_id) is int and isinstance(row, dict)
    }
    sources.append(model_path)
    return prefabs, models, sources


def _load_model_cells(decoded_bindicts: Path) -> dict[int, Vec3]:
    path = decoded_bindicts / "editor_model.json"
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    cells: dict[int, Vec3] = {}

    def visit(value: Any) -> None:
        mapping = _pairs(value)
        if mapping is not None and type(mapping.get("key")) is int:
            cell = _tuple(mapping.get("cell"))
            if (
                cell is not None
                and len(cell) == 3
                and all(type(v) in (int, float) for v in cell)
            ):
                cells[mapping["key"]] = tuple(float(v) for v in cell)  # type: ignore[assignment]
        if isinstance(value, dict):
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(data)
    return cells


def _load_exported_model_cells(root: Path) -> dict[int, Vec3]:
    path = root / "model-cells.json"
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    result: dict[int, Vec3] = {}
    for key, value in payload.items():
        if (
            not isinstance(value, list)
            or len(value) != 3
            or not all(type(item) in (int, float) for item in value)
        ):
            raise CatalogError(f"invalid model cell for model {key}")
        result[int(key)] = tuple(float(item) for item in value)  # type: ignore[assignment]
    return result


def open_package_catalog(
    path: str | Path, *, decoded_bindicts: str | Path | None = None
) -> PackageCatalog:
    root = Path(path).expanduser().resolve()
    csv_path = root if root.is_file() else root / "unit-components.csv"
    if not csv_path.is_file():
        raise CatalogError(f"unit-components.csv not found under {root}")
    decoded_candidates = [root / "decoded-bindicts", root.parent / "decoded-bindicts"]
    decoded = (
        Path(decoded_bindicts).expanduser().resolve()
        if decoded_bindicts is not None
        else next((p for p in decoded_candidates if p.is_dir()), None)
    )
    if decoded is not None and not decoded.is_dir():
        raise CatalogError(f"decoded package-table directory does not exist: {decoded}")
    model_cells = (
        _load_model_cells(decoded)
        if decoded is not None
        else _load_exported_model_cells(csv_path.parent)
    )
    raw = csv_path.read_bytes()
    entries: dict[int, CatalogEntry] = {}
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            try:
                eid = int(row["component_id"])
            except (KeyError, TypeError, ValueError) as exc:
                raise CatalogError("invalid component_id in catalog") from exc
            if eid in entries:
                raise CatalogError(f"duplicate component EID {eid}")
            model_id = int(row["model_id"]) if row.get("model_id", "").strip() else None
            try:
                keys = tuple(json.loads(row.get("property_keys_json") or "[]"))
            except json.JSONDecodeError as exc:
                raise CatalogError(f"invalid property list for EID {eid}") from exc
            entries[eid] = CatalogEntry(
                eid=eid,
                name=row.get("component_name", ""),
                structural_family=row.get("structural_family", ""),
                asset_type=row.get("asset_type", ""),
                model_id=model_id,
                model_path=row.get("model_path") or None,
                model_cell=model_cells.get(model_id) if model_id is not None else None,
                property_keys=keys,
                static_status=row.get("current_session_static_status", ""),
                evidence=row.get("evidence", ""),
            )
    prefabs: dict[int, dict[str, Any]] = {}
    models: dict[int, dict[str, Any]] = {}
    source_paths: list[Path] = []
    if decoded is not None:
        prefabs, models, source_paths = _load_package_defaults(decoded)
    fingerprint_hash = hashlib.sha256()
    fingerprint_hash.update(csv_path.name.encode())
    fingerprint_hash.update(raw)
    for source in sorted(source_paths):
        fingerprint_hash.update(source.name.encode())
        fingerprint_hash.update(source.read_bytes())
    fingerprint = fingerprint_hash.hexdigest()
    return PackageCatalog(
        root=csv_path.parent,
        entries=entries,
        fingerprint=fingerprint,
        prefab_defaults=prefabs,
        model_defaults=models,
    )


def require_components(catalog: PackageCatalog, eids: set[int]) -> None:
    missing = sorted(eids - catalog.entries.keys())
    if missing:
        raise CatalogError(f"package catalog is missing component EIDs: {missing}")
    unavailable = sorted(
        eid for eid in eids if "pass" not in catalog.entries[eid].static_status
    )
    if unavailable:
        raise CatalogError(
            f"components do not pass the recovered package gates: {unavailable}"
        )

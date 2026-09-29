#!/usr/bin/env python3
"""Convert locally decoded editor tables into the existing catalog input format.

All entries remain unverified unless a matching, locally reviewed static-gate
file is supplied. No package declaration is automatically made writable.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from eggy_map_api.catalog import _decode_safe_json, _load_model_cells

REQUIRED = (
    "editor_unit",
    "editor_trigger",
    "editor_virtual_point",
    "editor_decoration",
    "editor_model",
)
FULL_OUTPUT = {"editor_virtual_point", "editor_decoration"}
UNIT_FIELDS = (
    "component_id",
    "component_name",
    "structural_family",
    "asset_type",
    "model_id",
    "model_path",
    "property_keys_json",
    "current_session_static_status",
    "evidence",
)
EFFECT_FIELDS = (
    "effect_eid",
    "effect_name",
    "effect_type",
    "model_id",
    "effect_path",
    "static_filter_status",
    "evidence_scope",
)


def table(source: Path, name: str) -> tuple[dict, dict]:
    options = [source / f"{name}.full.json", source / f"{name}.json"]
    path = next((p for p in options if p.is_file()), None)
    if path is None:
        raise ValueError(f"Missing decoded table: {name}")
    document = json.loads(path.read_text())
    if "data" in document:
        encoded = document["data"]
    else:
        bindicts = document.get("bindicts", [])
        if len(bindicts) != 1:
            raise ValueError(f"{name}: expected one decoded table")
        encoded = bindicts[0]["parsed"]["data"]
    decoded = _decode_safe_json(encoded)
    if not isinstance(decoded, dict):
        raise ValueError(f"{name}: decoded table must be a mapping")
    return encoded, decoded


def write_csv(path: Path, fields: tuple[str, ...], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def prepare(
    source: Path, output: Path, apk_sha256: str, gates_path: Path | None = None
) -> Path:
    if output.exists():
        raise ValueError("Output already exists; choose a fresh output directory")
    if len(apk_sha256) != 64 or any(c not in "0123456789abcdef" for c in apk_sha256):
        raise ValueError("apk_sha256 must be a lowercase SHA-256 digest")
    gates = {}
    if gates_path:
        gates_document = json.loads(gates_path.read_text())
        if gates_document.get("apk_sha256") != apk_sha256:
            raise ValueError("Static-gate evidence does not match this game package")
        gates = gates_document["components"]
        for eid, record in gates.items():
            if not eid.isdecimal() or record.get("status") not in {
                "pass",
                "blocked",
                "unverified",
            }:
                raise ValueError("Invalid static-gate record")
            if (
                not isinstance(record.get("evidence"), str)
                or not record["evidence"].strip()
            ):
                raise ValueError(
                    "Every static-gate record needs a local review explanation"
                )
    tables = {name: table(source, name) for name in REQUIRED}
    models = tables["editor_model"][1]
    language = {}
    for name in ("editor_model_language_zh",):
        if any((source / f"{name}{suffix}.json").exists() for suffix in ("", ".full")):
            language = table(source, name)[1]
    seen = set()
    units = []
    for family in REQUIRED:
        if family == "editor_model":
            continue
        for eid, record in tables[family][1].items():
            if type(eid) is not int or not isinstance(record, dict):
                continue
            if eid in seen:
                raise ValueError(f"Duplicate EID across families: {eid}")
            seen.add(eid)
            model = models.get(record.get("model"), {})
            gate = gates.get(
                str(eid),
                {"status": "unverified", "evidence": "local-package-declaration-only"},
            )
            name = (
                record.get("name")
                or language.get(eid)
                or model.get("name")
                or f"component-{eid}"
            )
            name = (
                language.get(name, name)
                if isinstance(name, (str, int))
                else f"component-{eid}"
            )
            units.append(
                dict(
                    zip(
                        UNIT_FIELDS,
                        (
                            eid,
                            str(name),
                            family,
                            "unit",
                            record.get("model", ""),
                            model.get("path", ""),
                            json.dumps(record.get("edit_attr_list") or []),
                            gate["status"],
                            gate["evidence"],
                        ),
                    )
                )
            )
    effects = []
    if any(
        (source / f"editor_effect{suffix}.json").exists() for suffix in ("", ".full")
    ):
        for eid, record in table(source, "editor_effect")[1].items():
            if type(eid) is int and isinstance(record, dict):
                effects.append(
                    dict(
                        zip(
                            EFFECT_FIELDS,
                            (
                                eid,
                                str(
                                    record.get("name")
                                    or language.get(eid)
                                    or f"effect-{eid}"
                                ),
                                "effect",
                                "",
                                record.get("path", ""),
                                "declared",
                                "local-package-declaration-only",
                            ),
                        )
                    )
                )
    decoded = output / "decoded-bindicts"
    decoded.mkdir(parents=True)
    for name, (encoded, _) in tables.items():
        full = name in FULL_OUTPUT
        document = (
            {"data": encoded} if full else {"bindicts": [{"parsed": {"data": encoded}}]}
        )
        if name == "editor_model":
            cells = _load_model_cells(source)
            document["dimension_records"] = [
                {"__dict_pairs__": [["key", model_id], ["cell", list(cell)]]}
                for model_id, cell in sorted(cells.items())
            ]
        (decoded / f"{name}{'.full' if full else ''}.json").write_text(
            json.dumps(document, ensure_ascii=False)
        )
    write_csv(output / "unit-components.csv", UNIT_FIELDS, units)
    write_csv(output / "effect-components.csv", EFFECT_FIELDS, effects)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decoded", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--apk-sha256", required=True)
    parser.add_argument("--static-gates", type=Path)
    args = parser.parse_args()
    try:
        print(prepare(args.decoded, args.output, args.apk_sha256, args.static_gates))
    except (ValueError, KeyError, OSError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()

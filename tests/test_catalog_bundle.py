import csv
import json
from pathlib import Path

import pytest

from eggy_map_api.catalog_bundle import CompiledCatalog, build_catalog_bundle
from eggy_map_api.errors import CatalogError


def encoded_map(rows):
    return {"__dict_pairs__": [[key, value] for key, value in rows]}


def write_synthetic_sources(root: Path) -> tuple[Path, Path]:
    catalog = root / "catalog-source"
    decoded = root / "decoded-source"
    catalog.mkdir()
    decoded.mkdir()
    unit_fields = [
        "component_id",
        "component_name",
        "structural_family",
        "asset_type",
        "model_id",
        "model_path",
        "property_keys_json",
        "current_session_static_status",
        "evidence",
    ]
    with (catalog / "unit-components.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=unit_fields)
        writer.writeheader()
        writer.writerow(
            {
                "component_id": 101,
                "component_name": "Synthetic platform",
                "structural_family": "editor_unit",
                "asset_type": "unit",
                "model_id": 201,
                "model_path": "synthetic/platform.gim",
                "property_keys_json": "[]",
                "current_session_static_status": "pass",
                "evidence": "synthetic",
            }
        )
    effect_fields = [
        "effect_eid",
        "effect_name",
        "effect_type",
        "model_id",
        "effect_path",
        "static_filter_status",
        "evidence_scope",
    ]
    with (catalog / "effect-components.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=effect_fields)
        writer.writeheader()
        writer.writerow(
            {
                "effect_eid": 301,
                "effect_name": "Synthetic sparkle",
                "effect_type": "effect",
                "model_id": "",
                "effect_path": "synthetic/sparkle.effect",
                "static_filter_status": "declared",
                "evidence_scope": "synthetic",
            }
        )

    standard_tables = {
        "editor_unit": encoded_map(
            [
                (
                    101,
                    {
                        "type": 256,
                        "model": 201,
                        "paint_area1": [1, 2, 3],
                    },
                )
            ]
        ),
        "editor_trigger": encoded_map([]),
        "editor_model": encoded_map([(201, {"scale": [1.0, 1.0, 1.0]})]),
    }
    for stem, data in standard_tables.items():
        document = {"bindicts": [{"parsed": {"data": data}}]}
        if stem == "editor_model":
            document["cell_record"] = {
                "__dict__": [
                    ["key", 201],
                    ["cell", {"__tuple__": [2.0, 2.0, 2.0]}],
                ]
            }
        (decoded / f"{stem}.json").write_text(json.dumps(document), encoding="utf-8")
    for stem in ("editor_virtual_point", "editor_decoration"):
        (decoded / f"{stem}.full.json").write_text(
            json.dumps({"data": encoded_map([])}), encoding="utf-8"
        )
    return catalog, decoded


def test_compiled_catalog_search_profile_and_payload(tmp_path: Path) -> None:
    source, decoded = write_synthetic_sources(tmp_path)
    bundle = build_catalog_bundle(
        catalog_directory=source,
        decoded_bindicts=decoded,
        output=tmp_path / "bundle",
        version_code=1,
        version_name="synthetic",
        apk_sha256="a" * 64,
    )
    compiled = CompiledCatalog(
        bundle / "catalog-manifest.json", data_directory=tmp_path / "runtime"
    )
    assert compiled.counts == {
        "components": 2,
        "units": 1,
        "effects": 1,
        "writable_units": 1,
    }
    writable = compiled.search("platform", writable_only=True)
    assert writable["total"] == 1
    component = compiled.get(writable["items"][0]["component_ref"])
    assert component["write_capability"]["writable"] is True
    assert component["evidence_level"] == "static-derived"
    assert component["prefab"]["runtime_type"] == 256
    assert component["model"]["cell"] == [2.0, 2.0, 2.0]
    assert component["accepted_parameters"]["color"] is not None
    assert (
        compiled.search(kind="effect")["items"][0]["write_capability"]["writable"]
        is False
    )
    runtime = compiled.package_catalog()
    assert runtime.entries[101].model_cell == (2.0, 2.0, 2.0)
    assert runtime.prefab_defaults[101]["model"] == 201


def test_compiled_catalog_cursor_is_version_bound(tmp_path: Path) -> None:
    source, decoded = write_synthetic_sources(tmp_path)
    bundle = build_catalog_bundle(
        catalog_directory=source,
        decoded_bindicts=decoded,
        output=tmp_path / "bundle",
        version_code=1,
        version_name="synthetic",
        apk_sha256="b" * 64,
    )
    compiled = CompiledCatalog(
        bundle / "catalog-manifest.json", data_directory=tmp_path / "runtime"
    )
    first = compiled.search(limit=1)
    assert first["next_cursor"] is not None
    second = compiled.search(limit=1, cursor=first["next_cursor"])
    assert first["items"][0]["component_ref"] != second["items"][0]["component_ref"]
    with pytest.raises(CatalogError, match="cursor"):
        compiled.search(cursor="not-a-valid-cursor")

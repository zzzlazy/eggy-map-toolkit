"""Observable release contracts: anonymous refs and local-only catalog gates."""

import importlib.util
import json
from pathlib import Path

import pytest

from eggy_map_api.catalog import open_package_catalog
from eggy_map_api.capabilities import runtime_component_capability
from eggy_map_api.catalog_bundle import build_catalog_bundle
from eggy_map_api.errors import DeviceError
from eggy_map_mcp.service import EggyMapService
from test_catalog_bundle import write_synthetic_sources

ROOT = Path(__file__).resolve().parents[1]


def load_tool(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_private_scan_uses_external_tokens_without_echoing_identity():
    scan = load_tool("check_release")
    secret = b"FICTIONAL_EXAMPLE_TITLE"
    findings = scan.privacy_findings("example.md", b"prefix " + secret, [secret])
    assert findings == ["example.md: private-identity"]
    assert secret.decode() not in str(findings)


def test_catalog_conversion_preserves_dimensions_and_requires_evidence(tmp_path):
    convert = load_tool("prepare_catalog_sources")
    _, decoded = write_synthetic_sources(tmp_path)
    first = convert.prepare(decoded, tmp_path / "first", "0" * 64)
    catalog = open_package_catalog(first, decoded_bindicts=first / "decoded-bindicts")
    assert catalog.entries[101].model_cell == (2.0, 2.0, 2.0)
    assert not runtime_component_capability(catalog, 101).writable
    gates = tmp_path / "gates.json"
    gates.write_text(
        json.dumps(
            {
                "apk_sha256": "0" * 64,
                "components": {
                    "101": {"status": "pass", "evidence": "synthetic fixture only"}
                },
            }
        )
    )
    second = convert.prepare(decoded, tmp_path / "second", "0" * 64, gates)
    checked = open_package_catalog(second, decoded_bindicts=second / "decoded-bindicts")
    assert runtime_component_capability(checked, 101).writable
    with pytest.raises(ValueError, match="does not match"):
        convert.prepare(decoded, tmp_path / "mismatch", "1" * 64, gates)


def test_coverage_only_references_shipped_anonymous_evidence():
    skill = ROOT / "plugin/eggy-map-tools/skills/eggy-map-designer"
    coverage = json.loads((skill / "references/research-coverage.json").read_text())
    for section in ("primary_types", "modifiers", "visual_worlds", "hybrid_pairs"):
        for entry in coverage[section]:
            for reference in entry["positive_refs"] + entry["boundary_refs"]:
                assert reference.startswith("skill:eggy-map-designer/")
                path = skill / reference.split("/", 1)[1]
                assert path.is_file()
                if path.parent.name == "exemplars":
                    assert path.stem.startswith("case-")


def test_catalog_service_starts_without_adb_but_device_operations_fail_closed(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("EGGY_ADB_PATH", str(tmp_path / "unavailable-adb"))
    source, decoded = write_synthetic_sources(tmp_path)
    bundle = build_catalog_bundle(
        catalog_directory=source,
        decoded_bindicts=decoded,
        output=tmp_path / "bundle",
        version_code=1,
        version_name="synthetic",
        apk_sha256="0" * 64,
    )
    service = EggyMapService(
        catalog_manifest=bundle / "catalog-manifest.json",
        data_directory=tmp_path / "runtime",
    )
    assert service.search_components("platform")["total"] == 1
    assert service._adb is None
    for operation in (service.device_status, lambda: service.transactions):
        with pytest.raises(DeviceError) as caught:
            operation()
        assert caught.value.error_code == "ADB_NOT_FOUND"
    assert service._transactions is None

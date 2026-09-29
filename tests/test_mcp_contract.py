import asyncio

import pytest
from pydantic import ValidationError

from eggy_map_api.errors import StateError
from eggy_map_mcp.schemas import ReconcileManifestInput, TransformInput
from eggy_map_mcp.server import build_server


class FakeService:
    def device_status(self):
        return {"mode": "read_only"}


def test_mcp_tool_inventory_and_annotations() -> None:
    tools = asyncio.run(build_server(FakeService()).list_tools())
    by_name = {tool.name: tool for tool in tools}
    assert set(by_name) == {
        "device_status",
        "list_maps",
        "search_components",
        "get_component",
        "inspect_map",
        "validate_map",
        "add_component",
        "delete_components",
        "reset_map_upload_failure",
        "reconcile_map",
        "get_deployment",
        "list_deployments",
        "rollback",
    }
    for name in (
        "device_status",
        "list_maps",
        "search_components",
        "get_component",
        "inspect_map",
        "validate_map",
        "get_deployment",
        "list_deployments",
    ):
        assert by_name[name].annotations.read_only_hint is True
        assert by_name[name].annotations.destructive_hint is False
    for name in (
        "add_component",
        "delete_components",
        "reset_map_upload_failure",
        "reconcile_map",
        "rollback",
    ):
        assert by_name[name].annotations.read_only_hint is False
        assert by_name[name].annotations.destructive_hint is True


def test_mcp_returns_structured_domain_error() -> None:
    class FailingService(FakeService):
        def device_status(self):
            raise StateError("synthetic failure", code="SYNTHETIC_FAILURE")

    result = asyncio.run(build_server(FailingService()).call_tool("device_status", {}))
    assert result.structured_content == {
        "ok": False,
        "error": {"code": "SYNTHETIC_FAILURE", "message": "synthetic failure"},
    }


def test_reconcile_schema_binds_map_ref_and_rejects_coercion() -> None:
    manifest = ReconcileManifestInput(
        map_ref="map_reference",
        components=[],
        cleanup_policy="managed_only",
    )
    assert manifest.map_ref == "map_reference"
    with pytest.raises(ValidationError):
        TransformInput(center=("1", 0, 0), size=(1, 1, 1))

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from eggy_map_api.errors import EggyMapError

from .schemas import ReconcileManifestInput, TransformInput
from .service import EggyMapService, default_data_directory

T = TypeVar("T")

SERVER_INSTRUCTIONS = (
    "Read-only catalog and map inspection tools may run without changing the device. "
    "Before any mutation, the user must explicitly confirm that the editor is closed and the game "
    "is on its map list. Mutations create a complete local triplet backup, validate a fresh output, "
    "and atomically replace only the scoped editable map bytes or index file. Never operate UI, restart the game, "
    "press Android Back, or enter run mode. After a map-content deployment, ask the user to inspect edit mode; "
    "on anomaly, exit without saving and use rollback. After an upload-failure reset, ask the user to delete from "
    "the map list; if the UI still reports uploading, the user must manually fully close and reopen the game first."
)

READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)
WRITE = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=False,
    openWorldHint=False,
)


def _safe(call: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    try:
        return {"ok": True, "result": call()}
    except EggyMapError as exc:
        return {"ok": False, "error": exc.to_dict()}
    except Exception as exc:  # noqa: BLE001
        print(f"eggy-map-tools internal error: {type(exc).__name__}", file=sys.stderr)
        return {
            "ok": False,
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "An unexpected local server error occurred; no successful deployment was reported.",
            },
        }


def build_server(service: EggyMapService) -> MCPServer:
    server = MCPServer(
        name="eggy-map",
        title="蛋仔地图本地工具",
        description="Version-pinned component catalog and fail-closed local map editing",
        instructions=SERVER_INSTRUCTIONS,
        version="0.2.0",
        log_level="WARNING",
    )

    @server.tool(
        description="Inspect the unique MuMu device, game process, root status, and catalog profile match.",
        annotations=READ_ONLY,
        structured_output=True,
    )
    def device_status() -> dict[str, Any]:
        return _safe(service.device_status)

    @server.tool(
        description="List editable maps and return opaque revision-bound map references. Exact names are never guessed.",
        annotations=READ_ONLY,
        structured_output=True,
    )
    def list_maps(
        exact_name: str | None = None, include_archived: bool = False
    ) -> dict[str, Any]:
        return _safe(lambda: service.list_maps(exact_name, include_archived))

    @server.tool(
        description="Search the complete versioned package catalog, including read-only effects and write gates.",
        annotations=READ_ONLY,
        structured_output=True,
    )
    def search_components(
        query: str = "",
        kind: str | None = None,
        family: str | None = None,
        static_status: str | None = None,
        writable_only: bool = False,
        limit: int = 50,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        return _safe(
            lambda: service.search_components(
                query,
                kind,
                family,
                static_status,
                writable_only,
                limit,
                cursor,
            )
        )

    @server.tool(
        description="Get one component's package metadata, supported inputs, evidence, and write blockers.",
        annotations=READ_ONLY,
        structured_output=True,
    )
    def get_component(
        component_ref: str | None = None, eid: int | None = None
    ) -> dict[str, Any]:
        return _safe(lambda: service.get_component(component_ref, eid))

    @server.tool(
        description="Inspect map units and return opaque snapshot-bound unit references without exposing device paths.",
        annotations=READ_ONLY,
        structured_output=True,
    )
    def inspect_map(map_ref: str) -> dict[str, Any]:
        return _safe(lambda: service.inspect_map(map_ref))

    @server.tool(
        description="Strictly decode and validate the current map without writing to the device.",
        annotations=READ_ONLY,
        structured_output=True,
    )
    def validate_map(map_ref: str) -> dict[str, Any]:
        return _safe(lambda: service.validate_map(map_ref))

    @server.tool(
        description="Add one statically writable component in a backed-up, validated, atomic deployment.",
        annotations=WRITE,
        structured_output=True,
    )
    def add_component(
        map_ref: str,
        component_ref: str,
        logical_name: str,
        transform: TransformInput,
        color: tuple[int, int, int] | None = None,
        properties: dict[str, Any] | None = None,
        editor_closed_confirmed: bool = False,
    ) -> dict[str, Any]:
        return _safe(
            lambda: service.add_component(
                map_ref=map_ref,
                component_ref=component_ref,
                logical_name=logical_name,
                transform=transform,
                color=color,
                properties=properties,
                editor_closed_confirmed=editor_closed_confirmed,
            )
        )

    @server.tool(
        description="Delete complete component closures selected by opaque unit references in one atomic deployment.",
        annotations=WRITE,
        structured_output=True,
    )
    def delete_components(
        map_ref: str,
        unit_refs: list[str],
        editor_closed_confirmed: bool = False,
    ) -> dict[str, Any]:
        return _safe(
            lambda: service.delete_components(
                map_ref=map_ref,
                unit_refs=unit_refs,
                editor_closed_confirmed=editor_closed_confirmed,
            )
        )

    @server.tool(
        description=(
            "Reset one map's persistent local upload-failure flag from true to false in a "
            "backed-up, whitelist-validated, atomic index deployment. This does not cancel a "
            "cloud upload or clear the running game's in-memory upload lock."
        ),
        annotations=WRITE,
        structured_output=True,
    )
    def reset_map_upload_failure(
        map_ref: str,
        editor_closed_confirmed: bool = False,
    ) -> dict[str, Any]:
        return _safe(
            lambda: service.reset_map_upload_failure(
                map_ref=map_ref,
                editor_closed_confirmed=editor_closed_confirmed,
            )
        )

    @server.tool(
        description="Idempotently reconcile a flat component manifest, validate it twice, and deploy once.",
        annotations=WRITE,
        structured_output=True,
    )
    def reconcile_map(
        manifest: ReconcileManifestInput,
        editor_closed_confirmed: bool = False,
    ) -> dict[str, Any]:
        return _safe(
            lambda: service.reconcile_map(
                manifest=manifest,
                editor_closed_confirmed=editor_closed_confirmed,
            )
        )

    @server.tool(
        description="Read one deployment receipt without changing device state.",
        annotations=READ_ONLY,
        structured_output=True,
    )
    def get_deployment(deployment_id: str) -> dict[str, Any]:
        return _safe(lambda: service.get_deployment(deployment_id))

    @server.tool(
        description="List local deployment receipts, optionally limited to one map reference.",
        annotations=READ_ONLY,
        structured_output=True,
    )
    def list_deployments(map_ref: str | None = None) -> dict[str, Any]:
        return _safe(lambda: service.list_deployments(map_ref))

    @server.tool(
        description="Restore the exact backed-up map directory, archive, index, ownership, modes, and hashes.",
        annotations=WRITE,
        structured_output=True,
    )
    def rollback(
        deployment_id: str, editor_closed_confirmed: bool = False
    ) -> dict[str, Any]:
        return _safe(
            lambda: service.rollback(
                deployment_id=deployment_id,
                editor_closed_confirmed=editor_closed_confirmed,
            )
        )

    return server


def _catalog_manifest() -> Path:
    configured = os.getenv("EGGY_MAP_CATALOG_MANIFEST")
    if configured:
        return Path(configured).expanduser().resolve()
    plugin_root = os.getenv("EGGY_MAP_PLUGIN_ROOT")
    if plugin_root:
        return (
            Path(plugin_root).expanduser().resolve()
            / "catalog"
            / "catalog-manifest.json"
        )
    return Path.cwd() / "build" / "catalog" / "catalog-manifest.json"


def main() -> None:
    manifest = _catalog_manifest()
    if not manifest.is_file():
        raise SystemExit(
            "Local component catalog missing. Follow docs/local-catalog.md and "
            "set EGGY_MAP_CATALOG_MANIFEST to its catalog-manifest.json. "
            "Design skills and offline tests work without game data."
        )
    service = EggyMapService(
        catalog_manifest=manifest, data_directory=default_data_directory()
    )
    build_server(service).run(transport="stdio")


if __name__ == "__main__":
    main()

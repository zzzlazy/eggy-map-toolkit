#!/usr/bin/env python3
"""Build a plugin from synthetic data and verify offline MCP startup.

Requires development/test dependencies. Never connects to a game device.
"""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from test_catalog_bundle import write_synthetic_sources  # noqa: E402
from eggy_map_api.catalog_bundle import build_catalog_bundle  # noqa: E402
from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402


async def handshake(plugin: Path, data: Path) -> None:
    env = {
        **os.environ,
        "EGGY_MAP_BOOTSTRAP_PYTHON": sys.executable,
        "EGGY_MAP_DATA_DIR": str(data),
    }
    env.pop("EGGY_MAP_CATALOG_MANIFEST", None)
    params = StdioServerParameters(
        command="/bin/sh", args=[str(plugin / "scripts/run-mcp.sh")], env=env
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.list_tools()
            names = {tool.name for tool in result.tools}
            expected = {"device_status", "list_maps", "reconcile_map", "rollback"}
            if len(names) != 13 or not expected <= names:
                raise AssertionError(f"Unexpected MCP tool interface: {names}")
    print("Offline bootstrap and MCP handshake passed (13 tools; no device calls).")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-identities", type=Path)
    args = parser.parse_args()
    # Temporary directories are removed by the standard context manager.
    with tempfile.TemporaryDirectory(prefix="eggy-public-smoke-") as temp:
        work = Path(temp)
        source, decoded = write_synthetic_sources(work)
        catalog = build_catalog_bundle(
            catalog_directory=source,
            decoded_bindicts=decoded,
            output=work / "catalog",
            version_code=1,
            version_name="synthetic",
            apk_sha256="0" * 64,
        )
        plugin = work / "dist/eggy-map-tools"
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools/build_local_plugin.py"),
                "--workspace",
                str(ROOT),
                "--catalog",
                str(catalog),
                "--destination",
                str(plugin),
            ],
            check=True,
        )
        scan = [
            sys.executable,
            str(ROOT / "tools/check_release.py"),
            "--plugin",
            str(plugin),
        ]
        if args.private_identities:
            scan += ["--private-identities", str(args.private_identities.resolve())]
        subprocess.run(scan, check=True)
        asyncio.run(asyncio.wait_for(handshake(plugin, work / "runtime"), timeout=60))


if __name__ == "__main__":
    main()

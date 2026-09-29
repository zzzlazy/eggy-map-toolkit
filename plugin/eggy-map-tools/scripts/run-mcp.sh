#!/bin/sh
set -eu

PLUGIN_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
HOST_PYTHON=${EGGY_MAP_BOOTSTRAP_PYTHON:-python3}
RUNTIME_PYTHON=$($HOST_PYTHON "$PLUGIN_ROOT/scripts/bootstrap.py")

export EGGY_MAP_PLUGIN_ROOT="$PLUGIN_ROOT"
export EGGY_MAP_CATALOG_MANIFEST="${EGGY_MAP_CATALOG_MANIFEST:-$PLUGIN_ROOT/catalog/catalog-manifest.json}"
exec "$RUNTIME_PYTHON" -m eggy_map_mcp

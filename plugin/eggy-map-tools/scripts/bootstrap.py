#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import venv
from pathlib import Path


def main() -> int:
    plugin = Path(__file__).resolve().parent.parent
    metadata = plugin / "BUILD-METADATA.json"
    if not metadata.is_file():
        raise SystemExit("Build this plugin first; see the repository README.")
    required = json.loads(metadata.read_text())["python_version"]
    if f"{sys.version_info.major}.{sys.version_info.minor}" != required:
        raise SystemExit(f"This wheelhouse requires Python {required}; rebuild it for another interpreter.")
    lock = plugin / "wheelhouse" / "requirements.lock"
    if not lock.is_file():
        raise SystemExit("eggy-map-tools wheelhouse lock is missing")
    digest = hashlib.sha256(lock.read_bytes()).hexdigest()[:24]
    configured = os.getenv("EGGY_MAP_DATA_DIR")
    data = (
        Path(configured).expanduser().resolve()
        if configured
        else (Path.home() / "Library" / "Application Support" / "eggy-map-tools").resolve()
    )
    runtime = data / "runtime" / digest
    python = runtime / "bin" / "python"
    marker = runtime / ".complete"
    if not marker.is_file():
        runtime.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if runtime.exists():
            raise SystemExit("incomplete eggy-map-tools runtime exists; inspect it before retrying")
        venv.EnvBuilder(with_pip=True, clear=False).create(runtime)
        subprocess.run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--no-index",
                "--find-links",
                str(plugin / "wheelhouse"),
                "--require-hashes",
                "-r",
                str(lock),
            ],
            check=True,
            stdout=sys.stderr,
            stderr=sys.stderr,
        )
        marker.write_text(digest + "\n", encoding="utf-8")
        os.chmod(marker, 0o600)
    print(python)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import email.parser
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def wheel_identity(path: Path) -> tuple[str, str]:
    with zipfile.ZipFile(path) as archive:
        names = [
            name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
        ]
        if len(names) != 1:
            raise ValueError(f"{path.name}: expected one wheel METADATA file")
        message = email.parser.BytesParser().parsebytes(archive.read(names[0]))
    name, version = message.get("Name"), message.get("Version")
    if not name or not version:
        raise ValueError(f"{path.name}: wheel name or version is missing")
    return name, version


def write_lock(wheelhouse: Path) -> Path:
    rows: list[tuple[str, str, str]] = []
    for wheel in sorted(wheelhouse.glob("*.whl")):
        name, version = wheel_identity(wheel)
        rows.append((name, version, digest(wheel)))
    if not rows:
        raise ValueError("wheelhouse is empty")
    lock = wheelhouse / "requirements.lock"
    lock.write_text(
        "".join(
            f"{name}=={version} --hash=sha256:{sha256}\n"
            for name, version, sha256 in sorted(rows, key=lambda row: row[0].lower())
        ),
        encoding="utf-8",
    )
    return lock


def run(command: list[str], *, cwd: Path | None = None) -> None:
    subprocess.run(command, cwd=cwd, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a portable eggy-map-tools plugin without installing it"
    )
    parser.add_argument(
        "--workspace", type=Path, default=Path(__file__).resolve().parent.parent
    )
    parser.add_argument("--destination", type=Path, default=Path("dist/eggy-map-tools"))
    parser.add_argument(
        "--catalog",
        type=Path,
        required=True,
        help="locally generated directory containing catalog-manifest.json",
    )
    parser.add_argument("--python", default=sys.executable)
    args = parser.parse_args()
    workspace = args.workspace.expanduser().resolve()
    destination = args.destination.expanduser().resolve()
    template = workspace / "plugin" / "eggy-map-tools"
    catalog = args.catalog.expanduser().resolve()
    if not (template / ".codex-plugin" / "plugin.json").is_file():
        raise SystemExit("plugin template is incomplete")
    if not (catalog / "catalog-manifest.json").is_file():
        raise SystemExit(
            "Compiled catalog missing; follow docs/local-catalog.md, then pass --catalog <directory>."
        )
    if destination.exists():
        raise SystemExit(
            "Destination already exists; choose a new build directory with --destination."
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_root = Path(
        tempfile.mkdtemp(prefix=".eggy-map-tools-build-", dir=destination.parent)
    )
    stage = temporary_root / "eggy-map-tools"
    previous: Path | None = None
    try:
        shutil.copytree(template, stage)
        shutil.copytree(catalog, stage / "catalog")
        wheelhouse = stage / "wheelhouse"
        wheelhouse.mkdir()
        run(
            [
                args.python,
                "-m",
                "pip",
                "wheel",
                "--disable-pip-version-check",
                "--wheel-dir",
                str(wheelhouse),
                str(workspace),
            ],
            cwd=workspace,
        )
        lock = write_lock(wheelhouse)
        for script in (stage / "scripts").iterdir():
            if script.is_file():
                script.chmod(0o755)
        run(
            [
                args.python,
                str(workspace / "tools" / "check_release.py"),
                "--plugin",
                str(stage),
            ]
        )
        plugin_manifest = json.loads(
            (stage / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
        )
        metadata = {
            "schema_version": 1,
            "python_version": subprocess.check_output(
                [
                    args.python,
                    "-c",
                    "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')",
                ],
                text=True,
            ).strip(),
            "plugin": "eggy-map-tools",
            "plugin_version": plugin_manifest["version"],
            "wheelhouse_lock_sha256": digest(lock),
            "catalog_manifest_sha256": digest(
                stage / "catalog" / "catalog-manifest.json"
            ),
            "catalog_database_sha256": digest(
                stage / "catalog" / "catalog.sqlite3.zst"
            ),
        }
        (stage / "BUILD-METADATA.json").write_text(
            json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        if destination.exists():
            raise SystemExit(
                "Destination appeared during build; refusing to overwrite it."
            )
        try:
            os.replace(stage, destination)
        except Exception:
            if previous is not None and not destination.exists():
                os.replace(previous, destination)
            raise
        print(
            json.dumps(
                {
                    "plugin": str(destination),
                    "previous": str(previous) if previous else None,
                    "wheel_count": len(
                        list((destination / "wheelhouse").glob("*.whl"))
                    ),
                },
                indent=2,
            )
        )
        return 0
    finally:
        if temporary_root.exists():
            shutil.rmtree(temporary_root)


if __name__ == "__main__":
    raise SystemExit(main())

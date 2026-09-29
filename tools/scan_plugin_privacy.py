#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import zipfile
from pathlib import Path

GENERIC_FORBIDDEN = (
    re.compile(rb"(?:127\.0\.0\.1|localhost):[0-9]{2,5}"),
    re.compile(rb"/Users/[^/]+/Documents/ChatGPT/"),
    re.compile(rb"(?:task_cloud|/backups/|/artifacts/|/generated/)"),
)


def payloads(root: Path):
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        raw = path.read_bytes()
        yield path.relative_to(root).as_posix(), raw
        if path.suffix == ".whl" and path.name.startswith("eggy_map_api-"):
            with zipfile.ZipFile(path) as archive:
                for name in archive.namelist():
                    if name.endswith((".py", ".json", ".md", ".yaml", ".toml")):
                        yield f"{path.name}!{name}", archive.read(name)


def index_tokens(path: Path) -> set[bytes]:
    if not path.is_file():
        return set()
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return set()
    rows = document.get("map_conf", {})
    if not isinstance(rows, dict):
        return set()
    names = {
        value["name"].encode("utf-8")
        for value in rows.values()
        if isinstance(value, dict)
        and isinstance(value.get("name"), str)
        and value["name"]
    }
    identifiers = {
        key.encode("utf-8")
        for key in rows
        if isinstance(key, str) and len(key.encode("utf-8")) >= 8
    }
    return names | identifiers


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reject task-specific data in a built plugin"
    )
    parser.add_argument("plugin", type=Path)
    parser.add_argument("--forbidden-index", action="append", type=Path, default=[])
    parser.add_argument(
        "--forbidden-index-root", action="append", type=Path, default=[]
    )
    args = parser.parse_args()
    forbidden_names: set[bytes] = set()
    for index in args.forbidden_index:
        forbidden_names.update(index_tokens(index))
    for root in args.forbidden_index_root:
        for index in root.expanduser().resolve().rglob("*.conf"):
            forbidden_names.update(index_tokens(index))
    failures: list[str] = []
    for name, raw in payloads(args.plugin.resolve()):
        if any(pattern.search(raw) for pattern in GENERIC_FORBIDDEN):
            failures.append(name)
            continue
        if any(token in raw for token in forbidden_names):
            failures.append(name)
    if failures:
        raise SystemExit("privacy scan failed: " + ", ".join(sorted(set(failures))))
    print(f"privacy scan passed: {args.plugin.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

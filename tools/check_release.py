#!/usr/bin/env python3
"""Check release contents, local links, plugin shape, and optional private tokens.

The optional identity file stays outside the repository. Diagnostics print paths
and rule names only, never the token that triggered a finding.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOP_LEVEL = {
    ".github",
    ".gitignore",
    "LICENSE",
    "README.md",
    "THIRD_PARTY_NOTICES.md",
    "pyproject.toml",
    "src",
    "tests",
    "tools",
    "docs",
    "plugin",
}
SOURCE_SUFFIXES = {".py", ".md", ".json", ".yaml", ".yml", ".toml", ".sh"}
SKILL_NAMES = {"eggy-map-designer", "eggy-component-finder", "eggy-map-code-editor"}
PERSONAL_PATH = re.compile(rb"/(?:Users|home)/[A-Za-z0-9_.-]+/")
MAP_CODE = re.compile(rb"(?<![0-9])[0-9]{4}-[0-9]{4}(?![0-9])")


def source_files(root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"], capture_output=True, check=False
    )
    if result.returncode == 0 and result.stdout:
        return [root / name for name in result.stdout.decode().split("\0") if name]
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file()
        and path.relative_to(root).parts[0] in TOP_LEVEL
        and "__pycache__" not in path.parts
        and ".egg-info" not in str(path)
    )


def private_tokens(path: Path | None) -> list[bytes]:
    if path is None:
        return []
    data = json.loads(path.read_text())
    if isinstance(data, list):
        values = data
    else:
        values = (
            list(data.get("names", {}))
            + list(data.get("slugs", {}))
            + data.get("identifiers", [])
        )
    return [value.encode() for value in values if value and value != "蛋仔派对"]


def privacy_findings(name: str, content: bytes, tokens: list[bytes]) -> list[str]:
    findings = []
    if PERSONAL_PATH.search(content):
        findings.append(f"{name}: personal-path")
    if MAP_CODE.search(content):
        findings.append(f"{name}: map-code-pattern")
    if any(
        token in content
        or token in name.encode()
        or json.dumps(token.decode(), ensure_ascii=True)[1:-1].encode() in content
        for token in tokens
    ):
        findings.append(f"{name}: private-identity")
    return findings


def check_plugin(plugin: Path) -> list[str]:
    failures = []
    manifest = json.loads((plugin / ".codex-plugin/plugin.json").read_text())
    if manifest.get("name") != "eggy-map-tools" or plugin.name != "eggy-map-tools":
        failures.append("plugin identity mismatch")
    if (
        manifest.get("skills") != "./skills/"
        or manifest.get("mcpServers") != "./.mcp.json"
    ):
        failures.append("plugin entrypoints mismatch")
    found = {p.name for p in (plugin / "skills").iterdir() if p.is_dir()}
    if found != SKILL_NAMES:
        failures.append("plugin must contain exactly three public skills")
    for name in SKILL_NAMES:
        content = (plugin / "skills" / name / "SKILL.md").read_text()
        if (
            not content.startswith("---\n")
            or f"name: {name}\n" not in content
            or "description:" not in content
        ):
            failures.append(f"{name}: invalid skill frontmatter")
    return failures


def check_links(files: list[Path]) -> list[str]:
    failures = []
    for path in files:
        if path.suffix != ".md":
            continue
        for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", path.read_text()):
            target = target.strip("<>").split("#", 1)[0]
            if not target or re.match(r"[a-z]+://|mailto:", target):
                continue
            if not (path.parent / target).is_file():
                failures.append(f"{path.name}: broken local link {target}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--plugin", type=Path)
    parser.add_argument("--private-identities", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    tokens = private_tokens(args.private_identities)
    if args.plugin:
        plugin = args.plugin.resolve()
        files = [p for p in plugin.rglob("*") if p.is_file()]
    else:
        plugin = root / "plugin/eggy-map-tools"
        files = source_files(root)
    failures = check_plugin(plugin)
    for path in files:
        base = plugin if args.plugin else root
        name = path.relative_to(base).as_posix()
        if not args.plugin:
            if path.relative_to(root).parts[0] not in TOP_LEVEL:
                failures.append(f"{name}: outside-source-allowlist")
            if path.suffix not in SOURCE_SUFFIXES and path.name not in {
                "LICENSE",
                ".gitignore",
            }:
                failures.append(f"{name}: forbidden-source-file-type")
            if path.is_symlink():
                failures.append(f"{name}: symlink-not-permitted")
        failures += privacy_findings(name, path.read_bytes(), tokens)
        if args.plugin and path.suffix == ".zst":
            import zstandard

            with path.open("rb") as stream:
                with zstandard.ZstdDecompressor().stream_reader(stream) as reader:
                    failures += privacy_findings(
                        name + "!decoded", reader.read(), tokens
                    )
        if path.suffix == ".whl" and path.name.startswith("eggy_map_api-"):
            with zipfile.ZipFile(path) as archive:
                for member in archive.namelist():
                    failures += privacy_findings(
                        f"{name}!{member}", archive.read(member), tokens
                    )
    failures += check_links(files)
    if failures:
        print("\n".join(sorted(set(failures))))
        return 1
    print(f"Release checks passed: {len(files)} files; identity input remains private.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

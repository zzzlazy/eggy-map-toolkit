#!/usr/bin/env python3
"""Run the portable design skill's existing behavioral checks."""

import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "plugin/eggy-map-tools/skills/eggy-map-designer"


def main() -> None:
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    scripts = sorted(
        p for p in (SKILL / "scripts").glob("*.py") if "--self-test" in p.read_text()
    )
    for script in scripts:
        subprocess.run(
            [sys.executable, str(script), "--self-test"], cwd=SKILL, env=env, check=True
        )
    subprocess.run(
        [
            sys.executable,
            str(SKILL / "scripts/audit_research_coverage.py"),
            "--design-packet",
            "--primary",
            "short_race",
            "--visual-world",
            "canyon_mountain_cave",
        ],
        cwd=SKILL,
        env=env,
        stdout=subprocess.DEVNULL,
        check=True,
    )
    print(f"Designer checks passed: {len(scripts)} self-tests and reference packet")


if __name__ == "__main__":
    main()

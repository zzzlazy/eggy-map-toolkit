from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from .errors import CapabilityError, ValidationError
from .models import ApplyResult, PatchPlan
from .runtime_rebuild import apply_runtime_rebuild
from .validate import validate


def apply(plan: PatchPlan, *, output: str | Path) -> ApplyResult:
    """Apply only a byte-complete plan into a new directory.

    Mutation handlers are intentionally not inferred from static candidates. A
    profile must register implementations before any business action can run.
    """
    validate(plan, level="strict-local")
    target = Path(output).expanduser().resolve()
    if target.exists():
        raise ValidationError(f"fresh output directory already exists: {target}")
    if plan.cache_strategy == "runtime-rebuild":
        return apply_runtime_rebuild(plan, target)
    business = [action for action in plan.actions if action.kind not in {"reuse"}]
    if business:
        raise CapabilityError(
            "matched mutation handlers are not registered; refusing to emit a partial map"
        )
    shutil.copytree(plan.snapshot.root, target, copy_function=shutil.copy2)
    hashes: dict[str, tuple[str, str]] = {}
    for item in sorted(target.rglob("*")):
        if item.is_file():
            raw = item.read_bytes()
            hashes[item.relative_to(target).as_posix()] = (
                hashlib.sha256(raw).hexdigest(),
                hashlib.blake2b(raw).hexdigest(),
            )
    return ApplyResult(plan=plan, output=target, hashes=hashes)

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .errors import CapabilityError
from .graph import ReferenceGraph

LOGIC_FILES = frozenset(
    {
        "triggereditor.mm",
        "globaltrigger.mm",
        "triggereditorruntime.mm",
        "customevent.mm",
        "ecapath.mm",
        "eui.mm",
        "dialog.mm",
        "eggimon.mm",
    }
)


def prune_logic(
    deleted_unit_ids: Iterable[int],
    preserve_manifest_refs: Iterable[int],
    *,
    graph: ReferenceGraph,
) -> dict[str, Any]:
    deleted = frozenset(deleted_unit_ids)
    preserved = frozenset(preserve_manifest_refs)
    if deleted & preserved:
        raise CapabilityError("a unit cannot be both deleted and preserved")
    refs = [
        ref
        for ref in graph.references
        if ref.file in LOGIC_FILES and ref.unit_id in deleted
    ]
    if refs:
        raise CapabilityError(
            "logic pruning requires a versioned slot profile; referenced deleted units: "
            + ", ".join(str(ref.unit_id) for ref in refs[:12])
        )
    return {"deleted_unit_ids": tuple(sorted(deleted)), "changed_files": ()}

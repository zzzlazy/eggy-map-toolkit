from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from .errors import SnapshotError
from .models import MapSnapshot


@dataclass(frozen=True)
class Reference:
    file: str
    path: str
    unit_id: int
    classification: str


@dataclass(frozen=True)
class ReferenceGraph:
    unit_ids: frozenset[int]
    unit_eids: dict[int, int]
    parents: dict[int, int]
    children: dict[int, tuple[int, ...]]
    references: tuple[Reference, ...]
    unknown_references: tuple[Reference, ...]

    def refs_to(self, unit_id: int) -> tuple[Reference, ...]:
        return tuple(ref for ref in self.references if ref.unit_id == unit_id)


KNOWN_REFERENCE_FILES = {
    "unit.mm",
    "uniteditor.mm",
    "editingcachewithlevel.mm",
    "editingcache.mm",
    "preloadres.mm",
    "newpreloadres.mm",
    "staticobstacle.mm",
    "commonl10ndata.mm",
}


def _bget(mapping: dict[Any, Any], name: str, default: Any = None) -> Any:
    return mapping.get(name, mapping.get(name.encode(), default))


def _walk(
    value: Any, unit_ids: frozenset[int], file: str, path: str = "$"
) -> Iterable[Reference]:
    if type(value) is int and value in unit_ids:
        classification = (
            "known-container"
            if file in KNOWN_REFERENCE_FILES
            else "unclassified-container"
        )
        yield Reference(
            file=file, path=path, unit_id=value, classification=classification
        )
    elif isinstance(value, dict):
        for key, child in value.items():
            if type(key) is int and key in unit_ids:
                classification = (
                    "known-container"
                    if file in KNOWN_REFERENCE_FILES
                    else "unclassified-container"
                )
                yield Reference(
                    file=file,
                    path=f"{path}.<key:{key}>",
                    unit_id=key,
                    classification=classification,
                )
            yield from _walk(child, unit_ids, file, f"{path}.{key!r}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            yield from _walk(child, unit_ids, file, f"{path}[{index}]")


def build_reference_graph(snapshot: MapSnapshot) -> ReferenceGraph:
    unit_data = snapshot.decoded("unit.mm")
    if not isinstance(unit_data, dict):
        raise SnapshotError("unit.mm root is not a map")
    units = _bget(unit_data, "unit")
    if not isinstance(units, dict):
        raise SnapshotError("unit.mm has no unit map")
    ids = frozenset(key for key in units if type(key) is int)
    if len(ids) != len(units):
        raise SnapshotError("unit.mm contains non-integer unit keys")
    eids: dict[int, int] = {}
    parents: dict[int, int] = {}
    children: dict[int, tuple[int, ...]] = {}
    for unit_id, unit in units.items():
        if not isinstance(unit, dict):
            raise SnapshotError(f"unit {unit_id} is not a map")
        embedded = _bget(unit, "unit_id")
        eid = _bget(unit, "eid")
        parent = _bget(unit, "parent_unit_id", 0)
        child_rows = _bget(unit, "children_unit_id", [])
        if (
            embedded != unit_id
            or type(eid) is not int
            or type(parent) is not int
            or not isinstance(child_rows, list)
        ):
            raise SnapshotError(
                f"unit {unit_id} has malformed identity or hierarchy fields"
            )
        if not all(type(child) is int for child in child_rows):
            raise SnapshotError(f"unit {unit_id} has malformed child IDs")
        eids[unit_id] = eid
        parents[unit_id] = parent
        children[unit_id] = tuple(child_rows)
    for unit_id, parent in parents.items():
        if parent and parent not in ids:
            raise SnapshotError(f"unit {unit_id} has missing parent {parent}")
    for unit_id, child_ids in children.items():
        for child in child_ids:
            if child not in ids or parents[child] != unit_id:
                raise SnapshotError(f"unit {unit_id} has inconsistent child {child}")
    for start in ids:
        seen: set[int] = set()
        current = start
        while current:
            if current in seen:
                raise SnapshotError(f"hierarchy cycle involving unit {start}")
            seen.add(current)
            current = parents[current]
    refs: list[Reference] = []
    for name, record in snapshot.files.items():
        if record.decoded is not None:
            refs.extend(_walk(record.decoded, ids, name))
    unknown = tuple(
        ref for ref in refs if ref.classification == "unclassified-container"
    )
    return ReferenceGraph(ids, eids, parents, children, tuple(refs), unknown)


def deletion_closure(graph: ReferenceGraph, roots: Iterable[int]) -> frozenset[int]:
    result: set[int] = set()
    pending = list(roots)
    while pending:
        current = pending.pop()
        if current in result:
            continue
        if current not in graph.unit_ids:
            raise SnapshotError(f"cannot delete missing unit {current}")
        result.add(current)
        pending.extend(graph.children[current])
    return frozenset(result)

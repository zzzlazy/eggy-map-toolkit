from __future__ import annotations

from collections import defaultdict
from typing import Any

from .capabilities import validate_component_spec
from .errors import CapabilityError, ValidationError
from .graph import build_reference_graph, deletion_closure
from .models import CourseManifest, MapSnapshot, PatchPlan, PlanAction
from .profiles import ResolvedProfile


def _get(mapping: dict[Any, Any], key: str, default: Any = None) -> Any:
    return mapping.get(key, mapping.get(key.encode(), default))


def _unit_name(unit: dict[Any, Any]) -> str | None:
    value = _get(unit, "name")
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return None
    return value if isinstance(value, str) else None


def plan_reconcile(
    *,
    snapshot: MapSnapshot,
    manifest: CourseManifest,
    profile: ResolvedProfile,
    cleanup_policy: str = "whitelist",
    managed_prefix: str | None = None,
) -> PatchPlan:
    if cleanup_policy not in {"managed_only", "whitelist"}:
        raise ValidationError("cleanup_policy must be 'managed_only' or 'whitelist'")
    if managed_prefix is not None and (not managed_prefix or "\x00" in managed_prefix):
        raise ValidationError("managed_prefix must be non-empty and contain no NUL")
    graph = build_reference_graph(snapshot)
    raw_unit = snapshot.decoded("unit.mm")
    units = _get(raw_unit, "unit")
    if not isinstance(units, dict):
        raise ValidationError("unit.mm unit table is malformed")

    desired_by_key = {
        (spec.logical_name, spec.eid): spec for spec in manifest.components
    }
    if len(desired_by_key) != len(manifest.components):
        raise ValidationError("manifest contains duplicate logical_name + EID keys")
    existing_by_key: dict[tuple[str, int], list[int]] = defaultdict(list)
    for unit_id, unit in units.items():
        if isinstance(unit, dict):
            name = _unit_name(unit)
            eid = _get(unit, "eid")
            if name is not None and type(eid) is int:
                existing_by_key[(name, eid)].append(unit_id)

    actions: list[PlanAction] = []
    blockers: list[str] = []
    warnings: list[str] = []
    runtime_rebuild = profile.cache_strategy == "runtime-rebuild"
    keep: set[int] = set()
    explicitly_deleted: set[int] = set()
    for key, spec in desired_by_key.items():
        matches = sorted(existing_by_key.get(key, []))
        if matches:
            keeper = matches[0]
            keep.add(keeper)
            if graph.parents[keeper] != 0 or graph.children[keeper]:
                blockers.append(
                    f"EID {spec.eid}: matched component is not a flat top-level unit"
                )
            actions.append(PlanAction("reuse", spec.logical_name, spec.eid, keeper))
            actions.append(
                PlanAction(
                    "update",
                    spec.logical_name,
                    spec.eid,
                    keeper,
                    {
                        "transform": spec.transform,
                        "color": spec.color,
                        "properties": dict(spec.properties),
                    },
                )
            )
            duplicates = matches[1:]
            for unit_id in duplicates:
                explicitly_deleted.add(unit_id)
                actions.append(
                    PlanAction(
                        "delete",
                        spec.logical_name,
                        spec.eid,
                        unit_id,
                        {"reason": "duplicate"},
                    )
                )
        else:
            actions.append(
                PlanAction(
                    "create",
                    spec.logical_name,
                    spec.eid,
                    None,
                    {
                        "transform": spec.transform,
                        "color": spec.color,
                        "properties": dict(spec.properties),
                    },
                )
            )
        if runtime_rebuild:
            try:
                validate_component_spec(spec, profile.catalog)
            except CapabilityError as exc:
                blockers.append(str(exc))
        else:
            try:
                component_profile = profile.components.require_create(
                    spec.eid, snapshot, profile.catalog
                )
                if spec.color is not None and not component_profile.color_complete:
                    raise CapabilityError(
                        f"EID {spec.eid}: color closure is incomplete"
                    )
            except CapabilityError as exc:
                blockers.append(str(exc))

    delete_roots: list[int] = []
    for unit_id in sorted(graph.unit_ids):
        if (
            unit_id in keep
            or unit_id in explicitly_deleted
            or graph.parents[unit_id] != 0
        ):
            continue
        if cleanup_policy == "whitelist":
            delete_roots.append(unit_id)
        elif managed_prefix is not None:
            name = _unit_name(units[unit_id])
            if name is not None and name.startswith(managed_prefix):
                delete_roots.append(unit_id)
    delete_ids = deletion_closure(graph, (*delete_roots, *explicitly_deleted))
    for unit_id in delete_roots:
        actions.append(
            PlanAction(
                "delete",
                _unit_name(units[unit_id]),
                graph.unit_eids[unit_id],
                unit_id,
                {"reason": "not-in-whitelist"},
            )
        )
    if not runtime_rebuild:
        for eid in sorted({graph.unit_eids[unit_id] for unit_id in delete_ids}):
            try:
                profile.components.require_delete(eid, snapshot, profile.catalog)
            except CapabilityError as exc:
                blockers.append(str(exc))
    unknown_delete_refs = [
        ref for ref in graph.unknown_references if ref.unit_id in delete_ids
    ]
    if unknown_delete_refs:
        blockers.append(
            "unclassified reverse references prevent deletion: "
            + ", ".join(f"{ref.file}:{ref.path}" for ref in unknown_delete_refs[:12])
        )

    for key, value in manifest.map_settings.items():
        actions.append(PlanAction("setting", details={"key": key, "value": value}))
    actions.append(
        PlanAction(
            "logic-prune", details={"deleted_unit_ids": tuple(sorted(delete_ids))}
        )
    )
    if not profile.allocator_complete and any(
        action.kind == "create" for action in actions
    ):
        blockers.append(
            "instance-ID/create-index allocator is not resolved for the matched package"
        )
    if not profile.desc_write_complete and manifest.map_settings:
        blockers.append("desc.mm write profile is not byte-complete")
    if runtime_rebuild:
        if not 1 <= profile.compression_level <= 22:
            blockers.append("runtime rebuild compression level must be in 1..22")
        warnings.extend(
            (
                "derived editor/load/preload/native/collision caches will be invalidated",
                "the current game process must rebuild derived caches on first open",
                "the game must not be saved until the rebuilt map is visually checked",
                "logic files are preserved byte-for-byte and referenced deletions are rejected",
            )
        )
    else:
        if not profile.logic_cleanup_complete:
            blockers.append(
                "logic reverse-reference cleanup profile is not byte-complete"
            )
        if not profile.transaction_complete:
            blockers.append(
                "multi-file transaction/save-UUID profile is not byte-complete"
            )
    return PatchPlan(
        snapshot=snapshot,
        catalog=profile.catalog,
        manifest=manifest,
        actions=tuple(actions),
        blockers=tuple(dict.fromkeys(blockers)),
        warnings=tuple(warnings),
        cleanup_policy=cleanup_policy,  # type: ignore[arg-type]
        profile_fingerprint=profile.fingerprint,
        cache_strategy=profile.cache_strategy,
        system_template=profile.system_template,
        compression_level=profile.compression_level,
    )

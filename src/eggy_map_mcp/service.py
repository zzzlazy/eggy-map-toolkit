from __future__ import annotations

import hashlib
import os
import shutil
import uuid
from collections import Counter
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from eggy_map_api.apply import apply
from eggy_map_api.capabilities import validate_component_spec
from eggy_map_api.catalog_bundle import CompiledCatalog
from eggy_map_api.component_builder import apply_component_addition_with_runtime_rebuild
from eggy_map_api.component_delete import apply_component_deletions
from eggy_map_api.device import (
    AdbClient,
    DeviceContext,
    discover_device,
    freeze_device_triplet,
    list_device_maps,
    read_remote_state,
)
from eggy_map_api.errors import CapabilityError, StateError, ValidationError
from eggy_map_api.graph import build_reference_graph
from eggy_map_api.models import (
    ComponentSpec,
    CourseManifest,
    MapSnapshot,
    TransformSpec,
    WorldAABB,
)
from eggy_map_api.planner import plan_reconcile
from eggy_map_api.profiles import ProfileRegistry, ResolvedProfile
from eggy_map_api.snapshot import open_snapshot
from eggy_map_api.state import StateStore, StoredDeployment, StoredMapRef
from eggy_map_api.transaction import BuildResult, TransactionCoordinator
from eggy_map_api.validate import (
    validate,
    validate_manifest,
    validate_snapshot_integrity,
)

from .schemas import ReconcileManifestInput, TransformInput

MAP_SETTING_SCHEMA: dict[str, type] = {
    "map_recommend_play_num": int,
    "min_play_num": int,
    "min_play_num_new": int,
    "max_game_time": int,
}


def default_data_directory() -> Path:
    configured = os.getenv("EGGY_MAP_DATA_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return (
        Path.home() / "Library" / "Application Support" / "eggy-map-tools"
    ).resolve()


def _get(mapping: Mapping[Any, Any], key: str, default: Any = None) -> Any:
    return mapping.get(key, mapping.get(key.encode(), default))


def _name(unit: Mapping[Any, Any]) -> str | None:
    value = _get(unit, "name")
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return None
    return value if isinstance(value, str) else None


def _transform(value: TransformInput) -> TransformSpec:
    return TransformSpec(
        world_aabb=WorldAABB(center=value.center, size=value.size),
        rotation_deg=value.rotation_deg,
        forward_axis=value.forward_axis,
    )


def _public_vec3(value: Any) -> list[float] | None:
    if not isinstance(value, (list, tuple)) or len(value) < 3:
        return None
    result = value[:3]
    if not all(type(item) in (int, float) for item in result):
        return None
    return [float(item) for item in result]


def _receipt_payload(receipt: Any) -> dict[str, Any]:
    if receipt.operation == "reset_upload_failure":
        next_step = (
            "Try deleting the map from the game map list. If the UI still reports an active "
            "upload, the persistent failure flag is already clear but the running game still "
            "holds an in-memory upload lock; manually fully close and reopen the game, then "
            "delete the map without opening or saving it."
        )
    else:
        next_step = (
            "Manually open the map in edit mode without entering run mode. "
            "If it is correct, save and exit. If it is wrong, exit without saving and call rollback."
        )
    return {
        "deployment_id": receipt.deployment_id,
        "map_ref": receipt.map_ref,
        "backup_id": receipt.backup_id,
        "operation": receipt.operation,
        "status": receipt.status,
        "changed_files": list(receipt.changed_files),
        "validation_checks": list(receipt.validation_checks),
        "next_step": next_step,
    }


class EggyMapService:
    def __init__(
        self,
        *,
        catalog_manifest: str | Path,
        data_directory: str | Path | None = None,
        adb: AdbClient | None = None,
    ) -> None:
        self.store = StateStore(data_directory or default_data_directory())
        self.catalog = CompiledCatalog(
            catalog_manifest, data_directory=self.store.catalog
        )
        self._adb = adb
        self._transactions: TransactionCoordinator | None = None
        self._package_catalog = None

    @property
    def adb(self) -> AdbClient:
        # Catalog queries and MCP discovery must not require device tooling.
        if self._adb is None:
            self._adb = AdbClient()
        return self._adb

    @property
    def transactions(self) -> TransactionCoordinator:
        if self._transactions is None:
            self._transactions = TransactionCoordinator(
                adb=self.adb, store=self.store, catalog=self.catalog
            )
        return self._transactions

    def _runtime_catalog(self):
        if self._package_catalog is None:
            self._package_catalog = self.catalog.package_catalog()
        return self._package_catalog

    def _discover(self, *, verify_apk: bool) -> DeviceContext:
        return discover_device(
            self.adb, game_profile=self.catalog.game_profile, verify_apk=verify_apk
        )

    def _resolve_current(self, map_ref: str) -> tuple[StoredMapRef, DeviceContext, Any]:
        stored = self.store.resolve_map(map_ref)
        device = self._discover(verify_apk=True)
        if (
            stored.serial != device.serial
            or stored.package != device.package
            or stored.maps_root != device.maps_root
        ):
            raise StateError(
                "map_ref belongs to another device or package", code="MAP_REF_INVALID"
            )
        state = read_remote_state(self.adb, device, stored.location)
        if state.revision != stored.revision:
            raise StateError("map_ref is stale", code="STALE_MAP_REF")
        return stored, device, state

    @contextmanager
    def _read_snapshot(
        self, map_ref: str
    ) -> Iterator[tuple[StoredMapRef, DeviceContext, Any, MapSnapshot]]:
        stored, device, state = self._resolve_current(map_ref)
        destination = self.store.work / f"read_{uuid.uuid4().hex}"
        try:
            frozen = freeze_device_triplet(
                self.adb, device, stored.location, destination
            )
            if frozen.state != state:
                raise StateError("map changed during read", code="STALE_MAP_REF")
            yield stored, device, state, open_snapshot(destination / "map")
        finally:
            if destination.exists():
                shutil.rmtree(destination)

    def device_status(self) -> dict[str, Any]:
        device = self._discover(verify_apk=True)
        return {
            "online_device_count": 1,
            "platform_profile": "mumu-macos",
            "game_version": {
                "version_code": device.version_code,
                "version_name": device.version_name,
            },
            "game_process_running": bool(device.pid),
            "root_available": device.root_available,
            "profile_match": device.profile_match,
            "mode": "writable" if device.writable else "read_only",
            "catalog_counts": self.catalog.counts,
        }

    def list_maps(
        self, exact_name: str | None = None, include_archived: bool = False
    ) -> dict[str, Any]:
        device = self._discover(verify_apk=True)
        maps = list_device_maps(
            self.adb,
            device,
            exact_name=exact_name,
            include_archived=include_archived,
        )
        counts = Counter(row.name for row in maps)
        items = []
        for location in maps:
            state = read_remote_state(self.adb, device, location)
            map_ref = self.store.register_map(device, location, state.revision)
            items.append(
                {
                    "map_ref": map_ref,
                    "name": location.name,
                    "save_time": location.save_time,
                    "duplicate_name": counts[location.name] > 1,
                    "profile_mode": "writable" if device.profile_match else "read_only",
                }
            )
        return {"items": items, "count": len(items)}

    def search_components(
        self,
        query: str = "",
        kind: str | None = None,
        family: str | None = None,
        static_status: str | None = None,
        writable_only: bool = False,
        limit: int = 50,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        return self.catalog.search(
            query,
            kind=kind,
            family=family,
            static_status=static_status,
            writable_only=writable_only,
            limit=limit,
            cursor=cursor,
        )

    def get_component(
        self, component_ref: str | None = None, eid: int | None = None
    ) -> dict[str, Any]:
        return self.catalog.get(component_ref, eid=eid)

    def inspect_map(self, map_ref: str) -> dict[str, Any]:
        with self._read_snapshot(map_ref) as (_stored, device, state, snapshot):
            graph = build_reference_graph(snapshot)
            units = _get(snapshot.decoded("unit.mm"), "unit")
            assert isinstance(units, dict)
            refs = {
                unit_id: self.store.register_unit(map_ref, unit_id, state.revision)
                for unit_id in sorted(graph.unit_ids)
            }
            catalog = self._runtime_catalog()
            rows = []
            for unit_id in sorted(graph.unit_ids):
                unit = units[unit_id]
                eid = graph.unit_eids[unit_id]
                entry = catalog.entries.get(eid)
                rows.append(
                    {
                        "unit_ref": refs[unit_id],
                        "logical_name": _name(unit),
                        "eid": eid,
                        "structural_family": entry.structural_family
                        if entry
                        else "unknown",
                        "parent_unit_ref": refs.get(graph.parents[unit_id]),
                        "child_count": len(graph.children[unit_id]),
                        "position": _public_vec3(_get(unit, "world_position")),
                        "rotation_deg": _public_vec3(_get(unit, "model_angle")),
                        "scale": _public_vec3(_get(unit, "scale")),
                    }
                )
            return {
                "map_ref": map_ref,
                "profile_mode": "writable" if device.profile_match else "read_only",
                "component_count": len(rows),
                "components": rows,
                "unknown_reference_count": len(graph.unknown_references),
            }

    def validate_map(self, map_ref: str) -> dict[str, Any]:
        with self._read_snapshot(map_ref) as (_stored, device, _state, snapshot):
            report = validate_snapshot_integrity(snapshot)
            return {
                "map_ref": map_ref,
                "valid": True,
                "checks": list(report.checks),
                "warnings": list(report.warnings),
                "profile_mode": "writable" if device.profile_match else "read_only",
            }

    def _validate_map_settings(self, settings: Mapping[str, Any]) -> None:
        unknown = sorted(set(settings) - set(MAP_SETTING_SCHEMA))
        if unknown:
            raise ValidationError("unsupported map settings: " + ", ".join(unknown))
        for key, value in settings.items():
            if type(value) is not MAP_SETTING_SCHEMA[key] or value < 0:
                raise ValidationError(
                    f"map setting {key!r} must be a non-negative integer"
                )

    def add_component(
        self,
        *,
        map_ref: str,
        component_ref: str,
        logical_name: str,
        transform: TransformInput,
        color: tuple[int, int, int] | None = None,
        properties: dict[str, Any] | None = None,
        editor_closed_confirmed: bool = False,
    ) -> dict[str, Any]:
        component = self.catalog.get(component_ref)
        if component["kind"] != "unit" or not component["write_capability"]["writable"]:
            raise CapabilityError(
                "component is not writable in the active catalog profile",
                context=component["write_capability"],
            )
        spec = ComponentSpec(
            logical_name=logical_name,
            eid=int(component["eid"]),
            transform=_transform(transform),
            color=color,
            properties=dict(properties or {}),
        )
        runtime_catalog = self._runtime_catalog()
        validate_component_spec(spec, runtime_catalog)

        def builder(snapshot: MapSnapshot, output: Path) -> BuildResult:
            result, _unit_id = apply_component_addition_with_runtime_rebuild(
                snapshot, spec, catalog=runtime_catalog, output=output
            )
            checks = validate_snapshot_integrity(open_snapshot(result)).checks
            return BuildResult(result, checks + ("single-component-addition",))

        receipt, _remote = self.transactions.execute(
            map_ref=map_ref,
            operation="add",
            editor_closed_confirmed=editor_closed_confirmed,
            builder=builder,
        )
        return _receipt_payload(receipt)

    def delete_components(
        self,
        *,
        map_ref: str,
        unit_refs: list[str],
        editor_closed_confirmed: bool = False,
    ) -> dict[str, Any]:
        if not unit_refs or len(unit_refs) != len(set(unit_refs)):
            raise ValidationError("unit_refs must be a non-empty unique list")
        resolved = [
            self.store.resolve_unit(value, map_ref=map_ref) for value in unit_refs
        ]
        stored = self.store.resolve_map(map_ref)
        if any(row.revision != stored.revision for row in resolved):
            raise StateError(
                "one or more unit_ref values are stale", code="STALE_MAP_REF"
            )
        unit_ids = [row.unit_id for row in resolved]

        def builder(snapshot: MapSnapshot, output: Path) -> BuildResult:
            result = apply_component_deletions(snapshot, unit_ids, output=output)
            checks = validate_snapshot_integrity(open_snapshot(result)).checks
            return BuildResult(result, checks + ("full-deletion-closure",))

        receipt, _remote = self.transactions.execute(
            map_ref=map_ref,
            operation="delete",
            editor_closed_confirmed=editor_closed_confirmed,
            builder=builder,
        )
        return _receipt_payload(receipt)

    def reset_map_upload_failure(
        self,
        *,
        map_ref: str,
        editor_closed_confirmed: bool = False,
    ) -> dict[str, Any]:
        receipt = self.transactions.reset_map_upload_failure(
            map_ref=map_ref,
            editor_closed_confirmed=editor_closed_confirmed,
        )
        result = _receipt_payload(receipt)
        result.update(
            {
                "upload_failure_before": True,
                "upload_failure_after": False,
                "cloud_upload_cancelled": False,
                "in_memory_upload_lock_cleared": False,
            }
        )
        return result

    def reconcile_map(
        self,
        *,
        manifest: ReconcileManifestInput,
        editor_closed_confirmed: bool = False,
    ) -> dict[str, Any]:
        map_ref = manifest.map_ref
        self._validate_map_settings(manifest.map_settings)
        specs: list[ComponentSpec] = []
        for row in manifest.components:
            component = self.catalog.get(row.component_ref)
            if (
                component["kind"] != "unit"
                or not component["write_capability"]["writable"]
            ):
                raise CapabilityError(
                    f"component {row.logical_name!r} is not writable",
                    context=component["write_capability"],
                )
            specs.append(
                ComponentSpec(
                    logical_name=row.logical_name,
                    eid=int(component["eid"]),
                    transform=_transform(row.transform),
                    color=row.color,
                    properties=dict(row.properties),
                    role=row.role,
                )
            )
        course = CourseManifest(
            schema_version=manifest.schema_version,
            components=tuple(specs),
            map_settings=dict(manifest.map_settings),
            constraints=dict(manifest.constraints),
        )
        runtime_catalog = self._runtime_catalog()
        profile = ResolvedProfile(
            catalog=runtime_catalog,
            components=ProfileRegistry(),
            allocator_complete=True,
            desc_write_complete=True,
            cache_strategy="runtime-rebuild",
        )
        validate_manifest(course, runtime_catalog)
        for spec in specs:
            validate_component_spec(spec, runtime_catalog)

        def builder(snapshot: MapSnapshot, output: Path) -> BuildResult:
            plan = plan_reconcile(
                snapshot=snapshot,
                manifest=course,
                profile=profile,
                cleanup_policy=manifest.cleanup_policy,
                managed_prefix=manifest.managed_prefix,
            )
            report = validate(plan)
            first = apply(plan, output=output)
            generated = open_snapshot(first.output)
            integrity = validate_snapshot_integrity(generated)
            second_plan = plan_reconcile(
                snapshot=generated,
                manifest=course,
                profile=profile,
                cleanup_policy=manifest.cleanup_policy,
                managed_prefix=manifest.managed_prefix,
            )
            idempotence = output.parent / "idempotence"
            second = apply(second_plan, output=idempotence)
            first_hash = {
                path.relative_to(first.output).as_posix(): hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()
                for path in first.output.rglob("*")
                if path.is_file()
            }
            second_hash = {
                path.relative_to(second.output).as_posix(): hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()
                for path in second.output.rglob("*")
                if path.is_file()
            }
            if first_hash != second_hash:
                raise ValidationError("second reconciliation is not byte-idempotent")
            checks = tuple(
                dict.fromkeys((*report.checks, *integrity.checks, "byte-idempotence"))
            )
            return BuildResult(first.output, checks)

        receipt, _remote = self.transactions.execute(
            map_ref=map_ref,
            operation="reconcile",
            editor_closed_confirmed=editor_closed_confirmed,
            builder=builder,
        )
        return _receipt_payload(receipt)

    @staticmethod
    def _deployment_payload(row: StoredDeployment) -> dict[str, Any]:
        return {
            "deployment_id": row.deployment_id,
            "operation": row.operation,
            "map_ref": row.map_ref,
            "backup_id": row.backup_id,
            "status": row.status,
            "changed_files": list(row.changed_files),
            "validation_checks": list(row.validation_checks),
        }

    def get_deployment(self, deployment_id: str) -> dict[str, Any]:
        return self._deployment_payload(self.store.get_deployment(deployment_id))

    def list_deployments(self, map_ref: str | None = None) -> dict[str, Any]:
        rows = self.store.list_deployments(map_ref)
        return {
            "items": [self._deployment_payload(row) for row in rows],
            "count": len(rows),
        }

    def rollback(
        self, *, deployment_id: str, editor_closed_confirmed: bool = False
    ) -> dict[str, Any]:
        receipt, _retained = self.transactions.rollback(
            deployment_id=deployment_id,
            editor_closed_confirmed=editor_closed_confirmed,
        )
        return _receipt_payload(receipt)

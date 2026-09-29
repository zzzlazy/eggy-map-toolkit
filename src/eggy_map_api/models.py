from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

Vec3 = tuple[float, float, float]
Color = tuple[int, int, int]


@dataclass(frozen=True)
class WorldAABB:
    center: Vec3
    size: Vec3

    @property
    def minimum(self) -> Vec3:
        return tuple(c - s / 2 for c, s in zip(self.center, self.size, strict=True))  # type: ignore[return-value]

    @property
    def maximum(self) -> Vec3:
        return tuple(c + s / 2 for c, s in zip(self.center, self.size, strict=True))  # type: ignore[return-value]

    def intersects(self, other: WorldAABB, *, touching: bool = True) -> bool:
        if touching:
            return all(
                a1 >= b0 and b1 >= a0
                for a0, a1, b0, b1 in zip(
                    self.minimum,
                    self.maximum,
                    other.minimum,
                    other.maximum,
                    strict=True,
                )
            )
        return all(
            a1 > b0 and b1 > a0
            for a0, a1, b0, b1 in zip(
                self.minimum, self.maximum, other.minimum, other.maximum, strict=True
            )
        )


@dataclass(frozen=True)
class TransformSpec:
    world_aabb: WorldAABB
    rotation_deg: Vec3 = (0.0, 0.0, 0.0)
    forward_axis: Literal["+x", "-x", "+z", "-z"] | None = None


@dataclass(frozen=True)
class ComponentSpec:
    logical_name: str
    eid: int
    transform: TransformSpec
    color: Color | None = None
    properties: Mapping[str, Any] = field(default_factory=dict)
    role: str = "obstacle"


@dataclass(frozen=True)
class CourseManifest:
    schema_version: int
    components: tuple[ComponentSpec, ...]
    map_settings: Mapping[str, Any]
    constraints: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FileRecord:
    relative_path: str
    size: int
    sha256: str
    blake2b: str
    mode: int
    uid: int
    gid: int
    raw: bytes
    decoded: Any | None = None


@dataclass(frozen=True)
class MapSnapshot:
    root: Path
    files: Mapping[str, FileRecord]
    format_fingerprint: str

    def decoded(self, name: str) -> Any:
        record = self.files.get(name)
        if record is None or record.decoded is None:
            raise KeyError(f"snapshot has no decoded file {name!r}")
        return record.decoded


@dataclass(frozen=True)
class CatalogEntry:
    eid: int
    name: str
    structural_family: str
    asset_type: str
    model_id: int | None
    model_path: str | None
    model_cell: Vec3 | None
    property_keys: tuple[str, ...]
    static_status: str
    evidence: str
    kind: Literal["unit", "effect"] = "unit"
    write_capability: bool = False
    write_blockers: tuple[str, ...] = ()
    supported_properties: tuple[str, ...] = ()
    color_supported: bool = False


@dataclass(frozen=True)
class PackageCatalog:
    root: Path
    entries: Mapping[int, CatalogEntry]
    fingerprint: str
    prefab_defaults: Mapping[int, Mapping[str, Any]] = field(default_factory=dict)
    model_defaults: Mapping[int, Mapping[str, Any]] = field(default_factory=dict)


@dataclass(frozen=True)
class ComponentProfile:
    eid: int
    package_fingerprint: str
    map_format_fingerprint: str
    prefab_complete: bool
    public_cache_complete: bool
    native_create_complete: bool
    native_delete_complete: bool
    transform_complete: bool
    color_complete: bool
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class OutputClosureProfile:
    """Exact per-family membership rules for derived output containers."""

    loader_version: Literal[1, 2]
    batch_task_by_eid: Mapping[int, bool]
    preload_cache_by_eid: Mapping[int, bool]
    loader_content_by_eid: Mapping[int, bool]
    unit_display_by_eid: Mapping[int, bool]
    preload_material_by_eid: Mapping[int, bool]
    static_obstacle_by_eid: Mapping[int, bool]
    character_start_by_eid: Mapping[int, bool]
    color_var_by_eid: Mapping[int, bytes | None]


@dataclass(frozen=True)
class PlanAction:
    kind: Literal["reuse", "create", "update", "delete", "setting", "logic-prune"]
    logical_name: str | None = None
    eid: int | None = None
    unit_id: int | None = None
    details: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PatchPlan:
    snapshot: MapSnapshot
    catalog: PackageCatalog
    manifest: CourseManifest
    actions: tuple[PlanAction, ...]
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    cleanup_policy: Literal["managed_only", "whitelist"]
    profile_fingerprint: str
    cache_strategy: Literal["strict", "runtime-rebuild"] = "strict"
    system_template: MapSnapshot | None = None
    compression_level: int = 3

    @property
    def deployable(self) -> bool:
        return not self.blockers


@dataclass(frozen=True)
class ApplyResult:
    plan: PatchPlan
    output: Path
    hashes: Mapping[str, tuple[str, str]]


@dataclass(frozen=True)
class DeploymentTarget:
    serial: str
    map_directory: str
    uid: int
    gid: int
    directory_mode: int
    file_modes: Mapping[str, int]
    backup_directory: Path
    remote_rollback_directory: str | None = None
    atomic_swap_complete: bool = False


@dataclass(frozen=True)
class DeploymentReceipt:
    deployment_id: str
    operation: Literal[
        "add", "delete", "reconcile", "reset_upload_failure", "rollback"
    ]
    map_ref: str
    backup_id: str
    input_revision: str
    output_revision: str
    changed_files: tuple[str, ...]
    validation_checks: tuple[str, ...]
    status: Literal["deployed", "rolled_back", "failed"]

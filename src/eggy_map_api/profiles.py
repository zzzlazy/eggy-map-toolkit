from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .errors import CapabilityError
from .models import ComponentProfile, MapSnapshot, PackageCatalog


@dataclass(frozen=True)
class ResolvedProfile:
    catalog: PackageCatalog
    components: ProfileRegistry
    allocator_complete: bool = False
    desc_write_complete: bool = False
    logic_cleanup_complete: bool = False
    transaction_complete: bool = False
    cache_strategy: Literal["strict", "runtime-rebuild"] = "strict"
    system_template: MapSnapshot | None = None
    compression_level: int = 3

    @property
    def fingerprint(self) -> str:
        payload = {
            "catalog": self.catalog.fingerprint,
            "components": self.components.fingerprint,
            "allocator_complete": self.allocator_complete,
            "desc_write_complete": self.desc_write_complete,
            "logic_cleanup_complete": self.logic_cleanup_complete,
            "transaction_complete": self.transaction_complete,
            "cache_strategy": self.cache_strategy,
            "system_template": (
                self.system_template.format_fingerprint
                if self.system_template is not None
                else None
            ),
            "compression_level": self.compression_level,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


class ProfileRegistry:
    def __init__(self, profiles: Mapping[int, ComponentProfile] | None = None) -> None:
        self._profiles = dict(profiles or {})

    def get(self, eid: int) -> ComponentProfile | None:
        return self._profiles.get(eid)

    def require_create(
        self, eid: int, snapshot: MapSnapshot, catalog: PackageCatalog
    ) -> ComponentProfile:
        profile = self.get(eid)
        if profile is None:
            raise CapabilityError(f"EID {eid}: no component profile")
        failures: list[str] = []
        if profile.package_fingerprint != catalog.fingerprint:
            failures.append("package fingerprint mismatch")
        if profile.map_format_fingerprint != snapshot.format_fingerprint:
            failures.append("map format fingerprint mismatch")
        if not profile.prefab_complete:
            failures.append("prefab construction is incomplete")
        if not profile.public_cache_complete:
            failures.append("public cache closure is incomplete")
        if not profile.native_create_complete:
            failures.append("native create-task closure is incomplete")
        if not profile.transform_complete:
            failures.append("transform closure is incomplete")
        if failures:
            raise CapabilityError(f"EID {eid}: " + "; ".join(failures))
        return profile

    def require_delete(
        self, eid: int, snapshot: MapSnapshot, catalog: PackageCatalog
    ) -> ComponentProfile:
        profile = self.require_create(eid, snapshot, catalog)
        if not profile.native_delete_complete:
            raise CapabilityError(
                f"EID {eid}: native delete-task closure is incomplete"
            )
        return profile

    def require_color(
        self, eid: int, snapshot: MapSnapshot, catalog: PackageCatalog
    ) -> ComponentProfile:
        profile = self.require_create(eid, snapshot, catalog)
        if not profile.color_complete:
            raise CapabilityError(f"EID {eid}: color closure is incomplete")
        return profile

    @property
    def fingerprint(self) -> str:
        rows = [vars(profile) for _, profile in sorted(self._profiles.items())]
        return hashlib.sha256(
            json.dumps(rows, sort_keys=True, default=list).encode()
        ).hexdigest()


def load_profiles(path: str | Path) -> ProfileRegistry:
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    profiles: dict[int, ComponentProfile] = {}
    for row in payload.get("profiles", []):
        profile = ComponentProfile(
            eid=int(row["eid"]),
            package_fingerprint=str(row["package_fingerprint"]),
            map_format_fingerprint=str(row["map_format_fingerprint"]),
            prefab_complete=bool(row["prefab_complete"]),
            public_cache_complete=bool(row["public_cache_complete"]),
            native_create_complete=bool(row["native_create_complete"]),
            native_delete_complete=bool(row["native_delete_complete"]),
            transform_complete=bool(row["transform_complete"]),
            color_complete=bool(row["color_complete"]),
            notes=tuple(str(note) for note in row.get("notes", [])),
        )
        if profile.eid in profiles:
            raise CapabilityError(f"duplicate component profile for EID {profile.eid}")
        profiles[profile.eid] = profile
    return ProfileRegistry(profiles)


def unresolved_profile_reasons(
    eids: Iterable[int],
    registry: ProfileRegistry,
    snapshot: MapSnapshot,
    catalog: PackageCatalog,
) -> tuple[str, ...]:
    reasons: list[str] = []
    for eid in sorted(set(eids)):
        try:
            registry.require_create(eid, snapshot, catalog)
        except CapabilityError as exc:
            reasons.append(str(exc))
    return tuple(reasons)

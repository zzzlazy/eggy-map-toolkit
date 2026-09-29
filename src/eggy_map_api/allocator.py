from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Protocol

from .errors import CapabilityError

PACKAGE_RANDOM_MIN = 1_000_000_000
PACKAGE_RANDOM_MAX = 2_147_483_647


class RandIntSource(Protocol):
    def randint(self, minimum: int, maximum: int) -> int: ...


@dataclass
class InstanceAllocator:
    """Package-derived unit-ID and per-EID creation-index allocator.

    The package calls ``random.randint`` over the signed-positive range.  The
    collision guard is an offline safety addition: a collision is retried and
    never silently overwrites an existing unit.
    """

    create_indices: dict[int, int]
    used_unit_ids: set[int]
    algorithm: str | None = None
    random_source: RandIntSource = field(default_factory=random.SystemRandom)
    max_attempts: int = 10_000

    def allocate(self, eid: int) -> tuple[int, int]:
        if self.algorithm != "package-randint-positive-i31":
            raise CapabilityError(
                f"EID {eid}: instance-ID generation algorithm is not resolved for this package/profile"
            )
        for _ in range(self.max_attempts):
            unit_id = self.random_source.randint(PACKAGE_RANDOM_MIN, PACKAGE_RANDOM_MAX)
            if type(unit_id) is int and unit_id not in self.used_unit_ids:
                break
        else:
            raise CapabilityError("unable to allocate a collision-free instance ID")
        self.used_unit_ids.add(unit_id)
        create_index = self.create_indices.get(eid, 0) + 1
        self.create_indices[eid] = create_index
        return unit_id, create_index

    def observe_deletion(self, _unit_id: int) -> None:
        """Deletion deliberately does not decrement the historical create index."""

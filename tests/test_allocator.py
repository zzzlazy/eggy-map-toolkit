import random

import pytest

from eggy_map_api.allocator import (
    PACKAGE_RANDOM_MAX,
    PACKAGE_RANDOM_MIN,
    InstanceAllocator,
)
from eggy_map_api.errors import CapabilityError


def test_package_allocator_range_and_monotonic_per_eid() -> None:
    allocator = InstanceAllocator(
        create_indices={7: 4},
        used_unit_ids=set(),
        algorithm="package-randint-positive-i31",
        random_source=random.Random(3),
    )
    first_id, first_index = allocator.allocate(7)
    second_id, second_index = allocator.allocate(7)
    _, other_index = allocator.allocate(9)
    assert PACKAGE_RANDOM_MIN <= first_id <= PACKAGE_RANDOM_MAX
    assert PACKAGE_RANDOM_MIN <= second_id <= PACKAGE_RANDOM_MAX
    assert first_id != second_id
    assert (first_index, second_index, other_index) == (5, 6, 1)


def test_allocator_fails_closed_without_package_algorithm() -> None:
    allocator = InstanceAllocator(create_indices={}, used_unit_ids=set())
    with pytest.raises(CapabilityError, match="not resolved"):
        allocator.allocate(7)

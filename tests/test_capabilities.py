from pathlib import Path
from types import SimpleNamespace

import pytest

from eggy_map_api.capabilities import (
    runtime_component_capability,
    validate_component_spec,
)
from eggy_map_api.errors import CapabilityError
from eggy_map_api.models import (
    CatalogEntry,
    ComponentSpec,
    PackageCatalog,
    TransformSpec,
    WorldAABB,
)
from eggy_map_api.runtime_rebuild import build_runtime_rebuild_unit


def make_catalog() -> PackageCatalog:
    families = {
        11: ("editor_unit", 256, True),
        12: ("editor_decoration", 1024, False),
        13: ("editor_trigger", 512, True),
        14: ("editor_virtual_point", 16384, False),
    }
    entries = {
        eid: CatalogEntry(
            eid=eid,
            name=f"synthetic-{eid}",
            structural_family=family,
            asset_type="unit",
            model_id=eid + 100,
            model_path=f"synthetic/{eid}.gim",
            model_cell=(2.0, 2.0, 2.0),
            property_keys=(),
            static_status="pass",
            evidence="synthetic",
        )
        for eid, (family, _type_id, _paint) in families.items()
    }
    prefabs = {
        eid: {
            "type": type_id,
            "model": eid + 100,
            **({"paint_area1": (1, 2, 3)} if paint else {}),
        }
        for eid, (_family, type_id, paint) in families.items()
    }
    return PackageCatalog(
        root=Path("."),
        entries=entries,
        fingerprint="synthetic",
        prefab_defaults=prefabs,
        model_defaults={eid + 100: {"scale": (1.0, 1.0, 1.0)} for eid in families},
    )


def spec(eid: int, *, color=None, properties=None, yaw: float = 0.0) -> ComponentSpec:
    return ComponentSpec(
        logical_name=f"logical-{eid}",
        eid=eid,
        transform=TransformSpec(
            WorldAABB((0.0, 0.0, 0.0), (2.0, 2.0, 2.0)),
            rotation_deg=(0.0, yaw, 0.0),
        ),
        color=color,
        properties=properties or {},
    )


def test_all_four_runtime_families_build() -> None:
    catalog = make_catalog()
    expected_types = {11: 256, 12: 1024, 13: 512, 14: 16384}
    for create_index, (eid, type_id) in enumerate(expected_types.items(), start=1):
        row = build_runtime_rebuild_unit(
            spec(eid),
            unit_id=1000 + eid,
            create_index=create_index,
            plan=SimpleNamespace(catalog=catalog),
        )
        assert row[b"unit_type"] == type_id


def test_capability_exposes_only_declared_properties() -> None:
    catalog = make_catalog()
    capability = runtime_component_capability(catalog, 14)
    assert capability.writable
    assert capability.supported_properties == ("camp_id", "role_id")
    validate_component_spec(spec(14, properties={"camp_id": 2}), catalog)
    with pytest.raises(CapabilityError) as caught:
        validate_component_spec(spec(14, properties={"undocumented": 1}), catalog)
    assert caught.value.error_code == "INVALID_PROPERTY"


def test_color_and_transform_fail_closed() -> None:
    catalog = make_catalog()
    validate_component_spec(spec(11, color=(0, 127, 255)), catalog)
    with pytest.raises(CapabilityError, match="paint_area1"):
        validate_component_spec(spec(12, color=(0, 127, 255)), catalog)
    with pytest.raises(CapabilityError, match="0/90-degree"):
        validate_component_spec(spec(11, yaw=45.0), catalog)

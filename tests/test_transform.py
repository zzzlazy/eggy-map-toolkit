from eggy_map_api.models import CatalogEntry, TransformSpec, WorldAABB
from eggy_map_api.transform import scale_for_world_aabb


def entry(cell: tuple[float, float, float]) -> CatalogEntry:
    return CatalogEntry(
        eid=1,
        name="合成组件",
        structural_family="editor_unit",
        asset_type="unit",
        model_id=1,
        model_path="synthetic/model.gim",
        model_cell=cell,
        property_keys=(),
        static_status="pass",
        evidence="synthetic",
    )


def test_scale_for_unrotated_world_aabb_uses_matching_local_axes() -> None:
    transform = TransformSpec(
        WorldAABB((0.0, 0.0, 0.0), (10.0, 2.5, 0.3)),
        rotation_deg=(0.0, 0.0, 0.0),
    )
    assert scale_for_world_aabb(entry((1.0, 2.5, 5.0)), transform) == (
        10.0,
        1.0,
        0.06,
    )


def test_scale_for_quarter_turn_returns_local_axis_scale() -> None:
    transform = TransformSpec(
        WorldAABB((0.0, 0.0, 0.0), (10.0, 2.5, 0.3)),
        rotation_deg=(0.0, 90.0, 0.0),
    )
    assert scale_for_world_aabb(entry((1.0, 2.5, 5.0)), transform) == (
        0.3,
        1.0,
        2.0,
    )

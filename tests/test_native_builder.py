import struct

import pytest

from eggy_map_api.errors import CapabilityError
from eggy_map_api.hashing import engine_string_hash
from eggy_map_api.native_tasks import (
    NativeAudioAttrs,
    NativeMaterialVar,
    NativeModelTaskV1Spec,
    NativeTaskContainer,
    NativeTaskV1Builder,
    build_model_task_v1,
    decode_task_container,
    encode_task_container,
)


def test_v1_builder_uses_recovered_transform_and_scene_layouts() -> None:
    task = (
        NativeTaskV1Builder(1_000_000_007, b"asset/model.gim")
        .set_model_uid(1_000_000_007)
        .set_local_scale((1.0, 2.0, 3.0))
        .set_local_angle((4.0, 5.0, 6.0))
        .scene_add_object()
        .set_local_position((7.0, 8.0, 9.0))
        .add_to_group(b"Unit")
        .set_scene_flag(0x600000000)
        .finish()
    )
    assert [param.opcode for param in task.params] == [1, 10, 12, 14, 11, 16, 2]
    for parameter, expected in zip(
        task.params[1:3] + task.params[4:5],
        ((1.0, 2.0, 3.0), (4.0, 5.0, 6.0), (7.0, 8.0, 9.0)),
        strict=True,
    ):
        assert (
            tuple(
                struct.unpack_from("<f", parameter.data, offset)[0]
                for offset in (0, 8, 16)
            )
            == expected
        )
    assert struct.unpack_from("<Q", task.params[-1].data, 8)[0] == 0x600000000
    assert task.strings == (b"Unit",)
    container = NativeTaskContainer(1, False, 0, (task,))
    assert decode_task_container(encode_task_container(container), 1) == container


def test_v1_builder_material_pool_and_value_layouts() -> None:
    task = (
        NativeTaskV1Builder(1_000_000_007, b"asset/model.gim")
        .set_all_material_var(b"Tint", (0.1, 0.2, 0.3, 1.0), hash_argument=17)
        .set_all_material_var(b"Strength", 0.75, hash_argument=19)
        .set_all_material_macro(b"Outlined", b"TRUE")
        .finish()
    )
    vector_param, float_param, macro_param = task.params
    assert [param.opcode for param in task.params] == [24, 24, 33]
    assert struct.unpack_from("<I", vector_param.data, 8)[0] == 17
    assert struct.unpack_from("<I", vector_param.data, 16)[0] == 4
    assert struct.unpack_from("<Q", vector_param.data, 24)[0] == 0
    assert struct.unpack_from("<I", float_param.data, 8)[0] == 19
    assert struct.unpack_from("<I", float_param.data, 16)[0] == 3
    assert struct.unpack_from("<f", float_param.data, 24)[0] == 0.75
    assert struct.unpack_from("<Q", macro_param.data, 0)[0] == 2
    assert struct.unpack_from("<Q", macro_param.data, 8)[0] == 3
    assert task.strings == (
        b"Tint",
        b"Strength",
        b"Outlined",
        b"TRUE",
    )
    assert struct.unpack("<4f", task.array_pools[0][0]) == pytest.approx(
        (
            0.1,
            0.2,
            0.3,
            1.0,
        )
    )


def test_v1_builder_animation_dither_and_alpha_records() -> None:
    task = (
        NativeTaskV1Builder(1_000_000_007, b"asset/model.gim")
        .set_animation(b"idle")
        .set_all_material_dither(False)
        .set_all_material_alpha(255)
        .finish()
    )
    assert [param.opcode for param in task.params] == [30, 26, 27]
    assert struct.unpack_from("<Q", task.params[0].data)[0] == 0
    assert task.params[1].data == bytes(32)
    assert struct.unpack_from("<I", task.params[2].data)[0] == 255
    assert task.strings == (b"idle",)


def test_profile_resolved_model_task_has_runtime_loader_order() -> None:
    task = build_model_task_v1(
        NativeModelTaskV1Spec(
            task_id=1_000_000_021,
            source=b"synthetic/model.gim",
            scale=(1.0, 1.0, 1.0),
            angle=(0.0, 0.0, 0.0),
            position=(4.0, 5.0, 6.0),
            primary_group=b"Unit",
            pickable=True,
            scene_flag=17,
            cast_shadow=True,
            receive_shadow=True,
            visible=True,
            animation=b"idle",
            post_animation_groups=(b"Obstacle",),
            audio=NativeAudioAttrs(
                max_distance=15.0,
                local_position=(0.0, 0.0, 0.0),
                diff_tag=(True, False, False),
            ),
            material_dither=False,
            material_alpha=255,
            material_vars=(
                NativeMaterialVar(
                    name=b"Tint",
                    hash_argument=engine_string_hash(b"Tint"),
                    value=(0.0, 0.5, 1.0, 1.0),
                ),
            ),
            material_macros=((b"Feature", b"TRUE"),),
        )
    )
    assert [param.opcode for param in task.params] == [
        1,
        10,
        12,
        14,
        11,
        16,
        18,
        2,
        3,
        4,
        5,
        30,
        16,
        7,
        8,
        9,
        26,
        27,
        24,
        33,
    ]
    container = NativeTaskContainer(1, True, 0, (task,))
    assert decode_task_container(encode_task_container(container), 1).tasks == (task,)


@pytest.mark.parametrize(
    ("method", "value"),
    (("set_all_material_alpha", 256), ("set_scene_flag", -1)),
)
def test_v1_builder_rejects_values_outside_recovered_abi(
    method: str, value: int
) -> None:
    builder = NativeTaskV1Builder(1_000_000_031, b"synthetic/model.gim")
    with pytest.raises(CapabilityError, match=r"range|\[0, 255\]"):
        getattr(builder, method)(value)


def test_engine_string_hash_matches_recovered_native_binding() -> None:
    assert engine_string_hash(b"MaskColor0") == 0xEEC0605A
    assert engine_string_hash("Intensity") == 0x30D0B0F0
    assert engine_string_hash(b"") == 0xEBB6C228

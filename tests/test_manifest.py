import json

import pytest

from eggy_map_api.errors import ValidationError
from eggy_map_api.manifest import load_manifest
from eggy_map_api.validate import validate_course_manifest, validate_manifest


def write_manifest(tmp_path, components):
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "map_settings": {
                    "map_recommend_play_num": 8,
                    "min_play_num": 1,
                    "min_play_num_new": 1,
                    "max_game_time": 180,
                },
                "components": components,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def component(name, role, center):
    return {
        "logical_name": name,
        "eid": 7,
        "role": role,
        "world_aabb": {"center": center, "size": [1, 1, 1]},
    }


def test_manifest_region_separation(tmp_path) -> None:
    path = write_manifest(
        tmp_path,
        [
            component("赛道_出生", "spawn", [0, 2, 0]),
            component("赛道_销毁", "destroy", [0, -5, 0]),
        ],
    )
    assert (
        "trigger-region-separation"
        in validate_course_manifest(load_manifest(path)).checks
    )


def test_manifest_rejects_destroy_overlap(tmp_path) -> None:
    path = write_manifest(
        tmp_path,
        [
            component("赛道_出生", "spawn", [0, 0, 0]),
            component("赛道_销毁", "destroy", [0, 0, 0]),
        ],
    )
    with pytest.raises(ValidationError, match="intersects"):
        validate_course_manifest(load_manifest(path))


def test_manifest_declared_counts(tmp_path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "map_settings": {
                    "map_recommend_play_num": 8,
                    "min_play_num": 1,
                    "min_play_num_new": 1,
                    "max_game_time": 180,
                },
                "constraints": {
                    "expected_component_count": 2,
                    "expected_eid_counts": {"7": 2},
                },
                "components": [
                    component("赛道_出生", "spawn", [0, 2, 0]),
                    component("赛道_销毁", "destroy", [0, -5, 0]),
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    report = validate_manifest(load_manifest(path))
    assert "expected-component-count" in report.checks
    assert "expected-eid-counts" in report.checks

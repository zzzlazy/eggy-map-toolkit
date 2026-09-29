#!/usr/bin/env python3
"""Generate primitive-led assembly seeds for every Eggy map primary type.

The output is deliberately component-agnostic and design-space-only.  It gives
the designer a substantial, auditable world-building starting point without
guessing game EIDs, pivots, Euler angles, collision semantics, or device logic.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import sys
from typing import Any, Callable

from audit_build_bundle import BundleError, validate_bundle
from audit_component_binding import (
    BindingError,
    binding_template as component_binding_template,
    validate_binding as validate_component_binding,
)
from audit_density_plan import (
    DENSITY_PROFILE_MINIMUMS,
    PlanError as DensityPlanError,
    validate_plan as validate_density_plan,
)
from audit_design_plan import (
    DesignPlanError,
    PRIMARY_TYPES,
    design_template_plan,
    validate_design_plan,
)
from audit_performance_plan import (
    PerformancePlanError,
    performance_plan_template,
    validate_performance_plan,
)
from audit_theme_adaptation import (
    ThemeAdaptationError,
    theme_adaptation_template,
    validate_theme_adaptation,
)
from expand_assembly_plan import ExpansionError, expand_plan


BASIS = {"u": [1, 0, 0], "v": [0, 1, 0], "f": [0, 0, 1]}


class SeedError(ValueError):
    pass


def _piece(
    name: str,
    component_role: str,
    layer: str,
    design_roles: list[str],
    position: list[float],
    size: list[float],
    *,
    construction_kind: str = "BASIC_PRIMITIVE",
    include_variants: list[str] | None = None,
) -> dict[str, Any]:
    cost_role = {
        "BASIC_PRIMITIVE": "VIS_STATIC",
        "COLLISION_PROXY": "COL_PROXY",
        "FX_LIGHT_AUDIO": "LIGHT_FX",
    }[construction_kind]
    result: dict[str, Any] = {
        "name": name,
        "component_role": component_role,
        "layer": layer,
        "cost_role": cost_role,
        "construction_kind": construction_kind,
        "design_roles": design_roles,
        "local_position": position,
        "local_size": size,
    }
    if include_variants is not None:
        result["include_variants"] = include_variants
    return result


def _variant_markers(
    *,
    y: float,
    z: float,
    width: float,
    height: float,
) -> list[dict[str, Any]]:
    return [
        _piece(
            f"VARIANT_{variant}",
            "basic_variant_marker",
            "PROP",
            ["SURFACE_DETAIL", "STATE_FEEDBACK"],
            [offset, y, z],
            [width, height, 0.2],
            include_variants=[variant],
        )
        for variant, offset in (("A", -width), ("B", 0.0), ("C", width))
    ]


def _route_family(name: str) -> dict[str, Any]:
    pieces: list[dict[str, Any]] = [
        _piece(
            "FLOOR_PROXY",
            "continuous_floor_proxy",
            "COL",
            ["COLLISION"],
            [0, -0.3, 0],
            [12, 0.5, 4],
            construction_kind="COLLISION_PROXY",
        )
    ]
    for column, x in enumerate((-4.5, -1.5, 1.5, 4.5), 1):
        pieces.append(
            _piece(
                f"FLOOR_TILE_{column:02d}",
                "basic_floor_slab",
                "ROUTE",
                ["CONTACT", "NAVIGATION", "SURFACE_DETAIL"],
                [x, 0, 0],
                [2.8, 0.2, 4],
            )
        )
    for side_name, x in (("L", -5.8), ("R", 5.8)):
        for row, y in enumerate((1.4, 4.1, 6.8), 1):
            pieces.append(
                _piece(
                    f"WALL_{side_name}_{row:02d}",
                    "basic_wall_panel",
                    "MASS",
                    ["SILHOUETTE", "ENCLOSURE"],
                    [x, y, 0],
                    [0.4, 2.6, 4],
                )
            )
        for post, z in enumerate((-1.6, 0.0, 1.6), 1):
            pieces.append(
                _piece(
                    f"POST_{side_name}_{post:02d}",
                    "basic_support_post",
                    "MID",
                    ["STRUCTURE", "SCALE_REFERENCE"],
                    [x - 0.25 if side_name == "L" else x + 0.25, 4, z],
                    [0.5, 8, 0.5],
                )
            )
        for plate, y in enumerate((2.0, 4.4, 6.7), 1):
            pieces.append(
                _piece(
                    f"SIDE_PLATE_{side_name}_{plate:02d}",
                    "basic_surface_plate",
                    "PROP",
                    ["SURFACE_DETAIL", "ENCLOSURE"],
                    [x * 0.96, y, 0.65 * (plate - 2)],
                    [0.18, 1.1, 1.2],
                )
            )
    for beam, z in enumerate((-1.5, 0.0, 1.5), 1):
        pieces.append(
            _piece(
                f"ROOF_BEAM_{beam:02d}",
                "basic_cross_beam",
                "MID",
                ["STRUCTURE", "ENCLOSURE"],
                [0, 8, z],
                [12, 0.45, 0.45],
            )
        )
    for side_name, x in (("L", -5.25), ("R", 5.25)):
        pieces.append(
            _piece(
                f"ROUTE_EDGE_{side_name}",
                "basic_route_edge",
                "ROUTE",
                ["NAVIGATION", "DANGER"],
                [x, 0.18, 0],
                [0.28, 0.22, 4],
            )
        )
        pieces.append(
            _piece(
                f"LIGHT_{side_name}",
                "light_strip_placeholder",
                "FX",
                ["ATMOSPHERE", "NAVIGATION"],
                [x * 0.92, 6.0, 0],
                [0.15, 0.15, 2.8],
                construction_kind="FX_LIGHT_AUDIO",
            )
        )
    pieces.extend(_variant_markers(y=7.3, z=1.7, width=0.8, height=0.5))
    return {"name": name, "parameters": {}, "variants": ["A", "B", "C"], "pieces": pieces}


def _room_family(name: str) -> dict[str, Any]:
    pieces: list[dict[str, Any]] = [
        _piece(
            "FLOOR_PROXY",
            "continuous_room_floor_proxy",
            "COL",
            ["COLLISION"],
            [0, -0.3, 0],
            [24, 0.5, 24],
            construction_kind="COLLISION_PROXY",
        )
    ]
    tile_positions = (-9.8, -5.9, -2.0, 2.0, 5.9, 9.8)
    for row, z in enumerate(tile_positions, 1):
        for column, x in enumerate(tile_positions, 1):
            pieces.append(
                _piece(
                    f"FLOOR_{column:02d}_{row:02d}",
                    "basic_floor_tile",
                    "ROUTE",
                    ["CONTACT", "NAVIGATION", "SURFACE_DETAIL"],
                    [x, 0, z],
                    [3.75, 0.2, 3.75],
                )
            )
    wall_centers = (-9.8, -5.9, -2.0, 2.0, 5.9, 9.8)
    wall_heights = (2.0, 6.0, 10.0)
    for side_name, axis, sign in (
        ("L", "x", -1),
        ("R", "x", 1),
        ("FRONT", "z", -1),
        ("BACK", "z", 1),
    ):
        for column, along in enumerate(wall_centers, 1):
            for row, y in enumerate(wall_heights, 1):
                if side_name in {"FRONT", "BACK"} and row == 1 and column in {3, 4}:
                    continue
                position = [sign * 11.8, y, along] if axis == "x" else [along, y, sign * 11.8]
                size = [0.35, 3.8, 3.75] if axis == "x" else [3.75, 3.8, 0.35]
                pieces.append(
                    _piece(
                        f"WALL_{side_name}_{column:02d}_{row:02d}",
                        "basic_wall_panel",
                        "MASS",
                        ["SILHOUETTE", "ENCLOSURE", "SURFACE_DETAIL"],
                        position,
                        size,
                    )
                )
    for index, offset in enumerate(wall_centers, 1):
        pieces.append(
            _piece(
                f"CEILING_RIB_U_{index:02d}",
                "basic_ceiling_rib",
                "MID",
                ["STRUCTURE", "ENCLOSURE"],
                [offset, 12, 0],
                [0.4, 0.4, 24],
            )
        )
        pieces.append(
            _piece(
                f"CEILING_RIB_F_{index:02d}",
                "basic_ceiling_rib",
                "MID",
                ["STRUCTURE", "ENCLOSURE"],
                [0, 12.25, offset],
                [24, 0.4, 0.4],
            )
        )
    for index, (x, z) in enumerate(
        ((-11, -11), (-11, 0), (-11, 11), (0, -11), (0, 11), (11, -11), (11, 0), (11, 11)),
        1,
    ):
        pieces.append(
            _piece(
                f"COLUMN_{index:02d}",
                "basic_room_column",
                "MID",
                ["STRUCTURE", "SCALE_REFERENCE"],
                [x, 6, z],
                [0.7, 12, 0.7],
            )
        )
    for index, (x, z) in enumerate(((-7, -7), (7, -7), (-7, 7), (7, 7)), 1):
        pieces.append(
            _piece(
                f"INTERACTION_PLINTH_{index:02d}",
                "basic_interaction_plinth",
                "PROP",
                ["INTERACTION", "STATE_FEEDBACK", "SCALE_REFERENCE"],
                [x, 0.8, z],
                [2.2, 1.6, 2.2],
            )
        )
    for index, (x, z) in enumerate(
        ((-8, -8), (0, -8), (8, -8), (-8, 8), (0, 8), (8, 8), (-8, 0), (8, 0)),
        1,
    ):
        pieces.append(
            _piece(
                f"LIGHT_{index:02d}",
                "light_panel_placeholder",
                "FX",
                ["ATMOSPHERE", "STATE_FEEDBACK"],
                [x, 11.6, z],
                [1.4, 0.15, 1.4],
                construction_kind="FX_LIGHT_AUDIO",
            )
        )
    pieces.extend(_variant_markers(y=9.5, z=-11.5, width=1.2, height=1.0))
    return {"name": name, "parameters": {}, "variants": ["A", "B", "C"], "pieces": pieces}


def _sector_family(name: str) -> dict[str, Any]:
    pieces: list[dict[str, Any]] = [
        _piece(
            "FLOOR_PROXY",
            "continuous_sector_floor_proxy",
            "COL",
            ["COLLISION"],
            [0, -0.25, 0],
            [8, 0.45, 6],
            construction_kind="COLLISION_PROXY",
        )
    ]
    for row, z in enumerate((-2.1, -0.7, 0.7, 2.1), 1):
        for column, x in enumerate((-3, -1, 1, 3), 1):
            pieces.append(
                _piece(
                    f"DECK_{column:02d}_{row:02d}",
                    "basic_sector_tile",
                    "ROUTE",
                    ["CONTACT", "NAVIGATION", "SURFACE_DETAIL"],
                    [x, 0, z],
                    [1.9, 0.18, 1.3],
                )
            )
    for index, x in enumerate((-3.5, -1.2, 1.2, 3.5), 1):
        pieces.append(
            _piece(
                f"OUTER_WALL_{index:02d}",
                "basic_outer_wall",
                "MASS",
                ["SILHOUETTE", "ENCLOSURE"],
                [x, 2.5, -2.85],
                [2.1, 5, 0.35],
            )
        )
        pieces.append(
            _piece(
                f"SUPPORT_{index:02d}",
                "basic_sector_support",
                "MID",
                ["STRUCTURE", "SCALE_REFERENCE"],
                [x, 1.8, 2.7],
                [0.45, 3.6, 0.45],
            )
        )
        pieces.append(
            _piece(
                f"TELEGRAPH_{index:02d}",
                "basic_state_strip",
                "PROP",
                ["DANGER", "STATE_FEEDBACK"],
                [x, 0.16, 2.65],
                [1.5, 0.16, 0.3],
            )
        )
    for index, x in enumerate((-2.5, 0, 2.5), 1):
        pieces.append(
            _piece(
                f"STAND_BLOCK_{index:02d}",
                "basic_stand_block",
                "MASS",
                ["SILHOUETTE", "SCALE_REFERENCE"],
                [x, 4.8, -3.4],
                [2.2, 1.8 + 0.4 * index, 1.2],
            )
        )
    for side_name, x in (("L", -3.6), ("R", 3.6)):
        pieces.append(
            _piece(
                f"LIGHT_{side_name}",
                "light_post_placeholder",
                "FX",
                ["ATMOSPHERE", "STATE_FEEDBACK"],
                [x, 4.5, 0],
                [0.2, 3.5, 0.2],
                construction_kind="FX_LIGHT_AUDIO",
            )
        )
    pieces.extend(_variant_markers(y=5.7, z=-3.0, width=0.7, height=0.7))
    return {"name": name, "parameters": {}, "variants": ["A", "B", "C"], "pieces": pieces}


def _node_family(name: str) -> dict[str, Any]:
    pieces: list[dict[str, Any]] = [
        _piece(
            "PLATFORM_PROXY",
            "continuous_node_floor_proxy",
            "COL",
            ["COLLISION"],
            [0, -0.25, 0],
            [10, 0.45, 10],
            construction_kind="COLLISION_PROXY",
        )
    ]
    for row, z in enumerate((-3.75, -1.25, 1.25, 3.75), 1):
        for column, x in enumerate((-3.75, -1.25, 1.25, 3.75), 1):
            pieces.append(
                _piece(
                    f"PLATFORM_{column:02d}_{row:02d}",
                    "basic_node_tile",
                    "ROUTE",
                    ["CONTACT", "NAVIGATION", "SURFACE_DETAIL"],
                    [x, 0, z],
                    [2.35, 0.18, 2.35],
                )
            )
    for index, (x, z) in enumerate(
        ((-4.4, -4.4), (-4.4, 0), (-4.4, 4.4), (0, -4.4), (0, 4.4), (4.4, -4.4), (4.4, 0), (4.4, 4.4)),
        1,
    ):
        pieces.append(
            _piece(
                f"POST_{index:02d}",
                "basic_node_post",
                "MID",
                ["STRUCTURE", "SCALE_REFERENCE"],
                [x, 4, z],
                [0.5, 8, 0.5],
            )
        )
    for index, (x, z, sx, sz) in enumerate(
        ((0, -4.5, 10, 0.5), (0, 4.5, 10, 0.5), (-4.5, 0, 0.5, 10), (4.5, 0, 0.5, 10)),
        1,
    ):
        pieces.append(
            _piece(
                f"CANOPY_BEAM_{index:02d}",
                "basic_canopy_beam",
                "MID",
                ["STRUCTURE", "ENCLOSURE"],
                [x, 8, z],
                [sx, 0.45, sz],
            )
        )
    for index, (x, z) in enumerate(((-2.5, -2.5), (2.5, -2.5), (-2.5, 2.5), (2.5, 2.5)), 1):
        pieces.append(
            _piece(
                f"CANOPY_{index:02d}",
                "basic_canopy_panel",
                "MASS",
                ["SILHOUETTE", "ENCLOSURE"],
                [x, 8.25, z],
                [4.8, 0.25, 4.8],
            )
        )
        pieces.append(
            _piece(
                f"FEEDBACK_{index:02d}",
                "basic_feedback_frame",
                "PROP",
                ["INTERACTION", "STATE_FEEDBACK"],
                [x * 1.2, 1.2, z * 1.2],
                [1.4, 2.4, 0.25],
            )
        )
        pieces.append(
            _piece(
                f"LIGHT_{index:02d}",
                "light_beacon_placeholder",
                "FX",
                ["ATMOSPHERE", "STATE_FEEDBACK"],
                [x, 7.7, z],
                [0.3, 0.3, 0.3],
                construction_kind="FX_LIGHT_AUDIO",
            )
        )
    pieces.extend(_variant_markers(y=6.6, z=-4.6, width=0.9, height=0.8))
    return {"name": name, "parameters": {}, "variants": ["A", "B", "C"], "pieces": pieces}


def _landmark_family(name: str) -> dict[str, Any]:
    pieces: list[dict[str, Any]] = [
        _piece(
            "BASE_PROXY",
            "landmark_base_proxy",
            "COL",
            ["COLLISION"],
            [0, -0.3, 0],
            [18, 0.5, 12],
            construction_kind="COLLISION_PROXY",
        )
    ]
    for level, y in enumerate((1.5, 4.5), 1):
        for row, z in enumerate((-3, 3), 1):
            for column, x in enumerate((-6, -2, 2, 6), 1):
                pieces.append(
                    _piece(
                        f"MASS_{level:02d}_{column:02d}_{row:02d}",
                        "basic_landmark_mass",
                        "MASS",
                        ["SILHOUETTE", "ENCLOSURE", "SCALE_REFERENCE"],
                        [x, y, z],
                        [3.6, 2.8, 5.6],
                    )
                )
    for index, (x, z) in enumerate(
        ((-8, -5), (-8, 0), (-8, 5), (8, -5), (8, 0), (8, 5), (-3, -5), (3, -5), (-3, 5), (3, 5)),
        1,
    ):
        pieces.append(
            _piece(
                f"PILLAR_{index:02d}",
                "basic_landmark_pillar",
                "MID",
                ["STRUCTURE", "SCALE_REFERENCE"],
                [x, 7, z],
                [0.8, 14, 0.8],
            )
        )
    for index, (y, z) in enumerate(((7, -5), (7, 0), (7, 5), (12, -5), (12, 0), (12, 5)), 1):
        pieces.append(
            _piece(
                f"BEAM_{index:02d}",
                "basic_landmark_beam",
                "MID",
                ["STRUCTURE", "SILHOUETTE"],
                [0, y, z],
                [18, 0.6, 0.6],
            )
        )
    for row, y in enumerate((3, 6, 9, 12), 1):
        for column, x in enumerate((-6, -2, 2, 6), 1):
            pieces.append(
                _piece(
                    f"FACADE_{column:02d}_{row:02d}",
                    "basic_facade_panel",
                    "PROP",
                    ["SURFACE_DETAIL", "SILHOUETTE"],
                    [x, y, -5.7],
                    [3.5, 2.4, 0.25],
                )
            )
    for index, x in enumerate((-7.5, -4.5, -1.5, 1.5, 4.5, 7.5), 1):
        pieces.append(
            _piece(
                f"CROWN_{index:02d}",
                "basic_silhouette_fin",
                "MASS",
                ["SILHOUETTE", "ATMOSPHERE"],
                [x, 15.5, 0],
                [1.2, 4 + 0.3 * (index % 2), 1.2],
            )
        )
        pieces.append(
            _piece(
                f"LIGHT_{index:02d}",
                "light_landmark_placeholder",
                "FX",
                ["ATMOSPHERE", "NAVIGATION"],
                [x, 13.5, -5.8],
                [0.35, 0.35, 0.2],
                construction_kind="FX_LIGHT_AUDIO",
            )
        )
    pieces.extend(_variant_markers(y=10.5, z=-5.9, width=1.4, height=1.3))
    return {"name": name, "parameters": {}, "variants": ["A", "B", "C"], "pieces": pieces}


def _tile_family(name: str) -> dict[str, Any]:
    pieces = [
        _piece(
            "CELL_PROXY",
            "continuous_cell_proxy",
            "COL",
            ["COLLISION"],
            [0, -0.2, 0],
            [4, 0.35, 4],
            construction_kind="COLLISION_PROXY",
        ),
        _piece(
            "CELL_TOP",
            "basic_cell_top",
            "ROUTE",
            ["CONTACT", "NAVIGATION", "STATE_FEEDBACK"],
            [0, 0, 0],
            [3.8, 0.15, 3.8],
        ),
    ]
    for index, (x, z, sx, sz) in enumerate(
        ((0, -1.9, 4, 0.18), (0, 1.9, 4, 0.18), (-1.9, 0, 0.18, 4), (1.9, 0, 0.18, 4)),
        1,
    ):
        pieces.append(
            _piece(
                f"EDGE_{index:02d}",
                "basic_cell_edge",
                "MID",
                ["STRUCTURE", "NAVIGATION"],
                [x, 0.15, z],
                [sx, 0.22, sz],
            )
        )
    for index, (x, z) in enumerate(((-1.35, -1.35), (1.35, -1.35), (-1.35, 1.35), (1.35, 1.35)), 1):
        pieces.append(
            _piece(
                f"MARKER_{index:02d}",
                "basic_cell_marker",
                "PROP",
                ["INTERACTION", "STATE_FEEDBACK"],
                [x, 0.25, z],
                [0.35, 0.25, 0.35],
            )
        )
    pieces.extend(_variant_markers(y=0.35, z=-1.2, width=0.3, height=0.25))
    return {"name": name, "parameters": {}, "variants": ["A", "B", "C"], "pieces": pieces}


FAMILY_BUILDERS: dict[str, Callable[[str], dict[str, Any]]] = {
    "route": _route_family,
    "room": _room_family,
    "sector": _sector_family,
    "node": _node_family,
    "landmark": _landmark_family,
    "tile": _tile_family,
}


TYPE_BLUEPRINTS: dict[str, dict[str, Any]] = {
    "short_race": {
        "density": "themed_short",
        "shell": "linear_corridor",
        "intent": "A readable themed sprint with overtaking pockets and landmark turns.",
        "families": [("RACE_ROUTE_BAY", "route"), ("LANDMARK_TURN", "landmark"), ("START_FINISH_FRAME", "node")],
        "assembly_reference": "references/linear-and-experiential-kits.md#一短竞速-short_race",
    },
    "chapter_challenge": {
        "density": "multi_scene",
        "shell": "multi_scene_threshold",
        "intent": "Four differentiated chapters connected by explicit thresholds and recovery frames.",
        "families": [("CHAPTER_ROUTE_BAY", "route"), ("CHAPTER_SCENE_PACK", "room"), ("CHAPTER_LANDMARK", "landmark")],
        "assembly_reference": "references/linear-and-experiential-kits.md#二章节挑战-chapter_challenge",
    },
    "mechanism_puzzle": {
        "density": "themed_short",
        "shell": "room_sequence",
        "intent": "A sequence of legible puzzle rooms with a shared observation and reset language.",
        "families": [("PUZZLE_ROOM_CELL", "room"), ("PUZZLE_SHELL_BAY", "route"), ("RESET_OBSERVATION_POD", "node")],
        "assembly_reference": "references/linear-and-experiential-kits.md#三机制解谜-mechanism_puzzle",
    },
    "cooperative": {
        "density": "themed_short",
        "shell": "branch_rejoin",
        "intent": "Parallel role routes joined by visible handoffs, regroup points, and a fallback branch.",
        "families": [("ROLE_ROUTE_BAY", "route"), ("COOP_HANDOFF_CELL", "node"), ("REGROUP_LANDMARK", "landmark")],
        "assembly_reference": "references/linear-and-experiential-kits.md#四双人多人合作-cooperative",
    },
    "narrative_exploration": {
        "density": "multi_scene",
        "shell": "hub_spoke",
        "intent": "A returnable landmark network whose scene state can change without copying the whole world.",
        "families": [("LANDMARK_SCENE_CELL", "room"), ("STORY_ROUTE_BAY", "route"), ("HORIZON_LANDMARK", "landmark")],
        "assembly_reference": "references/linear-and-experiential-kits.md#五叙事探索-narrative_exploration",
    },
    "social_showcase": {
        "density": "multi_scene",
        "shell": "showcase_panorama",
        "intent": "A central panorama with several destinations, activities, and explicit return paths.",
        "families": [("SOCIAL_DESTINATION", "node"), ("PANORAMA_SECTOR", "sector"), ("PHOTO_LANDMARK", "landmark")],
        "assembly_reference": "references/linear-and-experiential-kits.md#六休闲社交展示-social_showcase",
    },
    "survival": {
        "density": "themed_short",
        "shell": "arena_bowl",
        "intent": "A wrapped arena with readable hazard sectors, safe choices, and spectator framing.",
        "families": [("SURVIVAL_SECTOR", "sector"), ("SPECTATOR_POD", "node"), ("CORE_TELEGRAPH", "landmark")],
        "assembly_reference": "references/nonlinear-and-economy-kits.md#一生存竞技场套件",
    },
    "score_contest": {
        "density": "themed_short",
        "shell": "hub_spoke",
        "intent": "A fair radial contest field with resource approaches, hotspots, and readable score gates.",
        "families": [("CONTEST_SECTOR", "sector"), ("RESOURCE_SCORE_NODE", "node"), ("TEAM_LANDMARK", "landmark")],
        "assembly_reference": "references/nonlinear-and-economy-kits.md#二积分争夺场套件",
    },
    "management_simulation": {
        "density": "themed_short",
        "shell": "open_district",
        "intent": "A visible production network whose station shells, logistics, and expansion lanes remain separate from logic.",
        "families": [("FACTORY_ROUTE_BAY", "route"), ("PRODUCTION_CELL", "room"), ("DELIVERY_UPGRADE_POD", "node")],
        "assembly_reference": "references/nonlinear-and-economy-kits.md#三经营与建造套件",
    },
    "rhythm_performance": {
        "density": "themed_short",
        "shell": "linear_corridor",
        "intent": "A performance shell with one cue direction, stable judgment framing, and a separate result stage.",
        "families": [("RHYTHM_LANE_BAY", "route"), ("PERFORMANCE_SECTOR", "sector"), ("COUNT_RESULT_STAGE", "node")],
        "assembly_reference": "references/specialized-assembly-kits.md#一纯音游舞台",
    },
    "combat_boss": {
        "density": "themed_short",
        "shell": "arena_bowl",
        "intent": "A boss arena with attack-readable sectors, recovery mouths, and a primitive-built focal silhouette.",
        "families": [("BOSS_ARENA_SECTOR", "sector"), ("BOSS_SHELL_PART", "landmark"), ("RECOVERY_RESULT_POD", "node")],
        "assembly_reference": "references/specialized-assembly-kits.md#二boss-战斗场",
    },
    "defense_strategy": {
        "density": "themed_short",
        "shell": "branch_rejoin",
        "intent": "Two readable enemy lanes with construction pads, source framing, and a visible core destination.",
        "families": [("DEFENSE_LANE_BAY", "route"), ("DEFENSE_PAD", "node"), ("SOURCE_CORE_FORT", "landmark")],
        "assembly_reference": "references/specialized-assembly-kits.md#三防守--塔防场",
    },
    "stealth_infiltration": {
        "density": "themed_short",
        "shell": "room_sequence",
        "intent": "A sequence of recognizable infiltration cells with observation pockets and alternate exfiltration.",
        "families": [("INFILTRATION_CELL", "room"), ("STEALTH_ROUTE_BAY", "route"), ("OBJECTIVE_EXFIL_LANDMARK", "landmark")],
        "assembly_reference": "references/specialized-assembly-kits.md#四潜行渗透场",
    },
    "turn_based_strategy": {
        "density": "themed_short",
        "shell": "arena_bowl",
        "intent": "A legible board inside a venue shell with distinct action, resolution, and spectator edges.",
        "families": [("BOARD_CELL", "tile"), ("BOARD_VENUE_BAY", "route"), ("TURN_RESOLUTION_STAGE", "landmark")],
        "assembly_reference": "references/specialized-assembly-kits.md#五回合棋盘--卡牌场",
    },
    "sports_match": {
        "density": "themed_short",
        "shell": "arena_bowl",
        "intent": "A field with stable play lines, symmetric restart landmarks, and a structurally wrapped stand ring.",
        "families": [("SPORT_FIELD_CELL", "tile"), ("STAND_BAY", "route"), ("GOAL_RESTART_LANDMARK", "landmark")],
        "assembly_reference": "references/specialized-assembly-kits.md#六体育比赛场",
    },
    "sandbox_creation": {
        "density": "themed_short",
        "shell": "open_district",
        "intent": "Neutral build plots with bounded catalog pods, testing exits, and a studio shell outside player budgets.",
        "families": [("BUILD_PLOT_CELL", "room"), ("CATALOG_POD", "node"), ("STUDIO_SHELL_BAY", "route")],
        "assembly_reference": "references/specialized-assembly-kits.md#七创造沙盒场",
    },
    "social_deduction": {
        "density": "themed_short",
        "shell": "hub_spoke",
        "intent": "Functionally distinct public rooms around a meeting hub with traceable corridors and isolated afterlife framing.",
        "families": [("DEDUCTION_ROOM_BAY", "room"), ("PUBLIC_CORRIDOR_BAY", "route"), ("MEETING_VOTE_POD", "node")],
        "assembly_reference": "references/specialized-assembly-kits.md#八阵营推理场",
    },
}


def _linear(name: str, zone: str, family: str, origin: list[float], count: int, step: float) -> dict[str, Any]:
    return {
        "name": name,
        "zone": zone,
        "family": family,
        "layout": "linear",
        "origin": origin,
        "basis": BASIS,
        "count": count,
        "step": step,
        "variant_sequence": ["A", "B", "A", "C", "B"],
    }


def _grid(
    name: str,
    zone: str,
    family: str,
    origin: list[float],
    count_u: int,
    count_f: int,
    step_u: float,
    step_f: float,
) -> dict[str, Any]:
    return {
        "name": name,
        "zone": zone,
        "family": family,
        "layout": "grid",
        "origin": origin,
        "basis": BASIS,
        "count_u": count_u,
        "count_f": count_f,
        "step_u": step_u,
        "step_f": step_f,
        "variant_sequence": ["A", "B", "C", "A", "B"],
    }


def _arc(name: str, zone: str, family: str, center: list[float], radius: float, count: int) -> dict[str, Any]:
    return {
        "name": name,
        "zone": zone,
        "family": family,
        "layout": "arc",
        "center": center,
        "radius": radius,
        "up": [0, 1, 0],
        "radial0": [1, 0, 0],
        "count": count,
        "step_angle_deg": 360 / count,
        "variant_sequence": ["A", "B", "A", "C", "B"],
    }


def _radial(
    name: str,
    zone: str,
    family: str,
    center: list[float],
    radius: float,
    count: int,
    *,
    facing: str = "outward",
) -> dict[str, Any]:
    return {
        "name": name,
        "zone": zone,
        "family": family,
        "layout": "radial",
        "center": center,
        "radius": radius,
        "up": [0, 1, 0],
        "radial0": [1, 0, 0],
        "count": count,
        "step_angle_deg": 360 / count,
        "facing": facing,
        "variant_sequence": ["A", "B", "C", "A", "B"],
    }


def _explicit(name: str, zone: str, family: str, origins: list[list[float]]) -> dict[str, Any]:
    return {
        "name": name,
        "zone": zone,
        "family": family,
        "layout": "explicit",
        "variant_sequence": ["A", "B", "C"],
        "instances": [
            {
                "name": f"{name}_{index + 1:03d}",
                "origin": origin,
                "basis": BASIS,
                "variant": ("A", "B", "C")[index % 3],
            }
            for index, origin in enumerate(origins)
        ],
    }


def _zigzag_points(start: list[float], count: int, step: float, run: int = 6) -> list[list[float]]:
    if count < 2:
        raise SeedError("polyline seeds require at least two points")
    directions = ((0, 0, 1), (1, 0, 0), (0, 0, 1), (-1, 0, 0))
    point = [float(value) for value in start]
    points: list[list[float]] = []
    for index in range(count):
        points.append([round(value, 6) for value in point])
        dx, dy, dz = directions[(index // run) % len(directions)]
        point = [point[0] + dx * step, point[1] + dy * step, point[2] + dz * step]
    return points


def _polyline(name: str, zone: str, family: str, start: list[float], count: int, step: float) -> dict[str, Any]:
    return {
        "name": name,
        "zone": zone,
        "family": family,
        "layout": "polyline",
        "points": _zigzag_points(start, count, step),
        "up": [0, 1, 0],
        "variant_sequence": ["A", "B", "A", "C", "B"],
    }


def _placements(type_name: str, family_names: list[str]) -> list[dict[str, Any]]:
    first, second, third = family_names
    if type_name == "short_race":
        return [
            _polyline("RACE_PATH", "ROUTE", first, [0, 0, 0], 28, 6),
            _explicit("TURN_LANDMARKS", "LANDMARKS", second, [[0, 0, 36], [36, 0, 36], [36, 0, 72], [0, 0, 72]]),
            _explicit("START_FINISH", "TERMINAL", third, [[0, 0, -10], [0, 0, 100]]),
        ]
    if type_name == "chapter_challenge":
        result: list[dict[str, Any]] = []
        for chapter in range(4):
            origin = [chapter * 90, chapter * 4, 0]
            result.append(_polyline(f"CHAPTER_{chapter + 1}_PATH", f"CHAPTER_{chapter + 1}", first, origin, 18, 6))
        result.append(_explicit("CHAPTER_ROOMS", "CHAPTER_CORES", second, [[45 + 90 * i, 4 * i, 55] for i in range(4)]))
        result.append(_explicit("CHAPTER_LANDMARKS", "THRESHOLDS", third, [[90 * i, 4 * i, -12] for i in range(8)]))
        return result
    if type_name == "mechanism_puzzle":
        return [
            _grid("PUZZLE_ROOMS", "ROOMS", first, [0, 0, 0], 4, 2, 32, 32),
            _arc("OUTER_SHELL", "SHELL", second, [48, 0, 16], 62, 38),
            _explicit("RESET_PODS", "RECOVERY", third, [[16 + 32 * i, 0, 16] for i in range(4)]),
        ]
    if type_name == "cooperative":
        return [
            _linear("ROLE_A", "ROLE_A_ROUTE", first, [-10, 0, 0], 24, 6),
            _linear("ROLE_B", "ROLE_B_ROUTE", first, [10, 0, 0], 24, 6),
            _explicit("HANDOFFS", "HANDOFFS", second, [[0, 0, 12 + 14 * i] for i in range(8)]),
            _explicit("REGROUPS", "REGROUPS", third, [[0, 0, 35 + 28 * i] for i in range(4)]),
        ]
    if type_name == "narrative_exploration":
        return [
            _radial("SCENE_CELLS", "SCENES", first, [0, 0, 0], 70, 8, facing="inward"),
            _arc("STORY_RING", "TRANSITIONS", second, [0, 0, 0], 42, 42),
            _radial("HORIZON_MARKERS", "LANDMARKS", third, [0, 0, 0], 105, 8, facing="inward"),
        ]
    if type_name == "social_showcase":
        return [
            _radial("DESTINATIONS", "ACTIVITIES", first, [0, 0, 0], 52, 10, facing="inward"),
            _arc("PANORAMA_RING", "PANORAMA", second, [0, 0, 0], 75, 36),
            _radial("PHOTO_LANDMARKS", "LANDMARKS", third, [0, 0, 0], 100, 6, facing="inward"),
        ]
    if type_name == "survival":
        return [
            _arc("PLAY_SECTORS", "ARENA", first, [0, 0, 0], 28, 20),
            _radial("SPECTATOR_PODS", "SPECTATOR", second, [0, 5, 0], 48, 10, facing="inward"),
            _explicit("CORE", "CORE", third, [[0, 0, 0]]),
        ]
    if type_name == "score_contest":
        return [
            _arc("CONTEST_RING", "CONTEST_FIELD", first, [0, 0, 0], 35, 20),
            _radial("RESOURCE_NODES", "RESOURCES", second, [0, 0, 0], 22, 12, facing="inward"),
            _explicit("TEAM_LANDMARKS", "TEAM_BASES", third, [[-58, 0, 0], [58, 0, 0]]),
        ]
    if type_name == "management_simulation":
        return [
            _linear("FACTORY_SHELL_L", "FACTORY_SHELL", first, [-42, 0, 0], 32, 6),
            _linear("FACTORY_SHELL_R", "FACTORY_SHELL", first, [42, 0, 0], 32, 6),
            _grid("PRODUCTION_GRID", "PRODUCTION", second, [-30, 0, 25], 4, 3, 20, 34),
            _linear("DELIVERY_UPGRADES", "SERVICES", third, [-24, 0, 120], 6, 12),
        ]
    if type_name == "rhythm_performance":
        return [
            _linear("RHYTHM_LANES", "PERFORMANCE", first, [0, 0, 0], 28, 6),
            _arc("STAGE_SHELL", "STAGE_SHELL", second, [0, 0, 70], 32, 18),
            _explicit("COUNT_RESULT", "TERMINAL", third, [[0, 0, -12], [0, 0, 172]]),
        ]
    if type_name == "combat_boss":
        return [
            _arc("BATTLE_RING", "ARENA", first, [0, 0, 0], 35, 20),
            _radial("BOSS_PARTS", "BOSS_FOCAL", second, [0, 0, 0], 12, 8, facing="outward"),
            _radial("RECOVERY_PODS", "RECOVERY", third, [0, 0, 0], 52, 6, facing="inward"),
        ]
    if type_name == "defense_strategy":
        return [
            _polyline("LANE_A", "LANE_A", first, [-18, 0, -70], 20, 6),
            _polyline("LANE_B", "LANE_B", first, [18, 0, -70], 20, 6),
            _grid("DEFENSE_PADS", "BUILD_PADS", second, [-28, 0, -30], 4, 3, 18, 34),
            _explicit("SOURCE_CORE", "TERMINALS", third, [[0, 0, -90], [0, 0, 90]]),
        ]
    if type_name == "stealth_infiltration":
        return [
            _grid("INFILTRATION_CELLS", "CELLS", first, [0, 0, 0], 4, 3, 30, 30),
            _polyline("STEALTH_ROUTE", "ROUTE", second, [-12, 0, -18], 36, 6),
            _explicit("OBJECTIVE_EXFIL", "OBJECTIVES", third, [[15, 0, 15], [75, 0, 15], [15, 0, 45], [75, 0, 45]]),
        ]
    if type_name == "turn_based_strategy":
        return [
            _grid("BOARD", "BOARD", first, [-10, 0, -10], 6, 6, 4, 4),
            _arc("VENUE", "VENUE", second, [0, 0, 0], 38, 40),
            _explicit("TURN_STAGE", "RESOLUTION", third, [[0, 0, -52], [0, 0, 52]]),
        ]
    if type_name == "sports_match":
        return [
            _grid("FIELD", "FIELD", first, [-28, 0, -48], 8, 12, 8, 8),
            _arc("STANDS", "STANDS", second, [0, 0, 0], 62, 34),
            _explicit("GOALS_RESTART", "TERMINALS", third, [[0, 0, -58], [0, 0, 0], [0, 0, 58]]),
        ]
    if type_name == "sandbox_creation":
        return [
            _grid("BUILD_PLOTS", "BUILD_PLOTS", first, [-35, 0, -18], 4, 2, 28, 32),
            _radial("CATALOGS", "CATALOGS", second, [0, 0, 0], 52, 12, facing="inward"),
            _arc("STUDIO_SHELL", "STUDIO_SHELL", third, [0, 0, 0], 78, 40),
        ]
    if type_name == "social_deduction":
        return [
            _radial("PUBLIC_ROOMS", "PUBLIC_ROOMS", first, [0, 0, 0], 58, 12, facing="inward"),
            _arc("PUBLIC_CORRIDORS", "PUBLIC_CORRIDORS", second, [0, 0, 0], 34, 40),
            _radial("MEETING_VOTE", "MEETING", third, [0, 0, 0], 16, 12, facing="inward"),
        ]
    raise SeedError(f"no placement recipe for {type_name}")


def generate_seed(type_name: str) -> dict[str, Any]:
    if type_name not in TYPE_BLUEPRINTS:
        raise SeedError(f"unknown primary type {type_name}")
    blueprint = TYPE_BLUEPRINTS[type_name]
    family_specs: list[tuple[str, str]] = blueprint["families"]
    families = [FAMILY_BUILDERS[kind](name) for name, kind in family_specs]
    placements = _placements(type_name, [name for name, _ in family_specs])
    plan: dict[str, Any] = {
        "schema_version": 1,
        "name_prefix": f"SEED_{type_name.upper()}",
        "max_expanded": 20_000,
        "seed_status": "design_space_only_not_deployable",
        "primary_type": type_name,
        "density_profile": blueprint["density"],
        "world_shell_morphology": blueprint["shell"],
        "design_intent": blueprint["intent"],
        "read_with": [
            "references/parametric-layout.md",
            blueprint["assembly_reference"],
            "references/performance-and-budget.md",
        ],
        "construction_strategy": {
            "mode": "primitive_led",
            "primitive_visible_share_min": 0.85,
            "rationale": "Basic primitives carry silhouette, enclosure, structure, contact, and navigation; lights are sparse placeholders.",
        },
        "not_deployable_until": [
            "replace abstract component roles with current-version writable component evidence",
            "calibrate player, camera, vehicle, and mechanism clearances in the target map",
            "convert design bases to verified game pivots, rotations, and scale semantics",
            "bind zones and families to the final design-plan world shells",
            "add and pass a map-specific quality_contract, density ledger, state audit, and build-bundle audit",
            "inspect seams, collisions, occlusion, peak view cost, and recovery in editor and playtest",
        ],
        "families": families,
        "placements": placements,
    }
    result = expand_plan(plan)
    total = result["summary"]["expanded_total"]
    minimum = DENSITY_PROFILE_MINIMUMS[blueprint["density"]]
    if total < minimum:
        raise SeedError(
            f"{type_name} expands to {total}, below {blueprint['density']} minimum {minimum}"
        )
    plan["expected_total"] = total
    plan["density_profile_evidence"] = (
        "Design-space seed only: "
        f"morphology={blueprint['shell']}, generated_zones={len(result['summary']['zones'])}; "
        f"{blueprint['intent']} Replace with map-specific spatial evidence before final review."
    )
    plan["seed_acceptance"] = {
        "density_minimum": minimum,
        "expanded_total": total,
        "family_count": len(result["summary"]["families"]),
        "zone_count": len(result["summary"]["zones"]),
        "layouts_used": sorted({placement["layout"] for placement in placements}),
        "warning": "Passing this seed check proves organized quantity and transform generation only, not gameplay, visual quality, performance, or deployability.",
    }
    return plan


def generate_density_ledger(plan: dict[str, Any]) -> dict[str, Any]:
    """Derive a graybox-stage density ledger from actual expanded instances."""
    if plan.get("seed_status") != "design_space_only_not_deployable":
        raise SeedError("density derivation accepts only a marked design-space seed")
    expanded = expand_plan(plan)
    summary = expanded["summary"]
    instances = expanded["instances"]
    family_placements: dict[str, Counter[str]] = defaultdict(Counter)
    family_zones: dict[str, Counter[str]] = defaultdict(Counter)
    family_layers: dict[str, Counter[str]] = defaultdict(Counter)
    component_roles: set[str] = set()
    for instance in instances:
        family = instance["family"]
        family_placements[family][instance["placement"]] += 1
        family_zones[family][instance["zone"]] += 1
        family_layers[family][instance["layer"]] += 1
        component_roles.add(instance["component_role"])

    assemblies: list[dict[str, Any]] = []
    for family in sorted(family_placements):
        per_placement = family_placements[family]
        piece_counts = list(per_placement.values())
        if not piece_counts:
            raise SeedError(f"expanded family {family} has no placements")
        base_piece_count = min(piece_counts)
        placement_count = len(piece_counts)
        family_total = sum(piece_counts)
        adjustment = family_total - base_piece_count * placement_count
        item: dict[str, Any] = {
            "name": family,
            "pieces_per_instance": base_piece_count,
            "placements": placement_count,
            "adjustment": adjustment,
            "zones": dict(sorted(family_zones[family].items())),
            "layers": dict(sorted(family_layers[family].items())),
        }
        if adjustment:
            item["adjustment_reason"] = (
                "Controlled variants add pieces above the smallest placement; "
                "counts are derived from expanded instances."
            )
        assemblies.append(item)

    graybox_total = summary["layers"].get("COL", 0)
    if graybox_total <= 0:
        raise SeedError("seed has no collision proxies to ground its graybox total")
    ledger: dict[str, Any] = {
        "schema_version": 1,
        "stage": "graybox",
        "source_seed_status": plan["seed_status"],
        "primary_type": plan["primary_type"],
        "density_profile": plan["density_profile"],
        "density_profile_evidence": plan["density_profile_evidence"],
        "graybox_total": graybox_total,
        "asset_vocabulary_count": len(component_roles),
        "vocabulary_basis": (
            "Count of distinct abstract component_role values; replace with verified "
            "current-version asset vocabulary before final review."
        ),
        "assemblies": assemblies,
        "independent": [],
        "declared": {
            "expanded_total": summary["expanded_total"],
            "zones": summary["zones"],
            "layers": summary["layers"],
        },
        "not_final_until": [
            "the assembly seed has been reshaped to the actual map and world shells",
            "abstract component roles have been mapped to verified assets and devices",
            "a final quality contract and performance ledger have passed review",
        ],
    }
    validate_density_plan(ledger)
    return ledger


def generate_design_ledger(
    plan: dict[str, Any],
    density: dict[str, Any],
) -> dict[str, Any]:
    """Align a concept design ledger with one generated assembly and density seed."""
    type_name = plan.get("primary_type")
    if not isinstance(type_name, str) or type_name not in PRIMARY_TYPES:
        raise SeedError("assembly seed has no valid primary_type")
    expanded = expand_plan(plan)
    summary = expanded["summary"]
    if validate_density_plan(density)["expanded_total"] != summary["expanded_total"]:
        raise SeedError("density ledger does not describe the supplied assembly seed")

    design = design_template_plan(type_name)
    family_names = [family["name"] for family in plan["families"]]
    if set(family_names) != set(summary["families"]):
        raise SeedError("declared family order does not match expanded families")
    design["theme"]["assembly_families"] = family_names

    families_by_zone: dict[str, set[str]] = defaultdict(set)
    zones_by_family: dict[str, set[str]] = defaultdict(set)
    for instance in expanded["instances"]:
        zone = instance["zone"]
        family = instance["family"]
        families_by_zone[zone].add(family)
        zones_by_family[family].add(zone)

    shells = design["theme"]["world_shells"]
    if not shells:
        raise SeedError("design template has no world shells")
    shell_zones: list[set[str]] = [set() for _ in shells]
    for family_index, family in enumerate(family_names):
        zones = sorted(zones_by_family[family])
        if not zones:
            raise SeedError(f"assembly family {family} has no visible zone")
        for shell_index in range(len(shells)):
            shell_zones[shell_index].add(zones[shell_index % len(zones)])
        for zone_index, zone in enumerate(zones):
            shell_zones[(zone_index + family_index) % len(shells)].add(zone)

    for shell_index, shell in enumerate(shells):
        zones = sorted(shell_zones[shell_index])
        actual_families: set[str] = set()
        for zone in zones:
            actual_families.update(families_by_zone[zone])
        ordered_families = [family for family in family_names if family in actual_families]
        if len(ordered_families) < 2:
            raise SeedError(
                f"world shell {shell['name']} would contain fewer than two assembly families"
            )
        shell["assembly_zones"] = zones
        shell["assembly_families"] = ordered_families
        shell["enclosure_strategy"] = (
            f"{ordered_families[0]} carries the primary playable mass and enclosure; "
            f"{ordered_families[1]} establishes structural rhythm and readable openings."
        )
        shell["depth_layers"] = {
            "foreground": f"contact edges and scale detail from {ordered_families[0]}",
            "midground": f"the next reachable action framed by {ordered_families[1]}",
            "background": (
                f"a low-cost directional silhouette from {ordered_families[-1]}"
            ),
        }

    budget = design["assembly_budget"]
    budget.pop("low_count_exception", None)
    budget.update(
        {
            "density_profile": plan["density_profile"],
            "density_profile_evidence": plan["density_profile_evidence"],
            "graybox_total": density["graybox_total"],
            "expanded_total": summary["expanded_total"],
            "asset_vocabulary_count": density["asset_vocabulary_count"],
            "layers": summary["layers"],
        }
    )
    design["evidence"]["unknowns"].append(
        {
            "text": "the generic assembly seed has not yet been reshaped into the chosen theme grammar",
            "impact": "silhouette, proportions, material rhythm, and focal hierarchy may remain generic",
            "validation": "replace generic roles and review every world shell from its declared cameras",
            "blocking": True,
        }
    )
    design["seed_alignment"] = {
        "status": "concept_ledgers_aligned_not_deployable",
        "assembly_seed_status": plan["seed_status"],
        "density_stage": density["stage"],
        "expanded_total": summary["expanded_total"],
        "family_names": family_names,
        "zone_names": sorted(summary["zones"]),
        "warning": (
            "This alignment proves ledger arithmetic and shell routing only; it does not "
            "supply component evidence, a quality contract, device logic, or playtest results."
        ),
    }
    validate_design_plan(design)
    validate_bundle(design, plan, density)
    return design


def generate_component_binding(plan: dict[str, Any]) -> dict[str, Any]:
    """Create a complete but explicitly unresolved component-role ledger."""
    binding = component_binding_template(plan)
    binding["primary_type"] = plan["primary_type"]
    binding["source_seed_status"] = plan["seed_status"]
    validate_component_binding(plan, binding)
    return binding


def generate_theme_adaptation(
    plan: dict[str, Any], design: dict[str, Any]
) -> dict[str, Any]:
    """Create a complete but unresolved family/zone theme adaptation ledger."""
    adaptation = theme_adaptation_template(design, plan)
    adaptation["source_seed_status"] = plan["seed_status"]
    validate_theme_adaptation(design, plan, adaptation)
    return adaptation


def generate_performance_plan(
    plan: dict[str, Any], design: dict[str, Any]
) -> dict[str, Any]:
    """Create an assembly-derived but explicitly unmeasured performance ledger."""
    performance = performance_plan_template(design, plan)
    performance["source_seed_status"] = plan["seed_status"]
    validate_performance_plan(design, plan, performance)
    return performance


def _seed_summary(type_name: str) -> dict[str, Any]:
    plan = generate_seed(type_name)
    result = expand_plan(plan)["summary"]
    visible = (
        result["construction_kinds"].get("BASIC_PRIMITIVE", 0)
        + result["construction_kinds"].get("THEME_ASSET", 0)
        + result["construction_kinds"].get("FX_LIGHT_AUDIO", 0)
    )
    primitive = result["construction_kinds"].get("BASIC_PRIMITIVE", 0)
    return {
        "primary_type": type_name,
        "density_profile": plan["density_profile"],
        "world_shell_morphology": plan["world_shell_morphology"],
        "expanded_total": result["expanded_total"],
        "zone_count": len(result["zones"]),
        "family_count": len(result["families"]),
        "layouts_used": plan["seed_acceptance"]["layouts_used"],
        "primitive_visible_share": round(primitive / visible, 6) if visible else 0,
    }


def _self_test() -> None:
    if set(TYPE_BLUEPRINTS) != PRIMARY_TYPES:
        raise AssertionError(
            f"type coverage mismatch: missing={sorted(PRIMARY_TYPES - set(TYPE_BLUEPRINTS))}, "
            f"extra={sorted(set(TYPE_BLUEPRINTS) - PRIMARY_TYPES)}"
        )
    for type_name in sorted(PRIMARY_TYPES):
        plan = generate_seed(type_name)
        if "quality_contract" in plan:
            raise AssertionError(f"{type_name} seed must not masquerade as a final build")
        result = expand_plan(plan)
        expanded = result["summary"]
        density = generate_density_ledger(plan)
        density_summary = validate_density_plan(density)
        design = generate_design_ledger(plan, density)
        design_summary = validate_design_plan(design)
        bundle_summary = validate_bundle(design, plan, density)
        binding = generate_component_binding(plan)
        binding_summary = validate_component_binding(plan, binding)
        theme_adaptation = generate_theme_adaptation(plan, design)
        theme_summary = validate_theme_adaptation(design, plan, theme_adaptation)
        performance = generate_performance_plan(plan, design)
        performance_summary = validate_performance_plan(design, plan, performance)
        summary = _seed_summary(type_name)
        if expanded["expanded_total"] != plan["expected_total"]:
            raise AssertionError(f"{type_name} expected_total drift")
        if summary["family_count"] < 3:
            raise AssertionError(f"{type_name} uses fewer than three assembly families")
        if summary["zone_count"] < 3:
            raise AssertionError(f"{type_name} uses fewer than three visible zones")
        if len(summary["layouts_used"]) < 2:
            raise AssertionError(f"{type_name} uses fewer than two layout generators")
        if summary["primitive_visible_share"] < 0.85:
            raise AssertionError(f"{type_name} is not primitive-led: {summary}")
        if summary["expanded_total"] > 10_000:
            raise AssertionError(f"{type_name} seed is implausibly large: {summary}")
        missing_layers = {"MASS", "MID", "ROUTE", "PROP"} - set(expanded["layers"])
        if missing_layers:
            raise AssertionError(f"{type_name} misses visible layers: {sorted(missing_layers)}")
        missing_roles = {
            "SILHOUETTE",
            "STRUCTURE",
            "NAVIGATION",
            "STATE_FEEDBACK",
        } - set(expanded["design_roles"])
        if missing_roles:
            raise AssertionError(f"{type_name} misses world roles: {sorted(missing_roles)}")
        collision_share = expanded["construction_kinds"].get("COLLISION_PROXY", 0) / expanded[
            "expanded_total"
        ]
        if collision_share > 0.10:
            raise AssertionError(f"{type_name} overuses collision proxies: {collision_share}")
        if density_summary["stage"] != "graybox":
            raise AssertionError(f"{type_name} density seed masquerades as final")
        if density_summary["expanded_total"] != expanded["expanded_total"]:
            raise AssertionError(f"{type_name} density total drift")
        if density_summary["zones"] != expanded["zones"]:
            raise AssertionError(f"{type_name} density zones drift")
        if density_summary["layers"] != expanded["layers"]:
            raise AssertionError(f"{type_name} density layers drift")
        if density_summary["graybox_total"] != expanded["layers"].get("COL", 0):
            raise AssertionError(f"{type_name} graybox proxy count drift")
        if design_summary["assembly"]["expanded_total"] != expanded["expanded_total"]:
            raise AssertionError(f"{type_name} design assembly total drift")
        if set(design["theme"]["assembly_families"]) != set(expanded["families"]):
            raise AssertionError(f"{type_name} design family routing drift")
        declared_family_order = [family["name"] for family in plan["families"]]
        if design["theme"]["assembly_families"] != declared_family_order:
            raise AssertionError(f"{type_name} design family priority order drift")
        if not bundle_summary["density_cross_checked"]:
            raise AssertionError(f"{type_name} concept bundle did not cross-check density")
        if bundle_summary["maturity"] != "concept":
            raise AssertionError(f"{type_name} generated design masquerades as final")
        if binding_summary["component_role_count"] != bundle_summary["component_role_count"]:
            raise AssertionError(f"{type_name} component binding coverage drift")
        if binding_summary["status_counts"] != {
            "unresolved": binding_summary["component_role_count"]
        }:
            raise AssertionError(f"{type_name} generated binding claims unverified evidence")
        if theme_summary["family_statuses"] != {
            "unresolved": len(expanded["families"])
        }:
            raise AssertionError(f"{type_name} generated theme family coverage drift")
        if theme_summary["zone_statuses"] != {
            "unresolved": len(expanded["zones"])
        }:
            raise AssertionError(f"{type_name} generated theme zone coverage drift")
        if performance_summary["view_count"] != len(expanded["zones"]) + 1:
            raise AssertionError(f"{type_name} generated performance view coverage drift")
        if performance_summary["measurement_statuses"] != {
            "unmeasured": performance_summary["view_count"]
        }:
            raise AssertionError(f"{type_name} generated performance claims fake measurements")

    invalid_density = generate_density_ledger(generate_seed("short_race"))
    invalid_density["declared"]["expanded_total"] += 1
    try:
        validate_density_plan(invalid_density)
    except DensityPlanError:
        pass
    else:
        raise AssertionError("a drifted generated density ledger was accepted")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a component-agnostic, primitive-led assembly seed for one "
            "of the 17 Eggy map primary types."
        )
    )
    parser.add_argument("--type", choices=sorted(PRIMARY_TYPES))
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--density-output",
        type=Path,
        help="also write a graybox-stage density ledger derived from expansion",
    )
    parser.add_argument(
        "--design-output",
        type=Path,
        help="also write a concept design ledger aligned to assembly and density",
    )
    parser.add_argument(
        "--binding-output",
        type=Path,
        help="also write a complete unresolved component-role binding template",
    )
    parser.add_argument(
        "--theme-output",
        type=Path,
        help="also write an unresolved family/zone theme-adaptation template",
    )
    parser.add_argument(
        "--performance-output",
        type=Path,
        help="also write an assembly-derived unmeasured per-view performance ledger",
    )
    parser.add_argument("--summary-only", action="store_true")
    parser.add_argument("--density-only", action="store_true")
    parser.add_argument("--design-only", action="store_true")
    parser.add_argument("--binding-only", action="store_true")
    parser.add_argument("--theme-only", action="store_true")
    parser.add_argument("--performance-only", action="store_true")
    parser.add_argument("--all-summary", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        _self_test()
        print("self-test passed")
        return 0
    selected_output_modes = sum(
        bool(value)
        for value in (
            args.summary_only,
            args.density_only,
            args.design_only,
            args.binding_only,
            args.theme_only,
            args.performance_only,
        )
    )
    if selected_output_modes > 1:
        parser.error(
            "--summary-only, --density-only, --design-only, --binding-only, --theme-only "
            "and --performance-only "
            "are mutually exclusive"
        )
    if args.all_summary and (
        args.density_only
        or args.design_only
        or args.binding_only
        or args.theme_only
        or args.performance_only
        or args.density_output is not None
        or args.design_output is not None
        or args.binding_output is not None
        or args.theme_output is not None
        or args.performance_output is not None
    ):
        parser.error("ledger output requires one --type")
    if args.all_summary:
        payload: Any = [_seed_summary(type_name) for type_name in sorted(PRIMARY_TYPES)]
    else:
        if args.type is None:
            parser.error("--type is required unless --all-summary or --self-test is used")
        try:
            plan = generate_seed(args.type)
            density = generate_density_ledger(plan)
            design = generate_design_ledger(plan, density)
            binding = generate_component_binding(plan)
            theme_adaptation = generate_theme_adaptation(plan, design)
            performance = generate_performance_plan(plan, design)
            if args.performance_only:
                payload = performance
            elif args.theme_only:
                payload = theme_adaptation
            elif args.binding_only:
                payload = binding
            elif args.design_only:
                payload = design
            elif args.density_only:
                payload = density
            else:
                payload = _seed_summary(args.type) if args.summary_only else plan
        except (
            BundleError,
            BindingError,
            DensityPlanError,
            DesignPlanError,
            ExpansionError,
            PerformancePlanError,
            SeedError,
            ThemeAdaptationError,
        ) as exc:
            print(f"cannot generate seed: {exc}", file=sys.stderr)
            return 2
        if args.density_output is not None:
            args.density_output.write_text(
                json.dumps(density, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        if args.design_output is not None:
            args.design_output.write_text(
                json.dumps(design, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        if args.binding_output is not None:
            args.binding_output.write_text(
                json.dumps(binding, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        if args.theme_output is not None:
            args.theme_output.write_text(
                json.dumps(theme_adaptation, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        if args.performance_output is not None:
            args.performance_output.write_text(
                json.dumps(performance, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.output is not None:
        args.output.write_text(rendered, encoding="utf-8")
        if (
            not args.summary_only
            and not args.density_only
            and not args.design_only
            and not args.binding_only
            and not args.theme_only
            and not args.performance_only
            and not args.all_summary
        ):
            print(json.dumps(_seed_summary(args.type), ensure_ascii=False, indent=2))
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

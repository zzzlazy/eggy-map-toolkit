#!/usr/bin/env python3
"""Audit whether a parameterized Eggy world has been genuinely themed.

The design ledger states a theme and the assembly ledger states geometry.  This
third record binds the two: every assembly family and zone must explain how its
shape grammar, material rhythm, controlled variants, world-state response, and
real camera reviews express the promised world.  The audit checks coverage and
bookkeeping; it cannot judge visual quality without the referenced play-camera
reviews.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
import json
from pathlib import Path
import sys
from typing import Any

from audit_design_plan import (
    DesignPlanError,
    example_plan as design_example_plan,
    validate_design_plan,
)
from expand_assembly_plan import (
    ExpansionError,
    example_plan as assembly_example_plan,
    expand_plan,
)


STAGES = {"design", "review", "predeploy"}
ADAPTATION_STATUSES = {"unresolved", "planned", "reviewed"}
REVIEW_STATUSES = {"planned", "tested"}
STATE_MODES = {"unresolved", "static", "changes"}
GLOBAL_REVIEW_NAMES = {
    "silhouette",
    "prefab_removal",
    "three_distance",
    "grayscale",
    "repetition",
    "state",
    "clearance",
    "cost",
}
THEME_IDENTITY_FIELDS = (
    "world_sentence",
    "memory_silhouette",
    "proportion_words",
    "base_shapes",
    "material_rhythm",
    "color_roles",
    "world_state_change",
    "banned_list",
)
PLACEHOLDER_PREFIXES = (
    "tbd",
    "todo",
    "unresolved",
    "replace with",
    "define ",
    "待定",
    "未解析",
    "待填写",
)


class ThemeAdaptationError(ValueError):
    pass


def _mapping(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ThemeAdaptationError(f"{path} must be an object")
    return value


def _list(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise ThemeAdaptationError(f"{path} must be an array")
    return value


def _string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ThemeAdaptationError(f"{path} must be a non-empty string")
    return value.strip()


def _meaningful(value: Any, path: str) -> str:
    text = _string(value, path)
    lowered = text.casefold()
    if len(text) < 8 or lowered.startswith(PLACEHOLDER_PREFIXES):
        raise ThemeAdaptationError(f"{path} must replace the unresolved placeholder")
    return text


def _integer(value: Any, path: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ThemeAdaptationError(f"{path} must be an integer >= {minimum}")
    return value


def _string_list(value: Any, path: str, *, minimum: int = 0) -> list[str]:
    raw = _list(value, path)
    if len(raw) < minimum:
        raise ThemeAdaptationError(f"{path} must contain at least {minimum} items")
    result = [_string(item, f"{path}[{index}]") for index, item in enumerate(raw)]
    if len(result) != len(set(result)):
        raise ThemeAdaptationError(f"{path} contains duplicates")
    return result


def _require_fields(value: dict[str, Any], required: set[str], path: str) -> None:
    missing = sorted(required - set(value))
    if missing:
        raise ThemeAdaptationError(f"{path} is missing: {', '.join(missing)}")


def _theme_identity(theme: dict[str, Any]) -> dict[str, Any]:
    return {field: deepcopy(theme[field]) for field in THEME_IDENTITY_FIELDS}


def _source_facts(
    design_plan: Any, assembly_plan: Any
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    try:
        design_summary = validate_design_plan(design_plan)
        expanded = expand_plan(assembly_plan)
    except (DesignPlanError, ExpansionError) as exc:
        raise ThemeAdaptationError(str(exc)) from exc

    design = _mapping(design_plan, "design_plan")
    assembly = _mapping(assembly_plan, "assembly_plan")
    theme = _mapping(design.get("theme"), "design_plan.theme")
    summary = expanded["summary"]
    primary_type = _string(design.get("primary_type"), "design_plan.primary_type")
    assembly_type = assembly.get("primary_type")
    if assembly_type is not None and assembly_type != primary_type:
        raise ThemeAdaptationError(
            "assembly_plan.primary_type does not match design_plan.primary_type"
        )
    density_profile = _string(
        design["assembly_budget"].get("density_profile"),
        "design_plan.assembly_budget.density_profile",
    )
    assembly_density = assembly.get("density_profile")
    if assembly_density is not None and assembly_density != density_profile:
        raise ThemeAdaptationError(
            "assembly_plan.density_profile does not match the design ledger"
        )
    design_total = _integer(
        design["assembly_budget"].get("expanded_total"),
        "design_plan.assembly_budget.expanded_total",
    )
    if design_total != summary["expanded_total"]:
        raise ThemeAdaptationError(
            "design and assembly expanded totals differ: "
            f"{design_total} != {summary['expanded_total']}"
        )

    declared_families = _string_list(
        theme.get("assembly_families"), "design_plan.theme.assembly_families", minimum=1
    )
    actual_families = set(summary["families"])
    if set(declared_families) != actual_families:
        raise ThemeAdaptationError(
            "theme assembly families and expanded assembly families differ: "
            f"theme_only={sorted(set(declared_families) - actual_families)}, "
            f"assembly_only={sorted(actual_families - set(declared_families))}"
        )

    family_declarations: dict[str, dict[str, Any]] = {}
    for index, raw_family in enumerate(_list(assembly.get("families"), "assembly_plan.families")):
        family = _mapping(raw_family, f"assembly_plan.families[{index}]")
        name = _string(family.get("name"), f"assembly_plan.families[{index}].name")
        family_declarations[name] = family

    layouts_by_family: dict[str, set[str]] = defaultdict(set)
    for index, raw_placement in enumerate(
        _list(assembly.get("placements"), "assembly_plan.placements")
    ):
        placement = _mapping(raw_placement, f"assembly_plan.placements[{index}]")
        family_name = _string(
            placement.get("family"), f"assembly_plan.placements[{index}].family"
        )
        layouts_by_family[family_name].add(
            _string(placement.get("layout"), f"assembly_plan.placements[{index}].layout")
        )

    family_zones: dict[str, set[str]] = defaultdict(set)
    family_roles: dict[str, set[str]] = defaultdict(set)
    zone_families: dict[str, set[str]] = defaultdict(set)
    zone_layers: dict[str, Counter[str]] = defaultdict(Counter)
    zone_roles: dict[str, set[str]] = defaultdict(set)
    for instance in expanded["instances"]:
        family = instance["family"]
        zone = instance["zone"]
        family_zones[family].add(zone)
        family_roles[family].update(instance["design_roles"])
        zone_families[zone].add(family)
        zone_layers[zone][instance["layer"]] += 1
        zone_roles[zone].update(instance["design_roles"])

    shell_names_by_zone: dict[str, set[str]] = defaultdict(set)
    views_by_zone: dict[str, set[str]] = defaultdict(set)
    anchors_by_zone: dict[str, set[str]] = defaultdict(set)
    shell_family_coverage: set[str] = set()
    shell_zone_coverage: set[str] = set()
    all_review_views: set[str] = set()
    for index, raw_shell in enumerate(
        _list(theme.get("world_shells"), "design_plan.theme.world_shells")
    ):
        shell = _mapping(raw_shell, f"design_plan.theme.world_shells[{index}]")
        shell_name = _string(shell.get("name"), f"design_plan.theme.world_shells[{index}].name")
        zones = _string_list(
            shell.get("assembly_zones"),
            f"design_plan.theme.world_shells[{index}].assembly_zones",
            minimum=1,
        )
        shell_families = _string_list(
            shell.get("assembly_families"),
            f"design_plan.theme.world_shells[{index}].assembly_families",
            minimum=2,
        )
        shell_family_coverage.update(shell_families)
        shell_zone_coverage.update(zones)
        anchors = _string_list(
            shell.get("scale_anchors"),
            f"design_plan.theme.world_shells[{index}].scale_anchors",
            minimum=2,
        )
        view_names: list[str] = []
        for view_index, raw_view in enumerate(
            _list(shell.get("review_views"), f"design_plan.theme.world_shells[{index}].review_views")
        ):
            view = _mapping(
                raw_view,
                f"design_plan.theme.world_shells[{index}].review_views[{view_index}]",
            )
            view_name = _string(
                view.get("name"),
                f"design_plan.theme.world_shells[{index}].review_views[{view_index}].name",
            )
            if view_name in all_review_views:
                raise ThemeAdaptationError(f"duplicate world-shell review view {view_name}")
            all_review_views.add(view_name)
            view_names.append(view_name)
        for zone in zones:
            shell_names_by_zone[zone].add(shell_name)
            views_by_zone[zone].update(view_names)
            anchors_by_zone[zone].update(anchors)

    actual_zones = set(summary["zones"])
    if shell_zone_coverage != actual_zones:
        raise ThemeAdaptationError(
            "theme world-shell zones and expanded assembly zones differ: "
            f"theme_only={sorted(shell_zone_coverage - actual_zones)}, "
            f"assembly_only={sorted(actual_zones - shell_zone_coverage)}"
        )
    if shell_family_coverage != actual_families:
        raise ThemeAdaptationError(
            "every assembly family must be assigned to at least one world shell"
        )

    family_facts: dict[str, dict[str, Any]] = {}
    for family_name in declared_families:
        declaration = family_declarations[family_name]
        variants = _string_list(
            declaration.get("variants"),
            f"assembly_plan family {family_name}.variants",
            minimum=1,
        )
        zones = sorted(family_zones[family_name])
        available_views = sorted(
            {view for zone in zones for view in views_by_zone[zone]}
        )
        family_facts[family_name] = {
            "instance_count": summary["families"][family_name],
            "zones": zones,
            "layouts": sorted(layouts_by_family[family_name]),
            "variant_names": variants,
            "design_roles": sorted(family_roles[family_name]),
            "available_review_views": available_views,
        }

    zone_facts: dict[str, dict[str, Any]] = {}
    for zone_name in sorted(actual_zones):
        zone_facts[zone_name] = {
            "instance_count": summary["zones"][zone_name],
            "families": sorted(zone_families[zone_name]),
            "layers": dict(sorted(zone_layers[zone_name].items())),
            "design_roles": sorted(zone_roles[zone_name]),
            "world_shells": sorted(shell_names_by_zone[zone_name]),
            "available_review_views": sorted(views_by_zone[zone_name]),
            "available_scale_anchors": sorted(anchors_by_zone[zone_name]),
        }

    facts = {
        "primary_type": primary_type,
        "density_profile": density_profile,
        "expanded_total": summary["expanded_total"],
        "theme_identity": _theme_identity(theme),
        "theme_assembly_families": declared_families,
        "family_facts": family_facts,
        "zone_facts": zone_facts,
        "all_review_views": all_review_views,
        "design_stage": design_summary["stage"],
        "design_maturity": design_summary["maturity"],
    }
    return facts, design, assembly


def _global_review_template(name: str) -> dict[str, Any]:
    methods = {
        "silhouette": "Capture a play-camera view in flat value and compare landmark, route opening, and danger edge.",
        "prefab_removal": "Hide sparse theme assets and inspect whether primitive mass, structure, and seams still express the world.",
        "three_distance": "Inspect foreground contact, reachable midground anchor, and directional background in a real play camera.",
        "grayscale": "Remove hue information and check route, danger, interaction, and goal value separation.",
        "repetition": "Inspect consecutive copies for controlled A/B/C rhythm without random seams or gameplay drift.",
        "state": "Trigger the declared world-state change and compare feedback, system result, and recovery.",
        "clearance": "Traverse target-player routes and camera pockets with theme detail and moving sweeps enabled.",
        "cost": "Measure the densest view after collision, shadow, transparency, dynamics, and logic policies are applied.",
    }
    acceptance = {
        "silhouette": "The memory silhouette, next legal opening, and danger boundary remain distinct.",
        "prefab_removal": "Removing sparse hero assets does not collapse the theme into generic boxes.",
        "three_distance": "All three depth layers have different jobs and the midground contains a reachable action.",
        "grayscale": "Critical semantics remain readable without relying on hue alone.",
        "repetition": "Variation changes theme expression while interfaces, clearance, and fairness stay invariant.",
        "state": "The visible change and authoritative state agree, then reset without residue.",
        "clearance": "No theme detail blocks contact surfaces, multiplayer width, mechanisms, or the play camera.",
        "cost": "The tested target device remains within the declared performance contract after safe degradation.",
    }
    return {
        "name": name,
        "status": "planned",
        "method": methods[name],
        "acceptance": acceptance[name],
        "result": None,
        "review_views": [],
    }


def theme_adaptation_template(design_plan: Any, assembly_plan: Any) -> dict[str, Any]:
    facts, _, _ = _source_facts(design_plan, assembly_plan)
    family_adaptations: list[dict[str, Any]] = []
    for family_name in facts["theme_assembly_families"]:
        source = facts["family_facts"][family_name]
        family_adaptations.append(
            {
                "family_name": family_name,
                "instance_count": source["instance_count"],
                "zones": source["zones"],
                "layouts": source["layouts"],
                "variant_names": source["variant_names"],
                "design_roles": source["design_roles"],
                "available_review_views": source["available_review_views"],
                "status": "unresolved",
                "motif_sentence": "unresolved: define a place-specific repeated motif",
                "silhouette_contribution": "unresolved: define this family's silhouette job",
                "structural_grammar": "unresolved: define supports, spans, joints, seams, and endings",
                "shape_roles": [],
                "material_applications": [],
                "contact_and_clearance": "unresolved: define playable-contact and camera-clearance rules",
                "variant_rules": [],
                "world_state_response": {
                    "mode": "unresolved",
                    "description": "unresolved: decide whether this family changes with world state",
                },
                "prefab_removal_expectation": "unresolved: state what remains recognizable without sparse hero assets",
                "banned_shortcuts": [],
                "reviewed_views": [],
            }
        )

    zone_adaptations: list[dict[str, Any]] = []
    for zone_name, source in facts["zone_facts"].items():
        zone_adaptations.append(
            {
                "zone": zone_name,
                "instance_count": source["instance_count"],
                "families": source["families"],
                "layers": source["layers"],
                "design_roles": source["design_roles"],
                "world_shells": source["world_shells"],
                "available_review_views": source["available_review_views"],
                "status": "unresolved",
                "foreground": "unresolved: define contact-scale foreground treatment",
                "midground": "unresolved: define the next reachable themed action",
                "background": "unresolved: define a low-cost directional silhouette",
                "scale_anchors": source["available_scale_anchors"],
                "route_or_activity_readability": "unresolved: define how the player reads the next action",
                "density_rationale": "unresolved: explain why detail is concentrated here",
                "reviewed_views": [],
            }
        )

    return {
        "schema_version": 1,
        "stage": "design",
        "primary_type": facts["primary_type"],
        "density_profile": facts["density_profile"],
        "assembly_expected_total": facts["expanded_total"],
        "theme_identity": facts["theme_identity"],
        "family_adaptations": family_adaptations,
        "zone_adaptations": zone_adaptations,
        "global_reviews": [
            _global_review_template(name) for name in sorted(GLOBAL_REVIEW_NAMES)
        ],
        "verification_boundary": (
            "This ledger proves coverage and declared review status, not visual quality. "
            "Reviewed claims require the named real play-camera evidence."
        ),
    }


def _validate_family_adaptations(
    root: dict[str, Any], facts: dict[str, Any], stage: str
) -> tuple[Counter[str], Counter[str], int]:
    entries = _list(root.get("family_adaptations"), "family_adaptations")
    by_name: dict[str, dict[str, Any]] = {}
    statuses: Counter[str] = Counter()
    shape_use: Counter[str] = Counter()
    changing_count = 0
    color_roles = set(facts["theme_identity"]["color_roles"])
    allowed_shapes = set(facts["theme_identity"]["base_shapes"])

    for index, raw in enumerate(entries):
        path = f"family_adaptations[{index}]"
        entry = _mapping(raw, path)
        _require_fields(
            entry,
            {
                "family_name",
                "instance_count",
                "zones",
                "layouts",
                "variant_names",
                "design_roles",
                "available_review_views",
                "status",
                "motif_sentence",
                "silhouette_contribution",
                "structural_grammar",
                "shape_roles",
                "material_applications",
                "contact_and_clearance",
                "variant_rules",
                "world_state_response",
                "prefab_removal_expectation",
                "banned_shortcuts",
                "reviewed_views",
            },
            path,
        )
        name = _string(entry["family_name"], f"{path}.family_name")
        if name in by_name:
            raise ThemeAdaptationError(f"duplicate family adaptation {name}")
        by_name[name] = entry
        if name not in facts["family_facts"]:
            continue
        source = facts["family_facts"][name]
        comparisons = {
            "instance_count": _integer(entry["instance_count"], f"{path}.instance_count"),
            "zones": _string_list(entry["zones"], f"{path}.zones", minimum=1),
            "layouts": _string_list(entry["layouts"], f"{path}.layouts", minimum=1),
            "variant_names": _string_list(entry["variant_names"], f"{path}.variant_names", minimum=1),
            "design_roles": _string_list(entry["design_roles"], f"{path}.design_roles", minimum=1),
            "available_review_views": _string_list(
                entry["available_review_views"], f"{path}.available_review_views", minimum=1
            ),
        }
        for key, actual in comparisons.items():
            expected = source[key]
            if key == "instance_count":
                equal = actual == expected
            else:
                equal = set(actual) == set(expected)
            if not equal:
                raise ThemeAdaptationError(
                    f"{path}.{key} drifted from the current assembly/design source"
                )

        status = _string(entry["status"], f"{path}.status")
        if status not in ADAPTATION_STATUSES:
            raise ThemeAdaptationError(
                f"{path}.status must be one of {', '.join(sorted(ADAPTATION_STATUSES))}"
            )
        statuses[status] += 1
        reviewed_views = _string_list(
            entry["reviewed_views"], f"{path}.reviewed_views"
        )
        unknown_views = set(reviewed_views) - set(source["available_review_views"])
        if unknown_views:
            raise ThemeAdaptationError(
                f"{path}.reviewed_views contains unavailable views: {sorted(unknown_views)}"
            )
        state = _mapping(entry["world_state_response"], f"{path}.world_state_response")
        mode = _string(state.get("mode"), f"{path}.world_state_response.mode")
        if mode not in STATE_MODES:
            raise ThemeAdaptationError(
                f"{path}.world_state_response.mode must be unresolved, static, or changes"
            )

        if status == "unresolved":
            if stage != "design":
                raise ThemeAdaptationError(
                    f"{path} cannot remain unresolved at stage={stage}"
                )
            continue

        for field in (
            "motif_sentence",
            "silhouette_contribution",
            "structural_grammar",
            "contact_and_clearance",
            "prefab_removal_expectation",
        ):
            _meaningful(entry[field], f"{path}.{field}")
        _meaningful(state.get("description"), f"{path}.world_state_response.description")
        if mode == "unresolved":
            raise ThemeAdaptationError(
                f"{path}.world_state_response.mode must be resolved"
            )
        if mode == "changes":
            changing_count += 1

        shape_roles = _list(entry["shape_roles"], f"{path}.shape_roles")
        if not shape_roles:
            raise ThemeAdaptationError(f"{path}.shape_roles cannot be empty once planned")
        seen_shapes: set[str] = set()
        for role_index, raw_role in enumerate(shape_roles):
            role_path = f"{path}.shape_roles[{role_index}]"
            role = _mapping(raw_role, role_path)
            shape = _string(role.get("shape"), f"{role_path}.shape")
            if shape not in allowed_shapes:
                raise ThemeAdaptationError(
                    f"{role_path}.shape must come from theme_identity.base_shapes"
                )
            if shape in seen_shapes:
                raise ThemeAdaptationError(f"{path}.shape_roles repeats {shape}")
            seen_shapes.add(shape)
            shape_use[shape] += 1
            _meaningful(role.get("job"), f"{role_path}.job")

        materials = _list(
            entry["material_applications"], f"{path}.material_applications"
        )
        if not materials:
            raise ThemeAdaptationError(
                f"{path}.material_applications cannot be empty once planned"
            )
        used_semantics: set[str] = set()
        for material_index, raw_material in enumerate(materials):
            material_path = f"{path}.material_applications[{material_index}]"
            material = _mapping(raw_material, material_path)
            semantic = _string(
                material.get("semantic_role"), f"{material_path}.semantic_role"
            )
            if semantic not in color_roles:
                raise ThemeAdaptationError(
                    f"{material_path}.semantic_role is absent from theme color roles"
                )
            if semantic in used_semantics:
                raise ThemeAdaptationError(
                    f"{path}.material_applications repeats semantic role {semantic}"
                )
            used_semantics.add(semantic)
            _meaningful(material.get("application"), f"{material_path}.application")

        variant_rules = _list(entry["variant_rules"], f"{path}.variant_rules")
        variant_names: set[str] = set()
        for variant_index, raw_rule in enumerate(variant_rules):
            rule_path = f"{path}.variant_rules[{variant_index}]"
            rule = _mapping(raw_rule, rule_path)
            variant = _string(rule.get("variant"), f"{rule_path}.variant")
            if variant in variant_names:
                raise ThemeAdaptationError(f"{path}.variant_rules repeats {variant}")
            variant_names.add(variant)
            _meaningful(rule.get("visible_change"), f"{rule_path}.visible_change")
            invariants = _string_list(
                rule.get("invariants"), f"{rule_path}.invariants", minimum=2
            )
            for invariant_index, invariant in enumerate(invariants):
                _meaningful(invariant, f"{rule_path}.invariants[{invariant_index}]")
        if variant_names != set(source["variant_names"]):
            raise ThemeAdaptationError(
                f"{path}.variant_rules must cover every declared family variant exactly once"
            )
        shortcuts = _string_list(
            entry["banned_shortcuts"], f"{path}.banned_shortcuts", minimum=1
        )
        for shortcut_index, shortcut in enumerate(shortcuts):
            _meaningful(shortcut, f"{path}.banned_shortcuts[{shortcut_index}]")
        if status == "reviewed" and not reviewed_views:
            raise ThemeAdaptationError(
                f"{path}.reviewed_views needs real play-camera evidence"
            )

    expected_names = set(facts["family_facts"])
    if set(by_name) != expected_names:
        raise ThemeAdaptationError(
            "family adaptation coverage mismatch: "
            f"missing={sorted(expected_names - set(by_name))}, "
            f"extra={sorted(set(by_name) - expected_names)}"
        )
    return statuses, shape_use, changing_count


def _validate_zone_adaptations(
    root: dict[str, Any], facts: dict[str, Any], stage: str
) -> Counter[str]:
    entries = _list(root.get("zone_adaptations"), "zone_adaptations")
    by_name: dict[str, dict[str, Any]] = {}
    statuses: Counter[str] = Counter()
    for index, raw in enumerate(entries):
        path = f"zone_adaptations[{index}]"
        entry = _mapping(raw, path)
        _require_fields(
            entry,
            {
                "zone",
                "instance_count",
                "families",
                "layers",
                "design_roles",
                "world_shells",
                "available_review_views",
                "status",
                "foreground",
                "midground",
                "background",
                "scale_anchors",
                "route_or_activity_readability",
                "density_rationale",
                "reviewed_views",
            },
            path,
        )
        zone = _string(entry["zone"], f"{path}.zone")
        if zone in by_name:
            raise ThemeAdaptationError(f"duplicate zone adaptation {zone}")
        by_name[zone] = entry
        if zone not in facts["zone_facts"]:
            continue
        source = facts["zone_facts"][zone]
        count = _integer(entry["instance_count"], f"{path}.instance_count")
        if count != source["instance_count"]:
            raise ThemeAdaptationError(f"{path}.instance_count drifted from assembly")
        for key in (
            "families",
            "design_roles",
            "world_shells",
            "available_review_views",
        ):
            actual = _string_list(entry[key], f"{path}.{key}", minimum=1)
            if set(actual) != set(source[key]):
                raise ThemeAdaptationError(f"{path}.{key} drifted from source")
        layers = _mapping(entry["layers"], f"{path}.layers")
        normalized_layers = {
            _string(key, f"{path}.layers key"): _integer(
                value, f"{path}.layers.{key}"
            )
            for key, value in layers.items()
        }
        if normalized_layers != source["layers"]:
            raise ThemeAdaptationError(f"{path}.layers drifted from assembly")

        status = _string(entry["status"], f"{path}.status")
        if status not in ADAPTATION_STATUSES:
            raise ThemeAdaptationError(
                f"{path}.status must be one of {', '.join(sorted(ADAPTATION_STATUSES))}"
            )
        statuses[status] += 1
        reviewed_views = _string_list(
            entry["reviewed_views"], f"{path}.reviewed_views"
        )
        unknown_views = set(reviewed_views) - set(source["available_review_views"])
        if unknown_views:
            raise ThemeAdaptationError(
                f"{path}.reviewed_views contains unavailable views: {sorted(unknown_views)}"
            )
        if status == "unresolved":
            if stage != "design":
                raise ThemeAdaptationError(
                    f"{path} cannot remain unresolved at stage={stage}"
                )
            continue
        for field in (
            "foreground",
            "midground",
            "background",
            "route_or_activity_readability",
            "density_rationale",
        ):
            _meaningful(entry[field], f"{path}.{field}")
        anchors = _string_list(entry["scale_anchors"], f"{path}.scale_anchors", minimum=2)
        if not set(anchors).issubset(set(source["available_scale_anchors"])):
            raise ThemeAdaptationError(
                f"{path}.scale_anchors must come from assigned world shells"
            )
        if status == "reviewed" and len(reviewed_views) < 2:
            raise ThemeAdaptationError(
                f"{path}.reviewed_views needs at least two real play-camera views"
            )

    expected_names = set(facts["zone_facts"])
    if set(by_name) != expected_names:
        raise ThemeAdaptationError(
            "zone adaptation coverage mismatch: "
            f"missing={sorted(expected_names - set(by_name))}, "
            f"extra={sorted(set(by_name) - expected_names)}"
        )
    return statuses


def _validate_global_reviews(
    root: dict[str, Any], facts: dict[str, Any], stage: str
) -> Counter[str]:
    entries = _list(root.get("global_reviews"), "global_reviews")
    by_name: dict[str, dict[str, Any]] = {}
    statuses: Counter[str] = Counter()
    for index, raw in enumerate(entries):
        path = f"global_reviews[{index}]"
        entry = _mapping(raw, path)
        _require_fields(
            entry,
            {"name", "status", "method", "acceptance", "result", "review_views"},
            path,
        )
        name = _string(entry["name"], f"{path}.name")
        if name in by_name:
            raise ThemeAdaptationError(f"duplicate global review {name}")
        by_name[name] = entry
        status = _string(entry["status"], f"{path}.status")
        if status not in REVIEW_STATUSES:
            raise ThemeAdaptationError(
                f"{path}.status must be planned or tested"
            )
        statuses[status] += 1
        _meaningful(entry["method"], f"{path}.method")
        _meaningful(entry["acceptance"], f"{path}.acceptance")
        views = _string_list(entry["review_views"], f"{path}.review_views")
        unknown_views = set(views) - facts["all_review_views"]
        if unknown_views:
            raise ThemeAdaptationError(
                f"{path}.review_views contains unknown views: {sorted(unknown_views)}"
            )
        if status == "tested":
            _meaningful(entry.get("result"), f"{path}.result")
            if not views:
                raise ThemeAdaptationError(
                    f"{path}.review_views must name the tested play-camera evidence"
                )
        elif entry.get("result") not in (None, ""):
            raise ThemeAdaptationError(
                f"{path}.result must remain null until the review is tested"
            )
    if set(by_name) != GLOBAL_REVIEW_NAMES:
        raise ThemeAdaptationError(
            "global review coverage mismatch: "
            f"missing={sorted(GLOBAL_REVIEW_NAMES - set(by_name))}, "
            f"extra={sorted(set(by_name) - GLOBAL_REVIEW_NAMES)}"
        )
    if stage == "predeploy" and statuses.get("planned", 0):
        raise ThemeAdaptationError("predeploy cannot retain planned global reviews")
    return statuses


def validate_theme_adaptation(
    design_plan: Any, assembly_plan: Any, adaptation_plan: Any
) -> dict[str, Any]:
    facts, _, _ = _source_facts(design_plan, assembly_plan)
    root = _mapping(adaptation_plan, "adaptation_plan")
    _require_fields(
        root,
        {
            "schema_version",
            "stage",
            "primary_type",
            "density_profile",
            "assembly_expected_total",
            "theme_identity",
            "family_adaptations",
            "zone_adaptations",
            "global_reviews",
            "verification_boundary",
        },
        "adaptation_plan",
    )
    version = _integer(root["schema_version"], "schema_version", minimum=1)
    if version != 1:
        raise ThemeAdaptationError(
            f"unsupported schema_version {version}; expected 1"
        )
    stage = _string(root["stage"], "stage")
    if stage not in STAGES:
        raise ThemeAdaptationError("stage must be design, review, or predeploy")
    if _string(root["primary_type"], "primary_type") != facts["primary_type"]:
        raise ThemeAdaptationError("primary_type drifted from design plan")
    if _string(root["density_profile"], "density_profile") != facts["density_profile"]:
        raise ThemeAdaptationError("density_profile drifted from design plan")
    if _integer(root["assembly_expected_total"], "assembly_expected_total") != facts[
        "expanded_total"
    ]:
        raise ThemeAdaptationError("assembly_expected_total drifted from assembly")
    identity = _mapping(root["theme_identity"], "theme_identity")
    if identity != facts["theme_identity"]:
        raise ThemeAdaptationError(
            "theme_identity drifted from the current design plan; regenerate or reconcile it"
        )
    _meaningful(root["verification_boundary"], "verification_boundary")

    family_statuses, shape_use, changing_count = _validate_family_adaptations(
        root, facts, stage
    )
    zone_statuses = _validate_zone_adaptations(root, facts, stage)
    review_statuses = _validate_global_reviews(root, facts, stage)

    if stage == "predeploy":
        if facts["design_stage"] != "predeploy" or facts["design_maturity"] != "final":
            raise ThemeAdaptationError(
                "theme predeploy requires a final design plan at stage=predeploy"
            )
        if family_statuses != Counter({"reviewed": len(facts["family_facts"])}):
            raise ThemeAdaptationError(
                "predeploy requires every family adaptation to be reviewed"
            )
        if zone_statuses != Counter({"reviewed": len(facts["zone_facts"])}):
            raise ThemeAdaptationError(
                "predeploy requires every zone adaptation to be reviewed"
            )
    if stage in {"review", "predeploy"}:
        minimum_shapes = min(2, len(facts["theme_identity"]["base_shapes"]))
        if len(shape_use) < minimum_shapes:
            raise ThemeAdaptationError(
                f"theme adaptation uses fewer than {minimum_shapes} declared base shapes"
            )
        if len(facts["family_facts"]) > 1 and max(shape_use.values(), default=0) < 2:
            raise ThemeAdaptationError(
                "at least one base shape must recur across families to unify the world"
            )
        if changing_count < 1:
            raise ThemeAdaptationError(
                "at least one assembly family must visibly respond to world state"
            )

    warnings: list[str] = []
    if family_statuses.get("unresolved"):
        warnings.append(
            f"{family_statuses['unresolved']} assembly families still need theme adaptation"
        )
    if zone_statuses.get("unresolved"):
        warnings.append(
            f"{zone_statuses['unresolved']} zones still need three-distance treatment"
        )
    if family_statuses.get("planned") or zone_statuses.get("planned"):
        warnings.append("planned adaptations still need real play-camera review")
    if review_statuses.get("planned"):
        warnings.append(
            f"{review_statuses['planned']} global visual reviews remain planned"
        )
    return {
        "schema_version": version,
        "stage": stage,
        "primary_type": facts["primary_type"],
        "density_profile": facts["density_profile"],
        "expanded_total": facts["expanded_total"],
        "family_count": len(facts["family_facts"]),
        "zone_count": len(facts["zone_facts"]),
        "family_statuses": dict(sorted(family_statuses.items())),
        "zone_statuses": dict(sorted(zone_statuses.items())),
        "global_review_statuses": dict(sorted(review_statuses.items())),
        "declared_shapes_used": sorted(shape_use),
        "state_changing_family_count": changing_count,
        "warnings": warnings,
    }


def _aligned_examples() -> tuple[dict[str, Any], dict[str, Any]]:
    design = design_example_plan()
    source_assembly = assembly_example_plan()
    base_family = source_assembly["families"][0]
    base_placement = source_assembly["placements"][0]
    family_names = [
        "SAIL_BRIDGE",
        "WIND_MAST",
        "SORTING_GATE",
        "DOCK_WALL",
        "ENVELOPE_FINISH",
    ]
    assembly = deepcopy(source_assembly)
    assembly["primary_type"] = "short_race"
    assembly["density_profile"] = "themed_short"
    assembly["families"] = []
    assembly["placements"] = []
    for index, name in enumerate(family_names):
        family = deepcopy(base_family)
        family["name"] = name
        assembly["families"].append(family)
        placement = deepcopy(base_placement)
        placement["name"] = f"FAMILY_{index}"
        placement["zone"] = "RUN"
        placement["family"] = name
        placement["origin"] = [index * 20, 0, 0]
        placement["count"] = 96
        assembly["placements"].append(placement)
    assembly["expected_total"] = 1200
    expanded = expand_plan(assembly)

    design["theme"]["assembly_families"] = family_names
    design["theme"]["world_shells"][0]["assembly_families"] = family_names
    design["theme"]["world_shells"][0]["assembly_zones"] = ["RUN"]
    design["assembly_budget"]["expanded_total"] = expanded["summary"][
        "expanded_total"
    ]
    design["assembly_budget"]["graybox_total"] = expanded["summary"][
        "layers"
    ].get("COL", 0)
    design["assembly_budget"]["asset_vocabulary_count"] = len(
        {instance["component_role"] for instance in expanded["instances"]}
    )
    design["assembly_budget"]["layers"] = expanded["summary"]["layers"]
    validate_design_plan(design)
    return design, assembly


def _completed_plan(
    design: dict[str, Any], assembly: dict[str, Any]
) -> dict[str, Any]:
    plan = theme_adaptation_template(design, assembly)
    plan["stage"] = "predeploy"
    shapes = plan["theme_identity"]["base_shapes"]
    semantics = list(plan["theme_identity"]["color_roles"])
    for index, family in enumerate(plan["family_adaptations"]):
        family["status"] = "reviewed"
        family["motif_sentence"] = (
            f"{family['family_name']} repeats a wind-loaded postal construction rhythm."
        )
        family["silhouette_contribution"] = (
            "It creates a distinct high-low span that supports the envelope-sail silhouette."
        )
        family["structural_grammar"] = (
            "Primary spans terminate in visible posts, joints, edge seams, and a deliberate end cap."
        )
        family["shape_roles"] = [
            {
                "shape": shapes[0],
                "job": "Carries the broad mass and readable long-distance silhouette.",
            },
            {
                "shape": shapes[1 + (index % (len(shapes) - 1))],
                "job": "Forms joints, edge rhythm, and contact-scale construction detail.",
            },
        ]
        family["material_applications"] = [
            {
                "semantic_role": semantics[0],
                "application": "Uses the quiet field material on broad non-interactive faces.",
            },
            {
                "semantic_role": "route",
                "application": "Uses a narrow high-value seam only where it confirms legal motion.",
            },
        ]
        family["contact_and_clearance"] = (
            "Decorative seams stay outside the continuous contact proxy and the target-player camera envelope."
        )
        family["variant_rules"] = [
            {
                "variant": variant,
                "visible_change": f"Variant {variant} changes the sail fold and seam cadence without changing traversal.",
                "invariants": [
                    "Entry, exit, and playable clearance remain identical across variants.",
                    "Collision, route length, and gameplay timing remain identical across variants.",
                ],
            }
            for variant in family["variant_names"]
        ]
        family["world_state_response"] = {
            "mode": "changes" if index == 0 else "static",
            "description": (
                "The first family folds its visible sail seams after the route commits."
                if index == 0
                else "This structural family stays stable so the changing route remains legible."
            ),
        }
        family["prefab_removal_expectation"] = (
            "Posts, spans, folds, and material seams still communicate a postal harbor after hero props are hidden."
        )
        family["banned_shortcuts"] = [
            "Do not replace the construction grammar with an unrelated one-piece decorative prefab."
        ]
        family["reviewed_views"] = family["available_review_views"][:1]

    for zone in plan["zone_adaptations"]:
        zone["status"] = "reviewed"
        zone["foreground"] = (
            "Contact edges, hardware, and seams establish thickness beside the player."
        )
        zone["midground"] = (
            "The next reachable postal span and its legal opening dominate the action layer."
        )
        zone["background"] = (
            "A low-cost sail silhouette preserves direction without duplicating contact detail."
        )
        zone["route_or_activity_readability"] = (
            "Warm edge stitching leads to the next opening while danger keeps a separate value and shape."
        )
        zone["density_rationale"] = (
            "Detail concentrates at landings, changes of direction, and the memory silhouette; backsides stay sparse."
        )
        zone["reviewed_views"] = zone["available_review_views"][:2]

    all_views = sorted(
        {
            view
            for zone in plan["zone_adaptations"]
            for view in zone["available_review_views"]
        }
    )
    for review in plan["global_reviews"]:
        review["status"] = "tested"
        review["result"] = (
            f"Recorded pass for {review['name']} in the named play-camera view."
        )
        review["review_views"] = all_views[:1]
    return plan


def _expect_invalid(
    design: dict[str, Any],
    assembly: dict[str, Any],
    plan: dict[str, Any],
    contains: str,
) -> None:
    try:
        validate_theme_adaptation(design, assembly, plan)
    except ThemeAdaptationError as exc:
        if contains not in str(exc):
            raise AssertionError(f"expected {contains!r}, got {str(exc)!r}") from exc
    else:
        raise AssertionError(f"expected invalid theme adaptation containing {contains!r}")


def _self_test() -> None:
    design, assembly = _aligned_examples()
    template = theme_adaptation_template(design, assembly)
    summary = validate_theme_adaptation(design, assembly, template)
    if summary["family_statuses"] != {"unresolved": 5}:
        raise AssertionError("template should keep all five families unresolved")
    if summary["zone_statuses"] != {"unresolved": 1}:
        raise AssertionError("template should keep the zone unresolved")

    completed = _completed_plan(design, assembly)
    completed_summary = validate_theme_adaptation(design, assembly, completed)
    if completed_summary["warnings"]:
        raise AssertionError(f"completed plan has warnings: {completed_summary['warnings']}")

    missing_family = deepcopy(completed)
    missing_family["family_adaptations"].pop()
    _expect_invalid(design, assembly, missing_family, "coverage mismatch")

    count_drift = deepcopy(completed)
    count_drift["family_adaptations"][0]["instance_count"] += 1
    _expect_invalid(design, assembly, count_drift, "drifted")

    missing_variants = deepcopy(completed)
    missing_variants["family_adaptations"][0]["variant_rules"].pop()
    _expect_invalid(design, assembly, missing_variants, "every declared family variant")

    identity_drift = deepcopy(completed)
    identity_drift["theme_identity"]["world_sentence"] = "A generic recolored world."
    _expect_invalid(design, assembly, identity_drift, "theme_identity drifted")

    planned_predeploy = deepcopy(completed)
    planned_predeploy["global_reviews"][0]["status"] = "planned"
    planned_predeploy["global_reviews"][0]["result"] = None
    planned_predeploy["global_reviews"][0]["review_views"] = []
    _expect_invalid(design, assembly, planned_predeploy, "predeploy cannot retain planned")


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Audit theme adaptation coverage between an Eggy design ledger and a "
            "parameterized assembly plan."
        )
    )
    parser.add_argument("design_plan", nargs="?", type=Path)
    parser.add_argument("assembly_plan", nargs="?", type=Path)
    parser.add_argument("adaptation_plan", nargs="?", type=Path)
    parser.add_argument("--template", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        _self_test()
        print("self-test passed")
        return 0
    if args.design_plan is None or args.assembly_plan is None:
        parser.error("design_plan and assembly_plan are required unless --self-test is used")
    if args.template and args.adaptation_plan is not None:
        parser.error("adaptation_plan is not accepted with --template")
    if not args.template and args.adaptation_plan is None:
        parser.error("adaptation_plan is required unless --template is used")

    try:
        design = _load(args.design_plan)
        assembly = _load(args.assembly_plan)
        if args.template:
            payload: Any = theme_adaptation_template(design, assembly)
        else:
            payload = validate_theme_adaptation(
                design, assembly, _load(args.adaptation_plan)
            )
    except (
        OSError,
        json.JSONDecodeError,
        ThemeAdaptationError,
        DesignPlanError,
        ExpansionError,
    ) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.output is not None:
        args.output.write_text(rendered, encoding="utf-8")
    if args.json or args.output is None:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

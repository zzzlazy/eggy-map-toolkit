#!/usr/bin/env python3
"""Audit and route Eggy visual-world design support.

The catalog is a synthetic design-space aid.  Empirical support comes only
from eggy-map-designer's coverage ledger, and boundary or missing evidence
is never promoted by the existence of a detailed design profile.  An optional
primary type adds a topology pairing prompt; it does not score themes or
declare a combination proven.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any

from audit_design_plan import PRIMARY_TYPES


DESIGNER_ROOT = Path(__file__).resolve().parents[1]
SKILLS_ROOT = DESIGNER_ROOT.parent
DEFAULT_CATALOG = DESIGNER_ROOT / "references" / "visual-world-catalog.json"
DEFAULT_COVERAGE = (
    SKILLS_ROOT
    / "eggy-map-designer"
    / "references"
    / "research-coverage.json"
)

VALID_EMPIRICAL_STATUSES = {
    "verified_positive",
    "partial_positive",
    "boundary_only",
    "missing",
}
POSITIVE_EMPIRICAL_STATUSES = {"verified_positive", "partial_positive"}
SHELL_TYPES = {
    "linear_corridor",
    "room_sequence",
    "arena_bowl",
    "hub_spoke",
    "open_district",
    "loop_track",
    "vertical_stack",
    "branch_rejoin",
    "multi_scene_threshold",
    "showcase_panorama",
}
EXPECTED_VISUAL_WORLDS = {
    "canyon_mountain_cave",
    "tropical_mud_character_world",
    "winter_garden_showcase",
    "cellar_food_facility",
    "modern_city_narrative",
    "school_human_scale_interior",
    "industrial_mixed_scale",
    "island_survival_world",
    "vehicle_track_facility",
    "toy_candy_fairy_miniature",
    "ancient_castle_historic_street",
    "scifi_station_cyber_facility",
    "ocean_underwater_floating",
    "horror_ruin_mystery",
    "abstract_dream_music_data",
}

# Routing anchors only.  The actual morphology contract remains in
# references/world-shells-and-keyframes.md.
TYPE_SHELL_STARTS = {
    "short_race": ["linear_corridor", "loop_track", "branch_rejoin"],
    "chapter_challenge": ["room_sequence", "vertical_stack", "multi_scene_threshold"],
    "mechanism_puzzle": ["room_sequence", "hub_spoke"],
    "cooperative": ["branch_rejoin", "room_sequence"],
    "narrative_exploration": ["hub_spoke", "open_district", "multi_scene_threshold"],
    "survival": ["arena_bowl", "vertical_stack"],
    "score_contest": ["arena_bowl", "open_district", "hub_spoke"],
    "social_showcase": ["showcase_panorama", "hub_spoke"],
    "management_simulation": ["open_district", "room_sequence", "multi_scene_threshold"],
    "rhythm_performance": ["showcase_panorama", "linear_corridor", "arena_bowl"],
    "combat_boss": ["arena_bowl", "multi_scene_threshold"],
    "defense_strategy": ["hub_spoke", "open_district", "arena_bowl"],
    "stealth_infiltration": ["room_sequence", "open_district", "branch_rejoin"],
    "turn_based_strategy": ["arena_bowl", "showcase_panorama"],
    "sports_match": ["arena_bowl", "loop_track"],
    "sandbox_creation": ["open_district", "showcase_panorama"],
    "social_deduction": ["hub_spoke", "open_district", "room_sequence"],
}


class VisualSupportError(ValueError):
    """Raised when the visual-world support data is incomplete or misleading."""


def _object(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise VisualSupportError(f"{path} must be an object")
    return value


def _array(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise VisualSupportError(f"{path} must be an array")
    return value


def _string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise VisualSupportError(f"{path} must be a non-empty string")
    return value.strip()


def _string_array(
    value: Any,
    path: str,
    *,
    minimum: int = 0,
    maximum: int | None = None,
) -> list[str]:
    values = [
        _string(item, f"{path}[{index}]")
        for index, item in enumerate(_array(value, path))
    ]
    if len(values) < minimum:
        raise VisualSupportError(f"{path} must contain at least {minimum} items")
    if maximum is not None and len(values) > maximum:
        raise VisualSupportError(f"{path} must contain at most {maximum} items")
    if len(values) != len(set(values)):
        raise VisualSupportError(f"{path} contains duplicate values")
    return values


def _read_json(path: Path, label: str) -> Any:
    if not path.is_file():
        raise VisualSupportError(f"{label} does not exist: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VisualSupportError(f"cannot read {label}: {exc}") from exc


def _github_heading_slug(text: str) -> str:
    text = re.sub(r"`([^`]*)`", r"\1", text.strip().lower())
    text = re.sub(r"[^\w\-\s]", "", text, flags=re.UNICODE)
    return re.sub(r"\s", "-", text)


def _heading_slugs(path: Path) -> set[str]:
    slugs: set[str] = set()
    duplicates: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^#{1,6}\s+(.+?)\s*#*\s*$", line)
        if not match:
            continue
        base = _github_heading_slug(match.group(1))
        count = duplicates.get(base, 0)
        duplicates[base] = count + 1
        slugs.add(base if count == 0 else f"{base}-{count}")
    return slugs


def _resolve_reference(reference: str) -> tuple[Path, str | None]:
    raw_path, separator, fragment = reference.partition("#")
    if raw_path.startswith("skill:"):
        payload = raw_path[len("skill:") :]
        skill_name, slash, relative = payload.partition("/")
        if not slash or not skill_name or not relative:
            raise VisualSupportError(f"malformed skill reference: {reference}")
        path = SKILLS_ROOT / skill_name / relative
    else:
        path = DESIGNER_ROOT / raw_path
    return path.resolve(), fragment if separator else None


def _validate_reference(reference: str) -> None:
    path, fragment = _resolve_reference(reference)
    if not path.is_file():
        raise VisualSupportError(f"reference target does not exist: {reference}")
    if fragment and fragment not in _heading_slugs(path):
        raise VisualSupportError(
            f"reference fragment does not match a heading: {reference}"
        )


def _validate_profile(raw: Any, path: str) -> dict[str, Any]:
    profile = _object(raw, path)
    required = {
        "id",
        "label",
        "playbook_references",
        "world_sentence_pattern",
        "memory_silhouette",
        "proportion_words",
        "base_shape_roles",
        "assembly_families",
        "material_rhythm",
        "state_axes",
        "shell_starts",
        "primitive_expansion",
        "proof_gates",
        "banned_shortcuts",
    }
    if set(profile) != required:
        raise VisualSupportError(
            f"{path} fields mismatch: missing={sorted(required - set(profile))}, "
            f"extra={sorted(set(profile) - required)}"
        )

    identifier = _string(profile["id"], f"{path}.id")
    label = _string(profile["label"], f"{path}.label")
    references = _string_array(
        profile["playbook_references"], f"{path}.playbook_references", minimum=1
    )
    for reference in references:
        _validate_reference(reference)

    shapes: list[dict[str, Any]] = []
    for index, raw_shape in enumerate(_array(profile["base_shape_roles"], f"{path}.base_shape_roles")):
        shape_path = f"{path}.base_shape_roles[{index}]"
        shape = _object(raw_shape, shape_path)
        if set(shape) != {"shape", "roles"}:
            raise VisualSupportError(f"{shape_path} must contain only shape and roles")
        shapes.append(
            {
                "shape": _string(shape["shape"], f"{shape_path}.shape"),
                "roles": _string_array(shape["roles"], f"{shape_path}.roles", minimum=2),
            }
        )
    if len(shapes) < 3:
        raise VisualSupportError(f"{path}.base_shape_roles needs at least 3 shapes")
    if len({shape["shape"] for shape in shapes}) != len(shapes):
        raise VisualSupportError(f"{path}.base_shape_roles contains duplicate shapes")

    shells = _string_array(profile["shell_starts"], f"{path}.shell_starts", minimum=2)
    unknown_shells = sorted(set(shells) - SHELL_TYPES)
    if unknown_shells:
        raise VisualSupportError(f"{path}.shell_starts has unknown values: {unknown_shells}")

    expansion = _object(profile["primitive_expansion"], f"{path}.primitive_expansion")
    expansion_fields = {"mass", "mid", "route_contact", "state_detail", "proxy_split"}
    if set(expansion) != expansion_fields:
        raise VisualSupportError(
            f"{path}.primitive_expansion fields mismatch: "
            f"missing={sorted(expansion_fields - set(expansion))}, "
            f"extra={sorted(set(expansion) - expansion_fields)}"
        )
    normalized_expansion = {
        field: _string(expansion[field], f"{path}.primitive_expansion.{field}")
        for field in sorted(expansion_fields)
    }

    return {
        "id": identifier,
        "label": label,
        "playbook_references": references,
        "world_sentence_pattern": _string(
            profile["world_sentence_pattern"], f"{path}.world_sentence_pattern"
        ),
        "memory_silhouette": _string(
            profile["memory_silhouette"], f"{path}.memory_silhouette"
        ),
        "proportion_words": _string_array(
            profile["proportion_words"], f"{path}.proportion_words", minimum=2, maximum=4
        ),
        "base_shape_roles": shapes,
        "assembly_families": _string_array(
            profile["assembly_families"], f"{path}.assembly_families", minimum=4
        ),
        "material_rhythm": _string(profile["material_rhythm"], f"{path}.material_rhythm"),
        "state_axes": _string_array(profile["state_axes"], f"{path}.state_axes", minimum=2),
        "shell_starts": shells,
        "primitive_expansion": normalized_expansion,
        "proof_gates": _string_array(profile["proof_gates"], f"{path}.proof_gates", minimum=3),
        "banned_shortcuts": _string_array(
            profile["banned_shortcuts"], f"{path}.banned_shortcuts", minimum=3
        ),
    }


def _load_catalog(path: Path) -> tuple[list[str], dict[str, dict[str, Any]]]:
    root = _object(_read_json(path, "visual-world catalog"), "catalog")
    root_fields = {"schema_version", "catalog_kind", "shared_references", "worlds"}
    if set(root) != root_fields:
        raise VisualSupportError(
            "visual-world catalog root fields mismatch: "
            f"missing={sorted(root_fields - set(root))}, "
            f"extra={sorted(set(root) - root_fields)}"
        )
    if root.get("schema_version") != 1:
        raise VisualSupportError("visual-world catalog schema_version must be 1")
    if root.get("catalog_kind") != "eggy_visual_world_design_space":
        raise VisualSupportError("visual-world catalog has an unexpected catalog_kind")
    shared = _string_array(root.get("shared_references"), "catalog.shared_references", minimum=1)
    for reference in shared:
        _validate_reference(reference)
    profiles = [
        _validate_profile(item, f"catalog.worlds[{index}]")
        for index, item in enumerate(_array(root.get("worlds"), "catalog.worlds"))
    ]
    indexed: dict[str, dict[str, Any]] = {}
    for profile in profiles:
        identifier = profile["id"]
        if identifier in indexed:
            raise VisualSupportError(f"duplicate visual-world profile: {identifier}")
        indexed[identifier] = profile
    return shared, indexed


def _load_coverage(path: Path) -> dict[str, dict[str, Any]]:
    root = _object(_read_json(path, "research coverage ledger"), "coverage")
    entries = _array(root.get("visual_worlds"), "coverage.visual_worlds")
    indexed: dict[str, dict[str, Any]] = {}
    required = {
        "id",
        "label",
        "status",
        "positive_refs",
        "boundary_refs",
        "supported_claims",
        "next_gap",
        "next_entry_gate",
    }
    for index, raw_entry in enumerate(entries):
        entry_path = f"coverage.visual_worlds[{index}]"
        entry = _object(raw_entry, entry_path)
        missing = sorted(required - set(entry))
        if missing:
            raise VisualSupportError(f"{entry_path} missing fields: {missing}")
        identifier = _string(entry["id"], f"{entry_path}.id")
        if identifier in indexed:
            raise VisualSupportError(f"duplicate visual-world coverage: {identifier}")
        status = _string(entry["status"], f"{entry_path}.status")
        if status not in VALID_EMPIRICAL_STATUSES:
            raise VisualSupportError(f"{entry_path}.status is invalid: {status}")
        positive_refs = _string_array(entry["positive_refs"], f"{entry_path}.positive_refs")
        boundary_refs = _string_array(entry["boundary_refs"], f"{entry_path}.boundary_refs")
        claims = _string_array(entry["supported_claims"], f"{entry_path}.supported_claims")
        for reference in positive_refs + boundary_refs:
            _validate_reference(reference)
        if status in POSITIVE_EMPIRICAL_STATUSES and (not positive_refs or not claims):
            raise VisualSupportError(f"{entry_path} claims positive evidence without refs and claims")
        if status == "boundary_only" and (positive_refs or not boundary_refs or claims):
            raise VisualSupportError(f"{entry_path} has an invalid boundary_only evidence shape")
        if status == "missing" and (positive_refs or boundary_refs or claims):
            raise VisualSupportError(f"{entry_path} has an invalid missing evidence shape")
        indexed[identifier] = {
            "id": identifier,
            "label": _string(entry["label"], f"{entry_path}.label"),
            "status": status,
            "positive_refs": positive_refs,
            "boundary_refs": boundary_refs,
            "supported_claims": claims,
            "next_gap": _string(entry["next_gap"], f"{entry_path}.next_gap"),
            "next_entry_gate": _string(
                entry["next_entry_gate"], f"{entry_path}.next_entry_gate"
            ),
        }
    return indexed


def _assert_contract_sets(
    profiles: dict[str, dict[str, Any]], coverage: dict[str, dict[str, Any]]
) -> None:
    if set(TYPE_SHELL_STARTS) != PRIMARY_TYPES:
        raise VisualSupportError(
            "primary-type shell routing drift: "
            f"missing={sorted(PRIMARY_TYPES - set(TYPE_SHELL_STARTS))}, "
            f"extra={sorted(set(TYPE_SHELL_STARTS) - PRIMARY_TYPES)}"
        )
    if set(profiles) != EXPECTED_VISUAL_WORLDS:
        raise VisualSupportError(
            "visual-world catalog id drift: "
            f"missing={sorted(EXPECTED_VISUAL_WORLDS - set(profiles))}, "
            f"extra={sorted(set(profiles) - EXPECTED_VISUAL_WORLDS)}"
        )
    if set(coverage) != EXPECTED_VISUAL_WORLDS:
        raise VisualSupportError(
            "visual-world research coverage id drift: "
            f"missing={sorted(EXPECTED_VISUAL_WORLDS - set(coverage))}, "
            f"extra={sorted(set(coverage) - EXPECTED_VISUAL_WORLDS)}"
        )
    if set(profiles) != set(coverage):
        raise VisualSupportError(
            "visual-world design/research drift: "
            f"missing_design={sorted(set(coverage) - set(profiles))}, "
            f"missing_research={sorted(set(profiles) - set(coverage))}"
        )
    for world_id in profiles:
        if profiles[world_id]["label"] != coverage[world_id]["label"]:
            raise VisualSupportError(
                f"{world_id} label drift between design and research coverage"
            )
    for type_name, shells in TYPE_SHELL_STARTS.items():
        if len(shells) != len(set(shells)) or not shells:
            raise VisualSupportError(f"{type_name} has invalid shell routing")
        unknown = sorted(set(shells) - SHELL_TYPES)
        if unknown:
            raise VisualSupportError(f"{type_name} shell routing has unknown values: {unknown}")


def _type_pairing(primary_type: str, profile: dict[str, Any]) -> dict[str, Any]:
    if primary_type not in PRIMARY_TYPES:
        raise VisualSupportError(f"unknown primary type: {primary_type}")
    type_shells = TYPE_SHELL_STARTS[primary_type]
    world_shells = profile["shell_starts"]
    shared = [shell for shell in type_shells if shell in world_shells]
    if shared:
        recommended = shared[0]
        fit = "shared_starting_morphology"
        rationale = (
            "This shell is a starting point shared by the gameplay type and visual "
            "world. Validate it against the actual player loop and camera before use."
        )
    else:
        recommended = type_shells[0]
        fit = "gameplay_topology_overrides_theme_default"
        rationale = (
            "No default shell is shared. Keep the gameplay topology, then translate "
            "the visual world's mass, mid-structure, material, and state grammar into it."
        )
    return {
        "primary_type": primary_type,
        "type_support_command": f"python3 scripts/audit_type_support.py --type {primary_type}",
        "primary_type_shell_starts": type_shells,
        "visual_world_shell_starts": world_shells,
        "shared_shell_starts": shared,
        "recommended_start": recommended,
        "fit": fit,
        "rationale": rationale,
        "required_coupling_questions": [
            "Which authoritative loop action visibly changes this world's state?",
            "Which primitive assembly family carries the loop's interaction boundary without becoming a decorative prop?",
            "How do failure, reset, re-entry, and terminal states restore both logic and the visible world?",
        ],
        "proven_combination": False,
    }


def visual_support_card(
    world_id: str,
    profiles: dict[str, dict[str, Any]],
    coverage: dict[str, dict[str, Any]],
    shared_references: list[str],
    primary_type: str | None = None,
) -> dict[str, Any]:
    _assert_contract_sets(profiles, coverage)
    if world_id not in profiles:
        raise VisualSupportError(f"unknown visual world: {world_id}")
    profile = profiles[world_id]
    empirical = coverage[world_id]
    positive = empirical["status"] in POSITIVE_EMPIRICAL_STATUSES
    design_contract = {
        key: value
        for key, value in profile.items()
        if key not in {"id", "label", "playbook_references"}
    }
    pairing = _type_pairing(primary_type, profile) if primary_type else None
    return {
        "schema_version": 1,
        "card_kind": "eggy_visual_world_support",
        "visual_world": world_id,
        "label": profile["label"],
        "design_space": {
            "status": "complete",
            "catalog_reference": "references/visual-world-catalog.json",
            "playbook_references": profile["playbook_references"],
            "shared_references": shared_references,
            "profile": design_contract,
            "primary_type_pairing": pairing,
            "status_meaning": (
                "The skill has an exact, primitive-led design profile for this world. "
                "It is still a hypothesis until adapted to the map and reviewed in play camera."
            ),
        },
        "empirical": {
            "status": empirical["status"],
            "may_claim_positive_reference": positive,
            "positive_refs": empirical["positive_refs"],
            "boundary_refs": empirical["boundary_refs"],
            "supported_claims": empirical["supported_claims"],
            "current_limit": empirical["next_gap"],
            "future_entry_gate": empirical["next_entry_gate"],
        },
        "use_policy": (
            "Only supported_claims may be described as observed. Adapt the design profile "
            "freely, but label all other choices as design inference."
            if positive
            else "Use the design profile only as design-space guidance. Boundary evidence "
            "may reject bad assumptions; missing evidence supports no positive claim."
        ),
        "next_tools": {
            "theme_ledger": "python3 scripts/audit_theme_adaptation.py <design-plan> <assembly-plan> --template",
            "research_packet": (
                "python3 scripts/audit_research_coverage.py "
                f"--design-packet --primary <primary_type> --visual-world {world_id}"
            ),
        },
        "deployable": False,
    }


def all_visual_summary(
    profiles: dict[str, dict[str, Any]], coverage: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    _assert_contract_sets(profiles, coverage)
    summaries: list[dict[str, Any]] = []
    for world_id in sorted(profiles):
        profile = profiles[world_id]
        empirical = coverage[world_id]
        summaries.append(
            {
                "visual_world": world_id,
                "label": profile["label"],
                "design_space_status": "complete",
                "empirical_status": empirical["status"],
                "positive_reference_count": len(empirical["positive_refs"]),
                "boundary_reference_count": len(empirical["boundary_refs"]),
                "base_shape_count": len(profile["base_shape_roles"]),
                "assembly_family_count": len(profile["assembly_families"]),
                "shell_start_count": len(profile["shell_starts"]),
                "state_axis_count": len(profile["state_axes"]),
            }
        )
    return summaries


def _self_test(catalog_path: Path, coverage_path: Path) -> None:
    shared, profiles = _load_catalog(catalog_path)
    coverage = _load_coverage(coverage_path)
    _assert_contract_sets(profiles, coverage)
    summaries = all_visual_summary(profiles, coverage)
    if len(summaries) != 15:
        raise AssertionError(f"expected 15 visual worlds, got {len(summaries)}")
    if any(item["design_space_status"] != "complete" for item in summaries):
        raise AssertionError("every visual world must have complete design-space routing")

    positive = visual_support_card(
        "canyon_mountain_cave", profiles, coverage, shared, "chapter_challenge"
    )
    boundary = visual_support_card(
        "scifi_station_cyber_facility", profiles, coverage, shared
    )
    missing = visual_support_card(
        "ancient_castle_historic_street", profiles, coverage, shared
    )
    if not positive["empirical"]["may_claim_positive_reference"]:
        raise AssertionError("partial positive visual evidence was not exposed")
    if boundary["empirical"]["may_claim_positive_reference"]:
        raise AssertionError("boundary visual evidence was promoted to positive")
    if missing["empirical"]["positive_refs"] or missing["empirical"]["boundary_refs"]:
        raise AssertionError("missing visual evidence unexpectedly acquired refs")

    for world_id in profiles:
        for primary_type in PRIMARY_TYPES:
            card = visual_support_card(
                world_id, profiles, coverage, shared, primary_type
            )
            pairing = card["design_space"]["primary_type_pairing"]
            if pairing["recommended_start"] not in SHELL_TYPES:
                raise AssertionError(f"invalid pairing for {primary_type}+{world_id}")
            if pairing["proven_combination"]:
                raise AssertionError("synthetic type/world pairing was marked proven")
            if card["deployable"]:
                raise AssertionError("visual support card must never claim deployability")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Audit and print exact visual-world design profiles plus separately "
            "tracked empirical support."
        )
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--world", help="exact visual-world id")
    mode.add_argument("--all-summary", action="store_true")
    mode.add_argument("--self-test", action="store_true")
    parser.add_argument("--primary-type", choices=sorted(PRIMARY_TYPES))
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--coverage", type=Path, default=DEFAULT_COVERAGE)
    args = parser.parse_args()

    if args.primary_type and not args.world:
        parser.error("--primary-type requires --world")
    try:
        if args.self_test:
            _self_test(args.catalog, args.coverage)
            print("self-test passed")
            return
        shared, profiles = _load_catalog(args.catalog)
        coverage = _load_coverage(args.coverage)
        if args.all_summary:
            summaries = all_visual_summary(profiles, coverage)
            status_counts: dict[str, int] = {}
            for item in summaries:
                status = item["empirical_status"]
                status_counts[status] = status_counts.get(status, 0) + 1
            payload: Any = {
                "schema_version": 1,
                "report_kind": "eggy_all_visual_world_support",
                "design_space_complete": len(summaries),
                "empirical_status_counts": dict(sorted(status_counts.items())),
                "visual_worlds": summaries,
            }
        else:
            payload = visual_support_card(
                args.world, profiles, coverage, shared, args.primary_type
            )
    except (OSError, VisualSupportError) as exc:
        parser.error(str(exc))
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

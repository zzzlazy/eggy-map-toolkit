#!/usr/bin/env python3
"""Validate and report the empirical coverage of the Eggy map case library.

The design skill can synthesize every supported primary type without pretending
that a synthetic template is an observed exemplar.  This auditor keeps that
boundary explicit: a partial positive case may support only its named claims,
while boundary-only and missing entries remain research gaps.
"""

from __future__ import annotations

import argparse
import ast
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import sys
from typing import Any


STATUSES = {
    "verified_positive",
    "partial_positive",
    "boundary_only",
    "missing",
}
POSITIVE_STATUSES = {"verified_positive", "partial_positive"}
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


class CoverageError(ValueError):
    """Raised when the research coverage ledger is structurally misleading."""


def _object(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CoverageError(f"{path} must be an object")
    return value


def _array(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise CoverageError(f"{path} must be an array")
    return value


def _string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CoverageError(f"{path} must be a non-empty string")
    return value.strip()


def _string_array(value: Any, path: str) -> list[str]:
    items = [_string(item, f"{path}[{index}]") for index, item in enumerate(_array(value, path))]
    if len(items) != len(set(items)):
        raise CoverageError(f"{path} contains duplicate values")
    return items


def _literal_assignment(path: Path, name: str) -> set[str]:
    """Read a top-level literal set assignment without importing the script."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except OSError as exc:
        raise CoverageError(f"cannot read designer contract {path}: {exc}") from exc
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            continue
        try:
            value = ast.literal_eval(node.value)
        except (ValueError, TypeError) as exc:
            raise CoverageError(f"designer contract {name} is not a literal collection") from exc
        if not isinstance(value, (set, list, tuple)) or not all(isinstance(item, str) for item in value):
            raise CoverageError(f"designer contract {name} must contain strings")
        return set(value)
    raise CoverageError(f"designer contract has no top-level {name} assignment")


def _designer_contract(skills_root: Path) -> tuple[set[str], set[str], set[str]]:
    path = skills_root / "eggy-map-designer" / "scripts" / "audit_design_plan.py"
    return (
        _literal_assignment(path, "PRIMARY_TYPES"),
        _literal_assignment(path, "MODIFIERS"),
        _literal_assignment(path, "HYBRID_MODES"),
    )


def _resolve_ref(reference: str, skills_root: Path, path: str) -> Path:
    prefix = "skill:"
    if not reference.startswith(prefix):
        raise CoverageError(f"{path} must use skill:<skill-name>/<relative-path>")
    relative = reference[len(prefix) :]
    if not relative or Path(relative).is_absolute():
        raise CoverageError(f"{path} has an invalid skill reference")
    root = skills_root.resolve()
    resolved = (root / relative).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise CoverageError(f"{path} escapes the skills root") from exc
    if not resolved.is_file():
        raise CoverageError(f"{path} does not exist: {resolved}")
    if resolved.suffix.lower() != ".md":
        raise CoverageError(f"{path} must point to a distilled Markdown artifact")
    return resolved


def _validate_entry(
    raw: Any,
    path: str,
    skills_root: Path,
) -> dict[str, Any]:
    entry = _object(raw, path)
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
    missing = sorted(required - set(entry))
    if missing:
        raise CoverageError(f"{path} missing fields: {', '.join(missing)}")
    identifier = _string(entry["id"], f"{path}.id")
    label = _string(entry["label"], f"{path}.label")
    status = _string(entry["status"], f"{path}.status")
    if status not in STATUSES:
        raise CoverageError(f"{path}.status must be one of {', '.join(sorted(STATUSES))}")
    positive_refs = _string_array(entry["positive_refs"], f"{path}.positive_refs")
    boundary_refs = _string_array(entry["boundary_refs"], f"{path}.boundary_refs")
    overlap = sorted(set(positive_refs) & set(boundary_refs))
    if overlap:
        raise CoverageError(f"{path} uses the same artifact as positive and boundary evidence: {overlap}")
    for field, references in (("positive_refs", positive_refs), ("boundary_refs", boundary_refs)):
        for index, reference in enumerate(references):
            _resolve_ref(reference, skills_root, f"{path}.{field}[{index}]")
    claims = _string_array(entry["supported_claims"], f"{path}.supported_claims")
    if status in POSITIVE_STATUSES:
        if not positive_refs:
            raise CoverageError(f"{path} claims {status} without a positive reference")
        if not claims:
            raise CoverageError(f"{path} claims {status} without a bounded supported claim")
    elif positive_refs:
        raise CoverageError(f"{path} status {status} cannot contain positive_refs")
    if status == "boundary_only" and not boundary_refs:
        raise CoverageError(f"{path} boundary_only status requires boundary_refs")
    if status == "missing" and boundary_refs:
        raise CoverageError(f"{path} with boundary evidence must use boundary_only, not missing")
    if status in {"boundary_only", "missing"} and claims:
        raise CoverageError(f"{path} status {status} cannot claim positive support")
    return {
        "id": identifier,
        "label": label,
        "status": status,
        "positive_refs": positive_refs,
        "boundary_refs": boundary_refs,
        "supported_claims": claims,
        "next_gap": _string(entry["next_gap"], f"{path}.next_gap"),
        "next_entry_gate": _string(entry["next_entry_gate"], f"{path}.next_entry_gate"),
    }


def _validate_section(
    raw: Any,
    path: str,
    expected_ids: set[str],
    skills_root: Path,
) -> list[dict[str, Any]]:
    entries = [
        _validate_entry(item, f"{path}[{index}]", skills_root)
        for index, item in enumerate(_array(raw, path))
    ]
    identifiers = [entry["id"] for entry in entries]
    if len(identifiers) != len(set(identifiers)):
        duplicates = sorted(identifier for identifier, count in Counter(identifiers).items() if count > 1)
        raise CoverageError(f"{path} has duplicate ids: {duplicates}")
    actual = set(identifiers)
    if actual != expected_ids:
        raise CoverageError(
            f"{path} coverage mismatch: missing={sorted(expected_ids - actual)}, "
            f"extra={sorted(actual - expected_ids)}"
        )
    return entries


def _validate_hybrid_pairs(
    raw: Any,
    path: str,
    primary_types: set[str],
    hybrid_modes: set[str],
    skills_root: Path,
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    seen_pairs: set[tuple[str, str, str]] = set()
    for index, item in enumerate(_array(raw, path)):
        item_path = f"{path}[{index}]"
        raw_entry = _object(item, item_path)
        entry = _validate_entry(raw_entry, item_path, skills_root)
        primary = _string(raw_entry.get("primary_type"), f"{item_path}.primary_type")
        secondary = _string(
            raw_entry.get("secondary_type"), f"{item_path}.secondary_type"
        )
        mode = _string(
            raw_entry.get("combination_mode"), f"{item_path}.combination_mode"
        )
        if primary not in primary_types:
            raise CoverageError(f"{item_path}.primary_type is unknown: {primary}")
        if secondary not in primary_types:
            raise CoverageError(f"{item_path}.secondary_type is unknown: {secondary}")
        if secondary == primary:
            raise CoverageError(f"{item_path} cannot pair a type with itself")
        if mode not in hybrid_modes:
            raise CoverageError(
                f"{item_path}.combination_mode must be one of "
                f"{', '.join(sorted(hybrid_modes))}"
            )
        expected_id = f"{primary}+{secondary}@{mode}"
        if entry["id"] != expected_id:
            raise CoverageError(
                f"{item_path}.id must be {expected_id!r} for its ordered pair"
            )
        pair = (primary, secondary, mode)
        if pair in seen_pairs:
            raise CoverageError(f"{path} has duplicate ordered pair: {expected_id}")
        seen_pairs.add(pair)
        entries.append(
            {
                **entry,
                "primary_type": primary,
                "secondary_type": secondary,
                "combination_mode": mode,
            }
        )
    return entries


def validate_coverage(root: Any, skills_root: Path) -> dict[str, Any]:
    ledger = _object(root, "root")
    if ledger.get("schema_version") != 1:
        raise CoverageError("schema_version must be 1")
    primary_types, modifiers, hybrid_modes = _designer_contract(skills_root)
    primary = _validate_section(
        ledger.get("primary_types"), "primary_types", primary_types, skills_root
    )
    modifier_entries = _validate_section(
        ledger.get("modifiers"), "modifiers", modifiers, skills_root
    )
    visual = _validate_section(
        ledger.get("visual_worlds"),
        "visual_worlds",
        EXPECTED_VISUAL_WORLDS,
        skills_root,
    )
    hybrid_pairs = _validate_hybrid_pairs(
        ledger.get("hybrid_pairs"),
        "hybrid_pairs",
        primary_types,
        hybrid_modes,
        skills_root,
    )
    return {
        "schema_version": 1,
        "primary_types": primary,
        "modifiers": modifier_entries,
        "visual_worlds": visual,
        "hybrid_pairs": hybrid_pairs,
        "_hybrid_modes": sorted(hybrid_modes),
    }


def _summary(entries: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(entry["status"] for entry in entries)
    return {status: counts.get(status, 0) for status in sorted(STATUSES)}


def _find_entry(validated: dict[str, Any], identifier: str) -> tuple[str, dict[str, Any]]:
    for section in ("primary_types", "modifiers", "visual_worlds", "hybrid_pairs"):
        for entry in validated[section]:
            if entry["id"] == identifier:
                return section, entry
    raise CoverageError(f"unknown coverage id: {identifier}")


def _entry_lookup(validated: dict[str, Any]) -> dict[str, dict[str, dict[str, Any]]]:
    return {
        section: {entry["id"]: entry for entry in validated[section]}
        for section in ("primary_types", "modifiers", "visual_worlds", "hybrid_pairs")
    }


def _design_reference_packet(
    validated: dict[str, Any],
    *,
    primary: str,
    secondary: str | None,
    hybrid_mode: str | None,
    modifiers: list[str],
    visual_worlds: list[str],
) -> dict[str, Any]:
    """Build a conservative, machine-readable handoff for one design brief.

    An axis is positive only when every selected member for that axis has
    positive evidence.  This prevents one supported modifier or visual world
    from hiding a boundary-only companion selection.
    """

    if len(modifiers) != len(set(modifiers)):
        raise CoverageError("design packet contains duplicate modifiers")
    if len(visual_worlds) != len(set(visual_worlds)):
        raise CoverageError("design packet contains duplicate visual worlds")
    if secondary == primary:
        raise CoverageError("design packet secondary type must differ from primary type")
    if secondary is None and hybrid_mode is not None:
        raise CoverageError("design packet hybrid mode requires a secondary type")
    if secondary is not None and hybrid_mode is None:
        raise CoverageError("design packet secondary type requires a hybrid mode")
    if hybrid_mode is not None and hybrid_mode not in set(validated["_hybrid_modes"]):
        raise CoverageError(
            "design packet hybrid mode must be one of "
            + ", ".join(validated["_hybrid_modes"])
        )
    if not visual_worlds:
        raise CoverageError("design packet requires at least one visual world")

    lookup = _entry_lookup(validated)

    def select(section: str, identifier: str, axes: list[str]) -> dict[str, Any]:
        try:
            entry = lookup[section][identifier]
        except KeyError as exc:
            raise CoverageError(
                f"unknown {section} id in design packet: {identifier}"
            ) from exc
        return {
            "selection_key": f"{section}:{identifier}",
            "section": section,
            "id": identifier,
            "label": entry["label"],
            "axes": axes,
            "status": entry["status"],
            "positive_refs": entry["positive_refs"],
            "boundary_refs": entry["boundary_refs"],
            "supported_claims": entry["supported_claims"],
            "limits": entry["next_gap"],
            "next_entry_gate": entry["next_entry_gate"],
        }

    selections = [select("primary_types", primary, ["primary_loop"])]
    if secondary is not None:
        selections.append(select("primary_types", secondary, ["secondary_loop"]))
        pair_id = f"{primary}+{secondary}@{hybrid_mode}"
        if pair_id in lookup["hybrid_pairs"]:
            selections.append(select("hybrid_pairs", pair_id, ["hybrid_relation"]))
        else:
            adjacent_pairs = [
                entry
                for entry in validated["hybrid_pairs"]
                if entry["primary_type"] == primary
                and entry["secondary_type"] == secondary
            ]
            selections.append(
                {
                    "selection_key": f"hybrid_pairs:{pair_id}",
                    "section": "hybrid_pairs",
                    "id": pair_id,
                    "label": f"{primary} 主 × {secondary} 次 / {hybrid_mode}",
                    "axes": ["hybrid_relation"],
                    "status": "missing",
                    "positive_refs": [],
                    "boundary_refs": [],
                    "supported_claims": [],
                    "limits": (
                        "没有已审计案例同时证明这两个循环的主次关系、状态交接、"
                        "失败优先级和清理。"
                    ),
                    "next_entry_gate": (
                        "同一张身份已核对的地图中，主终局保持唯一，次循环具有可见"
                        "入口/出口，并至少观察一次交接、失败恢复和清理。"
                    ),
                    "adjacent_mode_refs": sorted(
                        {
                            reference
                            for entry in adjacent_pairs
                            for reference in entry["positive_refs"]
                        }
                    ),
                    "registered_adjacent_modes": sorted(
                        entry["combination_mode"] for entry in adjacent_pairs
                    ),
                }
            )
    selections.extend(
        select("modifiers", identifier, ["modifier"]) for identifier in modifiers
    )
    selections.extend(
        select(
            "visual_worlds",
            identifier,
            ["world_grammar", "spatial_scale"],
        )
        for identifier in visual_worlds
    )

    required_axes = ["primary_loop", "world_grammar", "spatial_scale"]
    if secondary is not None:
        required_axes.extend(["secondary_loop", "hybrid_relation"])
    if modifiers:
        required_axes.append("modifier")
    required_axes = sorted(required_axes)

    axis_coverage: dict[str, Any] = {}
    gaps: list[dict[str, Any]] = []
    for axis in required_axes:
        members = [selection for selection in selections if axis in selection["axes"]]
        if not members:
            raise CoverageError(f"design packet failed to bind required axis {axis}")
        statuses = {member["status"] for member in members}
        complete_positive = all(
            member["status"] in POSITIVE_STATUSES for member in members
        )
        positive_refs = sorted(
            {
                reference
                for member in members
                for reference in member["positive_refs"]
            }
        )
        boundary_refs = sorted(
            {
                reference
                for member in members
                for reference in member["boundary_refs"]
            }
        )
        claims = list(
            dict.fromkeys(
                claim
                for member in members
                for claim in member["supported_claims"]
            )
        )
        incomplete = [
            member
            for member in members
            if member["status"] not in POSITIVE_STATUSES
        ]
        axis_entry: dict[str, Any] = {
            "complete_positive": complete_positive,
            "selection_keys": [member["selection_key"] for member in members],
            "statuses": sorted(statuses),
            "positive_refs": positive_refs,
            "boundary_refs": boundary_refs,
            "supported_claims": claims,
        }
        if incomplete:
            axis_entry["blocking_selections"] = [
                {
                    "selection_key": member["selection_key"],
                    "status": member["status"],
                    "next_gap": member["limits"],
                    "next_entry_gate": member["next_entry_gate"],
                }
                for member in incomplete
            ]
            gaps.append(
                {
                    "axis": axis,
                    "reason": (
                        "One or more selected coverage entries have only boundary "
                        "evidence or no audited case."
                    ),
                    "blocking_selections": [
                        member["selection_key"] for member in incomplete
                    ],
                }
            )
        axis_coverage[axis] = axis_entry

    return {
        "schema_version": 1,
        "packet_kind": "eggy_design_reference_packet",
        "primary_type": primary,
        "secondary_type": secondary,
        "hybrid_mode": hybrid_mode,
        "modifiers": modifiers,
        "visual_worlds": visual_worlds,
        "required_axes": required_axes,
        "all_required_axes_positive": not gaps,
        "selections": selections,
        "axis_coverage": axis_coverage,
        "reference_gaps": gaps,
        "use_contract": (
            "Only selected positive_refs and their supported_claims may justify a "
            "positive design decision. Separate primary and secondary cases do not "
            "prove their hybrid relation; that requires a positive hybrid_relation "
            "selection. boundary_refs define exclusions; missing or boundary selections "
            "remain explicit reference gaps."
        ),
    }


def _report(validated: dict[str, Any]) -> dict[str, Any]:
    gaps: list[dict[str, str]] = []
    for section in ("primary_types", "modifiers", "visual_worlds", "hybrid_pairs"):
        for entry in validated[section]:
            if entry["status"] in {"boundary_only", "missing"}:
                gaps.append(
                    {
                        "section": section,
                        "id": entry["id"],
                        "status": entry["status"],
                        "next_gap": entry["next_gap"],
                        "next_entry_gate": entry["next_entry_gate"],
                    }
                )
    return {
        "valid": True,
        "summary": {
            section: _summary(validated[section])
            for section in ("primary_types", "modifiers", "visual_worlds", "hybrid_pairs")
        },
        "positive_primary_type_count": sum(
            entry["status"] in POSITIVE_STATUSES for entry in validated["primary_types"]
        ),
        "primary_type_count": len(validated["primary_types"]),
        "all_primary_types_have_positive_evidence": all(
            entry["status"] in POSITIVE_STATUSES
            for entry in validated["primary_types"]
        ),
        "open_positive_gaps": gaps,
    }


def _self_test(validated: dict[str, Any], skills_root: Path) -> None:
    missing = deepcopy(validated)
    missing["primary_types"] = missing["primary_types"][:-1]
    try:
        validate_coverage(missing, skills_root)
    except CoverageError as exc:
        if "coverage mismatch" not in str(exc):
            raise AssertionError(f"unexpected missing-type error: {exc}") from exc
    else:
        raise AssertionError("missing primary type was accepted")

    promoted = deepcopy(validated)
    target = next(item for item in promoted["primary_types"] if item["status"] == "missing")
    target["status"] = "verified_positive"
    try:
        validate_coverage(promoted, skills_root)
    except CoverageError as exc:
        if "without a positive reference" not in str(exc):
            raise AssertionError(f"unexpected fabricated-evidence error: {exc}") from exc
    else:
        raise AssertionError("fabricated positive coverage was accepted")

    boundary = deepcopy(validated)
    target = next(item for item in boundary["primary_types"] if item["status"] == "boundary_only")
    target["positive_refs"] = target["boundary_refs"][:1]
    try:
        validate_coverage(boundary, skills_root)
    except CoverageError as exc:
        if "same artifact as positive and boundary" not in str(exc):
            raise AssertionError(f"unexpected boundary-overlap error: {exc}") from exc
    else:
        raise AssertionError("boundary evidence was accepted as positive evidence")

    malformed_pair = deepcopy(validated)
    malformed_pair["hybrid_pairs"][0]["id"] = "wrong+pair"
    try:
        validate_coverage(malformed_pair, skills_root)
    except CoverageError as exc:
        if "ordered pair" not in str(exc):
            raise AssertionError(f"unexpected hybrid pair identity error: {exc}") from exc
    else:
        raise AssertionError("a hybrid evidence entry with the wrong pair id was accepted")

    positive_packet = _design_reference_packet(
        validated,
        primary="short_race",
        secondary=None,
        hybrid_mode=None,
        modifiers=["rising_pressure"],
        visual_worlds=["cellar_food_facility"],
    )
    if not positive_packet["all_required_axes_positive"]:
        raise AssertionError("positive design packet was reported as incomplete")

    missing_packet = _design_reference_packet(
        validated,
        primary="social_deduction",
        secondary=None,
        hybrid_mode=None,
        modifiers=[],
        visual_worlds=["ancient_castle_historic_street"],
    )
    if missing_packet["all_required_axes_positive"]:
        raise AssertionError("missing design evidence was reported as positive")
    if {gap["axis"] for gap in missing_packet["reference_gaps"]} != {
        "primary_loop",
        "world_grammar",
        "spatial_scale",
    }:
        raise AssertionError("missing design packet did not preserve every gap axis")

    mixed_modifier_packet = _design_reference_packet(
        validated,
        primary="short_race",
        secondary=None,
        hybrid_mode=None,
        modifiers=["rising_pressure", "asymmetric_roles"],
        visual_worlds=["cellar_food_facility"],
    )
    modifier_axis = mixed_modifier_packet["axis_coverage"]["modifier"]
    if modifier_axis["complete_positive"]:
        raise AssertionError("one positive modifier hid a boundary-only modifier")
    if modifier_axis["blocking_selections"] != [
        {
            "selection_key": "modifiers:asymmetric_roles",
            "status": "boundary_only",
            "next_gap": next(
                entry["next_gap"]
                for entry in validated["modifiers"]
                if entry["id"] == "asymmetric_roles"
            ),
            "next_entry_gate": next(
                entry["next_entry_gate"]
                for entry in validated["modifiers"]
                if entry["id"] == "asymmetric_roles"
            ),
        }
    ]:
        raise AssertionError("mixed modifier packet lost the exact unsupported member")

    positive_hybrid_packet = _design_reference_packet(
        validated,
        primary="management_simulation",
        secondary="survival",
        hybrid_mode="overlay",
        modifiers=[],
        visual_worlds=["island_survival_world"],
    )
    if not positive_hybrid_packet["all_required_axes_positive"]:
        raise AssertionError("audited management-survival relation was reported missing")
    if not positive_hybrid_packet["axis_coverage"]["hybrid_relation"][
        "complete_positive"
    ]:
        raise AssertionError("positive hybrid relation did not bind its own axis")

    unobserved_hybrid_packet = _design_reference_packet(
        validated,
        primary="short_race",
        secondary="social_showcase",
        hybrid_mode="optional_branch",
        modifiers=[],
        visual_worlds=["winter_garden_showcase"],
    )
    if unobserved_hybrid_packet["all_required_axes_positive"]:
        raise AssertionError("separate positive type cases fabricated hybrid evidence")
    hybrid_gaps = [
        gap
        for gap in unobserved_hybrid_packet["reference_gaps"]
        if gap["axis"] == "hybrid_relation"
    ]
    if hybrid_gaps != [
        {
            "axis": "hybrid_relation",
            "reason": (
                "One or more selected coverage entries have only boundary evidence "
                "or no audited case."
            ),
            "blocking_selections": [
                "hybrid_pairs:short_race+social_showcase@optional_branch"
            ],
        }
    ]:
        raise AssertionError("unobserved hybrid relation did not preserve its exact gap")


def _default_paths() -> tuple[Path, Path]:
    skill_root = Path(__file__).resolve().parents[1]
    return skill_root / "references" / "research-coverage.json", skill_root.parent


def main(argv: list[str] | None = None) -> int:
    default_ledger, default_skills_root = _default_paths()
    parser = argparse.ArgumentParser(
        description="Audit empirical exemplar coverage without treating design templates as evidence."
    )
    parser.add_argument("ledger", nargs="?", type=Path, default=default_ledger)
    parser.add_argument("--skills-root", type=Path, default=default_skills_root)
    parser.add_argument(
        "--id",
        help="Report one primary type, modifier, visual-world, or ordered hybrid-pair id",
    )
    parser.add_argument("--json", action="store_true", help="Emit the report as JSON")
    parser.add_argument(
        "--design-packet",
        action="store_true",
        help="Emit a conservative reference packet for one design brief",
    )
    parser.add_argument("--primary", help="Primary type for --design-packet")
    parser.add_argument("--secondary", help="Optional secondary type for --design-packet")
    parser.add_argument(
        "--hybrid-mode",
        help="Combination mode for --design-packet; required with --secondary",
    )
    parser.add_argument(
        "--modifier",
        action="append",
        default=[],
        help="Selected modifier; repeat for multiple modifiers",
    )
    parser.add_argument(
        "--visual-world",
        action="append",
        default=[],
        help="Selected visual world; repeat for multiple worlds",
    )
    parser.add_argument(
        "--require-positive-primary-types",
        action="store_true",
        help="Return a non-zero status until every primary type has positive case evidence",
    )
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)

    packet_args_used = bool(
        args.primary
        or args.secondary
        or args.hybrid_mode
        or args.modifier
        or args.visual_world
    )
    if args.design_packet:
        if args.id:
            parser.error("--design-packet cannot be combined with --id")
        if not args.primary:
            parser.error("--design-packet requires --primary")
        if args.secondary and not args.hybrid_mode:
            parser.error("--secondary requires --hybrid-mode")
        if args.hybrid_mode and not args.secondary:
            parser.error("--hybrid-mode requires --secondary")
        if args.require_positive_primary_types:
            parser.error(
                "--design-packet cannot be combined with --require-positive-primary-types"
            )
    elif packet_args_used:
        parser.error(
            "--primary, --secondary, --hybrid-mode, --modifier and --visual-world "
            "require --design-packet"
        )

    try:
        raw = json.loads(args.ledger.read_text(encoding="utf-8"))
        validated = validate_coverage(raw, args.skills_root)
        if args.self_test:
            _self_test(validated, args.skills_root)
        if args.design_packet:
            output = _design_reference_packet(
                validated,
                primary=args.primary,
                secondary=args.secondary,
                hybrid_mode=args.hybrid_mode,
                modifiers=args.modifier,
                visual_worlds=args.visual_world,
            )
        elif args.id:
            section, entry = _find_entry(validated, args.id)
            output: dict[str, Any] = {"valid": True, "section": section, "entry": entry}
        else:
            output = _report(validated)
    except (OSError, json.JSONDecodeError, CoverageError, AssertionError) as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 2

    if args.design_packet:
        print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
    elif args.json:
        print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
    elif args.id:
        entry = output["entry"]
        print(f"OK {output['section']}:{entry['id']} [{entry['status']}]")
        print(f"supports: {', '.join(entry['supported_claims']) or 'none'}")
        print(f"next gap: {entry['next_gap']}")
        print(f"entry gate: {entry['next_entry_gate']}")
    else:
        print("OK research coverage ledger")
        for section, counts in output["summary"].items():
            values = ", ".join(f"{status}={count}" for status, count in counts.items())
            print(f"{section}: {values}")
        print(
            "positive primary types: "
            f"{output['positive_primary_type_count']}/{output['primary_type_count']}"
        )
        print(f"open boundary/missing targets: {len(output['open_positive_gaps'])}")
    if (
        args.require_positive_primary_types
        and not args.id
        and not output["all_primary_types_have_positive_evidence"]
    ):
        print(
            "INCOMPLETE: one or more primary types still have only boundary evidence or no case",
            file=sys.stderr,
        )
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

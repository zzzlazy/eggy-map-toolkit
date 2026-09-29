#!/usr/bin/env python3
"""Audit and route the design references for every Eggy map primary type.

This script deliberately keeps two claims separate:

* ``design_space`` means the designer contains a playbook, an assembly kit,
  type-specific ledgers, failure scenarios, and a substantial primitive-led
  seed.  It does not mean that the seed is deployable.
* ``empirical`` comes only from eggy-map-designer's coverage ledger.  A
  synthetic playbook can never upgrade a missing or boundary-only case.

The split lets another Codex instance answer "what can I design from?" and
"what has actually been observed?" without hunting through several files or
silently conflating the two.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any

from audit_design_plan import (
    PRIMARY_TYPES,
    TYPE_FIELDS,
    TYPE_METRICS,
    TYPE_SCENARIOS,
)
from generate_type_assembly_seed import TYPE_BLUEPRINTS, _seed_summary


DESIGNER_ROOT = Path(__file__).resolve().parents[1]
SKILLS_ROOT = DESIGNER_ROOT.parent
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

# These are routing anchors, not a second set of gameplay rules.  The actual
# contracts stay in the referenced playbooks and audit modules.
TYPE_PLAYBOOK_REFERENCES = {
    "short_race": "references/type-playbooks.md#短竞速",
    "chapter_challenge": "references/type-playbooks.md#章节挑战",
    "mechanism_puzzle": "references/type-playbooks.md#机制解谜",
    "cooperative": "references/type-playbooks.md#双人多人合作",
    "narrative_exploration": "references/type-playbooks.md#叙事探索",
    "survival": "references/type-playbooks.md#生存淘汰",
    "score_contest": "references/type-playbooks.md#积分争夺",
    "social_showcase": "references/type-playbooks.md#休闲社交展示",
    "management_simulation": "references/type-playbooks.md#经营模拟建造",
    "rhythm_performance": (
        "references/specialized-type-playbooks.md"
        "#纯音游--节奏演出-rhythm_performance"
    ),
    "combat_boss": (
        "references/specialized-type-playbooks.md"
        "#boss--pve-战斗-combat_boss"
    ),
    "defense_strategy": (
        "references/specialized-type-playbooks.md"
        "#防守--塔防-defense_strategy"
    ),
    "stealth_infiltration": (
        "references/specialized-type-playbooks.md"
        "#潜行--渗透-stealth_infiltration"
    ),
    "turn_based_strategy": (
        "references/specialized-type-playbooks.md"
        "#回合制棋盘--卡牌-turn_based_strategy"
    ),
    "sports_match": (
        "references/specialized-type-playbooks.md#体育对局-sports_match"
    ),
    "sandbox_creation": (
        "references/specialized-type-playbooks.md#创造沙盒-sandbox_creation"
    ),
    "social_deduction": (
        "references/specialized-type-playbooks.md"
        "#阵营推理--社交推理-social_deduction"
    ),
}

SHARED_AUDIT_REFERENCES = [
    "references/design-plan-audit.md",
    "references/logic-and-reset-patterns.md",
    "references/assembly-and-density.md",
    "references/component-binding-audit.md",
    "references/theme-adaptation-audit.md",
    "references/performance-and-budget.md",
]


class SupportError(ValueError):
    pass


def _github_heading_slug(text: str) -> str:
    """Return the subset of GitHub-style heading slugs used by these files."""
    text = re.sub(r"`([^`]*)`", r"\1", text.strip().lower())
    text = re.sub(r"[^\w\-\s]", "", text, flags=re.UNICODE)
    # Preserve repeated spaces as repeated hyphens; current generated links use
    # that behavior around punctuation such as " / ".
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
            raise SupportError(f"malformed skill reference: {reference}")
        path = SKILLS_ROOT / skill_name / relative
    else:
        path = DESIGNER_ROOT / raw_path
    return path.resolve(), fragment if separator else None


def _validate_reference(reference: str) -> None:
    path, fragment = _resolve_reference(reference)
    if not path.is_file():
        raise SupportError(f"reference target does not exist: {reference} -> {path}")
    if fragment and fragment not in _heading_slugs(path):
        raise SupportError(
            f"reference fragment does not match a heading: {reference}"
        )


def _load_coverage(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        raise SupportError(f"research coverage ledger does not exist: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SupportError(f"cannot read research coverage ledger: {exc}") from exc
    entries = payload.get("primary_types")
    if not isinstance(entries, list):
        raise SupportError("research coverage ledger has no primary_types list")
    indexed: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
            raise SupportError("research coverage contains an invalid primary type entry")
        type_name = entry["id"]
        if type_name in indexed:
            raise SupportError(f"duplicate research coverage entry: {type_name}")
        status = entry.get("status")
        if status not in VALID_EMPIRICAL_STATUSES:
            raise SupportError(
                f"{type_name} has invalid empirical status: {status!r}"
            )
        positive_refs = entry.get("positive_refs")
        boundary_refs = entry.get("boundary_refs")
        if not isinstance(positive_refs, list) or not isinstance(boundary_refs, list):
            raise SupportError(f"{type_name} evidence refs must be lists")
        if status in POSITIVE_EMPIRICAL_STATUSES and not positive_refs:
            raise SupportError(f"{type_name} claims positive evidence without a case")
        if status == "boundary_only" and (positive_refs or not boundary_refs):
            raise SupportError(
                f"{type_name} boundary_only must have boundary refs and no positive refs"
            )
        if status == "missing" and (positive_refs or boundary_refs):
            raise SupportError(f"{type_name} missing status must not carry case refs")
        for reference in positive_refs + boundary_refs:
            if not isinstance(reference, str):
                raise SupportError(f"{type_name} has a non-string evidence ref")
            _validate_reference(reference)
        indexed[type_name] = entry
    return indexed


def _assert_type_sets(coverage: dict[str, dict[str, Any]]) -> None:
    sources = {
        "assembly blueprints": set(TYPE_BLUEPRINTS),
        "playbook routes": set(TYPE_PLAYBOOK_REFERENCES),
        "type fields": set(TYPE_FIELDS),
        "type metrics": set(TYPE_METRICS),
        "type failure scenarios": set(TYPE_SCENARIOS),
        "research coverage": set(coverage),
    }
    for label, values in sources.items():
        if values != PRIMARY_TYPES:
            raise SupportError(
                f"{label} drift: missing={sorted(PRIMARY_TYPES - values)}, "
                f"extra={sorted(values - PRIMARY_TYPES)}"
            )


def type_support_card(
    type_name: str,
    coverage: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if type_name not in PRIMARY_TYPES:
        raise SupportError(f"unknown primary type: {type_name}")
    _assert_type_sets(coverage)

    blueprint = TYPE_BLUEPRINTS[type_name]
    playbook_reference = TYPE_PLAYBOOK_REFERENCES[type_name]
    assembly_reference = blueprint["assembly_reference"]
    for reference in [
        playbook_reference,
        assembly_reference,
        *SHARED_AUDIT_REFERENCES,
    ]:
        _validate_reference(reference)

    empirical = coverage[type_name]
    seed = _seed_summary(type_name)
    positive = empirical["status"] in POSITIVE_EMPIRICAL_STATUSES
    evidence_policy = (
        "Only the listed supported_claims may be treated as observed support; "
        "all other design decisions remain hypotheses for this map."
        if positive
        else "Use the playbook as design-space guidance only. Boundary refs may "
        "exclude false classifications but cannot support a positive design claim."
    )

    return {
        "schema_version": 1,
        "card_kind": "eggy_primary_type_support",
        "primary_type": type_name,
        "label": empirical.get("label", type_name),
        "design_space": {
            "status": "complete",
            "playbook_reference": playbook_reference,
            "assembly_reference": assembly_reference,
            "shared_audit_references": SHARED_AUDIT_REFERENCES,
            "assembly_intent": blueprint["intent"],
            "required_type_fields": sorted(TYPE_FIELDS[type_name]),
            "required_metrics": sorted(TYPE_METRICS[type_name]),
            "required_failure_scenarios": sorted(TYPE_SCENARIOS[type_name]),
            "seed_command": (
                "python3 scripts/generate_type_assembly_seed.py "
                f"--type {type_name}"
            ),
            "seed_status": "design_space_only_not_deployable",
            "seed_summary": seed,
        },
        "empirical": {
            "status": empirical["status"],
            "may_claim_positive_reference": positive,
            "positive_refs": empirical["positive_refs"],
            "boundary_refs": empirical["boundary_refs"],
            "supported_claims": empirical.get("supported_claims", []),
            "current_limit": empirical.get("next_gap", ""),
            "future_entry_gate": empirical.get("next_entry_gate", ""),
        },
        "use_policy": evidence_policy,
        "deployable": False,
    }


def all_type_summary(coverage: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    _assert_type_sets(coverage)
    result: list[dict[str, Any]] = []
    for type_name in sorted(PRIMARY_TYPES):
        card = type_support_card(type_name, coverage)
        seed = card["design_space"]["seed_summary"]
        empirical = card["empirical"]
        result.append(
            {
                "primary_type": type_name,
                "label": card["label"],
                "design_space_status": card["design_space"]["status"],
                "empirical_status": empirical["status"],
                "positive_reference_count": len(empirical["positive_refs"]),
                "boundary_reference_count": len(empirical["boundary_refs"]),
                "expanded_total": seed["expanded_total"],
                "family_count": seed["family_count"],
                "zone_count": seed["zone_count"],
                "primitive_visible_share": seed["primitive_visible_share"],
            }
        )
    return result


def _self_test(coverage_path: Path) -> None:
    coverage = _load_coverage(coverage_path)
    _assert_type_sets(coverage)
    summaries = all_type_summary(coverage)
    if len(summaries) != 17:
        raise AssertionError(f"expected 17 primary types, got {len(summaries)}")
    if any(item["design_space_status"] != "complete" for item in summaries):
        raise AssertionError("every primary type must have complete design-space routing")
    if not all(item["expanded_total"] >= 1000 for item in summaries):
        raise AssertionError("every primary type needs a substantial assembly seed")

    positive = type_support_card("short_race", coverage)
    boundary = type_support_card("rhythm_performance", coverage)
    missing = type_support_card("social_deduction", coverage)
    if not positive["empirical"]["may_claim_positive_reference"]:
        raise AssertionError("partial positive evidence was not exposed as positive")
    if boundary["empirical"]["may_claim_positive_reference"]:
        raise AssertionError("boundary evidence was promoted to positive")
    if missing["empirical"]["positive_refs"] or missing["empirical"]["boundary_refs"]:
        raise AssertionError("missing evidence unexpectedly acquired references")
    if any(card["deployable"] for card in (positive, boundary, missing)):
        raise AssertionError("a design support card must never claim deployability")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Audit and print design-space plus empirical support for Eggy map "
            "primary types."
        )
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--type", choices=sorted(PRIMARY_TYPES))
    mode.add_argument("--all-summary", action="store_true")
    mode.add_argument("--self-test", action="store_true")
    parser.add_argument(
        "--coverage",
        type=Path,
        default=DEFAULT_COVERAGE,
        help="path to eggy-map-designer's research-coverage.json",
    )
    args = parser.parse_args()

    try:
        if args.self_test:
            _self_test(args.coverage)
            print("self-test passed")
            return
        coverage = _load_coverage(args.coverage)
        payload: Any
        if args.all_summary:
            summaries = all_type_summary(coverage)
            status_counts: dict[str, int] = {}
            for item in summaries:
                status = item["empirical_status"]
                status_counts[status] = status_counts.get(status, 0) + 1
            payload = {
                "schema_version": 1,
                "report_kind": "eggy_all_primary_type_support",
                "design_space_complete": len(summaries),
                "empirical_status_counts": dict(sorted(status_counts.items())),
                "types": summaries,
            }
        else:
            payload = type_support_card(args.type, coverage)
    except (SupportError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

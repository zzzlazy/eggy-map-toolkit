#!/usr/bin/env python3
"""Audit component-role bindings for an expanded Eggy assembly plan.

This ledger bridges abstract design roles and current-version component
evidence.  It validates coverage and evidence bookkeeping, but it cannot prove
that a claimed catalog record is authentic or writable without the actual
component query made in the same work record.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import sys
from typing import Any

from expand_assembly_plan import expand_plan, example_plan


EVIDENCE_STATUSES = {"unresolved", "catalog_candidate", "verified_writable"}
DEVICE_STATUSES = {"unknown", "read_only", "writable"}
STAGES = {"design", "predeploy"}
COLLISION_POLICIES = {
    "visual_only",
    "continuous_proxy",
    "gameplay_native",
    "trigger_only",
    "not_applicable",
}
SHADOW_POLICIES = {"off", "focal", "review", "required", "not_applicable"}
SHAPE_FAMILIES = {
    "BASIC_PRIMITIVE": {
        "box",
        "cylinder",
        "wedge",
        "plate",
        "ring",
        "sphere",
        "curve",
        "primitive_other",
    },
    "COLLISION_PROXY": {"box", "cylinder", "capsule", "plane", "proxy_other"},
    "FX_LIGHT_AUDIO": {"fx", "light", "audio"},
    "GAMEPLAY_DEVICE": {"gameplay_device"},
    "LOGIC_ONLY": {"logic_only"},
    "THEME_ASSET": {"theme_asset"},
}
VISIBLE_KINDS = {"BASIC_PRIMITIVE", "FX_LIGHT_AUDIO", "THEME_ASSET"}


class BindingError(ValueError):
    pass


def _mapping(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BindingError(f"{path} must be an object")
    return value


def _list(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise BindingError(f"{path} must be an array")
    return value


def _string(value: Any, path: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise BindingError(f"{path} must be a non-empty string")
    return value.strip()


def _integer(value: Any, path: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise BindingError(f"{path} must be an integer >= {minimum}")
    return value


def _string_list(value: Any, path: str, *, minimum: int = 0) -> list[str]:
    raw = _list(value, path)
    if len(raw) < minimum:
        raise BindingError(f"{path} must contain at least {minimum} items")
    result = [_string(item, f"{path}[{index}]") for index, item in enumerate(raw)]
    if len(result) != len(set(result)):
        raise BindingError(f"{path} contains duplicates")
    return result


def _role_usage(assembly_plan: Any) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    expanded = expand_plan(assembly_plan)
    roles: dict[str, dict[str, Any]] = {}
    counts: Counter[str] = Counter()
    kinds: dict[str, set[str]] = defaultdict(set)
    layers: dict[str, set[str]] = defaultdict(set)
    cost_roles: dict[str, set[str]] = defaultdict(set)
    design_roles: dict[str, set[str]] = defaultdict(set)
    for instance in expanded["instances"]:
        role = instance["component_role"]
        counts[role] += 1
        kinds[role].add(instance["construction_kind"])
        layers[role].add(instance["layer"])
        cost_roles[role].add(instance["cost_role"])
        design_roles[role].update(instance["design_roles"])
    for role in sorted(counts):
        if len(kinds[role]) != 1:
            raise BindingError(
                f"component_role {role} is used with multiple construction kinds: "
                + ", ".join(sorted(kinds[role]))
            )
        roles[role] = {
            "instance_count": counts[role],
            "construction_kind": next(iter(kinds[role])),
            "layers": sorted(layers[role]),
            "cost_roles": sorted(cost_roles[role]),
            "design_roles": sorted(design_roles[role]),
        }
    return roles, expanded["summary"]


def _default_shape(kind: str, role: str) -> str:
    lowered = role.lower()
    if kind == "BASIC_PRIMITIVE":
        if any(token in lowered for token in ("panel", "tile", "slab", "plate", "edge")):
            return "plate"
        if any(token in lowered for token in ("post", "pillar", "pipe")):
            return "cylinder"
        return "box"
    if kind == "COLLISION_PROXY":
        return "box"
    if kind == "FX_LIGHT_AUDIO":
        return "light" if "light" in lowered else "fx"
    return next(iter(sorted(SHAPE_FAMILIES[kind])))


def binding_template(assembly_plan: Any) -> dict[str, Any]:
    roles, summary = _role_usage(assembly_plan)
    bindings: list[dict[str, Any]] = []
    for role, usage in roles.items():
        kind = usage["construction_kind"]
        if kind == "COLLISION_PROXY":
            collision_policy = "continuous_proxy"
            shadow_policy = "off"
            material_slots: list[str] = []
        elif kind == "LOGIC_ONLY":
            collision_policy = "trigger_only"
            shadow_policy = "not_applicable"
            material_slots = []
        elif kind == "GAMEPLAY_DEVICE":
            collision_policy = "gameplay_native"
            shadow_policy = "review"
            material_slots = ["device_default_or_semantic_state"]
        else:
            collision_policy = "visual_only"
            shadow_policy = "review"
            material_slots = ["replace_with_theme_material_slot"]
        bindings.append(
            {
                "component_role": role,
                "construction_kind": kind,
                "instance_count": usage["instance_count"],
                "used_layers": usage["layers"],
                "used_design_roles": usage["design_roles"],
                "shape_family": _default_shape(kind, role),
                "component_ref": None,
                "component_name": None,
                "evidence_status": "unresolved",
                "evidence_source": "not yet queried in the current game version",
                "pivot_and_scale_notes": (
                    "measure pivot, native bounds, allowed non-uniform scale, and rotation semantics"
                ),
                "collision_policy": collision_policy,
                "shadow_policy": shadow_policy,
                "material_slots": material_slots,
                "substitution_notes": (
                    "replace this placeholder with a current-version candidate that preserves "
                    "the declared shape, layer, design roles, and performance policy"
                ),
            }
        )
    return {
        "schema_version": 1,
        "stage": "design",
        "game_version": "unknown",
        "device_status": "unknown",
        "catalog_source": "query current component evidence before implementation",
        "assembly_expected_total": summary["expanded_total"],
        "bindings": bindings,
        "verification_boundary": (
            "This template proves role coverage only. A verified_writable claim must be backed "
            "by the actual current-version catalog/device result in the same work record."
        ),
    }


def validate_binding(assembly_plan: Any, binding_plan: Any) -> dict[str, Any]:
    root = _mapping(binding_plan, "binding_plan")
    version = _integer(root.get("schema_version"), "schema_version", minimum=1)
    if version != 1:
        raise BindingError(f"unsupported schema_version {version}; expected 1")
    stage = _string(root.get("stage"), "stage")
    if stage not in STAGES:
        raise BindingError("stage must be design or predeploy")
    game_version = _string(root.get("game_version"), "game_version")
    device_status = _string(root.get("device_status"), "device_status")
    if device_status not in DEVICE_STATUSES:
        raise BindingError(
            "device_status must be one of " + ", ".join(sorted(DEVICE_STATUSES))
        )
    catalog_source = _string(root.get("catalog_source"), "catalog_source")
    _string(root.get("verification_boundary"), "verification_boundary")

    role_usage, expanded_summary = _role_usage(assembly_plan)
    expected_total = _integer(
        root.get("assembly_expected_total"),
        "assembly_expected_total",
    )
    if expected_total != expanded_summary["expanded_total"]:
        raise BindingError(
            "assembly_expected_total mismatch "
            f"(binding={expected_total}, expanded={expanded_summary['expanded_total']})"
        )

    bindings: dict[str, dict[str, Any]] = {}
    statuses: Counter[str] = Counter()
    refs: set[str] = set()
    for index, raw_binding in enumerate(_list(root.get("bindings"), "bindings")):
        path = f"bindings[{index}]"
        item = _mapping(raw_binding, path)
        role = _string(item.get("component_role"), f"{path}.component_role")
        if role in bindings:
            raise BindingError(f"duplicate binding for component_role {role}")
        kind = _string(item.get("construction_kind"), f"{path}.construction_kind")
        if kind not in SHAPE_FAMILIES:
            raise BindingError(f"{path}.construction_kind is unknown")
        _integer(item.get("instance_count"), f"{path}.instance_count")
        used_layers = _string_list(item.get("used_layers"), f"{path}.used_layers", minimum=1)
        used_design_roles = _string_list(
            item.get("used_design_roles"),
            f"{path}.used_design_roles",
            minimum=1,
        )
        shape_family = _string(item.get("shape_family"), f"{path}.shape_family")
        if shape_family not in SHAPE_FAMILIES[kind]:
            raise BindingError(
                f"{path}.shape_family must be one of "
                + ", ".join(sorted(SHAPE_FAMILIES[kind]))
            )
        status = _string(item.get("evidence_status"), f"{path}.evidence_status")
        if status not in EVIDENCE_STATUSES:
            raise BindingError(
                f"{path}.evidence_status must be one of "
                + ", ".join(sorted(EVIDENCE_STATUSES))
            )
        component_ref = item.get("component_ref")
        component_name = item.get("component_name")
        if status == "unresolved":
            if component_ref is not None or component_name is not None:
                raise BindingError(
                    f"{path} unresolved binding must not claim component_ref or component_name"
                )
        else:
            ref = _string(component_ref, f"{path}.component_ref")
            _string(component_name, f"{path}.component_name")
            refs.add(ref)
        _string(item.get("evidence_source"), f"{path}.evidence_source")
        _string(item.get("pivot_and_scale_notes"), f"{path}.pivot_and_scale_notes")
        collision_policy = _string(
            item.get("collision_policy"), f"{path}.collision_policy"
        )
        if collision_policy not in COLLISION_POLICIES:
            raise BindingError(
                f"{path}.collision_policy must be one of "
                + ", ".join(sorted(COLLISION_POLICIES))
            )
        shadow_policy = _string(item.get("shadow_policy"), f"{path}.shadow_policy")
        if shadow_policy not in SHADOW_POLICIES:
            raise BindingError(
                f"{path}.shadow_policy must be one of "
                + ", ".join(sorted(SHADOW_POLICIES))
            )
        material_slots = _string_list(
            item.get("material_slots"),
            f"{path}.material_slots",
            minimum=1 if kind in VISIBLE_KINDS else 0,
        )
        _string(item.get("substitution_notes"), f"{path}.substitution_notes")
        if kind == "COLLISION_PROXY" and collision_policy != "continuous_proxy":
            raise BindingError(
                f"{path} COLLISION_PROXY must use collision_policy=continuous_proxy"
            )
        if kind == "LOGIC_ONLY" and collision_policy not in {
            "trigger_only",
            "not_applicable",
        }:
            raise BindingError(
                f"{path} LOGIC_ONLY must use trigger_only or not_applicable collision policy"
            )
        bindings[role] = {
            "construction_kind": kind,
            "instance_count": item["instance_count"],
            "used_layers": used_layers,
            "used_design_roles": used_design_roles,
            "shape_family": shape_family,
            "evidence_status": status,
            "collision_policy": collision_policy,
            "shadow_policy": shadow_policy,
            "material_slots": material_slots,
        }
        statuses[status] += 1

    missing = sorted(set(role_usage) - set(bindings))
    extra = sorted(set(bindings) - set(role_usage))
    if missing:
        raise BindingError("missing component-role bindings: " + ", ".join(missing))
    if extra:
        raise BindingError("bindings contain unused component roles: " + ", ".join(extra))
    for role, usage in role_usage.items():
        binding = bindings[role]
        if binding["construction_kind"] != usage["construction_kind"]:
            raise BindingError(
                f"binding {role} construction_kind mismatch "
                f"(binding={binding['construction_kind']}, assembly={usage['construction_kind']})"
            )
        if binding["instance_count"] != usage["instance_count"]:
            raise BindingError(
                f"binding {role} instance_count mismatch "
                f"(binding={binding['instance_count']}, assembly={usage['instance_count']})"
            )
        if binding["used_layers"] != usage["layers"]:
            raise BindingError(f"binding {role} used_layers mismatch")
        if binding["used_design_roles"] != usage["design_roles"]:
            raise BindingError(f"binding {role} used_design_roles mismatch")

    unresolved = sorted(
        role for role, binding in bindings.items() if binding["evidence_status"] == "unresolved"
    )
    candidates = sorted(
        role
        for role, binding in bindings.items()
        if binding["evidence_status"] == "catalog_candidate"
    )
    if stage == "predeploy":
        if game_version.lower() == "unknown":
            raise BindingError("predeploy binding requires a concrete game_version")
        if device_status != "writable":
            raise BindingError("predeploy binding requires device_status=writable")
        not_verified = sorted(
            role
            for role, binding in bindings.items()
            if binding["evidence_status"] != "verified_writable"
        )
        if not_verified:
            raise BindingError(
                "predeploy binding has roles without verified_writable evidence: "
                + ", ".join(not_verified)
            )

    warnings: list[str] = []
    if stage == "design" and unresolved:
        warnings.append(
            f"{len(unresolved)} component roles remain unresolved; keep component_evidence planned"
        )
    if stage == "design" and candidates:
        warnings.append(
            f"{len(candidates)} component roles are catalog candidates, not verified writable"
        )
    return {
        "schema_version": 1,
        "stage": stage,
        "game_version": game_version,
        "device_status": device_status,
        "catalog_source": catalog_source,
        "expanded_total": expanded_summary["expanded_total"],
        "component_role_count": len(role_usage),
        "component_ref_count": len(refs),
        "status_counts": dict(sorted(statuses.items())),
        "unresolved_roles": unresolved,
        "candidate_roles": candidates,
        "warnings": warnings,
    }


def _expect_invalid(assembly: dict[str, Any], binding: dict[str, Any], needle: str) -> None:
    try:
        validate_binding(assembly, binding)
    except BindingError as exc:
        if needle not in str(exc):
            raise AssertionError(f"expected {needle!r} in error, got: {exc}") from exc
    else:
        raise AssertionError("invalid component binding was accepted")


def _self_test() -> None:
    assembly = example_plan()
    for piece in assembly["families"][0]["pieces"]:
        if piece["component_role"] == "basic_box":
            piece["layer"] = "COL"
            piece["cost_role"] = "COL_PROXY"
            piece["construction_kind"] = "COLLISION_PROXY"
            piece["design_roles"] = ["COLLISION"]
    template = binding_template(assembly)
    summary = validate_binding(assembly, template)
    if summary["component_role_count"] != 2:
        raise AssertionError("component-role template coverage mismatch")
    if summary["status_counts"] != {"unresolved": 2}:
        raise AssertionError("design template must remain unresolved")

    predeploy = json.loads(json.dumps(template))
    predeploy["stage"] = "predeploy"
    predeploy["game_version"] = "test-version"
    predeploy["device_status"] = "writable"
    predeploy["catalog_source"] = "test fixture representing a current-version catalog query"
    for index, binding in enumerate(predeploy["bindings"], 1):
        binding["evidence_status"] = "verified_writable"
        binding["component_ref"] = f"TEST_REF_{index}"
        binding["component_name"] = f"Test Component {index}"
        binding["evidence_source"] = "test fixture only"
    verified = validate_binding(assembly, predeploy)
    if verified["status_counts"] != {"verified_writable": 2}:
        raise AssertionError("verified binding summary mismatch")

    missing = json.loads(json.dumps(template))
    missing["bindings"].pop()
    _expect_invalid(assembly, missing, "missing component-role bindings")

    wrong_kind = json.loads(json.dumps(template))
    wrong_kind["bindings"][0]["construction_kind"] = "THEME_ASSET"
    wrong_kind["bindings"][0]["shape_family"] = "theme_asset"
    wrong_kind["bindings"][0]["material_slots"] = ["test_material"]
    _expect_invalid(assembly, wrong_kind, "construction_kind mismatch")

    false_claim = json.loads(json.dumps(template))
    false_claim["bindings"][0]["component_ref"] = "UNVERIFIED_REF"
    _expect_invalid(assembly, false_claim, "must not claim component_ref")

    bad_proxy = json.loads(json.dumps(template))
    proxy = next(
        item for item in bad_proxy["bindings"] if item["construction_kind"] == "COLLISION_PROXY"
    )
    proxy["collision_policy"] = "visual_only"
    _expect_invalid(assembly, bad_proxy, "must use collision_policy=continuous_proxy")

    incomplete_predeploy = json.loads(json.dumps(template))
    incomplete_predeploy["stage"] = "predeploy"
    incomplete_predeploy["game_version"] = "test-version"
    incomplete_predeploy["device_status"] = "writable"
    _expect_invalid(assembly, incomplete_predeploy, "without verified_writable")


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Audit complete coverage from expanded component roles to current-version "
            "component evidence."
        )
    )
    parser.add_argument("assembly_plan", nargs="?", type=Path)
    parser.add_argument("binding_plan", nargs="?", type=Path)
    parser.add_argument("--template", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        _self_test()
        print("self-test passed")
        return 0
    if args.assembly_plan is None:
        parser.error("assembly_plan is required unless --self-test is used")
    if not args.template and args.binding_plan is None:
        parser.error("binding_plan is required unless --template is used")
    if args.template and args.binding_plan is not None:
        parser.error("binding_plan is not used with --template")
    try:
        assembly = _read_json(args.assembly_plan)
        if args.template:
            payload = binding_template(assembly)
        else:
            binding = _read_json(args.binding_plan)
            payload = validate_binding(assembly, binding)
    except (OSError, json.JSONDecodeError, BindingError, ValueError) as exc:
        print(f"invalid component binding: {exc}", file=sys.stderr)
        return 2
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.output is not None:
        args.output.write_text(rendered, encoding="utf-8")
    if args.json or args.template or args.output is None:
        print(rendered, end="")
    else:
        print(
            "component binding valid: "
            f"stage={payload['stage']}, roles={payload['component_role_count']}, "
            f"refs={payload['component_ref_count']}, "
            f"unresolved={len(payload['unresolved_roles'])}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

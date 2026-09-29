#!/usr/bin/env python3
"""Audit per-view performance budgets for a parameterized Eggy map plan.

The ledger ties the design complexity budget to the current expanded assembly,
then keeps cold entry, stable view, and worst interaction measurements separate.
It checks declared counts and evidence bookkeeping; only target-device testing
can establish the reported runtime result.
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
MEASUREMENT_STATUSES = {"unmeasured", "observed", "measured"}
RESULT_STATUSES = {"untested", "pass", "fail"}
DEGRADATION_STATUSES = {"planned", "tested", "not_used"}
ACCEPTANCE_MODES = {"unresolved", "numeric", "qualitative"}
PEAK_FIELDS = (
    "visible_peak",
    "collision_peak",
    "shadow_peak",
    "dynamic_peak",
    "transparent_layer_peak",
    "active_timer_peak",
    "spawned_object_peak",
    "switch_load_peak",
)
VISUAL_PEAK_FIELDS = {
    "visible_peak",
    "collision_peak",
    "shadow_peak",
    "dynamic_peak",
    "transparent_layer_peak",
    "switch_load_peak",
}
CRITICAL_DESIGN_ROLES = {
    "NAVIGATION",
    "DANGER",
    "INTERACTION",
    "GOAL",
    "STATE_FEEDBACK",
    "COLLISION",
}
VISIBLE_CONSTRUCTION_KINDS = {
    "BASIC_PRIMITIVE",
    "THEME_ASSET",
    "GAMEPLAY_DEVICE",
    "FX_LIGHT_AUDIO",
}
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


class PerformancePlanError(ValueError):
    pass


def _mapping(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PerformancePlanError(f"{path} must be an object")
    return value


def _list(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise PerformancePlanError(f"{path} must be an array")
    return value


def _string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PerformancePlanError(f"{path} must be a non-empty string")
    return value.strip()


def _meaningful(value: Any, path: str) -> str:
    text = _string(value, path)
    if len(text) < 8 or text.casefold().startswith(PLACEHOLDER_PREFIXES):
        raise PerformancePlanError(f"{path} must replace the unresolved placeholder")
    return text


def _integer(value: Any, path: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise PerformancePlanError(f"{path} must be an integer >= {minimum}")
    return value


def _number(value: Any, path: str, *, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PerformancePlanError(f"{path} must be numeric")
    result = float(value)
    if result < minimum:
        raise PerformancePlanError(f"{path} must be >= {minimum}")
    return result


def _optional_number(value: Any, path: str, *, minimum: float = 0.0) -> float | None:
    if value is None:
        return None
    return _number(value, path, minimum=minimum)


def _string_list(value: Any, path: str, *, minimum: int = 0) -> list[str]:
    raw = _list(value, path)
    if len(raw) < minimum:
        raise PerformancePlanError(f"{path} must contain at least {minimum} items")
    result = [_string(item, f"{path}[{index}]") for index, item in enumerate(raw)]
    if len(result) != len(set(result)):
        raise PerformancePlanError(f"{path} contains duplicates")
    return result


def _require_fields(value: dict[str, Any], required: set[str], path: str) -> None:
    missing = sorted(required - set(value))
    if missing:
        raise PerformancePlanError(f"{path} is missing: {', '.join(missing)}")


def _complexity_peaks(complexity: dict[str, Any]) -> dict[str, int]:
    visual = _mapping(complexity.get("visual"), "complexity_budget.visual")
    logic = _mapping(complexity.get("logic"), "complexity_budget.logic")
    result: dict[str, int] = {}
    for field in VISUAL_PEAK_FIELDS:
        result[field] = _integer(visual.get(field), f"complexity_budget.visual.{field}")
    result["active_timer_peak"] = _integer(
        logic.get("active_timer_peak"), "complexity_budget.logic.active_timer_peak"
    )
    result["spawned_object_peak"] = _integer(
        logic.get("spawned_object_peak"),
        "complexity_budget.logic.spawned_object_peak",
    )
    return result


def _source_facts(design_plan: Any, assembly_plan: Any) -> dict[str, Any]:
    try:
        design_summary = validate_design_plan(design_plan)
        expanded = expand_plan(assembly_plan)
    except (DesignPlanError, ExpansionError) as exc:
        raise PerformancePlanError(str(exc)) from exc
    design = _mapping(design_plan, "design_plan")
    assembly = _mapping(assembly_plan, "assembly_plan")
    primary_type = _string(design.get("primary_type"), "design_plan.primary_type")
    if assembly.get("primary_type") not in (None, primary_type):
        raise PerformancePlanError(
            "assembly_plan.primary_type does not match design_plan.primary_type"
        )
    budget = _mapping(design.get("assembly_budget"), "design_plan.assembly_budget")
    density_profile = _string(
        budget.get("density_profile"), "design_plan.assembly_budget.density_profile"
    )
    if assembly.get("density_profile") not in (None, density_profile):
        raise PerformancePlanError(
            "assembly_plan.density_profile does not match design_plan"
        )
    summary = expanded["summary"]
    if _integer(
        budget.get("expanded_total"), "design_plan.assembly_budget.expanded_total"
    ) != summary["expanded_total"]:
        raise PerformancePlanError(
            "design and assembly expanded totals differ"
        )
    complexity = _mapping(
        design.get("complexity_budget"), "design_plan.complexity_budget"
    )
    declared_peaks = _complexity_peaks(complexity)
    degradation_order = _string_list(
        complexity.get("degradation_order"),
        "design_plan.complexity_budget.degradation_order",
        minimum=2,
    )
    measurement = _mapping(
        complexity.get("measurement"),
        "design_plan.complexity_budget.measurement",
    )
    worst_case_state = _string(
        measurement.get("worst_case_state"),
        "design_plan.complexity_budget.measurement.worst_case_state",
    )

    zone_costs: dict[str, Counter[str]] = defaultdict(Counter)
    zone_kinds: dict[str, Counter[str]] = defaultdict(Counter)
    zone_roles: dict[str, set[str]] = defaultdict(set)
    for instance in expanded["instances"]:
        zone = instance["zone"]
        zone_costs[zone][instance["cost_role"]] += 1
        zone_kinds[zone][instance["construction_kind"]] += 1
        zone_roles[zone].update(instance["design_roles"])

    def bounds_for(zones: list[str]) -> dict[str, Any]:
        cost_roles: Counter[str] = Counter()
        construction_kinds: Counter[str] = Counter()
        roles: set[str] = set()
        for zone in zones:
            cost_roles.update(zone_costs[zone])
            construction_kinds.update(zone_kinds[zone])
            roles.update(zone_roles[zone])
        total = sum(cost_roles.values())
        visible = sum(
            count
            for kind, count in construction_kinds.items()
            if kind in VISIBLE_CONSTRUCTION_KINDS
        )
        return {
            "source_instance_upper_bound": total,
            "visible_candidate_upper_bound": visible,
            "source_cost_roles": dict(sorted(cost_roles.items())),
            "source_construction_kinds": dict(sorted(construction_kinds.items())),
            "source_design_roles": sorted(roles),
        }

    zones = sorted(summary["zones"])
    all_bounds = bounds_for(zones)
    return {
        "primary_type": primary_type,
        "density_profile": density_profile,
        "expanded_total": summary["expanded_total"],
        "zones": zones,
        "zone_counts": summary["zones"],
        "zone_bounds": {zone: bounds_for([zone]) for zone in zones},
        "global_bounds": all_bounds,
        "global_cost_totals": {
            "expanded_total": summary["expanded_total"],
            "zones": summary["zones"],
            "cost_roles": summary["cost_roles"],
            "construction_kinds": summary["construction_kinds"],
        },
        "complexity_snapshot": deepcopy(complexity),
        "declared_peaks": declared_peaks,
        "degradation_order": degradation_order,
        "worst_case_state": worst_case_state,
        "critical_roles": sorted(
            set(all_bounds["source_design_roles"]) & CRITICAL_DESIGN_ROLES
        ),
        "target_player_count": design_summary["player_range"][1],
        "design_stage": design_summary["stage"],
        "design_maturity": design_summary["maturity"],
    }


def _measurement_template() -> dict[str, Any]:
    return {
        "status": "unmeasured",
        "result": "untested",
        "cold_entry": {
            "minimum_fps": None,
            "recovery_seconds": None,
            "qualitative_result": None,
        },
        "stable_view": {
            "typical_fps": None,
            "p95_frame_time_ms": None,
            "qualitative_result": None,
        },
        "worst_interaction": {
            "minimum_fps": None,
            "p95_frame_time_ms": None,
            "qualitative_result": None,
        },
        "evidence": [],
    }


def _view_template(
    *,
    name: str,
    kind: str,
    zones: list[str],
    bounds: dict[str, Any],
    scenario: str,
    peaks: dict[str, int | None],
) -> dict[str, Any]:
    return {
        "name": name,
        "kind": kind,
        "source_zones": zones,
        "source_instance_upper_bound": bounds["source_instance_upper_bound"],
        "visible_candidate_upper_bound": bounds["visible_candidate_upper_bound"],
        "source_cost_roles": bounds["source_cost_roles"],
        "source_construction_kinds": bounds["source_construction_kinds"],
        "source_design_roles": bounds["source_design_roles"],
        "scenario": scenario,
        "planned_peaks": peaks,
        "measurement": _measurement_template(),
    }


def performance_plan_template(design_plan: Any, assembly_plan: Any) -> dict[str, Any]:
    facts = _source_facts(design_plan, assembly_plan)
    views = [
        _view_template(
            name="GLOBAL_WORST_CASE",
            kind="global_worst_case",
            zones=facts["zones"],
            bounds=facts["global_bounds"],
            scenario=facts["worst_case_state"],
            peaks=deepcopy(facts["declared_peaks"]),
        )
    ]
    for zone in facts["zones"]:
        views.append(
            _view_template(
                name=f"ZONE_{zone}_DENSEST_VIEW",
                kind="zone",
                zones=[zone],
                bounds=facts["zone_bounds"][zone],
                scenario="unresolved: name the densest real camera and active state in this zone",
                peaks={field: None for field in PEAK_FIELDS},
            )
        )
    degradation_steps = [
        {
            "order": index,
            "action": action,
            "affected_cost_roles": [],
            "preserves_design_roles": facts["critical_roles"],
            "validation": "unresolved: define the view and gameplay checks after this step",
            "status": "planned",
            "result_or_reason": None,
        }
        for index, action in enumerate(facts["degradation_order"], start=1)
    ]
    return {
        "schema_version": 1,
        "stage": "design",
        "primary_type": facts["primary_type"],
        "density_profile": facts["density_profile"],
        "assembly_expected_total": facts["expanded_total"],
        "design_complexity_snapshot": facts["complexity_snapshot"],
        "global_cost_totals": facts["global_cost_totals"],
        "target_context": {
            "game_version": "unknown",
            "device": "unknown",
            "quality_profile": "unknown",
            "player_count": facts["target_player_count"],
            "measurement_capability": "unknown",
            "test_route": "unresolved: define a repeatable camera and interaction route",
            "acceptance": {
                "mode": "unresolved",
                "cold_recovery_seconds_max": None,
                "stable_fps_min": None,
                "worst_interaction_fps_min": None,
                "qualitative_contract": None,
            },
        },
        "view_budgets": views,
        "degradation_steps": degradation_steps,
        "verification_boundary": (
            "This ledger cross-checks declared counts and evidence fields. Runtime results "
            "must come from the named target device, player count, route, and active state."
        ),
    }


def _counter_mapping(value: Any, path: str) -> dict[str, int]:
    mapping = _mapping(value, path)
    return {
        _string(key, f"{path} key"): _integer(count, f"{path}.{key}")
        for key, count in mapping.items()
    }


def _validate_acceptance(target: dict[str, Any], stage: str) -> str:
    acceptance = _mapping(target.get("acceptance"), "target_context.acceptance")
    _require_fields(
        acceptance,
        {
            "mode",
            "cold_recovery_seconds_max",
            "stable_fps_min",
            "worst_interaction_fps_min",
            "qualitative_contract",
        },
        "target_context.acceptance",
    )
    mode = _string(acceptance["mode"], "target_context.acceptance.mode")
    if mode not in ACCEPTANCE_MODES:
        raise PerformancePlanError(
            "target_context.acceptance.mode must be unresolved, numeric, or qualitative"
        )
    if stage in {"review", "predeploy"} and mode == "unresolved":
        raise PerformancePlanError(
            f"stage={stage} requires a resolved performance acceptance contract"
        )
    if mode == "numeric":
        _number(
            acceptance["cold_recovery_seconds_max"],
            "target_context.acceptance.cold_recovery_seconds_max",
        )
        _number(
            acceptance["stable_fps_min"],
            "target_context.acceptance.stable_fps_min",
            minimum=1,
        )
        _number(
            acceptance["worst_interaction_fps_min"],
            "target_context.acceptance.worst_interaction_fps_min",
            minimum=1,
        )
        if acceptance["qualitative_contract"] not in (None, ""):
            _meaningful(
                acceptance["qualitative_contract"],
                "target_context.acceptance.qualitative_contract",
            )
    elif mode == "qualitative":
        for field in (
            "cold_recovery_seconds_max",
            "stable_fps_min",
            "worst_interaction_fps_min",
        ):
            if acceptance[field] is not None:
                raise PerformancePlanError(
                    f"target_context.acceptance.{field} must be null in qualitative mode"
                )
        _meaningful(
            acceptance["qualitative_contract"],
            "target_context.acceptance.qualitative_contract",
        )
    else:
        for field in (
            "cold_recovery_seconds_max",
            "stable_fps_min",
            "worst_interaction_fps_min",
            "qualitative_contract",
        ):
            if acceptance[field] not in (None, ""):
                raise PerformancePlanError(
                    f"target_context.acceptance.{field} must remain null while unresolved"
                )
    return mode


def _validate_phase(
    value: Any,
    path: str,
    *,
    fields: tuple[str, str, str],
    status: str,
) -> None:
    phase = _mapping(value, path)
    _require_fields(phase, set(fields), path)
    first = _optional_number(
        phase[fields[0]], f"{path}.{fields[0]}", minimum=0.001
    )
    second = _optional_number(
        phase[fields[1]],
        f"{path}.{fields[1]}",
        minimum=0.0 if fields[1] == "recovery_seconds" else 0.001,
    )
    qualitative = phase[fields[2]]
    if qualitative is not None:
        _meaningful(qualitative, f"{path}.{fields[2]}")
    if status == "observed" and qualitative is None:
        raise PerformancePlanError(
            f"{path}.{fields[2]} is required for qualitative observation"
        )
    if status == "measured" and first is None and second is None:
        raise PerformancePlanError(
            f"{path} needs at least one numeric measurement"
        )


def _validate_measurement(value: Any, path: str, stage: str) -> tuple[str, str]:
    measurement = _mapping(value, path)
    _require_fields(
        measurement,
        {
            "status",
            "result",
            "cold_entry",
            "stable_view",
            "worst_interaction",
            "evidence",
        },
        path,
    )
    status = _string(measurement["status"], f"{path}.status")
    result = _string(measurement["result"], f"{path}.result")
    if status not in MEASUREMENT_STATUSES:
        raise PerformancePlanError(
            f"{path}.status must be unmeasured, observed, or measured"
        )
    if result not in RESULT_STATUSES:
        raise PerformancePlanError(f"{path}.result must be untested, pass, or fail")
    evidence = _string_list(measurement["evidence"], f"{path}.evidence")
    _validate_phase(
        measurement["cold_entry"],
        f"{path}.cold_entry",
        fields=("minimum_fps", "recovery_seconds", "qualitative_result"),
        status=status,
    )
    _validate_phase(
        measurement["stable_view"],
        f"{path}.stable_view",
        fields=("typical_fps", "p95_frame_time_ms", "qualitative_result"),
        status=status,
    )
    _validate_phase(
        measurement["worst_interaction"],
        f"{path}.worst_interaction",
        fields=("minimum_fps", "p95_frame_time_ms", "qualitative_result"),
        status=status,
    )
    if status == "unmeasured":
        if result != "untested":
            raise PerformancePlanError(
                f"{path} cannot claim {result} while unmeasured"
            )
        if evidence:
            raise PerformancePlanError(
                f"{path}.evidence must remain empty while unmeasured"
            )
        for phase_name in ("cold_entry", "stable_view", "worst_interaction"):
            if any(
                value is not None
                for value in measurement[phase_name].values()
            ):
                raise PerformancePlanError(
                    f"{path}.{phase_name} must remain empty while unmeasured"
                )
    else:
        if result == "untested":
            raise PerformancePlanError(
                f"{path} must record pass or fail after observation"
            )
        if not evidence:
            raise PerformancePlanError(
                f"{path}.evidence must identify the target-device record"
            )
    if stage == "predeploy" and (status == "unmeasured" or result != "pass"):
        raise PerformancePlanError(
            f"predeploy requires a passing observed/measured result at {path}"
        )
    return status, result


def _validate_views(
    root: dict[str, Any],
    facts: dict[str, Any],
    stage: str,
    acceptance_mode: str,
    acceptance: dict[str, Any],
) -> tuple[Counter[str], Counter[str]]:
    views = _list(root.get("view_budgets"), "view_budgets")
    if not views:
        raise PerformancePlanError("view_budgets cannot be empty")
    names: set[str] = set()
    zone_view_coverage: set[str] = set()
    global_views = 0
    measurement_statuses: Counter[str] = Counter()
    result_statuses: Counter[str] = Counter()
    for index, raw in enumerate(views):
        path = f"view_budgets[{index}]"
        view = _mapping(raw, path)
        _require_fields(
            view,
            {
                "name",
                "kind",
                "source_zones",
                "source_instance_upper_bound",
                "visible_candidate_upper_bound",
                "source_cost_roles",
                "source_construction_kinds",
                "source_design_roles",
                "scenario",
                "planned_peaks",
                "measurement",
            },
            path,
        )
        name = _string(view["name"], f"{path}.name")
        if name in names:
            raise PerformancePlanError(f"duplicate performance view {name}")
        names.add(name)
        kind = _string(view["kind"], f"{path}.kind")
        if kind not in {"global_worst_case", "zone", "custom"}:
            raise PerformancePlanError(
                f"{path}.kind must be global_worst_case, zone, or custom"
            )
        zones = _string_list(view["source_zones"], f"{path}.source_zones", minimum=1)
        unknown_zones = set(zones) - set(facts["zones"])
        if unknown_zones:
            raise PerformancePlanError(
                f"{path}.source_zones contains unknown zones: {sorted(unknown_zones)}"
            )
        if kind == "zone":
            zone_view_coverage.update(zones)
        if kind == "global_worst_case":
            global_views += 1
            if set(zones) != set(facts["zones"]):
                raise PerformancePlanError(
                    "global_worst_case must include every actual assembly zone"
                )
        expected = facts["global_bounds"] if set(zones) == set(facts["zones"]) else None
        if expected is None:
            cost_roles: Counter[str] = Counter()
            kinds: Counter[str] = Counter()
            roles: set[str] = set()
            total = 0
            visible = 0
            for zone in zones:
                zone_bounds = facts["zone_bounds"][zone]
                total += zone_bounds["source_instance_upper_bound"]
                visible += zone_bounds["visible_candidate_upper_bound"]
                cost_roles.update(zone_bounds["source_cost_roles"])
                kinds.update(zone_bounds["source_construction_kinds"])
                roles.update(zone_bounds["source_design_roles"])
            expected = {
                "source_instance_upper_bound": total,
                "visible_candidate_upper_bound": visible,
                "source_cost_roles": dict(sorted(cost_roles.items())),
                "source_construction_kinds": dict(sorted(kinds.items())),
                "source_design_roles": sorted(roles),
            }
        if _integer(
            view["source_instance_upper_bound"], f"{path}.source_instance_upper_bound"
        ) != expected["source_instance_upper_bound"]:
            raise PerformancePlanError(
                f"{path}.source_instance_upper_bound drifted from assembly"
            )
        if _integer(
            view["visible_candidate_upper_bound"],
            f"{path}.visible_candidate_upper_bound",
        ) != expected["visible_candidate_upper_bound"]:
            raise PerformancePlanError(
                f"{path}.visible_candidate_upper_bound drifted from assembly"
            )
        if _counter_mapping(view["source_cost_roles"], f"{path}.source_cost_roles") != expected[
            "source_cost_roles"
        ]:
            raise PerformancePlanError(f"{path}.source_cost_roles drifted from assembly")
        if _counter_mapping(
            view["source_construction_kinds"],
            f"{path}.source_construction_kinds",
        ) != expected["source_construction_kinds"]:
            raise PerformancePlanError(
                f"{path}.source_construction_kinds drifted from assembly"
            )
        roles = _string_list(
            view["source_design_roles"], f"{path}.source_design_roles", minimum=1
        )
        if set(roles) != set(expected["source_design_roles"]):
            raise PerformancePlanError(
                f"{path}.source_design_roles drifted from assembly"
            )
        scenario = _string(view["scenario"], f"{path}.scenario")
        if stage in {"review", "predeploy"}:
            _meaningful(scenario, f"{path}.scenario")

        peaks = _mapping(view["planned_peaks"], f"{path}.planned_peaks")
        if set(peaks) != set(PEAK_FIELDS):
            raise PerformancePlanError(
                f"{path}.planned_peaks must contain exactly {', '.join(PEAK_FIELDS)}"
            )
        normalized_peaks: dict[str, int | None] = {}
        for field in PEAK_FIELDS:
            raw_peak = peaks[field]
            if raw_peak is None:
                if stage in {"review", "predeploy"}:
                    raise PerformancePlanError(
                        f"{path}.planned_peaks.{field} cannot remain unresolved"
                    )
                normalized_peaks[field] = None
            else:
                normalized_peaks[field] = _integer(
                    raw_peak, f"{path}.planned_peaks.{field}"
                )
        if kind == "global_worst_case" and normalized_peaks != facts["declared_peaks"]:
            raise PerformancePlanError(
                "global_worst_case planned peaks must equal design_complexity_snapshot"
            )
        for field in (
            "visible_peak",
            "collision_peak",
            "shadow_peak",
            "dynamic_peak",
            "switch_load_peak",
        ):
            peak = normalized_peaks[field]
            if peak is not None and peak > expected["source_instance_upper_bound"]:
                raise PerformancePlanError(
                    f"{path}.planned_peaks.{field} exceeds source instance upper bound"
                )
        visible_peak = normalized_peaks["visible_peak"]
        if (
            visible_peak is not None
            and visible_peak > expected["visible_candidate_upper_bound"]
        ):
            raise PerformancePlanError(
                f"{path}.planned_peaks.visible_peak exceeds visible candidate upper bound"
            )
        status, result = _validate_measurement(
            view["measurement"], f"{path}.measurement", stage
        )
        measurement = view["measurement"]
        if result == "pass" and acceptance_mode == "numeric":
            if status != "measured":
                raise PerformancePlanError(
                    f"{path} needs numeric measurement to claim a numeric acceptance pass"
                )
            cold_recovery = measurement["cold_entry"]["recovery_seconds"]
            if cold_recovery is None:
                raise PerformancePlanError(
                    f"{path}.measurement.cold_entry.recovery_seconds is required for numeric acceptance"
                )
            if float(cold_recovery) > float(acceptance["cold_recovery_seconds_max"]):
                raise PerformancePlanError(
                    f"{path} claims pass but cold-entry recovery exceeds acceptance"
                )

            stable_fps = measurement["stable_view"]["typical_fps"]
            stable_frame = measurement["stable_view"]["p95_frame_time_ms"]
            stable_effective = (
                float(stable_fps)
                if stable_fps is not None
                else 1000.0 / float(stable_frame)
            )
            if stable_effective < float(acceptance["stable_fps_min"]):
                raise PerformancePlanError(
                    f"{path} claims pass but stable performance is below acceptance"
                )

            worst_fps = measurement["worst_interaction"]["minimum_fps"]
            worst_frame = measurement["worst_interaction"]["p95_frame_time_ms"]
            worst_effective = (
                float(worst_fps)
                if worst_fps is not None
                else 1000.0 / float(worst_frame)
            )
            if worst_effective < float(acceptance["worst_interaction_fps_min"]):
                raise PerformancePlanError(
                    f"{path} claims pass but worst-interaction performance is below acceptance"
                )
        if result == "pass" and acceptance_mode == "qualitative":
            for phase_name in ("cold_entry", "stable_view", "worst_interaction"):
                if measurement[phase_name]["qualitative_result"] is None:
                    raise PerformancePlanError(
                        f"{path}.measurement.{phase_name}.qualitative_result is required for qualitative acceptance"
                    )
        measurement_statuses[status] += 1
        result_statuses[result] += 1

    if global_views != 1:
        raise PerformancePlanError(
            "view_budgets must contain exactly one global_worst_case"
        )
    if zone_view_coverage != set(facts["zones"]):
        raise PerformancePlanError(
            "zone performance view coverage mismatch: "
            f"missing={sorted(set(facts['zones']) - zone_view_coverage)}"
        )
    return measurement_statuses, result_statuses


def _validate_degradation(
    root: dict[str, Any], facts: dict[str, Any], stage: str
) -> Counter[str]:
    steps = _list(root.get("degradation_steps"), "degradation_steps")
    if len(steps) != len(facts["degradation_order"]):
        raise PerformancePlanError(
            "degradation_steps length drifted from design complexity budget"
        )
    statuses: Counter[str] = Counter()
    for index, (raw, expected_action) in enumerate(
        zip(steps, facts["degradation_order"]), start=1
    ):
        path = f"degradation_steps[{index - 1}]"
        step = _mapping(raw, path)
        _require_fields(
            step,
            {
                "order",
                "action",
                "affected_cost_roles",
                "preserves_design_roles",
                "validation",
                "status",
                "result_or_reason",
            },
            path,
        )
        if _integer(step["order"], f"{path}.order", minimum=1) != index:
            raise PerformancePlanError(f"{path}.order is not contiguous")
        if _string(step["action"], f"{path}.action") != expected_action:
            raise PerformancePlanError(f"{path}.action drifted from design plan")
        preserved = _string_list(
            step["preserves_design_roles"], f"{path}.preserves_design_roles"
        )
        if set(preserved) != set(facts["critical_roles"]):
            raise PerformancePlanError(
                f"{path}.preserves_design_roles must retain every actual critical role"
            )
        affected = _string_list(
            step["affected_cost_roles"], f"{path}.affected_cost_roles"
        )
        status = _string(step["status"], f"{path}.status")
        if status not in DEGRADATION_STATUSES:
            raise PerformancePlanError(
                f"{path}.status must be planned, tested, or not_used"
            )
        statuses[status] += 1
        if stage in {"review", "predeploy"}:
            if not affected:
                raise PerformancePlanError(
                    f"{path}.affected_cost_roles cannot remain empty"
                )
            _meaningful(step["validation"], f"{path}.validation")
        if status in {"tested", "not_used"}:
            _meaningful(step["result_or_reason"], f"{path}.result_or_reason")
        elif step["result_or_reason"] not in (None, ""):
            raise PerformancePlanError(
                f"{path}.result_or_reason must remain null while planned"
            )
        if stage == "predeploy" and status == "planned":
            raise PerformancePlanError(
                "predeploy cannot retain planned degradation steps"
            )
    return statuses


def validate_performance_plan(
    design_plan: Any, assembly_plan: Any, performance_plan: Any
) -> dict[str, Any]:
    facts = _source_facts(design_plan, assembly_plan)
    root = _mapping(performance_plan, "performance_plan")
    _require_fields(
        root,
        {
            "schema_version",
            "stage",
            "primary_type",
            "density_profile",
            "assembly_expected_total",
            "design_complexity_snapshot",
            "global_cost_totals",
            "target_context",
            "view_budgets",
            "degradation_steps",
            "verification_boundary",
        },
        "performance_plan",
    )
    version = _integer(root["schema_version"], "schema_version", minimum=1)
    if version != 1:
        raise PerformancePlanError(
            f"unsupported schema_version {version}; expected 1"
        )
    stage = _string(root["stage"], "stage")
    if stage not in STAGES:
        raise PerformancePlanError("stage must be design, review, or predeploy")
    if _string(root["primary_type"], "primary_type") != facts["primary_type"]:
        raise PerformancePlanError("primary_type drifted from design plan")
    if _string(root["density_profile"], "density_profile") != facts["density_profile"]:
        raise PerformancePlanError("density_profile drifted from design plan")
    if _integer(root["assembly_expected_total"], "assembly_expected_total") != facts[
        "expanded_total"
    ]:
        raise PerformancePlanError("assembly_expected_total drifted from assembly")
    if root["design_complexity_snapshot"] != facts["complexity_snapshot"]:
        raise PerformancePlanError(
            "design_complexity_snapshot drifted; regenerate or reconcile the ledger"
        )
    if root["global_cost_totals"] != facts["global_cost_totals"]:
        raise PerformancePlanError(
            "global_cost_totals drifted from the current expanded assembly"
        )
    _meaningful(root["verification_boundary"], "verification_boundary")

    target = _mapping(root["target_context"], "target_context")
    _require_fields(
        target,
        {
            "game_version",
            "device",
            "quality_profile",
            "player_count",
            "measurement_capability",
            "test_route",
            "acceptance",
        },
        "target_context",
    )
    if _integer(target["player_count"], "target_context.player_count", minimum=1) != facts[
        "target_player_count"
    ]:
        raise PerformancePlanError(
            "target_context.player_count must use the design maximum player count"
        )
    for field in (
        "game_version",
        "device",
        "quality_profile",
        "measurement_capability",
        "test_route",
    ):
        _string(target[field], f"target_context.{field}")
    acceptance_mode = _validate_acceptance(target, stage)
    if stage in {"review", "predeploy"}:
        _meaningful(target["test_route"], "target_context.test_route")
    if stage == "predeploy":
        if facts["design_stage"] != "predeploy" or facts["design_maturity"] != "final":
            raise PerformancePlanError(
                "performance predeploy requires a final design plan at stage=predeploy"
            )
        for field in (
            "game_version",
            "device",
            "quality_profile",
            "measurement_capability",
        ):
            value = _string(target[field], f"target_context.{field}")
            if value.casefold() in {"unknown", "unresolved", "tbd"}:
                raise PerformancePlanError(
                    f"target_context.{field} must be concrete at predeploy"
                )

    measurement_statuses, result_statuses = _validate_views(
        root,
        facts,
        stage,
        acceptance_mode,
        _mapping(target["acceptance"], "target_context.acceptance"),
    )
    degradation_statuses = _validate_degradation(root, facts, stage)

    collision_count = facts["global_cost_totals"]["cost_roles"].get(
        "COL_PROXY", 0
    )
    collision_share = collision_count / facts["expanded_total"]
    warnings: list[str] = []
    if measurement_statuses.get("unmeasured"):
        warnings.append(
            f"{measurement_statuses['unmeasured']} performance views remain unmeasured"
        )
    if result_statuses.get("fail"):
        warnings.append(
            f"{result_statuses['fail']} performance views currently fail acceptance"
        )
    if degradation_statuses.get("planned"):
        warnings.append(
            f"{degradation_statuses['planned']} degradation steps still need disposition"
        )
    if collision_share > 0.20:
        warnings.append(
            "collision proxies exceed 20% of expanded instances; review continuous proxy strategy"
        )
    return {
        "schema_version": version,
        "stage": stage,
        "primary_type": facts["primary_type"],
        "density_profile": facts["density_profile"],
        "expanded_total": facts["expanded_total"],
        "zone_count": len(facts["zones"]),
        "view_count": sum(measurement_statuses.values()),
        "acceptance_mode": acceptance_mode,
        "measurement_statuses": dict(sorted(measurement_statuses.items())),
        "result_statuses": dict(sorted(result_statuses.items())),
        "degradation_statuses": dict(sorted(degradation_statuses.items())),
        "collision_proxy_share": round(collision_share, 6),
        "warnings": warnings,
    }


def _aligned_examples() -> tuple[dict[str, Any], dict[str, Any]]:
    design = design_example_plan()
    source_assembly = assembly_example_plan()
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
        family = deepcopy(source_assembly["families"][0])
        family["name"] = name
        assembly["families"].append(family)
        placement = deepcopy(source_assembly["placements"][0])
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
    plan = performance_plan_template(design, assembly)
    plan["stage"] = "predeploy"
    target = plan["target_context"]
    target.update(
        {
            "game_version": "1.0.tested",
            "device": "target Android device model and OS build",
            "quality_profile": "fixed medium quality at native test resolution",
            "measurement_capability": "numeric FPS overlay plus repeatable video capture",
            "test_route": "repeat cold entry, stable pan, and maximum-player climax three times",
        }
    )
    target["acceptance"] = {
        "mode": "numeric",
        "cold_recovery_seconds_max": 5.0,
        "stable_fps_min": 45.0,
        "worst_interaction_fps_min": 30.0,
        "qualitative_contract": "No visible input stall, missing route surface, or late collision after recovery.",
    }
    declared = plan["design_complexity_snapshot"]
    for view in plan["view_budgets"]:
        if view["kind"] != "global_worst_case":
            view["scenario"] = (
                f"Maximum-player traversal through the densest camera in {view['source_zones'][0]}."
            )
            bounds = view["source_instance_upper_bound"]
            visible = view["visible_candidate_upper_bound"]
            view["planned_peaks"] = {
                "visible_peak": min(declared["visual"]["visible_peak"], visible),
                "collision_peak": min(declared["visual"]["collision_peak"], bounds),
                "shadow_peak": min(declared["visual"]["shadow_peak"], bounds),
                "dynamic_peak": min(declared["visual"]["dynamic_peak"], bounds),
                "transparent_layer_peak": declared["visual"]["transparent_layer_peak"],
                "active_timer_peak": declared["logic"]["active_timer_peak"],
                "spawned_object_peak": declared["logic"]["spawned_object_peak"],
                "switch_load_peak": min(declared["visual"]["switch_load_peak"], bounds),
            }
        view["measurement"] = {
            "status": "measured",
            "result": "pass",
            "cold_entry": {
                "minimum_fps": 31.0,
                "recovery_seconds": 3.2,
                "qualitative_result": "Control remained responsive while the view recovered.",
            },
            "stable_view": {
                "typical_fps": 57.0,
                "p95_frame_time_ms": 19.0,
                "qualitative_result": "Stable pan preserved route and interaction readability.",
            },
            "worst_interaction": {
                "minimum_fps": 36.0,
                "p95_frame_time_ms": 27.0,
                "qualitative_result": "Maximum-player climax stayed controllable without late collision.",
            },
            "evidence": [f"target-device capture for {view['name']} run 1-3"],
        }
    for step in plan["degradation_steps"]:
        step["affected_cost_roles"] = ["VIS_STATIC"]
        step["validation"] = (
            "Repeat the named worst view and verify navigation, danger, interaction, goal, and collision roles."
        )
        step["status"] = "not_used"
        step["result_or_reason"] = (
            "Baseline passed the acceptance contract, so this ordered fallback was retained but not applied."
        )
    return plan


def _expect_invalid(
    design: dict[str, Any],
    assembly: dict[str, Any],
    plan: dict[str, Any],
    contains: str,
) -> None:
    try:
        validate_performance_plan(design, assembly, plan)
    except PerformancePlanError as exc:
        if contains not in str(exc):
            raise AssertionError(f"expected {contains!r}, got {str(exc)!r}") from exc
    else:
        raise AssertionError(f"expected invalid performance plan containing {contains!r}")


def _self_test() -> None:
    design, assembly = _aligned_examples()
    template = performance_plan_template(design, assembly)
    summary = validate_performance_plan(design, assembly, template)
    if summary["view_count"] != 2:
        raise AssertionError("template should contain global and zone views")
    if summary["measurement_statuses"] != {"unmeasured": 2}:
        raise AssertionError("template should not invent measurements")

    completed = _completed_plan(design, assembly)
    completed_summary = validate_performance_plan(design, assembly, completed)
    if completed_summary["warnings"]:
        raise AssertionError(
            f"completed performance plan has warnings: {completed_summary['warnings']}"
        )

    drifted_snapshot = deepcopy(completed)
    drifted_snapshot["design_complexity_snapshot"]["visual"]["visible_peak"] += 1
    _expect_invalid(design, assembly, drifted_snapshot, "snapshot drifted")

    missing_zone_view = deepcopy(completed)
    missing_zone_view["view_budgets"].pop()
    _expect_invalid(design, assembly, missing_zone_view, "zone performance view coverage")

    excessive_visible = deepcopy(completed)
    excessive_visible["view_budgets"][1]["planned_peaks"]["visible_peak"] = 999999
    _expect_invalid(design, assembly, excessive_visible, "source instance upper bound")

    unmeasured_predeploy = deepcopy(completed)
    unmeasured_predeploy["view_budgets"][0]["measurement"] = _measurement_template()
    _expect_invalid(design, assembly, unmeasured_predeploy, "predeploy requires")

    false_numeric_pass = deepcopy(completed)
    false_numeric_pass["view_budgets"][0]["measurement"]["stable_view"][
        "typical_fps"
    ] = 10.0
    _expect_invalid(design, assembly, false_numeric_pass, "below acceptance")

    destructive_degradation = deepcopy(completed)
    destructive_degradation["degradation_steps"][0]["preserves_design_roles"] = []
    _expect_invalid(design, assembly, destructive_degradation, "critical role")


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Audit per-view performance budgets against an Eggy design and expanded assembly."
        )
    )
    parser.add_argument("design_plan", nargs="?", type=Path)
    parser.add_argument("assembly_plan", nargs="?", type=Path)
    parser.add_argument("performance_plan", nargs="?", type=Path)
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
    if args.template and args.performance_plan is not None:
        parser.error("performance_plan is not accepted with --template")
    if not args.template and args.performance_plan is None:
        parser.error("performance_plan is required unless --template is used")
    try:
        design = _load(args.design_plan)
        assembly = _load(args.assembly_plan)
        if args.template:
            payload: Any = performance_plan_template(design, assembly)
        else:
            payload = validate_performance_plan(
                design, assembly, _load(args.performance_plan)
            )
    except (
        OSError,
        json.JSONDecodeError,
        PerformancePlanError,
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

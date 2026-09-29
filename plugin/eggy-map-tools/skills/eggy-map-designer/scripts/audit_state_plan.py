#!/usr/bin/env python3
"""Audit reachability, reset paths, transitions, and scenario coverage."""

from __future__ import annotations

import argparse
from collections import defaultdict, deque
import json
from pathlib import Path
import sys
from typing import Any


SCOPES = {"ROUND", "TEAM", "PLAYER", "CHAPTER", "OBJECT", "SESSION"}
PRIMARY_TYPES = {
    "short_race",
    "chapter_challenge",
    "mechanism_puzzle",
    "cooperative",
    "narrative_exploration",
    "survival",
    "score_contest",
    "social_showcase",
    "management_simulation",
    "rhythm_performance",
    "combat_boss",
    "defense_strategy",
    "stealth_infiltration",
    "turn_based_strategy",
    "sports_match",
    "sandbox_creation",
    "social_deduction",
}
FEATURES = {
    "multiplayer",
    "checkpoints",
    "spawned_objects",
    "timed_logic",
    "rounds",
    "scoring",
    "cooperative",
    "narrative_events",
    "social_occupancy",
    "economy",
    "managed_actors",
    "persistent_world",
    "random",
    "vehicles",
    "destructibles",
}
BASE_SCENARIOS = {
    "first_load",
    "normal_complete",
    "duplicate_trigger",
    "out_of_order",
    "death_or_failure",
    "terminal_conflict",
}
FEATURE_SCENARIOS = {
    "multiplayer": {"simultaneous_players", "disconnect", "late_join"},
    "checkpoints": {"checkpoint_edge"},
    "spawned_objects": {"object_out_of_bounds", "old_generation"},
    "timed_logic": {"pending_timer_cancel", "timeout"},
    "rounds": {"second_round", "third_round", "no_winner_or_empty"},
    "scoring": {"simultaneous_score", "score_timeout_conflict"},
    "cooperative": {"handoff_failure", "missing_partner"},
    "narrative_events": {
        "event_interrupt",
        "event_skip",
        "revisit",
        "reload_restore",
        "duplicate_event_entry",
    },
    "social_occupancy": {"occupancy_release"},
    "economy": {
        "simultaneous_transaction",
        "capacity_or_insufficient",
        "interrupted_transaction",
        "product_duplicate_or_lost",
        "catalog_terminal_mismatch",
    },
    "managed_actors": {
        "worker_target_invalid",
        "demand_actor_abandon",
        "orphaned_order_cleanup",
    },
    "persistent_world": {
        "save_authority_absent",
        "reload_rebuild",
        "new_session_reset",
        "schema_migration_or_missing_field",
    },
    "random": {"extreme_random", "old_generation"},
    "vehicles": {"vehicle_abandon", "old_generation"},
    "destructibles": {
        "duplicate_damage_same_input",
        "duplicate_destruction_reward",
        "dependent_surface_during_contact",
        "partial_destruction_checkpoint",
        "destruction_terminal_conflict",
        "destruction_second_entry",
    },
}
TYPE_SCENARIOS = {
    "short_race": {"fast_player", "slow_player", "checkpoint_skip"},
    "chapter_challenge": {
        "late_chapter_reentry",
        "repeated_failure",
        "long_session",
    },
    "mechanism_puzzle": {
        "wrong_input",
        "out_of_order",
        "hint_timeout",
        "room_reentry",
        "checkpoint_recovery",
        "repeat_reset",
    },
    "cooperative": {
        "missing_partner",
        "simultaneous_failure",
        "handoff_out_of_order",
    },
    "narrative_exploration": {
        "event_skip",
        "revisit",
        "event_interrupt",
        "reload_restore",
        "duplicate_event_entry",
    },
    "survival": {
        "idle_no_input",
        "optional_overlay_ignored",
        "phase_transition",
        "all_eliminated",
        "draw",
        "second_round",
    },
    "score_contest": {"score_timeout_conflict", "tie", "second_round"},
    "social_showcase": {
        "full_occupancy",
        "walk_away_return",
        "interaction_abandon",
    },
    "management_simulation": {
        "capacity_full",
        "simultaneous_transaction",
        "interrupted_transaction",
        "product_duplicate_or_lost",
        "second_cycle",
        "catalog_terminal_mismatch",
        "save_authority_absent",
        "reload_rebuild",
    },
    "rhythm_performance": {
        "muted_performance",
        "latency_extremes",
        "early_late_input",
        "duplicate_note_input",
        "pause_resume_sequence",
        "second_sequence",
    },
    "combat_boss": {
        "idle_opening",
        "simultaneous_damage",
        "phase_transition_damage",
        "player_death_during_attack",
        "boss_boundary_escape",
        "all_players_down",
        "second_attempt",
    },
    "defense_strategy": {
        "empty_build",
        "full_build_slots",
        "simultaneous_purchase",
        "enemy_stuck_or_rerouted",
        "leak_terminal_conflict",
        "owner_disconnect",
        "second_wave_set",
    },
    "stealth_infiltration": {
        "idle_patrol",
        "visibility_boundary",
        "simultaneous_detection",
        "all_sensors_alert",
        "objective_before_exfiltration",
        "death_during_alert",
        "stealth_reentry",
    },
    "turn_based_strategy": {
        "empty_action",
        "simultaneous_turn_input",
        "turn_timeout",
        "active_player_disconnect",
        "stale_action",
        "draw_resolution",
        "second_match",
    },
    "sports_match": {
        "idle_kickoff",
        "simultaneous_touch",
        "out_of_bounds",
        "own_goal_or_wrong_side",
        "scorer_disconnect",
        "tie_at_timeout",
        "second_match",
    },
    "sandbox_creation": {
        "empty_world",
        "budget_full",
        "overlapping_placement",
        "simultaneous_edit",
        "owner_disconnect",
        "save_reload_creation",
        "session_cleanup",
    },
    "social_deduction": {
        "idle_opening",
        "duplicate_role_assignment",
        "simultaneous_report_or_meeting",
        "eliminated_player_input",
        "vote_tie",
        "active_role_disconnect",
        "stale_private_action",
        "second_round",
    },
}
HYBRID_SCENARIOS = {
    "hybrid_duplicate_entry",
    "hybrid_abandon_or_timeout",
    "hybrid_simultaneous_failure",
    "hybrid_state_handoff",
    "hybrid_second_entry",
}
SCENARIO_STATUSES = {"planned", "tested", "not_applicable"}


class StatePlanError(ValueError):
    pass


def _object(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise StatePlanError(f"{path} must be an object")
    return value


def _array(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise StatePlanError(f"{path} must be an array")
    return value


def _string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise StatePlanError(f"{path} must be a non-empty string")
    return value.strip()


def _boolean(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        raise StatePlanError(f"{path} must be a boolean")
    return value


def _string_array(value: Any, path: str) -> list[str]:
    raw = _array(value, path)
    result = [_string(item, f"{path}[{index}]") for index, item in enumerate(raw)]
    if len(set(result)) != len(result):
        raise StatePlanError(f"{path} contains duplicates")
    return result


def _reachable(start: str, graph: dict[str, set[str]]) -> set[str]:
    seen: set[str] = set()
    queue: deque[str] = deque([start])
    while queue:
        state = queue.popleft()
        if state in seen:
            continue
        seen.add(state)
        queue.extend(graph.get(state, set()) - seen)
    return seen


def _can_reach_any(
    start: str,
    targets: set[str],
    graph: dict[str, set[str]],
) -> bool:
    return bool(_reachable(start, graph) & targets)


def validate_state_plan(plan: Any) -> dict[str, Any]:
    root = _object(plan, "plan")
    version = root.get("schema_version")
    if isinstance(version, bool) or not isinstance(version, int) or version != 1:
        raise StatePlanError("schema_version must be integer 1")

    primary_type = _string(root.get("primary_type"), "primary_type")
    if primary_type not in PRIMARY_TYPES:
        raise StatePlanError(
            f"primary_type must be one of {', '.join(sorted(PRIMARY_TYPES))}"
        )
    raw_secondary_type = root.get("secondary_type")
    if raw_secondary_type is None:
        secondary_type = None
    else:
        secondary_type = _string(raw_secondary_type, "secondary_type")
        if secondary_type not in PRIMARY_TYPES:
            raise StatePlanError(
                f"secondary_type must be one of {', '.join(sorted(PRIMARY_TYPES))}"
            )
        if secondary_type == primary_type:
            raise StatePlanError("secondary_type must differ from primary_type")

    stage = _string(root.get("stage"), "stage")
    if stage not in {"design", "predeploy"}:
        raise StatePlanError("stage must be 'design' or 'predeploy'")
    lifecycle = _string(root.get("lifecycle"), "lifecycle")
    if lifecycle not in {"single_run", "repeatable_round"}:
        raise StatePlanError(
            "lifecycle must be 'single_run' or 'repeatable_round'"
        )
    initial_state = _string(root.get("initial_state"), "initial_state")

    raw_features = _string_array(root.get("features", []), "features")
    unknown_features = sorted(set(raw_features) - FEATURES)
    if unknown_features:
        raise StatePlanError(f"unknown features: {', '.join(unknown_features)}")
    features = set(raw_features)
    if lifecycle == "repeatable_round" and "rounds" not in features:
        raise StatePlanError("repeatable_round lifecycle requires feature 'rounds'")

    states: dict[str, dict[str, Any]] = {}
    terminal_states: set[str] = set()
    reset_states: set[str] = set()
    for index, raw_state in enumerate(_array(root.get("states"), "states")):
        path = f"states[{index}]"
        state = _object(raw_state, path)
        name = _string(state.get("name"), f"{path}.name")
        if name in states:
            raise StatePlanError(f"duplicate state name: {name}")
        scope = _string(state.get("scope"), f"{path}.scope")
        if scope not in SCOPES:
            raise StatePlanError(
                f"{path}.scope must be one of {', '.join(sorted(SCOPES))}"
            )
        _string(state.get("owner"), f"{path}.owner")
        terminal = _boolean(state.get("terminal", False), f"{path}.terminal")
        reset = _boolean(state.get("reset", False), f"{path}.reset")
        if terminal and reset:
            raise StatePlanError(f"{path} cannot be both terminal and reset")
        states[name] = state
        if terminal:
            terminal_states.add(name)
        if reset:
            reset_states.add(name)

    if not states:
        raise StatePlanError("states must not be empty")
    if initial_state not in states:
        raise StatePlanError(f"initial_state {initial_state!r} is not declared")
    if not terminal_states:
        raise StatePlanError("at least one terminal state is required")
    if lifecycle == "repeatable_round" and not reset_states:
        raise StatePlanError("repeatable_round requires at least one reset state")

    variables: set[str] = set()
    for index, raw_variable in enumerate(
        _array(root.get("variables", []), "variables")
    ):
        path = f"variables[{index}]"
        variable = _object(raw_variable, path)
        name = _string(variable.get("name"), f"{path}.name")
        if name in variables:
            raise StatePlanError(f"duplicate variable name: {name}")
        variables.add(name)
        scope = _string(variable.get("scope"), f"{path}.scope")
        if scope not in SCOPES:
            raise StatePlanError(
                f"{path}.scope must be one of {', '.join(sorted(SCOPES))}"
            )
        _string(variable.get("owner"), f"{path}.owner")
        if "initial" not in variable:
            raise StatePlanError(f"{path}.initial is required")
        _string(variable.get("reset_policy"), f"{path}.reset_policy")

    graph: dict[str, set[str]] = defaultdict(set)
    transition_names: set[str] = set()
    transition_signatures: set[tuple[str, str, str]] = set()
    outgoing: defaultdict[str, int] = defaultdict(int)
    terminal_lock_count = 0

    transitions = _array(root.get("transitions"), "transitions")
    for index, raw_transition in enumerate(transitions):
        path = f"transitions[{index}]"
        transition = _object(raw_transition, path)
        name = _string(transition.get("name"), f"{path}.name")
        if name in transition_names:
            raise StatePlanError(f"duplicate transition name: {name}")
        transition_names.add(name)
        source = _string(transition.get("from"), f"{path}.from")
        target = _string(transition.get("to"), f"{path}.to")
        event = _string(transition.get("event"), f"{path}.event")
        guard = _string(transition.get("guard", "always"), f"{path}.guard")
        if source not in states or target not in states:
            raise StatePlanError(
                f"{path} references undeclared state {source!r} or {target!r}"
            )
        signature = (source, event, guard)
        if signature in transition_signatures:
            raise StatePlanError(
                f"duplicate transition signature from={source}, event={event}, guard={guard}"
            )
        transition_signatures.add(signature)

        idempotent = _boolean(
            transition.get("idempotent"), f"{path}.idempotent"
        )
        if not idempotent:
            _string(transition.get("repeat_policy"), f"{path}.repeat_policy")
        atomic_changes = _string_array(
            transition.get("atomic_changes"), f"{path}.atomic_changes"
        )
        if not atomic_changes:
            raise StatePlanError(f"{path}.atomic_changes must not be empty")
        _string_array(transition.get("feedback", []), f"{path}.feedback")
        cleanup = _string_array(transition.get("cleanup", []), f"{path}.cleanup")
        cancels_pending = _boolean(
            transition.get("cancels_pending", False),
            f"{path}.cancels_pending",
        )
        terminal_lock = _boolean(
            transition.get("terminal_lock", False),
            f"{path}.terminal_lock",
        )
        if target in terminal_states:
            if not terminal_lock:
                raise StatePlanError(
                    f"{path} enters terminal state {target} without terminal_lock=true"
                )
            terminal_lock_count += 1
        elif terminal_lock:
            raise StatePlanError(
                f"{path} sets terminal_lock but target {target} is not terminal"
            )
        if target in reset_states and (not cleanup or not cancels_pending):
            raise StatePlanError(
                f"{path} enters reset state but lacks cleanup or cancels_pending=true"
            )

        graph[source].add(target)
        outgoing[source] += 1

    if not transitions:
        raise StatePlanError("transitions must not be empty")

    reachable = _reachable(initial_state, graph)
    unreachable = sorted(set(states) - reachable)
    if unreachable:
        raise StatePlanError(f"unreachable states: {', '.join(unreachable)}")
    for state in sorted(set(states) - terminal_states):
        if outgoing[state] == 0:
            raise StatePlanError(f"non-terminal state {state} has no outgoing transition")
        if not _can_reach_any(state, terminal_states, graph):
            raise StatePlanError(f"state {state} cannot reach any terminal state")

    if lifecycle == "repeatable_round":
        for terminal in sorted(terminal_states):
            if not _can_reach_any(terminal, {initial_state}, graph):
                raise StatePlanError(
                    f"terminal state {terminal} cannot return to initial state {initial_state}"
                )
        for reset in sorted(reset_states):
            if not _can_reach_any(reset, {initial_state}, graph):
                raise StatePlanError(
                    f"reset state {reset} cannot return to initial state {initial_state}"
                )

    scenario_matrix = _object(root.get("scenario_matrix"), "scenario_matrix")
    required_scenarios = set(BASE_SCENARIOS) | TYPE_SCENARIOS[primary_type]
    if secondary_type is not None:
        required_scenarios.update(TYPE_SCENARIOS[secondary_type])
        required_scenarios.update(HYBRID_SCENARIOS)
    for feature in features:
        required_scenarios.update(FEATURE_SCENARIOS[feature])
    missing_scenarios = sorted(required_scenarios - set(scenario_matrix))
    if missing_scenarios:
        raise StatePlanError(
            f"scenario_matrix is missing: {', '.join(missing_scenarios)}"
        )

    status_counts: defaultdict[str, int] = defaultdict(int)
    for scenario, raw_entry in scenario_matrix.items():
        entry = _object(raw_entry, f"scenario_matrix.{scenario}")
        status = _string(entry.get("status"), f"scenario_matrix.{scenario}.status")
        if status not in SCENARIO_STATUSES:
            allowed = ", ".join(sorted(SCENARIO_STATUSES))
            raise StatePlanError(
                f"scenario_matrix.{scenario}.status must be one of {allowed}"
            )
        if status == "not_applicable":
            _string(entry.get("reason"), f"scenario_matrix.{scenario}.reason")
        if stage == "predeploy" and status == "planned":
            raise StatePlanError(
                f"predeploy plan still has planned-only scenario: {scenario}"
            )
        status_counts[status] += 1

    warnings: list[str] = []
    if not variables:
        warnings.append("no state variables declared; verify this is intentional")
    if stage == "design" and status_counts["planned"]:
        warnings.append(f"{status_counts['planned']} scenarios remain planned-only")
    if lifecycle == "single_run" and reset_states:
        warnings.append("single_run plan declares reset states; verify lifecycle choice")

    return {
        "schema_version": 1,
        "stage": stage,
        "lifecycle": lifecycle,
        "primary_type": primary_type,
        "secondary_type": secondary_type,
        "state_count": len(states),
        "transition_count": len(transitions),
        "variable_count": len(variables),
        "terminal_states": sorted(terminal_states),
        "reset_states": sorted(reset_states),
        "terminal_lock_transitions": terminal_lock_count,
        "required_scenario_count": len(required_scenarios),
        "scenario_statuses": dict(sorted(status_counts.items())),
        "warnings": warnings,
    }


def _example_plan() -> dict[str, Any]:
    scenarios = {
        name: {"status": "tested"}
        for name in BASE_SCENARIOS
        | TYPE_SCENARIOS["survival"]
        | FEATURE_SCENARIOS["rounds"]
        | FEATURE_SCENARIOS["timed_logic"]
    }
    return {
        "schema_version": 1,
        "primary_type": "survival",
        "secondary_type": None,
        "stage": "predeploy",
        "lifecycle": "repeatable_round",
        "initial_state": "PREPARE",
        "features": ["rounds", "timed_logic"],
        "states": [
            {
                "name": "PREPARE",
                "scope": "ROUND",
                "owner": "ROUND_CTRL",
                "terminal": False,
                "reset": False,
            },
            {
                "name": "LIVE",
                "scope": "ROUND",
                "owner": "ROUND_CTRL",
                "terminal": False,
                "reset": False,
            },
            {
                "name": "SETTLE",
                "scope": "ROUND",
                "owner": "ROUND_CTRL",
                "terminal": True,
                "reset": False,
            },
            {
                "name": "RESET",
                "scope": "ROUND",
                "owner": "ROUND_CTRL",
                "terminal": False,
                "reset": True,
            },
        ],
        "variables": [
            {
                "name": "ROUND_PHASE",
                "scope": "ROUND",
                "owner": "ROUND_CTRL",
                "initial": "PREPARE",
                "reset_policy": "set PREPARE",
            }
        ],
        "transitions": [
            {
                "name": "START",
                "from": "PREPARE",
                "to": "LIVE",
                "event": "players_ready",
                "guard": "ready",
                "idempotent": True,
                "atomic_changes": ["phase=LIVE"],
                "feedback": ["start cue"],
                "cleanup": [],
                "cancels_pending": False,
                "terminal_lock": False,
            },
            {
                "name": "FINISH",
                "from": "LIVE",
                "to": "SETTLE",
                "event": "win_condition",
                "guard": "not result_locked",
                "idempotent": True,
                "atomic_changes": ["lock result", "phase=SETTLE"],
                "feedback": ["result cue"],
                "cleanup": ["stop hazards"],
                "cancels_pending": True,
                "terminal_lock": True,
            },
            {
                "name": "BEGIN_RESET",
                "from": "SETTLE",
                "to": "RESET",
                "event": "settle_done",
                "guard": "always",
                "idempotent": True,
                "atomic_changes": ["phase=RESET"],
                "feedback": [],
                "cleanup": ["cancel timers", "remove old objects"],
                "cancels_pending": True,
                "terminal_lock": False,
            },
            {
                "name": "RESET_DONE",
                "from": "RESET",
                "to": "PREPARE",
                "event": "reset_complete",
                "guard": "clean",
                "idempotent": True,
                "atomic_changes": ["phase=PREPARE"],
                "feedback": [],
                "cleanup": ["clear reset lock"],
                "cancels_pending": True,
                "terminal_lock": False,
            },
        ],
        "scenario_matrix": scenarios,
    }


def _expect_invalid(plan: dict[str, Any], label: str) -> None:
    try:
        validate_state_plan(plan)
    except StatePlanError:
        return
    raise AssertionError(f"invalid plan was accepted: {label}")


def _self_test() -> None:
    from audit_design_plan import (
        PRIMARY_TYPES as DESIGN_PRIMARY_TYPES,
        TYPE_SCENARIOS as DESIGN_TYPE_SCENARIOS,
    )

    if PRIMARY_TYPES != DESIGN_PRIMARY_TYPES:
        raise AssertionError("state/design primary type catalogs diverged")
    if TYPE_SCENARIOS != DESIGN_TYPE_SCENARIOS:
        raise AssertionError("state/design type scenario catalogs diverged")

    valid = _example_plan()
    result = validate_state_plan(valid)
    if result["state_count"] != 4 or result["transition_count"] != 4:
        raise AssertionError("valid plan summary mismatch")

    invalid = json.loads(json.dumps(valid))
    del invalid["primary_type"]
    _expect_invalid(invalid, "missing primary type")

    invalid = json.loads(json.dumps(valid))
    invalid["secondary_type"] = invalid["primary_type"]
    _expect_invalid(invalid, "secondary type duplicates primary type")

    invalid = json.loads(json.dumps(valid))
    invalid["transitions"][1]["terminal_lock"] = False
    _expect_invalid(invalid, "terminal transition without lock")

    invalid = json.loads(json.dumps(valid))
    invalid["states"].append(
        {
            "name": "ORPHAN",
            "scope": "ROUND",
            "owner": "ROUND_CTRL",
            "terminal": False,
            "reset": False,
        }
    )
    _expect_invalid(invalid, "unreachable state")

    invalid = json.loads(json.dumps(valid))
    invalid["transitions"] = invalid["transitions"][:-1]
    _expect_invalid(invalid, "broken reset path")

    invalid = json.loads(json.dumps(valid))
    invalid["scenario_matrix"]["first_load"]["status"] = "planned"
    _expect_invalid(invalid, "planned-only predeploy scenario")

    for primary_type in sorted(PRIMARY_TYPES):
        typed = json.loads(json.dumps(valid))
        typed["primary_type"] = primary_type
        for scenario in TYPE_SCENARIOS[primary_type]:
            typed["scenario_matrix"][scenario] = {"status": "tested"}
        typed_result = validate_state_plan(typed)
        if typed_result["primary_type"] != primary_type:
            raise AssertionError(f"primary type summary mismatch: {primary_type}")

    sports = json.loads(json.dumps(valid))
    sports["primary_type"] = "sports_match"
    for scenario in TYPE_SCENARIOS["sports_match"]:
        sports["scenario_matrix"][scenario] = {"status": "tested"}
    del sports["scenario_matrix"]["out_of_bounds"]
    _expect_invalid(sports, "missing sports dead-ball scenario")

    hybrid = json.loads(json.dumps(valid))
    hybrid["secondary_type"] = "score_contest"
    for scenario in TYPE_SCENARIOS["score_contest"] | HYBRID_SCENARIOS:
        hybrid["scenario_matrix"][scenario] = {"status": "tested"}
    hybrid_result = validate_state_plan(hybrid)
    if hybrid_result["secondary_type"] != "score_contest":
        raise AssertionError("secondary type summary mismatch")

    invalid = json.loads(json.dumps(hybrid))
    del invalid["scenario_matrix"]["hybrid_state_handoff"]
    _expect_invalid(invalid, "missing hybrid handoff scenario")

    economy = json.loads(json.dumps(valid))
    economy["features"].extend(["economy", "managed_actors", "persistent_world"])
    for feature in ("economy", "managed_actors", "persistent_world"):
        for scenario in FEATURE_SCENARIOS[feature]:
            economy["scenario_matrix"][scenario] = {"status": "tested"}
    economy_result = validate_state_plan(economy)
    if economy_result["required_scenario_count"] <= result["required_scenario_count"]:
        raise AssertionError("management feature scenarios were not added")

    invalid = json.loads(json.dumps(economy))
    del invalid["scenario_matrix"]["catalog_terminal_mismatch"]
    _expect_invalid(invalid, "missing economy terminal scenario")

    invalid = json.loads(json.dumps(economy))
    del invalid["scenario_matrix"]["reload_rebuild"]
    _expect_invalid(invalid, "missing persistent-world reload scenario")

    destructible = json.loads(json.dumps(valid))
    destructible["features"].append("destructibles")
    for scenario in FEATURE_SCENARIOS["destructibles"]:
        destructible["scenario_matrix"][scenario] = {"status": "tested"}
    destructible_result = validate_state_plan(destructible)
    if (
        destructible_result["required_scenario_count"]
        <= result["required_scenario_count"]
    ):
        raise AssertionError("destructible feature scenarios were not added")

    invalid = json.loads(json.dumps(destructible))
    del invalid["scenario_matrix"]["duplicate_destruction_reward"]
    _expect_invalid(invalid, "missing destructible reward scenario")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit an Eggy map state-plan JSON for graph and reset invariants."
    )
    parser.add_argument("plan", nargs="?", type=Path, help="state-plan JSON")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--example", action="store_true", help="print a valid example")
    parser.add_argument("--json", action="store_true", help="emit summary as JSON")
    args = parser.parse_args()

    if args.self_test:
        _self_test()
        print("self-test passed")
        return 0
    if args.example:
        print(json.dumps(_example_plan(), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.plan is None:
        parser.error("plan is required unless --self-test or --example is used")

    try:
        plan = json.loads(args.plan.read_text(encoding="utf-8"))
        summary = validate_state_plan(plan)
    except (OSError, json.JSONDecodeError, StatePlanError) as exc:
        print(f"invalid state plan: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(
            "state plan valid: "
            f"type={summary['primary_type']}, "
            f"states={summary['state_count']}, "
            f"transitions={summary['transition_count']}, "
            f"variables={summary['variable_count']}, "
            f"scenarios={summary['required_scenario_count']}"
        )
        for warning in summary["warnings"]:
            print(f"warning: {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

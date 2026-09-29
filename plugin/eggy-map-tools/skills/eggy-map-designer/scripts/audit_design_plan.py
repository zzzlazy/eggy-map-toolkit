#!/usr/bin/env python3
"""Audit cross-layer completeness of an Eggy map design plan."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict, deque
import json
from pathlib import Path
import sys
from typing import Any


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
TOPOLOGIES = {
    "linear_chain",
    "branch_and_rejoin",
    "loop_track",
    "hub_and_spoke",
    "arena",
    "open_network",
    "vertical_layers",
}
EDGE_KINDS = {"critical", "optional", "recovery", "return", "handoff"}
BEAT_OWNERS = {"primary", "secondary", "handoff", "shared"}
LAYERS = {"COL", "MASS", "MID", "ROUTE", "MECH", "PROP", "FX", "LOGIC", "SAFE"}
MATURITIES = {"concept", "graybox", "final"}
STAGES = {"design", "predeploy"}
DENSITY_PROFILE_MINIMUMS = {
    "micro_space": 300,
    "themed_short": 800,
    "multi_scene": 2000,
    "long_world": 5000,
}
LOW_COUNT_MODES = {"micro_space", "deliberate_minimalism", "large_asset_led"}
EVIDENCE_STATUSES = {"verified", "partial", "provisional"}
REFERENCE_COVERAGE_STATUSES = {
    "verified_positive",
    "partial_positive",
    "boundary_only",
}
REFERENCE_AXES = {
    "primary_loop",
    "secondary_loop",
    "hybrid_relation",
    "modifier",
    "world_grammar",
    "spatial_scale",
    "assembly",
    "performance",
    "failure_boundary",
}
BASE_REFERENCE_AXES = {"primary_loop", "world_grammar", "spatial_scale"}
CHECK_STATUSES = {"planned", "tested", "not_applicable"}
AUDIT_STATUSES = {"planned", "passed", "not_applicable"}
HYBRID_MODES = {"overlay", "local_station", "optional_branch", "phase_shift"}
RECOMMENDED_HYBRID_MODES = {
    ("short_race", "mechanism_puzzle"): "local_station",
    ("short_race", "narrative_exploration"): "overlay",
    ("chapter_challenge", "narrative_exploration"): "overlay",
    ("mechanism_puzzle", "cooperative"): "overlay",
    ("survival", "score_contest"): "overlay",
    ("score_contest", "short_race"): "overlay",
    ("social_showcase", "short_race"): "optional_branch",
    ("management_simulation", "cooperative"): "overlay",
    ("management_simulation", "survival"): "phase_shift",
    ("narrative_exploration", "mechanism_puzzle"): "local_station",
    ("defense_strategy", "management_simulation"): "phase_shift",
    ("defense_strategy", "cooperative"): "overlay",
    ("combat_boss", "cooperative"): "overlay",
    ("combat_boss", "narrative_exploration"): "local_station",
    ("stealth_infiltration", "cooperative"): "overlay",
    ("rhythm_performance", "social_showcase"): "optional_branch",
    ("turn_based_strategy", "narrative_exploration"): "phase_shift",
    ("sports_match", "social_showcase"): "optional_branch",
    ("sandbox_creation", "social_showcase"): "optional_branch",
    ("sandbox_creation", "management_simulation"): "overlay",
    ("social_deduction", "narrative_exploration"): "local_station",
}
WORLD_SHELL_VIEW_KINDS = {
    "spawn",
    "entry",
    "action",
    "reveal",
    "recovery",
    "return",
    "terminal",
}
MODIFIERS = {
    "rising_pressure",
    "escort_collection",
    "vehicles",
    "asymmetric_roles",
    "rhythm",
    "horror",
    "vertical_climb",
    "random_variation",
    "cumulative_growth",
    "destructible_world",
}
MODIFIER_SCENARIOS = {
    "rising_pressure": {
        "pressure_idle_start",
        "slow_path_margin",
        "checkpoint_pressure_collision",
        "pressure_terminal_conflict",
        "pressure_second_entry",
    },
    "escort_collection": {
        "object_out_of_bounds",
        "carrier_death_or_exit",
        "duplicate_delivery",
        "checkpoint_with_object",
        "missing_required_object",
    },
    "vehicles": {
        "mount_dismount_interrupt",
        "low_mid_high_speed",
        "tightest_turn",
        "multiplayer_vehicle_collision",
        "vehicle_respawn",
        "vehicle_second_entry",
    },
    "asymmetric_roles": {
        "missing_role",
        "late_join_role",
        "simultaneous_terminal",
        "information_leak",
        "role_swap_or_second_round",
    },
    "rhythm": {
        "muted_audio",
        "latency_extremes",
        "simultaneous_rhythm_input",
        "pause_or_reentry",
        "rhythm_sequence_reset",
    },
    "horror": {
        "sensory_fallback",
        "post_reveal_reorientation",
        "threat_reentry",
        "safe_space_integrity",
        "horror_interrupt",
    },
    "vertical_climb": {
        "maximum_fall",
        "overhead_camera",
        "shortcut_bypass",
        "vertical_checkpoint_death",
        "vertical_multiplayer_congestion",
    },
    "random_variation": {
        "minimum_extreme",
        "maximum_extreme",
        "incompatible_combination",
        "repeated_seed",
        "random_multiplayer_consistency",
        "second_generation_cleanup",
    },
    "cumulative_growth": {
        "growth_input_dedup",
        "growth_checkpoint_death",
        "growth_cap",
        "growth_second_entry",
    },
    "destructible_world": {
        "duplicate_damage_same_input",
        "duplicate_destruction_reward",
        "dependent_surface_during_contact",
        "partial_destruction_checkpoint",
        "destruction_terminal_conflict",
        "destruction_second_entry",
    },
}
MODIFIER_SPECIFIC_FIELDS = {
    "rising_pressure": {
        "authority",
        "start_gate",
        "pressure_reference",
        "pace_samples",
        "checkpoint_relation",
        "contact_or_timeout",
        "terminal_priority",
        "cleanup",
    },
    "escort_collection": {
        "object_identity",
        "object_states",
        "ownership",
        "visible_progress",
        "legal_area",
        "delivery_commit",
        "duplicate_prevention",
        "lost_object_recovery",
        "checkpoint_snapshot",
        "terminal_cleanup",
    },
    "vehicles": {
        "vehicle_envelope",
        "mount_dismount",
        "calibration_profiles",
        "camera_envelope",
        "route_rules",
        "collision_and_traffic",
        "respawn_or_replacement",
        "terminal_cleanup",
    },
    "asymmetric_roles": {
        "roles",
        "assignment",
        "information_boundary",
        "contact_or_scoring",
        "role_fill",
        "terminal_and_draw",
        "round_reset",
    },
    "rhythm": {
        "authoritative_clock",
        "cue_lead",
        "audio_visual_sync",
        "judgement_windows",
        "input_deduplication",
        "miss_and_combo",
        "latency_calibration",
        "mute_fallback",
        "sequence_reset",
    },
    "horror": {
        "readability_floor",
        "tension_beats",
        "threat_contract",
        "safe_space",
        "reveal_cooldown",
        "control_and_camera",
        "sensory_fallback",
        "recovery",
        "session_cleanup",
    },
    "vertical_climb": {
        "layers",
        "upward_target",
        "fall_graph",
        "head_clearance",
        "camera_envelope",
        "shortcut_guard",
        "recovery",
        "terminal_cleanup",
    },
    "random_variation": {
        "authority_and_seed",
        "candidate_pool",
        "solvability_filter",
        "compatibility_matrix",
        "telegraph",
        "fairness",
        "generation_id",
        "fallback",
        "cleanup",
    },
    "cumulative_growth": {
        "input_event",
        "deduplication",
        "authoritative_value",
        "clamp_or_cap",
        "feedback_tiers",
        "checkpoint_policy",
        "spatial_calibration_levels",
        "terminal_cleanup",
    },
    "destructible_world": {
        "authority",
        "target_identity",
        "target_states",
        "valid_damage_sources",
        "hit_deduplication",
        "damage_or_progress_rule",
        "destruction_commit",
        "dependency_groups",
        "collision_transition",
        "debris_budget",
        "checkpoint_policy",
        "terminal_priority",
        "cleanup",
    },
}

BASE_METRICS = {
    "first_goal_understanding",
    "first_screen_priority",
    "failure_recovery",
    "completion_or_exit",
}
TYPE_METRICS = {
    "short_race": {"first_move_time", "completion_time", "reset_loss", "congestion"},
    "chapter_challenge": {"chapter_time", "replay_loss", "chapter_recognition", "quit_point"},
    "mechanism_puzzle": {
        "room_entry_clarity",
        "rule_recall",
        "error_attribution",
        "hint_dependency",
        "local_reset_time",
        "reset_success",
        "stuck_time",
    },
    "cooperative": {"active_share", "max_wait", "handoff_failure", "missing_partner"},
    "narrative_exploration": {
        "lost_point",
        "missed_event",
        "control_loss",
        "choice_consequence",
        "reorientation",
        "return_change",
    },
    "survival": {
        "spawn_safety_window",
        "danger_attribution",
        "phase_readability",
        "safe_corner",
        "terminal_length",
        "reset_residue",
    },
    "score_contest": {"spawn_to_value_time", "leader_share", "comeback_window", "tie_reset"},
    "social_showcase": {"first_activity", "landmark_reach", "return_time", "occupancy"},
    "management_simulation": {
        "first_output",
        "bottleneck",
        "idle_wait",
        "resource_consistency",
        "catalog_progress_clarity",
        "terminal_state_match",
    },
    "rhythm_performance": {
        "timing_error_distribution",
        "visual_only_success",
        "input_deduplication_rate",
        "combo_break_attribution",
        "sequence_restart_residue",
    },
    "combat_boss": {
        "telegraph_to_impact_time",
        "damage_attribution",
        "arena_dead_time",
        "phase_duration",
        "team_contribution_gap",
        "wipe_recovery_time",
    },
    "defense_strategy": {
        "first_defense_decision",
        "lane_pressure_gap",
        "resource_idle_time",
        "defense_contribution",
        "leak_attribution",
        "wave_reset_residue",
    },
    "stealth_infiltration": {
        "detection_attribution",
        "hidden_time",
        "safe_route_dominance",
        "alert_recovery_time",
        "exfiltration_clarity",
    },
    "turn_based_strategy": {
        "invalid_action_rate",
        "decision_time",
        "board_state_readability",
        "turn_wait_time",
        "outcome_explainability",
    },
    "sports_match": {
        "spawn_to_object_time",
        "possession_share",
        "score_attribution",
        "dead_ball_time",
        "role_contribution_gap",
        "overtime_length",
    },
    "sandbox_creation": {
        "first_creation_time",
        "edit_iteration_time",
        "invalid_placement_rate",
        "budget_readability",
        "undo_success",
        "collaborator_conflict_rate",
    },
    "social_deduction": {
        "role_comprehension",
        "task_or_evidence_progress",
        "meeting_dead_time",
        "vote_attribution",
        "information_leak_rate",
        "outcome_explainability",
    },
}
BASE_SCENARIOS = {
    "first_time_player",
    "normal_complete_or_exit",
    "failure_recovery",
    "target_player_count",
}
TYPE_SCENARIOS = {
    "short_race": {"fast_player", "slow_player", "checkpoint_skip"},
    "chapter_challenge": {"late_chapter_reentry", "repeated_failure", "long_session"},
    "mechanism_puzzle": {
        "wrong_input",
        "out_of_order",
        "hint_timeout",
        "room_reentry",
        "checkpoint_recovery",
        "repeat_reset",
    },
    "cooperative": {"missing_partner", "simultaneous_failure", "handoff_out_of_order"},
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
    "social_showcase": {"full_occupancy", "walk_away_return", "interaction_abandon"},
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
HYBRID_METRICS = {
    "secondary_forced_time",
    "maximum_primary_pause",
    "handoff_recovery_time",
    "hybrid_residue_count",
}
HYBRID_SCENARIOS = {
    "hybrid_duplicate_entry",
    "hybrid_abandon_or_timeout",
    "hybrid_simultaneous_failure",
    "hybrid_fallback",
    "hybrid_second_entry",
}
TYPE_FIELDS = {
    "short_race": {
        "goal",
        "finish_rule",
        "flow_line",
        "overtake_or_parallel",
        "checkpoint_and_reset",
    },
    "chapter_challenge": {
        "goal",
        "chapters",
        "checkpoint_policy",
        "difficulty_wave",
        "quit_or_reentry",
    },
    "mechanism_puzzle": {
        "goal",
        "structure_mode",
        "shared_interface",
        "puzzle_units",
        "teaching_sequence",
        "hint_policy",
        "error_feedback",
        "checkpoint_policy",
        "reset",
    },
    "cooperative": {
        "goal",
        "roles",
        "handoffs",
        "missing_player_branch",
        "regroup_and_respawn",
    },
    "narrative_exploration": {
        "goal",
        "landmarks",
        "events",
        "story_state_authority",
        "control_return",
        "navigation_without_text",
        "revisit_and_reload",
        "ending_or_exit",
    },
    "survival": {
        "goal",
        "start_and_idle_contract",
        "danger_teaching",
        "phase_schedule",
        "escalation",
        "safe_space_change",
        "randomness_safety",
        "elimination_and_spectating",
        "terminal_and_draw",
        "round_reset",
    },
    "score_contest": {
        "goal",
        "scoring_cycle",
        "ownership_and_deduplication",
        "hotspot_migration",
        "fairness",
        "anti_snowball",
        "tie_and_timeout",
        "round_reset",
    },
    "social_showcase": {
        "goal",
        "landmarks",
        "activities",
        "return_loop",
        "occupancy_release",
        "idle_quality",
        "session_cleanup",
    },
    "management_simulation": {
        "goal",
        "resource_flow",
        "product_lifecycle",
        "ownership",
        "capacity",
        "automation_and_demand",
        "upgrade_choice",
        "visible_world_change",
        "progression_and_terminal",
        "persistence",
        "recovery_and_reset",
    },
    "rhythm_performance": {
        "goal",
        "sequence_authority",
        "cue_channels",
        "judgement_windows",
        "input_deduplication",
        "scoring_and_combo",
        "difficulty_curve",
        "latency_and_accessibility",
        "terminal_and_reset",
    },
    "combat_boss": {
        "goal",
        "boss_phases",
        "damage_authority",
        "player_tools",
        "arena_and_safe_recovery",
        "phase_escalation",
        "multiplayer_scaling",
        "defeat_wipe_and_draw",
        "terminal_and_reset",
    },
    "defense_strategy": {
        "goal",
        "defended_object",
        "lanes",
        "waves",
        "build_or_choice_slots",
        "resource_cycle",
        "target_and_path_authority",
        "leak_and_failure",
        "multiplayer_ownership",
        "terminal_and_reset",
    },
    "stealth_infiltration": {
        "goal",
        "detection_states",
        "sensors",
        "readable_cover",
        "player_tools_and_costs",
        "suspicion_feedback",
        "objective_and_exfiltration",
        "alert_recovery",
        "multiplayer_information",
        "terminal_and_reset",
    },
    "turn_based_strategy": {
        "goal",
        "turn_authority",
        "phases",
        "legal_actions",
        "board_state_feedback",
        "resource_and_ownership",
        "hidden_information",
        "resolution_order",
        "timeout_and_disconnect",
        "terminal_draw_and_reset",
    },
    "sports_match": {
        "goal",
        "teams",
        "play_object_states",
        "field_zones",
        "possession_and_contact",
        "out_of_bounds_restart",
        "scoring_commit",
        "spawn_and_kickoff",
        "illegal_play",
        "tie_overtime_and_reset",
    },
    "sandbox_creation": {
        "goal",
        "creation_loop",
        "catalog_categories",
        "build_states",
        "placement_validation",
        "ownership_and_permissions",
        "budget_limits",
        "undo_delete",
        "save_and_reload",
        "showcase_or_test",
        "exit_and_cleanup",
    },
    "social_deduction": {
        "goal",
        "round_authority",
        "role_set",
        "assignment_and_secrecy",
        "phase_cycle",
        "tasks_or_evidence",
        "meeting_and_reporting",
        "voting_commit",
        "elimination_and_afterlife",
        "win_predicates",
        "disconnect_and_fill",
        "terminal_and_reset",
    },
}
COMPLEX_STATE_TYPES = {
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


class DesignPlanError(ValueError):
    pass


def _object(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DesignPlanError(f"{path} must be an object")
    return value


def _array(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise DesignPlanError(f"{path} must be an array")
    return value


def _string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DesignPlanError(f"{path} must be a non-empty string")
    return value.strip()


def _integer(value: Any, path: str, *, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise DesignPlanError(f"{path} must be an integer")
    if minimum is not None and value < minimum:
        raise DesignPlanError(f"{path} must be >= {minimum}")
    return value


def _number(value: Any, path: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DesignPlanError(f"{path} must be a number")
    result = float(value)
    if minimum is not None and result < minimum:
        raise DesignPlanError(f"{path} must be >= {minimum}")
    return result


def _boolean(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        raise DesignPlanError(f"{path} must be a boolean")
    return value


def _string_array(value: Any, path: str, *, minimum: int = 0) -> list[str]:
    raw = _array(value, path)
    result = [_string(item, f"{path}[{index}]") for index, item in enumerate(raw)]
    if len(result) < minimum:
        raise DesignPlanError(f"{path} must contain at least {minimum} items")
    if len(set(result)) != len(result):
        raise DesignPlanError(f"{path} contains duplicates")
    return result


def _nonempty(value: Any, path: str) -> Any:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    if isinstance(value, str):
        return _string(value, path)
    if isinstance(value, list):
        if not value:
            raise DesignPlanError(f"{path} cannot be empty")
        return value
    if isinstance(value, dict):
        if not value:
            raise DesignPlanError(f"{path} cannot be empty")
        return value
    raise DesignPlanError(f"{path} must be a non-empty string, array, or object")


def _require_fields(value: dict[str, Any], fields: set[str], path: str) -> None:
    missing = sorted(fields - set(value))
    if missing:
        raise DesignPlanError(f"{path} is missing fields: {', '.join(missing)}")
    for field in sorted(fields):
        _nonempty(value[field], f"{path}.{field}")


def _require_keys(value: dict[str, Any], fields: set[str], path: str) -> None:
    missing = sorted(fields - set(value))
    if missing:
        raise DesignPlanError(f"{path} is missing fields: {', '.join(missing)}")


def _reachable(start: str, graph: dict[str, set[str]]) -> set[str]:
    seen: set[str] = set()
    queue: deque[str] = deque([start])
    while queue:
        node = queue.popleft()
        if node in seen:
            continue
        seen.add(node)
        queue.extend(graph.get(node, set()) - seen)
    return seen


def _can_reach_any(start: str, targets: set[str], graph: dict[str, set[str]]) -> bool:
    return bool(_reachable(start, graph) & targets)


def _validate_experience(root: dict[str, Any]) -> tuple[int, int, float, float]:
    experience = _object(root.get("experience"), "experience")
    _require_fields(
        experience,
        {
            "audience",
            "player_range",
            "target_duration_seconds",
            "main_verbs",
            "memory_image",
            "success",
            "failure_recovery",
            "emotion",
            "theme_promise",
        },
        "experience",
    )
    players = _array(experience["player_range"], "experience.player_range")
    if len(players) != 2:
        raise DesignPlanError("experience.player_range must be [minimum, maximum]")
    player_min = _integer(players[0], "experience.player_range[0]", minimum=1)
    player_max = _integer(players[1], "experience.player_range[1]", minimum=player_min)
    duration = _array(
        experience["target_duration_seconds"],
        "experience.target_duration_seconds",
    )
    if len(duration) != 2:
        raise DesignPlanError(
            "experience.target_duration_seconds must be [minimum, maximum]"
        )
    duration_min = _number(duration[0], "experience.target_duration_seconds[0]", minimum=0)
    duration_max = _number(
        duration[1], "experience.target_duration_seconds[1]", minimum=duration_min
    )
    verbs = _string_array(experience["main_verbs"], "experience.main_verbs", minimum=1)
    if len(verbs) > 3:
        raise DesignPlanError("experience.main_verbs must contain 1 to 3 verbs")
    return player_min, player_max, duration_min, duration_max


def _validate_topology(root: dict[str, Any]) -> dict[str, Any]:
    topology = _object(root.get("topology"), "topology")
    kind = _string(topology.get("kind"), "topology.kind")
    if kind not in TOPOLOGIES:
        raise DesignPlanError(f"topology.kind must be one of {', '.join(sorted(TOPOLOGIES))}")
    entry = _string(topology.get("entry"), "topology.entry")
    terminals = set(_string_array(topology.get("terminals"), "topology.terminals", minimum=1))
    recovery_nodes = set(
        _string_array(
            topology.get("recovery_nodes", []),
            "topology.recovery_nodes",
            minimum=1,
        )
    )
    nodes: dict[str, str] = {}
    for index, raw_node in enumerate(_array(topology.get("nodes"), "topology.nodes")):
        path = f"topology.nodes[{index}]"
        node = _object(raw_node, path)
        name = _string(node.get("name"), f"{path}.name")
        role = _string(node.get("role"), f"{path}.role")
        if name in nodes:
            raise DesignPlanError(f"duplicate topology node {name}")
        nodes[name] = role
    if len(nodes) < 2:
        raise DesignPlanError("topology.nodes must contain at least 2 nodes")
    unknown_special = ({entry} | terminals | recovery_nodes) - set(nodes)
    if unknown_special:
        raise DesignPlanError(
            f"topology entry/terminal/recovery references unknown nodes: {', '.join(sorted(unknown_special))}"
        )
    graph: dict[str, set[str]] = defaultdict(set)
    signatures: set[tuple[str, str, str]] = set()
    for index, raw_edge in enumerate(_array(topology.get("edges"), "topology.edges")):
        path = f"topology.edges[{index}]"
        edge = _object(raw_edge, path)
        source = _string(edge.get("from"), f"{path}.from")
        target = _string(edge.get("to"), f"{path}.to")
        kind_value = _string(edge.get("kind"), f"{path}.kind")
        if kind_value not in EDGE_KINDS:
            raise DesignPlanError(f"{path}.kind must be one of {', '.join(sorted(EDGE_KINDS))}")
        if source not in nodes or target not in nodes:
            raise DesignPlanError(f"{path} references unknown topology nodes")
        signature = (source, target, kind_value)
        if signature in signatures:
            raise DesignPlanError(f"duplicate topology edge {signature}")
        signatures.add(signature)
        graph[source].add(target)
    if not signatures:
        raise DesignPlanError("topology.edges cannot be empty")
    reachable = _reachable(entry, graph)
    missing = sorted(set(nodes) - reachable)
    if missing:
        raise DesignPlanError(f"topology has unreachable nodes: {', '.join(missing)}")
    for node in sorted(set(nodes) - terminals):
        if not _can_reach_any(node, terminals, graph):
            raise DesignPlanError(f"topology node {node} cannot reach a terminal/exit")
    return {
        "kind": kind,
        "node_count": len(nodes),
        "edge_count": len(signatures),
        "terminal_count": len(terminals),
        "recovery_count": len(recovery_nodes),
    }


def _validate_beats(
    root: dict[str, Any], maturity: str, has_secondary: bool
) -> tuple[int, float, Counter[str], dict[str, str], dict[str, float]]:
    beats = _array(root.get("beats"), "beats")
    required_count = 4 if maturity in {"graybox", "final"} else 3
    if len(beats) < required_count:
        raise DesignPlanError(f"beats must contain at least {required_count} entries")
    names: set[str] = set()
    owners: Counter[str] = Counter()
    owner_by_name: dict[str, str] = {}
    seconds_by_name: dict[str, float] = {}
    total_seconds = 0.0
    for index, raw_beat in enumerate(beats):
        path = f"beats[{index}]"
        beat = _object(raw_beat, path)
        _require_fields(
            beat,
            {"name", "owner", "information", "action", "consequence", "feedback"},
            path,
        )
        name = _string(beat["name"], f"{path}.name")
        if name in names:
            raise DesignPlanError(f"duplicate beat name {name}")
        names.add(name)
        owner = _string(beat["owner"], f"{path}.owner")
        if owner not in BEAT_OWNERS:
            raise DesignPlanError(f"{path}.owner must be one of {', '.join(sorted(BEAT_OWNERS))}")
        if not has_secondary and owner in {"secondary", "handoff"}:
            raise DesignPlanError(f"{path}.owner={owner} requires secondary_type")
        owners[owner] += 1
        owner_by_name[name] = owner
        if "target_seconds" in beat:
            target_seconds = _number(
                beat["target_seconds"], f"{path}.target_seconds", minimum=0
            )
            total_seconds += target_seconds
            seconds_by_name[name] = target_seconds
        elif maturity != "concept":
            raise DesignPlanError(f"{path}.target_seconds is required after concept")
        else:
            seconds_by_name[name] = 0.0
    if owners["primary"] + owners["shared"] == 0:
        raise DesignPlanError("beats must contain a primary/shared beat")
    if has_secondary and owners["secondary"] + owners["handoff"] == 0:
        raise DesignPlanError("secondary_type requires a secondary/handoff beat")
    return len(beats), total_seconds, owners, owner_by_name, seconds_by_name


def _validate_world_shells(
    root: dict[str, Any],
    theme: dict[str, Any],
    theme_families: set[str],
) -> dict[str, int]:
    path = "theme.world_shells"
    shells = _array(theme["world_shells"], path)
    if not shells:
        raise DesignPlanError(f"{path} cannot be empty")

    topology = _object(root.get("topology"), "topology")
    topology_nodes = {
        _string(_object(item, f"topology.nodes[{index}]").get("name"), f"topology.nodes[{index}].name")
        for index, item in enumerate(_array(topology.get("nodes"), "topology.nodes"))
    }
    topology_entry = _string(topology.get("entry"), "topology.entry")
    topology_terminals = set(
        _string_array(topology.get("terminals"), "topology.terminals", minimum=1)
    )
    beat_names = {
        _string(_object(item, f"beats[{index}]").get("name"), f"beats[{index}].name")
        for index, item in enumerate(_array(root.get("beats"), "beats"))
    }

    shell_names: set[str] = set()
    covered_nodes: set[str] = set()
    beat_owner: dict[str, str] = {}
    view_names: set[str] = set()
    view_count = 0
    scale_anchor_count = 0
    assembly_zones: set[str] = set()

    for index, raw_shell in enumerate(shells):
        shell_path = f"{path}[{index}]"
        shell = _object(raw_shell, shell_path)
        _require_fields(
            shell,
            {
                "name",
                "topology_nodes",
                "beats",
                "assembly_zones",
                "silhouette",
                "enclosure_strategy",
                "depth_layers",
                "scale_anchors",
                "assembly_families",
                "state_variants",
                "transition_in",
                "transition_out",
                "review_views",
            },
            shell_path,
        )
        name = _string(shell["name"], f"{shell_path}.name")
        if name in shell_names:
            raise DesignPlanError(f"duplicate world shell name {name}")
        shell_names.add(name)

        nodes = _string_array(
            shell["topology_nodes"], f"{shell_path}.topology_nodes", minimum=1
        )
        unknown_nodes = sorted(set(nodes) - topology_nodes)
        if unknown_nodes:
            raise DesignPlanError(
                f"{shell_path}.topology_nodes references unknown nodes: "
                + ", ".join(unknown_nodes)
            )
        covered_nodes.update(nodes)

        shell_beats = _string_array(shell["beats"], f"{shell_path}.beats", minimum=1)
        unknown_beats = sorted(set(shell_beats) - beat_names)
        if unknown_beats:
            raise DesignPlanError(
                f"{shell_path}.beats references unknown beats: "
                + ", ".join(unknown_beats)
            )
        for beat in shell_beats:
            previous = beat_owner.get(beat)
            if previous is not None:
                raise DesignPlanError(
                    f"beat {beat} is assigned to multiple world shells: {previous}, {name}"
                )
            beat_owner[beat] = name

        shell_zones = _string_array(
            shell["assembly_zones"], f"{shell_path}.assembly_zones", minimum=1
        )
        assembly_zones.update(shell_zones)

        depth_layers = _object(shell["depth_layers"], f"{shell_path}.depth_layers")
        _require_fields(
            depth_layers,
            {"foreground", "midground", "background"},
            f"{shell_path}.depth_layers",
        )

        scale_anchors = _string_array(
            shell["scale_anchors"], f"{shell_path}.scale_anchors", minimum=2
        )
        scale_anchor_count += len(scale_anchors)
        shell_families = _string_array(
            shell["assembly_families"],
            f"{shell_path}.assembly_families",
            minimum=2,
        )
        unknown_families = sorted(set(shell_families) - theme_families)
        if unknown_families:
            raise DesignPlanError(
                f"{shell_path}.assembly_families must come from theme.assembly_families; unknown: "
                + ", ".join(unknown_families)
            )
        _string_array(
            shell["state_variants"], f"{shell_path}.state_variants", minimum=2
        )

        raw_views = _array(shell["review_views"], f"{shell_path}.review_views")
        if len(raw_views) < 2:
            raise DesignPlanError(
                f"{shell_path}.review_views must contain at least 2 items"
            )
        shell_view_kinds: set[str] = set()
        for view_index, raw_view in enumerate(raw_views):
            view_path = f"{shell_path}.review_views[{view_index}]"
            view = _object(raw_view, view_path)
            _require_fields(
                view,
                {"name", "kind", "camera_intent", "must_show"},
                view_path,
            )
            view_name = _string(view["name"], f"{view_path}.name")
            if view_name in view_names:
                raise DesignPlanError(f"duplicate world-shell review view name {view_name}")
            view_names.add(view_name)
            kind = _string(view["kind"], f"{view_path}.kind")
            if kind not in WORLD_SHELL_VIEW_KINDS:
                raise DesignPlanError(
                    f"{view_path}.kind must be one of "
                    + ", ".join(sorted(WORLD_SHELL_VIEW_KINDS))
                )
            shell_view_kinds.add(kind)
            _string_array(view["must_show"], f"{view_path}.must_show", minimum=3)
            view_count += 1

        if topology_entry in nodes and not shell_view_kinds & {"spawn", "entry"}:
            raise DesignPlanError(
                f"world shell {name} covers topology entry but has no spawn/entry review view"
            )
        covered_terminals = topology_terminals & set(nodes)
        if covered_terminals and "terminal" not in shell_view_kinds:
            raise DesignPlanError(
                f"world shell {name} covers terminal nodes but has no terminal review view"
            )

    missing_nodes = sorted(topology_nodes - covered_nodes)
    if missing_nodes:
        raise DesignPlanError(
            f"theme.world_shells does not cover topology nodes: {', '.join(missing_nodes)}"
        )
    missing_beats = sorted(beat_names - set(beat_owner))
    if missing_beats:
        raise DesignPlanError(
            f"theme.world_shells does not cover beats: {', '.join(missing_beats)}"
        )
    return {
        "world_shell_count": len(shells),
        "world_shell_view_count": view_count,
        "scale_anchor_count": scale_anchor_count,
        "world_shell_zone_count": len(assembly_zones),
    }


def _validate_theme(root: dict[str, Any]) -> dict[str, int]:
    theme = _object(root.get("theme"), "theme")
    _require_fields(
        theme,
        {
            "world_sentence",
            "memory_silhouette",
            "proportion_words",
            "base_shapes",
            "assembly_families",
            "material_rhythm",
            "color_roles",
            "world_state_change",
            "banned_list",
            "world_shells",
        },
        "theme",
    )
    proportions = _string_array(theme["proportion_words"], "theme.proportion_words", minimum=2)
    if len(proportions) > 4:
        raise DesignPlanError("theme.proportion_words must contain 2 to 4 items")
    shapes = _string_array(theme["base_shapes"], "theme.base_shapes", minimum=1)
    families = _string_array(theme["assembly_families"], "theme.assembly_families", minimum=1)
    colors = _object(theme["color_roles"], "theme.color_roles")
    required_colors = {"environment", "structure", "route", "interaction", "goal"}
    missing_colors = sorted(required_colors - set(colors))
    if missing_colors:
        raise DesignPlanError(f"theme.color_roles is missing: {', '.join(missing_colors)}")
    for key in required_colors:
        _string(colors[key], f"theme.color_roles.{key}")
    _string_array(theme["banned_list"], "theme.banned_list", minimum=1)
    shell_summary = _validate_world_shells(root, theme, set(families))
    return {
        "shape_count": len(shapes),
        "assembly_family_count": len(families),
        **shell_summary,
    }


def _validate_low_count_exception(value: Any, path: str) -> dict[str, Any]:
    exception = _object(value, path)
    _require_keys(
        exception,
        {
            "mode",
            "scope_evidence",
            "layer_coverage",
            "visual_review_views",
            "tradeoff",
        },
        path,
    )
    mode = _string(exception["mode"], f"{path}.mode")
    if mode not in LOW_COUNT_MODES:
        raise DesignPlanError(
            f"{path}.mode must be one of {', '.join(sorted(LOW_COUNT_MODES))}"
        )
    scope_evidence = _string(
        exception["scope_evidence"], f"{path}.scope_evidence"
    )
    coverage_raw = _array(exception["layer_coverage"], f"{path}.layer_coverage")
    if len(coverage_raw) < 2:
        raise DesignPlanError(f"{path}.layer_coverage must contain at least 2 items")
    coverage: list[dict[str, str]] = []
    seen_layers: set[str] = set()
    for index, raw_item in enumerate(coverage_raw):
        item_path = f"{path}.layer_coverage[{index}]"
        item = _object(raw_item, item_path)
        _require_keys(item, {"layer", "handled_by"}, item_path)
        layer = _string(item["layer"], f"{item_path}.layer")
        if layer not in LAYERS:
            raise DesignPlanError(
                f"{item_path}.layer must be one of {', '.join(sorted(LAYERS))}"
            )
        if layer in seen_layers:
            raise DesignPlanError(f"{path}.layer_coverage has duplicate layer {layer}")
        seen_layers.add(layer)
        coverage.append(
            {
                "layer": layer,
                "handled_by": _string(
                    item["handled_by"], f"{item_path}.handled_by"
                ),
            }
        )
    missing_core = sorted({"MASS", "MID"} - seen_layers)
    if missing_core:
        raise DesignPlanError(
            f"{path}.layer_coverage must explain MASS and MID; missing "
            + ", ".join(missing_core)
        )
    visual_review_views = _string_array(
        exception["visual_review_views"],
        f"{path}.visual_review_views",
        minimum=2,
    )
    return {
        "mode": mode,
        "scope_evidence": scope_evidence,
        "layer_coverage": coverage,
        "visual_review_views": visual_review_views,
        "tradeoff": _string(exception["tradeoff"], f"{path}.tradeoff"),
    }


def _validate_assembly(
    root: dict[str, Any], maturity: str
) -> tuple[dict[str, Any], list[str]]:
    assembly = _object(root.get("assembly_budget"), "assembly_budget")
    _require_keys(
        assembly,
        {
            "density_profile",
            "density_profile_evidence",
            "graybox_total",
            "expanded_total",
            "asset_vocabulary_count",
            "layers",
        },
        "assembly_budget",
    )
    density_profile = _string(
        assembly["density_profile"], "assembly_budget.density_profile"
    )
    if density_profile not in DENSITY_PROFILE_MINIMUMS:
        raise DesignPlanError(
            "assembly_budget.density_profile must be one of "
            + ", ".join(sorted(DENSITY_PROFILE_MINIMUMS))
        )
    density_floor = DENSITY_PROFILE_MINIMUMS[density_profile]
    density_profile_evidence = _string(
        assembly["density_profile_evidence"],
        "assembly_budget.density_profile_evidence",
    )
    graybox = _integer(assembly["graybox_total"], "assembly_budget.graybox_total", minimum=0)
    expanded = _integer(assembly["expanded_total"], "assembly_budget.expanded_total", minimum=1)
    vocabulary = _integer(
        assembly["asset_vocabulary_count"],
        "assembly_budget.asset_vocabulary_count",
        minimum=1,
    )
    if vocabulary > expanded:
        raise DesignPlanError("asset_vocabulary_count cannot exceed expanded_total")
    if maturity in {"graybox", "final"} and expanded < graybox:
        raise DesignPlanError("expanded_total cannot be lower than graybox_total")
    layers_raw = _object(assembly["layers"], "assembly_budget.layers")
    layers: dict[str, int] = {}
    for key, value in layers_raw.items():
        if key not in LAYERS:
            raise DesignPlanError(f"assembly_budget.layers has unknown layer {key}")
        count = _integer(value, f"assembly_budget.layers.{key}", minimum=0)
        if count:
            layers[key] = count
    if sum(layers.values()) != expanded:
        raise DesignPlanError(
            f"assembly_budget.layers sums to {sum(layers.values())}, expected {expanded}"
        )
    warnings: list[str] = []
    low_count_exception: dict[str, Any] | None = None
    if maturity == "final" and expanded < density_floor:
        low_count_exception = _validate_low_count_exception(
            assembly.get("low_count_exception"),
            "assembly_budget.low_count_exception",
        )
        if (
            low_count_exception["mode"] == "micro_space"
            and density_profile != "micro_space"
        ):
            raise DesignPlanError(
                "assembly_budget.low_count_exception.mode='micro_space' requires "
                "density_profile='micro_space'"
            )
        warnings.append(
            "below-profile final accepted only as a structured exception pending visual review "
            f"(profile={density_profile}, floor={density_floor}, expanded={expanded})"
        )
    elif "low_count_exception" in assembly:
        raise DesignPlanError(
            "assembly_budget.low_count_exception is only valid when final expanded_total "
            f"is below the {density_profile} density profile floor {density_floor}"
        )
    if maturity == "final" and expanded <= graybox:
        raise DesignPlanError("final expanded_total must exceed graybox_total")
    for layer in ("MASS", "MID"):
        if maturity == "final" and layers.get(layer, 0) == 0:
            warnings.append(f"final plan has no {layer} layer; verify the exception")
    return {
        "density_profile": density_profile,
        "density_floor": density_floor,
        "density_profile_evidence": density_profile_evidence,
        "graybox_total": graybox,
        "expanded_total": expanded,
        "asset_vocabulary_count": vocabulary,
        "layers": dict(sorted(layers.items())),
        "low_count_exception": low_count_exception,
    }, warnings


def _validate_item_list(
    value: Any,
    path: str,
    required_fields: set[str],
    minimum: int,
) -> list[dict[str, Any]]:
    raw = _array(value, path)
    if len(raw) < minimum:
        raise DesignPlanError(f"{path} must contain at least {minimum} items")
    result: list[dict[str, Any]] = []
    for index, item_value in enumerate(raw):
        item_path = f"{path}[{index}]"
        item = _object(item_value, item_path)
        _require_fields(item, required_fields, item_path)
        result.append(item)
    return result


def _validate_complexity_budget(
    root: dict[str, Any], maturity: str, expanded_total: int
) -> dict[str, Any]:
    raw = root.get("complexity_budget")
    if raw is None:
        if maturity == "final":
            raise DesignPlanError("complexity_budget is required for final plans")
        return {"declared": False}
    budget = _object(raw, "complexity_budget")
    _require_keys(
        budget,
        {"visual", "logic", "measurement", "degradation_order"},
        "complexity_budget",
    )
    visual_raw = _object(budget["visual"], "complexity_budget.visual")
    visual_fields = {
        "visible_peak",
        "collision_peak",
        "shadow_peak",
        "dynamic_peak",
        "transparent_layer_peak",
        "switch_load_peak",
    }
    _require_keys(visual_raw, visual_fields, "complexity_budget.visual")
    visual = {
        key: _integer(visual_raw[key], f"complexity_budget.visual.{key}", minimum=0)
        for key in sorted(visual_fields)
    }
    for key in ("visible_peak", "collision_peak", "shadow_peak", "dynamic_peak", "switch_load_peak"):
        if visual[key] > expanded_total:
            raise DesignPlanError(
                f"complexity_budget.visual.{key} cannot exceed assembly expanded_total"
            )

    logic_raw = _object(budget["logic"], "complexity_budget.logic")
    logic_fields = {
        "persistent_state_count",
        "event_entry_count",
        "active_timer_peak",
        "action_fanout_peak",
        "spawned_object_peak",
        "reset_item_count",
    }
    _require_keys(logic_raw, logic_fields, "complexity_budget.logic")
    logic = {
        key: _integer(logic_raw[key], f"complexity_budget.logic.{key}", minimum=0)
        for key in sorted(logic_fields)
    }
    measurement = _object(budget["measurement"], "complexity_budget.measurement")
    _require_fields(
        measurement,
        {"visual_method", "logic_method", "worst_case_state"},
        "complexity_budget.measurement",
    )
    degradation = _string_array(
        budget["degradation_order"],
        "complexity_budget.degradation_order",
        minimum=2,
    )
    return {
        "declared": True,
        "visual": visual,
        "logic": logic,
        "degradation_step_count": len(degradation),
    }


def _validate_type_module(type_name: str, value: Any, path: str) -> None:
    module = _object(value, path)
    _require_fields(module, TYPE_FIELDS[type_name], path)
    if type_name == "chapter_challenge":
        _validate_item_list(
            module["chapters"],
            f"{path}.chapters",
            {"name", "action_identity", "visual_identity", "checkpoint", "recovery"},
            2,
        )
    elif type_name == "mechanism_puzzle":
        structure_mode = _string(module["structure_mode"], f"{path}.structure_mode")
        if structure_mode not in {"curriculum", "anthology"}:
            raise DesignPlanError(
                f"{path}.structure_mode must be curriculum or anthology"
            )
        _validate_item_list(
            module["puzzle_units"],
            f"{path}.puzzle_units",
            {
                "name",
                "rule_sentence",
                "observation",
                "input",
                "correct_feedback",
                "wrong_feedback",
                "local_reset",
                "completion",
            },
            2,
        )
        sequence = _string_array(
            module["teaching_sequence"], f"{path}.teaching_sequence", minimum=4
        )
        if len(sequence) > 8:
            raise DesignPlanError(f"{path}.teaching_sequence is too diffuse; keep 4 to 8 steps")
    elif type_name == "cooperative":
        _validate_item_list(
            module["roles"], f"{path}.roles", {"name", "exclusive_verb"}, 2
        )
        _validate_item_list(
            module["handoffs"],
            f"{path}.handoffs",
            {"a_action", "world_change", "b_opportunity", "feedback", "recovery"},
            1,
        )
    elif type_name == "narrative_exploration":
        _string_array(module["landmarks"], f"{path}.landmarks", minimum=2)
        _validate_item_list(
            module["events"],
            f"{path}.events",
            {
                "name",
                "trigger",
                "entry_lock",
                "control_mode",
                "player_agency",
                "atomic_commit",
                "environment_change",
                "objective_change",
                "immediate_feedback",
                "next_beat_feedback",
                "control_return",
                "reorientation",
                "recovery",
            },
            1,
        )
        for index, raw_event in enumerate(module["events"]):
            event = _object(raw_event, f"{path}.events[{index}]")
            _string_array(
                event["atomic_commit"],
                f"{path}.events[{index}].atomic_commit",
                minimum=2,
            )
        _string(module["story_state_authority"], f"{path}.story_state_authority")
        _string(module["revisit_and_reload"], f"{path}.revisit_and_reload")
    elif type_name == "social_showcase":
        _string_array(module["landmarks"], f"{path}.landmarks", minimum=2)
        _validate_item_list(
            module["activities"],
            f"{path}.activities",
            {"name", "arrival", "activity", "leave_or_return", "occupancy"},
            1,
        )
    elif type_name == "management_simulation":
        flow = _object(module["resource_flow"], f"{path}.resource_flow")
        _require_fields(flow, {"source", "process", "output", "delivery"}, f"{path}.resource_flow")
        _string_array(
            module["product_lifecycle"],
            f"{path}.product_lifecycle",
            minimum=4,
        )
        automation = _object(
            module["automation_and_demand"],
            f"{path}.automation_and_demand",
        )
        _require_fields(
            automation,
            {"workers_or_automation", "demand_or_orders", "claim_rule", "abandon_rule"},
            f"{path}.automation_and_demand",
        )
        progression = _object(
            module["progression_and_terminal"],
            f"{path}.progression_and_terminal",
        )
        _require_fields(
            progression,
            {
                "progress_source",
                "completion_predicate",
                "terminal_unlock",
                "exit_or_settlement",
                "deduplication",
            },
            f"{path}.progression_and_terminal",
        )
        persistence = _object(module["persistence"], f"{path}.persistence")
        _require_fields(
            persistence,
            {"authority", "snapshot_scope", "load_order", "new_session_policy"},
            f"{path}.persistence",
        )
    elif type_name == "rhythm_performance":
        _validate_item_list(
            module["cue_channels"],
            f"{path}.cue_channels",
            {"name", "lead", "judgement_feedback", "fallback"},
            2,
        )
        _string_array(
            module["judgement_windows"],
            f"{path}.judgement_windows",
            minimum=2,
        )
    elif type_name == "combat_boss":
        _validate_item_list(
            module["boss_phases"],
            f"{path}.boss_phases",
            {"name", "telegraph", "threat", "counterplay", "transition", "recovery"},
            2,
        )
        _validate_item_list(
            module["player_tools"],
            f"{path}.player_tools",
            {"name", "purpose", "cost_or_cooldown", "feedback"},
            2,
        )
    elif type_name == "defense_strategy":
        _validate_item_list(
            module["lanes"],
            f"{path}.lanes",
            {"name", "entry", "path", "defense_slots", "leak_terminal", "recovery"},
            1,
        )
        _validate_item_list(
            module["waves"],
            f"{path}.waves",
            {"name", "new_pressure", "telegraph", "completion", "cleanup"},
            2,
        )
    elif type_name == "stealth_infiltration":
        _string_array(
            module["detection_states"],
            f"{path}.detection_states",
            minimum=4,
        )
        _validate_item_list(
            module["sensors"],
            f"{path}.sensors",
            {"name", "range_or_rule", "telegraph", "counterplay", "recovery"},
            1,
        )
    elif type_name == "turn_based_strategy":
        _string_array(module["phases"], f"{path}.phases", minimum=3)
        _validate_item_list(
            module["legal_actions"],
            f"{path}.legal_actions",
            {"name", "precondition", "cost", "effect", "feedback"},
            2,
        )
    elif type_name == "sports_match":
        _validate_item_list(
            module["teams"],
            f"{path}.teams",
            {"name", "spawn_or_side", "color_or_shape"},
            2,
        )
        _string_array(
            module["play_object_states"],
            f"{path}.play_object_states",
            minimum=4,
        )
        _validate_item_list(
            module["field_zones"],
            f"{path}.field_zones",
            {"name", "role", "restart"},
            3,
        )
    elif type_name == "sandbox_creation":
        _validate_item_list(
            module["catalog_categories"],
            f"{path}.catalog_categories",
            {"name", "purpose", "budget"},
            3,
        )
        _string_array(
            module["build_states"],
            f"{path}.build_states",
            minimum=4,
        )
    elif type_name == "social_deduction":
        roles = _validate_item_list(
            module["role_set"],
            f"{path}.role_set",
            {
                "name",
                "alignment",
                "private_knowledge",
                "exclusive_action",
                "public_counterplay",
            },
            2,
        )
        role_names = [
            _string(role["name"], f"{path}.role_set[{index}].name")
            for index, role in enumerate(roles)
        ]
        if len(set(role_names)) != len(role_names):
            raise DesignPlanError(f"{path}.role_set contains duplicate role names")
        role_alignments = {
            _string(role["alignment"], f"{path}.role_set[{index}].alignment")
            for index, role in enumerate(roles)
        }
        if len(role_alignments) < 2:
            raise DesignPlanError(
                f"{path}.role_set must contain at least two distinct alignments"
            )
        _string_array(
            module["phase_cycle"],
            f"{path}.phase_cycle",
            minimum=4,
        )
        tasks = _validate_item_list(
            module["tasks_or_evidence"],
            f"{path}.tasks_or_evidence",
            {
                "name",
                "owner_scope",
                "progress_rule",
                "public_feedback",
                "duplication_guard",
                "recovery",
            },
            2,
        )
        task_names = [
            _string(task["name"], f"{path}.tasks_or_evidence[{index}].name")
            for index, task in enumerate(tasks)
        ]
        if len(set(task_names)) != len(task_names):
            raise DesignPlanError(
                f"{path}.tasks_or_evidence contains duplicate names"
            )
        predicates = _validate_item_list(
            module["win_predicates"],
            f"{path}.win_predicates",
            {"alignment", "predicate", "priority", "terminal_feedback"},
            2,
        )
        predicate_alignments = {
            _string(
                predicate["alignment"],
                f"{path}.win_predicates[{index}].alignment",
            )
            for index, predicate in enumerate(predicates)
        }
        missing_predicates = sorted(role_alignments - predicate_alignments)
        if missing_predicates:
            raise DesignPlanError(
                f"{path}.win_predicates is missing role alignments: "
                + ", ".join(missing_predicates)
            )


def _validate_hybrid(
    root: dict[str, Any],
    secondary_type: str | None,
    beat_owner_by_name: dict[str, str],
    beat_seconds_by_name: dict[str, float],
    duration_max: float,
) -> dict[str, Any] | None:
    if secondary_type is None:
        if root.get("hybrid") not in (None, {}):
            raise DesignPlanError("hybrid contract requires secondary_type")
        return None
    hybrid = _object(root.get("hybrid"), "hybrid")
    _require_fields(
        hybrid,
        {
            "mode",
            "secondary_purpose",
            "secondary_scope",
            "authoritative_terminal",
            "time_budget",
            "entry_condition",
            "exit_condition",
            "conflict_priority",
            "simultaneous_failure",
            "state_handoff",
            "cleanup_owner",
            "shared_visual_grammar",
            "fallback",
        },
        "hybrid",
    )
    mode = _string(hybrid["mode"], "hybrid.mode")
    if mode not in HYBRID_MODES:
        raise DesignPlanError(f"hybrid.mode must be one of {', '.join(sorted(HYBRID_MODES))}")
    secondary_scope = _string_array(
        hybrid["secondary_scope"], "hybrid.secondary_scope", minimum=1
    )
    unknown_beats = sorted(set(secondary_scope) - set(beat_owner_by_name))
    if unknown_beats:
        raise DesignPlanError(
            "hybrid.secondary_scope references unknown beats: "
            + ", ".join(unknown_beats)
        )
    primary_only = sorted(
        name
        for name in secondary_scope
        if beat_owner_by_name[name] == "primary"
    )
    if primary_only:
        raise DesignPlanError(
            "hybrid.secondary_scope cannot claim primary-only beats: "
            + ", ".join(primary_only)
        )
    declared_secondary_beats = {
        name
        for name, owner in beat_owner_by_name.items()
        if owner in {"secondary", "handoff"}
    }
    missing_scoped_beats = sorted(declared_secondary_beats - set(secondary_scope))
    if missing_scoped_beats:
        raise DesignPlanError(
            "hybrid.secondary_scope is missing secondary/handoff beats: "
            + ", ".join(missing_scoped_beats)
        )

    time_budget = _object(hybrid["time_budget"], "hybrid.time_budget")
    _require_fields(
        time_budget,
        {
            "forced_secondary_seconds_max",
            "continuous_primary_pause_seconds_max",
            "measurement",
        },
        "hybrid.time_budget",
    )
    forced_seconds = _number(
        time_budget["forced_secondary_seconds_max"],
        "hybrid.time_budget.forced_secondary_seconds_max",
        minimum=0,
    )
    pause_seconds = _number(
        time_budget["continuous_primary_pause_seconds_max"],
        "hybrid.time_budget.continuous_primary_pause_seconds_max",
        minimum=0,
    )
    if forced_seconds > duration_max:
        raise DesignPlanError(
            "hybrid forced_secondary_seconds_max cannot exceed target duration maximum"
        )
    if pause_seconds > forced_seconds:
        raise DesignPlanError(
            "hybrid continuous_primary_pause_seconds_max cannot exceed forced_secondary_seconds_max"
        )
    if mode == "optional_branch" and forced_seconds != 0:
        raise DesignPlanError(
            "hybrid optional_branch must have forced_secondary_seconds_max=0"
        )
    return {
        "mode": mode,
        "secondary_scope_count": len(secondary_scope),
        "scoped_target_seconds": sum(
            beat_seconds_by_name[name] for name in secondary_scope
        ),
        "forced_secondary_seconds_max": forced_seconds,
        "continuous_primary_pause_seconds_max": pause_seconds,
    }


def _validate_modifiers(
    root: dict[str, Any]
) -> tuple[list[str], set[str], set[str]]:
    modifiers = _string_array(root.get("modifiers", []), "modifiers")
    unknown = sorted(set(modifiers) - MODIFIERS)
    if unknown:
        raise DesignPlanError(f"unknown modifiers: {', '.join(unknown)}")
    contracts = _object(root.get("modifier_contracts", {}), "modifier_contracts")
    missing = sorted(set(modifiers) - set(contracts))
    extra = sorted(set(contracts) - set(modifiers))
    if missing or extra:
        raise DesignPlanError(
            f"modifier_contracts mismatch (missing={missing}, extra={extra})"
        )
    metric_keys: set[str] = set()
    scenario_keys: set[str] = set()
    for modifier in modifiers:
        contract = _object(contracts[modifier], f"modifier_contracts.{modifier}")
        _require_fields(
            contract,
            {"purpose", "precondition", "feedback", "failure_recovery", "reset", "metric"},
            f"modifier_contracts.{modifier}",
        )
        metric_key = _string(contract["metric"], f"modifier_contracts.{modifier}.metric")
        if metric_key in metric_keys:
            raise DesignPlanError(f"duplicate modifier metric key {metric_key}")
        metric_keys.add(metric_key)
        _require_fields(
            contract,
            MODIFIER_SPECIFIC_FIELDS[modifier],
            f"modifier_contracts.{modifier}",
        )
        if modifier == "rising_pressure":
            _string_array(
                contract["pace_samples"],
                f"modifier_contracts.{modifier}.pace_samples",
                minimum=3,
            )
        elif modifier == "escort_collection":
            _string_array(
                contract["object_states"],
                f"modifier_contracts.{modifier}.object_states",
                minimum=4,
            )
        elif modifier == "vehicles":
            _validate_item_list(
                contract["calibration_profiles"],
                f"modifier_contracts.{modifier}.calibration_profiles",
                {"name", "turn_radius", "stopping_distance", "camera", "clearance"},
                3,
            )
        elif modifier == "asymmetric_roles":
            _validate_item_list(
                contract["roles"],
                f"modifier_contracts.{modifier}.roles",
                {
                    "name",
                    "information",
                    "exclusive_ability",
                    "vulnerability",
                    "counterplay",
                    "objective",
            },
            2,
        )
        elif modifier == "rhythm":
            _string_array(
                contract["judgement_windows"],
                f"modifier_contracts.{modifier}.judgement_windows",
                minimum=2,
            )
        elif modifier == "horror":
            _string_array(
                contract["tension_beats"],
                f"modifier_contracts.{modifier}.tension_beats",
                minimum=4,
            )
        elif modifier == "vertical_climb":
            _validate_item_list(
                contract["layers"],
                f"modifier_contracts.{modifier}.layers",
                {"name", "upward_goal", "fall_destination", "camera_risk", "recovery"},
                2,
            )
        elif modifier == "random_variation":
            _string_array(
                contract["candidate_pool"],
                f"modifier_contracts.{modifier}.candidate_pool",
                minimum=2,
            )
        elif modifier == "cumulative_growth":
            _string_array(
                contract["feedback_tiers"],
                f"modifier_contracts.{modifier}.feedback_tiers",
                minimum=2,
            )
            _string_array(
                contract["spatial_calibration_levels"],
                f"modifier_contracts.{modifier}.spatial_calibration_levels",
                minimum=3,
            )
        elif modifier == "destructible_world":
            _string_array(
                contract["target_states"],
                f"modifier_contracts.{modifier}.target_states",
                minimum=4,
            )
            _string_array(
                contract["valid_damage_sources"],
                f"modifier_contracts.{modifier}.valid_damage_sources",
                minimum=1,
            )
            _validate_item_list(
                contract["dependency_groups"],
                f"modifier_contracts.{modifier}.dependency_groups",
                {
                    "name",
                    "prerequisite",
                    "commit",
                    "cycle_guard",
                    "failure_recovery",
                },
                1,
            )
            debris_budget = _object(
                contract["debris_budget"],
                f"modifier_contracts.{modifier}.debris_budget",
            )
            _require_fields(
                debris_budget,
                {"spawned_peak", "lifetime", "collision_policy", "cleanup"},
                f"modifier_contracts.{modifier}.debris_budget",
            )
            _integer(
                debris_budget["spawned_peak"],
                f"modifier_contracts.{modifier}.debris_budget.spawned_peak",
                minimum=0,
            )
        scenario_keys.update(MODIFIER_SCENARIOS.get(modifier, set()))
    interactions = root.get("modifier_interactions", [])
    if len(modifiers) <= 1:
        if interactions not in (None, []):
            raise DesignPlanError(
                "modifier_interactions is only used when at least two modifiers are active"
            )
    else:
        expected_pairs = {
            tuple(sorted((modifiers[left], modifiers[right])))
            for left in range(len(modifiers))
            for right in range(left + 1, len(modifiers))
        }
        rows = _validate_item_list(
            interactions,
            "modifier_interactions",
            {"modifiers", "interaction", "priority", "worst_case", "cleanup"},
            len(expected_pairs),
        )
        seen_pairs: set[tuple[str, str]] = set()
        for index, row in enumerate(rows):
            pair = _string_array(
                row["modifiers"],
                f"modifier_interactions[{index}].modifiers",
                minimum=2,
            )
            if len(pair) != 2:
                raise DesignPlanError(
                    f"modifier_interactions[{index}].modifiers must contain exactly 2 items"
                )
            if not set(pair) <= set(modifiers):
                raise DesignPlanError(
                    f"modifier_interactions[{index}] references an inactive modifier"
                )
            signature = tuple(sorted(pair))
            if signature in seen_pairs:
                raise DesignPlanError(
                    f"duplicate modifier_interactions pair {signature}"
                )
            seen_pairs.add(signature)
        missing_pairs = sorted(expected_pairs - seen_pairs)
        extra_pairs = sorted(seen_pairs - expected_pairs)
        if missing_pairs or extra_pairs:
            raise DesignPlanError(
                f"modifier_interactions pair coverage mismatch (missing={missing_pairs}, extra={extra_pairs})"
            )
    return modifiers, metric_keys, scenario_keys


def _expected_reference_axes(root: dict[str, Any]) -> set[str]:
    axes = set(BASE_REFERENCE_AXES)
    if root.get("secondary_type") is not None:
        axes.update({"secondary_loop", "hybrid_relation"})
    if root.get("modifiers"):
        axes.add("modifier")
    return axes


def _reference_gap(axis: str) -> dict[str, str]:
    return {
        "axis": axis,
        "reason": "No audited positive case has been selected for this evidence axis.",
        "next_research_question": (
            f"Find or inspect a case that directly tests the {axis} decision and its failure boundary."
        ),
    }


def _validate_evidence(root: dict[str, Any], stage: str) -> dict[str, int]:
    evidence = _object(root.get("evidence"), "evidence")
    expected_axes = _expected_reference_axes(root)
    required_axes_raw = _array(
        evidence.get("required_reference_axes"), "evidence.required_reference_axes"
    )
    required_axes = {
        _string(axis, f"evidence.required_reference_axes[{index}]")
        for index, axis in enumerate(required_axes_raw)
    }
    if len(required_axes) != len(required_axes_raw):
        raise DesignPlanError("evidence.required_reference_axes contains duplicate axes")
    unknown_axes = sorted(required_axes - REFERENCE_AXES)
    if unknown_axes:
        raise DesignPlanError(
            f"evidence.required_reference_axes contains unknown axes: {unknown_axes}"
        )
    if required_axes != expected_axes:
        raise DesignPlanError(
            "evidence.required_reference_axes mismatch: "
            f"missing={sorted(expected_axes - required_axes)}, "
            f"extra={sorted(required_axes - expected_axes)}"
        )

    references = _array(evidence.get("references", []), "evidence.references")
    positive_axes: set[str] = set()
    for index, raw_reference in enumerate(references):
        path = f"evidence.references[{index}]"
        reference = _object(raw_reference, path)
        _require_fields(
            reference, {"name", "status", "used_for", "limits", "supports"}, path
        )
        for field in ("name", "used_for", "limits"):
            _string(reference[field], f"{path}.{field}")
        status = _string(reference["status"], f"{path}.status")
        if status not in EVIDENCE_STATUSES:
            raise DesignPlanError(
                f"{path}.status must be one of {', '.join(sorted(EVIDENCE_STATUSES))}"
            )
        supports_raw = _array(reference["supports"], f"{path}.supports")
        if not supports_raw:
            raise DesignPlanError(f"{path}.supports cannot be empty")
        seen_axes: set[str] = set()
        for support_index, raw_support in enumerate(supports_raw):
            support_path = f"{path}.supports[{support_index}]"
            support = _object(raw_support, support_path)
            _require_fields(support, {"axis", "coverage_status"}, support_path)
            axis = _string(support["axis"], f"{support_path}.axis")
            if axis not in REFERENCE_AXES:
                raise DesignPlanError(
                    f"{support_path}.axis must be one of {', '.join(sorted(REFERENCE_AXES))}"
                )
            if axis in seen_axes:
                raise DesignPlanError(f"{path}.supports contains duplicate axis {axis}")
            seen_axes.add(axis)
            coverage_status = _string(
                support["coverage_status"], f"{support_path}.coverage_status"
            )
            if coverage_status not in REFERENCE_COVERAGE_STATUSES:
                raise DesignPlanError(
                    f"{support_path}.coverage_status must be one of "
                    f"{', '.join(sorted(REFERENCE_COVERAGE_STATUSES))}"
                )
            if coverage_status in {"verified_positive", "partial_positive"}:
                positive_axes.add(axis)

    gaps_raw = _array(evidence.get("reference_gaps"), "evidence.reference_gaps")
    gap_axes: set[str] = set()
    for index, raw_gap in enumerate(gaps_raw):
        path = f"evidence.reference_gaps[{index}]"
        gap = _object(raw_gap, path)
        _require_fields(gap, {"axis", "reason", "next_research_question"}, path)
        axis = _string(gap["axis"], f"{path}.axis")
        if axis not in required_axes:
            raise DesignPlanError(
                f"{path}.axis must be one of the required reference axes"
            )
        if axis in gap_axes:
            raise DesignPlanError(f"evidence.reference_gaps contains duplicate axis {axis}")
        gap_axes.add(axis)
        _string(gap["reason"], f"{path}.reason")
        _string(gap["next_research_question"], f"{path}.next_research_question")
    missing_positive = required_axes - positive_axes
    if gap_axes != missing_positive:
        raise DesignPlanError(
            "evidence.reference_gaps mismatch: "
            f"missing={sorted(missing_positive - gap_axes)}, "
            f"extra={sorted(gap_axes - missing_positive)}"
        )

    assumptions = _validate_item_list(
        evidence.get("assumptions", []),
        "evidence.assumptions",
        {"text", "validation"},
        1,
    )
    unknowns = _array(evidence.get("unknowns", []), "evidence.unknowns")
    blocking = 0
    for index, raw_unknown in enumerate(unknowns):
        path = f"evidence.unknowns[{index}]"
        unknown = _object(raw_unknown, path)
        _require_keys(unknown, {"text", "impact", "validation", "blocking"}, path)
        for field in ("text", "impact", "validation"):
            _string(unknown[field], f"{path}.{field}")
        if _boolean(unknown["blocking"], f"{path}.blocking"):
            blocking += 1
    if stage == "predeploy" and blocking:
        raise DesignPlanError(f"predeploy plan has {blocking} blocking unknowns")
    return {
        "reference_count": len(references),
        "positive_reference_axis_count": len(positive_axes & required_axes),
        "reference_gap_count": len(gap_axes),
        "assumption_count": len(assumptions),
        "unknown_count": len(unknowns),
    }


def _validate_check_entry(value: Any, path: str, stage: str) -> str:
    entry = _object(value, path)
    _require_fields(entry, {"status", "method"}, path)
    status = _string(entry["status"], f"{path}.status")
    if status not in CHECK_STATUSES:
        raise DesignPlanError(f"{path}.status must be one of {', '.join(sorted(CHECK_STATUSES))}")
    if status == "not_applicable":
        _string(entry.get("reason"), f"{path}.reason")
    else:
        _nonempty(entry.get("target_or_result"), f"{path}.target_or_result")
    if stage == "predeploy" and status == "planned":
        raise DesignPlanError(f"predeploy still has planned verification: {path}")
    return status


def _validate_verification(
    root: dict[str, Any],
    stage: str,
    primary_type: str,
    secondary_type: str | None,
    player_min: int,
    player_max: int,
    modifier_metrics: set[str],
    modifier_scenarios: set[str],
) -> dict[str, Any]:
    verification = _object(root.get("verification"), "verification")
    _string(verification.get("target_device"), "verification.target_device")
    player_counts = {
        _integer(value, f"verification.player_counts[{index}]", minimum=1)
        for index, value in enumerate(
            _array(verification.get("player_counts"), "verification.player_counts")
        )
    }
    if player_min not in player_counts or player_max not in player_counts:
        raise DesignPlanError(
            "verification.player_counts must include experience minimum and maximum"
        )
    required_metrics = set(BASE_METRICS) | TYPE_METRICS[primary_type]
    required_metrics.update(modifier_metrics)
    required_scenarios = set(BASE_SCENARIOS) | TYPE_SCENARIOS[primary_type]
    required_scenarios.update(modifier_scenarios)
    if secondary_type:
        required_metrics.update(TYPE_METRICS[secondary_type])
        required_scenarios.update(TYPE_SCENARIOS[secondary_type])
        required_metrics.update(HYBRID_METRICS)
        required_scenarios.update(HYBRID_SCENARIOS)
    metrics = _object(verification.get("metrics"), "verification.metrics")
    scenarios = _object(verification.get("scenarios"), "verification.scenarios")
    missing_metrics = sorted(required_metrics - set(metrics))
    missing_scenarios = sorted(required_scenarios - set(scenarios))
    if missing_metrics:
        raise DesignPlanError(f"verification.metrics is missing: {', '.join(missing_metrics)}")
    if missing_scenarios:
        raise DesignPlanError(f"verification.scenarios is missing: {', '.join(missing_scenarios)}")
    statuses: Counter[str] = Counter()
    for key, value in metrics.items():
        statuses[_validate_check_entry(value, f"verification.metrics.{key}", stage)] += 1
    for key, value in scenarios.items():
        statuses[_validate_check_entry(value, f"verification.scenarios.{key}", stage)] += 1
    return {
        "required_metric_count": len(required_metrics),
        "required_scenario_count": len(required_scenarios),
        "statuses": dict(sorted(statuses.items())),
    }


def _validate_audits(
    root: dict[str, Any],
    stage: str,
    expanded_total: int,
    types: set[str],
    modifiers: list[str],
) -> dict[str, str]:
    audits = _object(root.get("audits"), "audits")
    required = {
        "build_bundle",
        "component_evidence",
        "density",
        "parameter_expansion",
        "performance",
        "state",
        "theme_adaptation",
    }
    missing = sorted(required - set(audits))
    if missing:
        raise DesignPlanError(f"audits is missing: {', '.join(missing)}")
    result: dict[str, str] = {}
    for name in sorted(required):
        path = f"audits.{name}"
        entry = _object(audits[name], path)
        status = _string(entry.get("status"), f"{path}.status")
        if status not in AUDIT_STATUSES:
            raise DesignPlanError(f"{path}.status must be one of {', '.join(sorted(AUDIT_STATUSES))}")
        if status == "not_applicable":
            _string(entry.get("reason"), f"{path}.reason")
        result[name] = status
    if stage == "predeploy":
        planned = sorted(name for name, status in result.items() if status == "planned")
        if planned:
            raise DesignPlanError(
                f"predeploy audits still planned: {', '.join(planned)}"
            )
        if result["component_evidence"] != "passed":
            raise DesignPlanError("predeploy requires component_evidence status passed")
        for name in (
            "build_bundle",
            "density",
            "parameter_expansion",
            "performance",
            "theme_adaptation",
        ):
            if result[name] != "passed":
                raise DesignPlanError(
                    f"predeploy requires {name} status passed at every instance count"
                )
        state_required = bool(types & COMPLEX_STATE_TYPES) or bool(modifiers)
        if state_required and result["state"] != "passed":
            raise DesignPlanError("predeploy complex plan requires state audit status passed")
    return result


def validate_design_plan(plan: Any) -> dict[str, Any]:
    root = _object(plan, "plan")
    version = _integer(root.get("schema_version"), "schema_version", minimum=1)
    if version != 1:
        raise DesignPlanError(f"unsupported schema_version {version}; expected 1")
    stage = _string(root.get("stage"), "stage")
    if stage not in STAGES:
        raise DesignPlanError(f"stage must be one of {', '.join(sorted(STAGES))}")
    maturity = _string(root.get("maturity"), "maturity")
    if maturity not in MATURITIES:
        raise DesignPlanError(f"maturity must be one of {', '.join(sorted(MATURITIES))}")
    if stage == "predeploy" and maturity != "final":
        raise DesignPlanError("predeploy requires maturity='final'")
    primary_type = _string(root.get("primary_type"), "primary_type")
    if primary_type not in PRIMARY_TYPES:
        raise DesignPlanError(f"unknown primary_type {primary_type}")
    raw_secondary = root.get("secondary_type")
    secondary_type = None if raw_secondary is None else _string(raw_secondary, "secondary_type")
    if secondary_type is not None:
        if secondary_type not in PRIMARY_TYPES:
            raise DesignPlanError(f"unknown secondary_type {secondary_type}")
        if secondary_type == primary_type:
            raise DesignPlanError("secondary_type must differ from primary_type")

    player_min, player_max, duration_min, duration_max = _validate_experience(root)
    topology = _validate_topology(root)
    (
        beat_count,
        beat_seconds,
        beat_owners,
        beat_owner_by_name,
        beat_seconds_by_name,
    ) = _validate_beats(
        root, maturity, secondary_type is not None
    )
    theme = _validate_theme(root)
    assembly, warnings = _validate_assembly(root, maturity)
    minimum_world_shells = {
        "micro_space": 1,
        "themed_short": 1,
        "multi_scene": 2,
        "long_world": 3,
    }[assembly["density_profile"]]
    if theme["world_shell_count"] < minimum_world_shells:
        raise DesignPlanError(
            f"density_profile={assembly['density_profile']} requires at least "
            f"{minimum_world_shells} theme.world_shells"
        )
    complexity = _validate_complexity_budget(
        root, maturity, assembly["expanded_total"]
    )
    modules = _object(root.get("type_modules"), "type_modules")
    expected_modules = {primary_type}
    if secondary_type:
        expected_modules.add(secondary_type)
    missing_modules = sorted(expected_modules - set(modules))
    extra_modules = sorted(set(modules) - expected_modules)
    if missing_modules or extra_modules:
        raise DesignPlanError(
            f"type_modules mismatch (missing={missing_modules}, extra={extra_modules})"
        )
    for type_name in sorted(expected_modules):
        _validate_type_module(type_name, modules[type_name], f"type_modules.{type_name}")
    hybrid = _validate_hybrid(
        root,
        secondary_type,
        beat_owner_by_name,
        beat_seconds_by_name,
        duration_max,
    )
    modifiers, modifier_metrics, modifier_scenarios = _validate_modifiers(root)
    if "rhythm_performance" in expected_modules and "rhythm" in modifiers:
        raise DesignPlanError(
            "rhythm_performance already owns the rhythm loop; do not also enable rhythm modifier"
        )
    evidence = _validate_evidence(root, stage)
    verification = _validate_verification(
        root,
        stage,
        primary_type,
        secondary_type,
        player_min,
        player_max,
        modifier_metrics,
        modifier_scenarios,
    )
    audits = _validate_audits(
        root,
        stage,
        assembly["expanded_total"],
        expected_modules,
        modifiers,
    )
    if beat_seconds and (beat_seconds < duration_min * 0.5 or beat_seconds > duration_max * 1.5):
        warnings.append(
            "sum of beat target_seconds is far outside target duration; verify idle, loops, or optional time"
        )
    if maturity == "final" and theme["assembly_family_count"] < 3:
        warnings.append("final theme declares fewer than 3 assembly families")
    if maturity == "final" and theme["shape_count"] < 2:
        warnings.append("final theme declares only one base shape; verify deliberate narrow vocabulary")

    return {
        "schema_version": version,
        "stage": stage,
        "maturity": maturity,
        "primary_type": primary_type,
        "secondary_type": secondary_type,
        "hybrid": hybrid,
        "modifiers": modifiers,
        "player_range": [player_min, player_max],
        "target_duration_seconds": [duration_min, duration_max],
        "topology": topology,
        "beat_count": beat_count,
        "beat_owner_counts": dict(sorted(beat_owners.items())),
        "assembly": assembly,
        "complexity": complexity,
        "theme": theme,
        "evidence": evidence,
        "verification": verification,
        "audits": audits,
        "warnings": warnings,
    }


def _module_example(type_name: str) -> dict[str, Any]:
    common = {"goal": f"Complete the {type_name} loop."}
    values: dict[str, dict[str, Any]] = {
        "short_race": {
            "finish_rule": "Cross the single locked finish after legal checkpoints.",
            "flow_line": "orient -> teach -> vary -> combine -> finish",
            "overtake_or_parallel": "Two-player width plus one readable pass point.",
            "checkpoint_and_reset": "Return to the latest committed checkpoint.",
        },
        "chapter_challenge": {
            "chapters": [
                {"name": "C1", "action_identity": "jump", "visual_identity": "stone gate", "checkpoint": "CP1", "recovery": "CP1"},
                {"name": "C2", "action_identity": "time", "visual_identity": "light tower", "checkpoint": "CP2", "recovery": "CP2"},
            ],
            "checkpoint_policy": "Commit after each chapter result.",
            "difficulty_wave": "low -> medium -> rest -> high -> release",
            "quit_or_reentry": "Resume at the last committed chapter.",
        },
        "mechanism_puzzle": {
            "structure_mode": "curriculum",
            "shared_interface": "Each station keeps the same entry, rule panel, input bay, result frame, reset dock, checkpoint, and exit.",
            "puzzle_units": [
                {
                    "name": "safe demonstration",
                    "rule_sentence": "Matching shapes route power to the same framed output.",
                    "observation": "One source and one matching output remain visible before input.",
                    "input": "Choose one of two shape switches.",
                    "correct_feedback": "The matching line and output pulse together.",
                    "wrong_feedback": "The selected wrong branch flashes at its source.",
                    "local_reset": "Return both switches and the output to the initial state.",
                    "completion": "Lock the solved station and commit its checkpoint.",
                },
                {
                    "name": "direction variation",
                    "rule_sentence": "Matching shapes still route power when the framed output moves.",
                    "observation": "The same shape grammar is rotated around the input bay.",
                    "input": "Route two matching branches in order.",
                    "correct_feedback": "Both routed lines stay lit and open the result gate.",
                    "wrong_feedback": "Only the conflicting branch pulses, then releases input.",
                    "local_reset": "Cancel pending feedback and restore both branches and the gate.",
                    "completion": "Lock the solved state before opening the exit.",
                },
            ],
            "teaching_sequence": ["show", "verify", "vary direction", "combine", "recover"],
            "hint_policy": "While the current unit is active and incomplete, first point to the observation, then the relation, then the next action; cancel on progress, completion, exit, or reset.",
            "error_feedback": "The wrong branch pulses and resets locally.",
            "checkpoint_policy": "Commit only after the current puzzle unit is atomically complete.",
            "reset": "Restore inputs, outputs, objects, and pending timers.",
        },
        "cooperative": {
            "roles": [
                {"name": "A", "exclusive_verb": "route power"},
                {"name": "B", "exclusive_verb": "move the powered bridge"},
            ],
            "handoffs": [
                {"a_action": "route power", "world_change": "bridge lights", "b_opportunity": "move bridge", "feedback": "both see the same light", "recovery": "return both roles to CP1"}
            ],
            "missing_player_branch": "Grant a limited solo handoff tool.",
            "regroup_and_respawn": "Respawn both roles at the committed handoff.",
        },
        "narrative_exploration": {
            "landmarks": ["broken tower", "lit archive"],
            "events": [
                {
                    "name": "relight archive",
                    "trigger": "cross archive gate after reading the seal",
                    "entry_lock": "ignore duplicate entries while the event transaction is open",
                    "control_mode": "brief object close-up, movement paused",
                    "player_agency": "skip the close-up or inspect it; both commit the same reveal",
                    "atomic_commit": [
                        "story beat=ARCHIVE_REVEALED",
                        "scene variant=TOWER_LIT",
                        "active objective=return to tower",
                    ],
                    "environment_change": "tower relights and the old archive crowd clears",
                    "objective_change": "return to the lit tower",
                    "immediate_feedback": "seal pulses and the choice/skip input confirms",
                    "next_beat_feedback": "the tower beam and objective update together",
                    "control_return": "restore follow camera after the commit",
                    "reorientation": "return camera behind the player facing the lit tower",
                    "recovery": "interrupt rolls back; respawn after commit rebuilds the lit variant",
                }
            ],
            "story_state_authority": "One story controller owns beat, control mode, scene variant, objective, and choice history.",
            "control_return": "No forced camera during hazards.",
            "navigation_without_text": "Warm openings and tower silhouette lead the route.",
            "revisit_and_reload": "Revisits and reloads rebuild population, facilities, objective, and guide from the committed story snapshot.",
            "ending_or_exit": "Return to the relit central gate.",
        },
        "survival": {
            "start_and_idle_contract": "Control, timer start, host absence, optional overlays, and no-input outcome are explicit.",
            "danger_teaching": "One slow sweep with a full cue.",
            "phase_schedule": "ROUND authorizes SELECT -> TELEGRAPH -> ACTIVE -> CLEANUP for each hazard generation.",
            "escalation": "speed, then density, then safe-space reduction",
            "safe_space_change": "Outer safe ring closes in three readable steps.",
            "randomness_safety": "Field and weather candidates use a compatibility matrix and preserve one readable response.",
            "elimination_and_spectating": "Eliminated players cannot affect play and receive a clear view.",
            "terminal_and_draw": "Last survivor wins; all-out is a draw.",
            "round_reset": "Stop hazards and clear the prior generation.",
        },
        "score_contest": {
            "scoring_cycle": "collect -> expose -> return -> score",
            "ownership_and_deduplication": "Each token has one owner and one commit ID.",
            "hotspot_migration": "High-value hotspot rotates with a shared cue.",
            "fairness": "Measure spawn-to-resource and spawn-to-hotspot travel time.",
            "anti_snowball": "Leading position is exposed and cannot own the next spawn.",
            "tie_and_timeout": "A tie enters one neutral overtime objective.",
            "round_reset": "Clear scores, tokens, timers, and hotspot generation.",
        },
        "social_showcase": {
            "landmarks": ["central tree", "photo pier", "music hill"],
            "activities": [
                {"name": "photo pier", "arrival": "visible arch", "activity": "pose and light controls", "leave_or_return": "two-way gate to center", "occupancy": "controls release on exit"}
            ],
            "return_loop": "Every branch returns to the central tree.",
            "occupancy_release": "Abandonment timeout releases the control.",
            "idle_quality": "Observers can pose, sit, or choose another branch.",
            "session_cleanup": "Clear temporary text, props, and occupancy.",
        },
        "management_simulation": {
            "resource_flow": {"source": "intake", "process": "repair", "output": "toy", "delivery": "loading bay"},
            "product_lifecycle": ["ORDERED", "STORED", "PROCESSING", "READY", "STOCKED", "DELIVERED"],
            "ownership": "Shared inventory with atomic station claims.",
            "capacity": "Visible buffers have hard limits and overflow recovery.",
            "automation_and_demand": {
                "workers_or_automation": "Workers claim one current-generation job or stay disabled.",
                "demand_or_orders": "Orders bind to a product and release on completion or timeout.",
                "claim_rule": "One owner and one commit ID per job, station, and product batch.",
                "abandon_rule": "Cancel or requeue orphan work and release every occupancy lock.",
            },
            "upgrade_choice": "Choose capacity, route, or processing speed.",
            "visible_world_change": "Upgrades open a new belt or enlarge the buffer.",
            "progression_and_terminal": {
                "progress_source": "Derive visible progress from the stable required-unlock set.",
                "completion_predicate": "Every required production and delivery milestone is committed.",
                "terminal_unlock": "Lock the completion snapshot before enabling the result gate.",
                "exit_or_settlement": "The player deliberately enters the lit loading-office exit.",
                "deduplication": "Repeated purchases and reloads cannot increment progress twice.",
            },
            "persistence": {
                "authority": "Single-session world; no cross-session save is promised.",
                "snapshot_scope": "No persistent snapshot; all economy state is round-scoped.",
                "load_order": "Clear old jobs and rebuild the declared initial catalog before input.",
                "new_session_policy": "Start with the same clean inventory, stations, locks, and exit.",
            },
            "recovery_and_reset": "Rollback incomplete jobs and clear prior-round objects.",
        },
        "rhythm_performance": {
            "sequence_authority": "One clock owns cue generation, judgement, score, combo, pause, and settlement.",
            "cue_channels": [
                {"name": "visual lane", "lead": "travel-time preview", "judgement_feedback": "hit-line pulse", "fallback": "shape and motion remain readable without color"},
                {"name": "audio beat", "lead": "shared clock count-in", "judgement_feedback": "distinct hit or miss tone", "fallback": "the visual lane carries every required cue when muted"},
            ],
            "judgement_windows": ["perfect", "good", "miss"],
            "input_deduplication": "One physical input edge resolves at most one active note in the current generation.",
            "scoring_and_combo": "Judgement, score delta, combo, and note consumption commit atomically.",
            "difficulty_curve": "Teach one lane, add density, introduce holds, then combine lanes with a release phrase.",
            "latency_and_accessibility": "Calibrate representative device latency and preserve muted, low-flash, and non-color cues.",
            "terminal_and_reset": "Finish once, invalidate old notes and callbacks, clear combo, and rebuild the next sequence from one generation.",
        },
        "combat_boss": {
            "boss_phases": [
                {"name": "phase one", "telegraph": "wide floor arc", "threat": "slow sweep", "counterplay": "move behind the sweep", "transition": "health threshold locks damage and clears attacks", "recovery": "safe outer pocket"},
                {"name": "phase two", "telegraph": "weak-point flare and lane marks", "threat": "faster sweep plus lane strikes", "counterplay": "dodge then strike the exposed point", "transition": "zero health commits defeat", "recovery": "lit respawn alcove"},
            ],
            "damage_authority": "One encounter controller validates source, target, invulnerability, health delta, phase, and defeat once.",
            "player_tools": [
                {"name": "dodge", "purpose": "cross a telegraphed attack edge", "cost_or_cooldown": "short cooldown", "feedback": "brief safe outline"},
                {"name": "weak-point strike", "purpose": "deal legal boss damage", "cost_or_cooldown": "only while exposed", "feedback": "same-source health and weak-point pulse"},
            ],
            "arena_and_safe_recovery": "The combat ring, attack lanes, safe pockets, boss boundary, and respawn alcoves are visually distinct.",
            "phase_escalation": "Add one readable pressure dimension per phase while retaining learned counterplay.",
            "multiplayer_scaling": "Scale durable pressure or opportunity count without shrinking individual reaction readability.",
            "defeat_wipe_and_draw": "Define boss defeat, all-player wipe, simultaneous last-hit/wipe priority, and spectator behavior.",
            "terminal_and_reset": "Cancel attacks, clear invulnerability and projectiles, release players, and rebuild health and phase from a fresh generation.",
        },
        "defense_strategy": {
            "defended_object": "One core owns health, leak accounting, failure, and visible damage state.",
            "lanes": [
                {"name": "left lane", "entry": "north source", "path": "outer bend to core", "defense_slots": "three readable pads", "leak_terminal": "core gate", "recovery": "return stuck units to the latest lane beacon"},
                {"name": "right lane", "entry": "east source", "path": "short inner route", "defense_slots": "two stronger-choice pads", "leak_terminal": "core gate", "recovery": "despawn invalid units and restore their wave quota"},
            ],
            "waves": [
                {"name": "teaching wave", "new_pressure": "one slow unit family", "telegraph": "source beacon and route preview", "completion": "all spawned units resolved", "cleanup": "clear residual targets and claims"},
                {"name": "split wave", "new_pressure": "both lanes with one resistant family", "telegraph": "paired lane countdown", "completion": "all units resolved or core fails", "cleanup": "invalidate wave generation before build phase"},
            ],
            "build_or_choice_slots": "Pads expose legal choices, range or lane role, occupancy, upgrade path, and refund policy.",
            "resource_cycle": "Reward resolved threats once, show spendable value, and keep one recovery option before each wave.",
            "target_and_path_authority": "One wave controller owns route generation; defenses acquire only legal current-generation targets.",
            "leak_and_failure": "Each unit can leak once; core damage, wave completion, and failure have explicit priority.",
            "multiplayer_ownership": "Purchases and upgrades use atomic pad claims with disconnect release and shared contribution feedback.",
            "terminal_and_reset": "Stop spawning and targeting, clear units and claims, restore core and resources, then create a fresh wave generation.",
        },
        "stealth_infiltration": {
            "detection_states": ["UNSEEN", "SUSPICIOUS", "ALERT", "SEARCHING", "RESETTING"],
            "sensors": [
                {"name": "patrol cone", "range_or_rule": "line of sight inside the marked cone", "telegraph": "moving light and patrol facing", "counterplay": "break sight behind declared cover", "recovery": "search last seen point then return to route"},
            ],
            "readable_cover": "Cover silhouettes, gaps, peek edges, and unsafe reflective surfaces remain legible from the player camera.",
            "player_tools_and_costs": "Distraction, concealment, and sprint each declare range, duration, cooldown, and information cost.",
            "suspicion_feedback": "World-space direction, state color plus shape, and escalation pulse come from the authoritative detector state.",
            "objective_and_exfiltration": "The objective commits once; exfiltration unlocks only from that snapshot and remains spatially visible.",
            "alert_recovery": "Alert locks shortcuts, starts a readable search, then restores sensors without duplicating objectives.",
            "multiplayer_information": "Shared alerts are global; private detection direction stays per-player and disconnects release team locks.",
            "terminal_and_reset": "Clear suspicion, search targets, distractions, objective locks, and old sensor callbacks before restart.",
        },
        "turn_based_strategy": {
            "turn_authority": "One match controller owns active player, phase, action index, board generation, and settlement.",
            "phases": ["START", "ACTION", "RESOLVE", "END"],
            "legal_actions": [
                {"name": "place piece", "precondition": "active turn and valid empty cell", "cost": "one action and declared resource", "effect": "claim the cell", "feedback": "preview then committed board pulse"},
                {"name": "use ability", "precondition": "active turn and legal target", "cost": "ability charge", "effect": "modify one board relation", "feedback": "source, target, and resource change together"},
            ],
            "board_state_feedback": "Active side, legal targets, committed ownership, pending resolution, and history are readable without relying on prose alone.",
            "resource_and_ownership": "Costs, pieces, cells, and effects commit under the active turn transaction exactly once.",
            "hidden_information": "Private hands or intentions never leak through shared UI, world props, spectators, or discarded state.",
            "resolution_order": "Validate action, reserve resources, apply effects in declared order, check terminal, then advance turn.",
            "timeout_and_disconnect": "Use a declared pass, bot, reassignment, or safe abort without leaving the board locked.",
            "terminal_draw_and_reset": "Define win, no-action draw, simultaneous terminal priority, rematch consent, and full board-generation cleanup.",
        },
        "sports_match": {
            "teams": [
                {"name": "cyan", "spawn_or_side": "west half", "color_or_shape": "cyan circle"},
                {"name": "pink", "spawn_or_side": "east half", "color_or_shape": "pink triangle"},
            ],
            "play_object_states": ["FREE", "CONTROLLED", "CONTESTED", "DEAD", "RESETTING"],
            "field_zones": [
                {"name": "cyan goal", "role": "pink scoring target", "restart": "center kickoff"},
                {"name": "midfield", "role": "neutral contest and kickoff", "restart": "nearest legal mark"},
                {"name": "pink goal", "role": "cyan scoring target", "restart": "center kickoff"},
            ],
            "possession_and_contact": "One authority resolves simultaneous touch, control transfer, tackle immunity, and object generation.",
            "out_of_bounds_restart": "Dead-ball state freezes scoring, indicates restart ownership and mark, then releases play once.",
            "scoring_commit": "Validate object identity, legal goal direction, play state, and score once before resetting possession.",
            "spawn_and_kickoff": "Team spawns, minimum safe separation, control lock, countdown, and first legal touch are explicit.",
            "illegal_play": "Own-goal, wrong-side, spawn block, stale object, and player disconnect use declared penalty or neutral reset.",
            "tie_overtime_and_reset": "A tie enters one short neutral objective; settlement clears scores, objects, occupancy, and old callbacks.",
        },
        "sandbox_creation": {
            "creation_loop": "browse -> preview -> validate -> commit -> select -> revise -> test or showcase",
            "catalog_categories": [
                {"name": "structure", "purpose": "walkable mass and enclosure", "budget": "declared per-world share"},
                {"name": "interaction", "purpose": "player-authored activity or mechanism", "budget": "declared dynamic and logic share"},
                {"name": "decoration", "purpose": "identity and composition", "budget": "declared visible-detail share"},
            ],
            "build_states": ["PREVIEW", "VALID", "COMMITTED", "SELECTED", "REMOVED"],
            "placement_validation": "Bounds, overlap, support, protected zones, collision, and per-category quota resolve before commit.",
            "ownership_and_permissions": "Every object records owner and generation; edit, move, duplicate, and delete permissions are explicit.",
            "budget_limits": "World and per-player budgets show current, projected, and blocked cost before commit.",
            "undo_delete": "Undo targets the latest legal authored transaction; delete frees ownership, occupancy, references, and budget once.",
            "save_and_reload": "Serialize stable authored state, version it, reject partial snapshots, and rebuild references in a declared load order.",
            "showcase_or_test": "Test mode freezes authoring authority; returning restores edit state without duplicating creations.",
            "exit_and_cleanup": "Release selections, previews, edit locks, temporary tests, and unsaved-generation callbacks on exit.",
        },
        "social_deduction": {
            "round_authority": "One round controller owns generation, roles, phase, living roster, task or evidence state, meetings, votes, and terminal lock.",
            "role_set": [
                {
                    "name": "crew investigator",
                    "alignment": "crew",
                    "private_knowledge": "own role and completed private observations",
                    "exclusive_action": "complete tasks and submit one evidence observation",
                    "public_counterplay": "actions consume time in exposed world locations",
                },
                {
                    "name": "saboteur",
                    "alignment": "saboteur",
                    "private_knowledge": "saboteur team and available sabotage state",
                    "exclusive_action": "create one bounded disruption or elimination opportunity",
                    "public_counterplay": "cooldown, spatial exposure, repair, reporting, and vote",
                },
            ],
            "assignment_and_secrecy": "Assign exactly one current-generation role per player, reveal only permitted knowledge, and never mirror private state into shared props or spectator UI.",
            "phase_cycle": ["BRIEF", "FIELD", "REPORT_LOCK", "DISCUSS", "VOTE", "RESOLVE", "TERMINAL_OR_FIELD"],
            "tasks_or_evidence": [
                {
                    "name": "power routing task",
                    "owner_scope": "one living crew player with a shared completion result",
                    "progress_rule": "validate station, role permission, generation, and one commit ID",
                    "public_feedback": "station changes visibly without exposing the actor's full role",
                    "duplication_guard": "the task ID contributes once per round",
                    "recovery": "release an abandoned station and preserve only committed progress",
                },
                {
                    "name": "incident observation",
                    "owner_scope": "the observing living player until a legal meeting",
                    "progress_rule": "record bounded source, time window, and confidence without inventing hidden truth",
                    "public_feedback": "meeting shows the submitted observation source, not private system logs",
                    "duplication_guard": "one observation ID can be submitted once",
                    "recovery": "discard stale or prior-generation observations",
                },
            ],
            "meeting_and_reporting": "A valid report atomically freezes field actions, releases occupied stations, gathers eligible players, opens a bounded discussion state, and blocks duplicate reports.",
            "voting_commit": "Accept at most one current-generation vote per eligible living player, reveal only declared aggregates, resolve skip or tie once, then clear ballot state.",
            "elimination_and_afterlife": "Removed players lose report, vote, sabotage, collision, and outcome-changing actions; any afterlife tasks or spectating cannot leak private information or alter the terminal unless explicitly declared.",
            "win_predicates": [
                {
                    "alignment": "crew",
                    "predicate": "all required crew progress is committed or every saboteur is legally removed",
                    "priority": "evaluate after the current atomic action or vote resolution",
                    "terminal_feedback": "lock the roster and show the contributing public state",
                },
                {
                    "alignment": "saboteur",
                    "predicate": "declared parity or an unresolved critical sabotage reaches its terminal",
                    "priority": "use the documented same-frame order against crew completion",
                    "terminal_feedback": "lock the roster and show which public predicate resolved",
                },
            ],
            "disconnect_and_fill": "Release tasks, stations, votes, and cooldown claims; use a declared reassignment, neutralization, bot, or safe abort without exposing the role.",
            "terminal_and_reset": "Lock one terminal, cancel field and meeting inputs, reveal only end-state information, clear private UI and objects, then assign a fresh generation for rematch.",
        },
    }
    result = dict(common)
    result.update(values[type_name])
    return result


def _modifier_example(modifier: str) -> dict[str, Any]:
    common = {
        "purpose": f"Change the primary loop with {modifier} without owning a second terminal.",
        "precondition": "The primary loop is active and its safe introduction is complete.",
        "feedback": "The authoritative state and its spatial feedback change together.",
        "failure_recovery": "Return to the latest valid primary-loop state.",
        "reset": "Cancel the current generation, delayed actions, and temporary feedback.",
    }
    values: dict[str, dict[str, Any]] = {
        "rising_pressure": {
            "metric": "pressure_margin",
            "authority": "ROUND authorizes pressure start, pause, settlement, and cancellation.",
            "start_gate": "Start only after control and one safe route read.",
            "pressure_reference": "A persistent world-height marker shows current and near-future pressure.",
            "pace_samples": ["slow valid route", "median route", "fast route"],
            "checkpoint_relation": "A checkpoint cannot respawn behind the committed pressure frontier.",
            "contact_or_timeout": "Contact uses the declared recovery or elimination branch once.",
            "terminal_priority": "A committed legal finish wins a same-frame pressure contact.",
            "cleanup": "Stop motion and clear old pressure callbacks before settlement or reentry.",
        },
        "escort_collection": {
            "metric": "object_recovery_time",
            "object_identity": "Each required object has a stable unique identity and generation.",
            "object_states": ["AVAILABLE", "HELD_OR_FOLLOWING", "DELIVERING", "COMMITTED", "RECOVERING"],
            "ownership": "One player, team, or world authority owns the object at a time.",
            "visible_progress": "Object position and remaining delivery slots are visible in the world.",
            "legal_area": "Every route segment names its legal object bounds and recovery beacon.",
            "delivery_commit": "Validate identity and ownership, consume once, update world progress, then release occupancy.",
            "duplicate_prevention": "A committed object ID cannot increment progress again.",
            "lost_object_recovery": "Out-of-bounds, orphaned, or stuck objects return to the latest valid beacon.",
            "checkpoint_snapshot": "Commit player, object generation, ownership, and completed deliveries atomically.",
            "terminal_cleanup": "Release claims and remove uncommitted prior-generation objects.",
        },
        "vehicles": {
            "metric": "vehicle_control_margin",
            "vehicle_envelope": "Record body, collision, wheelbase, sweep, and passenger envelope on the target version.",
            "mount_dismount": "Reserve a clear bay and define interruption, occupancy, and control handoff.",
            "calibration_profiles": [
                {"name": "low speed", "turn_radius": "measured", "stopping_distance": "measured", "camera": "measured", "clearance": "measured"},
                {"name": "mid speed", "turn_radius": "measured", "stopping_distance": "measured", "camera": "measured", "clearance": "measured"},
                {"name": "high speed", "turn_radius": "measured", "stopping_distance": "measured", "camera": "measured", "clearance": "measured"},
            ],
            "camera_envelope": "Test follow-camera clipping, look-ahead, roll, and obstruction through every route family.",
            "route_rules": "Widths, bends, slopes, tunnels, rails, and brake zones derive from the measured vehicle envelope.",
            "collision_and_traffic": "Define overtaking, opposing flow, spawn blocking, and player/vehicle collision policy.",
            "respawn_or_replacement": "A stuck, destroyed, missing, or abandoned vehicle returns to a free recovery pocket.",
            "terminal_cleanup": "Release occupancy and stop or remove the current-generation vehicle after settlement.",
        },
        "asymmetric_roles": {
            "metric": "role_outcome_gap",
            "roles": [
                {"name": "seeker", "information": "recent traces", "exclusive_ability": "short scan", "vulnerability": "scan reveals position", "counterplay": "hider breaks line of sight", "objective": "confirm targets"},
                {"name": "hider", "information": "safe-zone decay", "exclusive_ability": "one decoy", "vulnerability": "must relocate", "counterplay": "seeker checks decoy tells", "objective": "survive settlement"},
            ],
            "assignment": "Assign and acknowledge roles before private information or movement begins.",
            "information_boundary": "Private cues never leak through shared UI, spawn view, audio, or spectators.",
            "contact_or_scoring": "One authority validates contact, ownership, cooldown, and score exactly once.",
            "role_fill": "Late join, missing role, and disconnect use an explicit bot, reassignment, or safe abort branch.",
            "terminal_and_draw": "Define simultaneous contact/time priority and a no-target draw.",
            "round_reset": "Clear roles, private cues, cooldowns, decoys, scores, and spectator knowledge.",
        },
        "rhythm": {
            "metric": "timing_error_distribution",
            "authoritative_clock": "One sequence clock owns cue position, judgement, combo, pause, and finish.",
            "cue_lead": "Spawn visual and audio cues early enough for the tested travel and device latency.",
            "audio_visual_sync": "Both cue channels derive from the same timestamp and generation.",
            "judgement_windows": ["perfect", "good", "miss"],
            "input_deduplication": "One physical input edge can resolve one active note at most once.",
            "miss_and_combo": "Early, late, duplicate, and missed inputs update one authoritative combo transaction.",
            "latency_calibration": "Measure low, median, and high target-device latency before fixing windows.",
            "mute_fallback": "Every required note has an anticipatory visual cue and distinct result feedback.",
            "sequence_reset": "Pause, exit, death, and next sequence invalidate old notes, inputs, and callbacks.",
        },
        "horror": {
            "metric": "post_reveal_reorientation_time",
            "readability_floor": "Required footing, exits, interaction faces, and active threats keep minimum contrast.",
            "tension_beats": ["safe", "anticipate", "reveal", "consequence", "release"],
            "threat_contract": "Threat telegraph, active rule, counteraction, end, and cooldown share one state source.",
            "safe_space": "Declared safe rooms stay safe until a separately telegraphed contract change.",
            "reveal_cooldown": "Repeated entries cannot immediately replay or stack the same reveal.",
            "control_and_camera": "Forced framing preserves a safe player state and restores direction afterward.",
            "sensory_fallback": "Required information remains available without audio or rapid flashing.",
            "recovery": "Death, skip, or interruption returns to a coherent pre- or post-reveal state.",
            "session_cleanup": "Clear threats, overlays, forced camera, audio loops, and reveal locks on exit.",
        },
        "vertical_climb": {
            "metric": "maximum_fall_recovery_time",
            "layers": [
                {"name": "lower layer", "upward_goal": "lit gantry", "fall_destination": "lower catch", "camera_risk": "overhead slab", "recovery": "lower checkpoint"},
                {"name": "upper layer", "upward_goal": "roof beacon", "fall_destination": "mid catch", "camera_risk": "tight shaft", "recovery": "upper checkpoint"},
            ],
            "upward_target": "Current and next layer landmarks remain visible from each committed landing.",
            "fall_graph": "Every fall volume resolves to a named catch, checkpoint, or terminal branch.",
            "head_clearance": "Jumps and moving platforms preserve measured head and camera clearance.",
            "camera_envelope": "Test upward aim, landing view, overhead occlusion, long fall, and rapid turn.",
            "shortcut_guard": "Cross-layer skips are either legal authored routes or return to the last valid layer.",
            "recovery": "Long falls resolve quickly and never restore above an uncommitted checkpoint.",
            "terminal_cleanup": "Stop vertical hazards and invalidate old fall/teleport callbacks.",
        },
        "random_variation": {
            "metric": "invalid_or_unreadable_roll_rate",
            "authority_and_seed": "One controller owns seed, selection, generation, and replay policy.",
            "candidate_pool": ["validated layout A", "validated layout B", "validated layout C"],
            "solvability_filter": "Filter by reaction path, required ability, spawn, and current world state before commit.",
            "compatibility_matrix": "Evaluate combined field, weather, item, and player-state candidates before selection.",
            "telegraph": "The committed result drives one readable preview before becoming active.",
            "fairness": "All affected players receive the same authoritative result and adequate reaction opportunity.",
            "generation_id": "Spawned objects, timers, and feedback carry the current random generation.",
            "fallback": "Use a tested deterministic candidate when filtering leaves no valid result.",
            "cleanup": "Cancel old generation callbacks and remove its spawned or moved state before reroll.",
        },
        "cumulative_growth": {
            "metric": "highest_tier_control",
            "input_event": "grounded jump edge",
            "deduplication": "one count per grounded jump cycle",
            "authoritative_value": "clamped player growth value",
            "clamp_or_cap": "hard cap at the tested highest tier",
            "feedback_tiers": ["low", "mid", "high"],
            "checkpoint_policy": "atomically save position and growth tier",
            "spatial_calibration_levels": ["minimum", "middle", "maximum"],
            "terminal_cleanup": "restore default movement before settlement",
        },
        "destructible_world": {
            "metric": "destruction_commit_error_rate",
            "authority": "One OBJECT controller owns target damage, completion, reward, collision, and cancellation for the current generation.",
            "target_identity": "Each target has a stable target ID, room or group ID, and generation independent of its visible model.",
            "target_states": ["INTACT", "DAMAGED", "CRITICAL", "COMMITTED_DESTROYED"],
            "valid_damage_sources": ["declared player tool hit"],
            "hit_deduplication": "One physical input and target pair advances damage at most once in the declared hit window.",
            "damage_or_progress_rule": "Validate phase, generation, source, cooldown, and remaining state before applying clamped progress.",
            "destruction_commit": "Atomically lock the target or room, change collision, resolve dependencies, grant one reward, and request the primary terminal check.",
            "dependency_groups": [
                {
                    "name": "room shell completion",
                    "prerequisite": "all required current-generation wall targets are committed",
                    "commit": "resolve the declared floor, ceiling, route, and feedback result once",
                    "cycle_guard": "dependencies form a directed acyclic graph with one owner per shared surface",
                    "failure_recovery": "move or protect players before a dependent contact surface changes",
                }
            ],
            "collision_transition": "The visible state and collision version switch from one authoritative commit with a safe contact branch.",
            "debris_budget": {
                "spawned_peak": 24,
                "lifetime": "bounded and measured on the target device",
                "collision_policy": "visual debris is non-blocking unless a tested gameplay role requires collision",
                "cleanup": "expire or pool current-generation debris and invalidate it on terminal or reset",
            },
            "checkpoint_policy": "Save only a complete destruction snapshot or rebuild a coherent room state; never mix damaged visuals with intact rewards or collision.",
            "terminal_priority": "The primary loop terminal lock resolves before any late damage, reward, dependency, or debris callback.",
            "cleanup": "Invalidate old hits, remove or pool debris, restore target and collision versions as declared, and clear completion locks.",
        },
    }
    if modifier not in values:
        raise DesignPlanError(f"unknown modifier {modifier}")
    result = dict(common)
    result.update(values[modifier])
    return result


def _attach_example_modifier(plan: dict[str, Any], modifier: str) -> None:
    contract = _modifier_example(modifier)
    plan["modifiers"] = [modifier]
    plan["modifier_contracts"] = {modifier: contract}
    metric = contract["metric"]
    plan["verification"]["metrics"][metric] = {
        "status": "tested",
        "method": "record the modifier-specific target-device metric",
        "target_or_result": "within the declared envelope",
    }
    for scenario in MODIFIER_SCENARIOS[modifier]:
        plan["verification"]["scenarios"][scenario] = {
            "status": "tested",
            "method": "run the named modifier scenario",
            "target_or_result": "pass",
        }


def _example_profile(type_name: str) -> dict[str, Any]:
    profiles = {
        "short_race": ([1, 4], [90, 120], ["run", "jump"], "cross the legal finish fastest"),
        "chapter_challenge": ([1, 4], [300, 900], ["move", "master"], "complete every committed chapter"),
        "mechanism_puzzle": ([1, 4], [180, 600], ["observe", "operate"], "apply the learned rule and open the result gate"),
        "cooperative": ([2, 4], [180, 600], ["help", "handoff"], "complete the shared terminal through reciprocal actions"),
        "narrative_exploration": ([1, 4], [300, 1200], ["explore", "observe"], "resolve the spatial event and find a clear exit"),
        "survival": ([2, 8], [90, 180], ["dodge", "position"], "reach the declared survival terminal"),
        "score_contest": ([2, 8], [120, 300], ["collect", "contest", "deliver"], "hold the highest legal score at settlement"),
        "social_showcase": ([1, 16], [300, 1800], ["explore", "express", "return"], "complete an activity loop and retain a clear exit"),
        "management_simulation": ([1, 4], [300, 900], ["produce", "route", "upgrade"], "complete production milestones without a resource soft-lock"),
        "rhythm_performance": ([1, 4], [120, 300], ["read", "tap", "hold"], "finish the authored sequence through legal timed inputs"),
        "combat_boss": ([1, 4], [180, 600], ["observe", "dodge", "attack"], "defeat the boss through readable counters without a state leak"),
        "defense_strategy": ([1, 4], [300, 900], ["build", "route", "adapt"], "protect the declared core through every committed wave"),
        "stealth_infiltration": ([1, 4], [180, 600], ["observe", "hide", "infiltrate"], "commit the objective and reach exfiltration under the detection contract"),
        "turn_based_strategy": ([2, 8], [120, 600], ["inspect", "choose", "resolve"], "reach the authoritative board terminal through legal turns"),
        "sports_match": ([2, 12], [180, 600], ["position", "pass", "score"], "win the settled match through legal scoring plays"),
        "sandbox_creation": ([1, 8], [300, 1800], ["place", "iterate", "show"], "author and retain a valid creation within permissions and budget"),
        "social_deduction": ([4, 12], [300, 900], ["observe", "act", "infer"], "resolve the authoritative alignment terminal without leaking private state"),
    }
    players, duration, verbs, success = profiles[type_name]
    return {
        "player_range": players,
        "target_duration_seconds": duration,
        "main_verbs": verbs,
        "success": success,
    }


def _topology_example(type_name: str) -> dict[str, Any]:
    specs: dict[str, tuple[str, str, list[str], list[str], list[tuple[str, str, str]], dict[str, str]]] = {
        "short_race": (
            "linear_chain", "START", ["FINISH"], ["SAFE"],
            [("START", "TEACH", "critical"), ("TEACH", "SAFE", "critical"), ("SAFE", "CLIMAX", "critical"), ("CLIMAX", "SAFE", "recovery"), ("CLIMAX", "FINISH", "critical")],
            {"START": "spawn", "TEACH": "teaching", "SAFE": "recovery", "CLIMAX": "risk", "FINISH": "terminal"},
        ),
        "chapter_challenge": (
            "linear_chain", "START", ["FINISH"], ["CP1"],
            [("START", "CHAPTER1", "critical"), ("CHAPTER1", "CP1", "critical"), ("CP1", "CHAPTER2", "critical"), ("CHAPTER2", "CP1", "recovery"), ("CHAPTER2", "FINISH", "critical")],
            {"START": "spawn", "CHAPTER1": "chapter", "CP1": "checkpoint", "CHAPTER2": "chapter", "FINISH": "terminal"},
        ),
        "mechanism_puzzle": (
            "branch_and_rejoin", "START", ["FINISH"], ["RESET"],
            [("START", "SHOW", "critical"), ("SHOW", "TEST", "critical"), ("TEST", "RESET", "recovery"), ("RESET", "TEST", "return"), ("TEST", "FINISH", "critical")],
            {"START": "spawn", "SHOW": "teaching", "TEST": "decision", "RESET": "recovery", "FINISH": "terminal"},
        ),
        "cooperative": (
            "branch_and_rejoin", "START", ["FINISH"], ["REGROUP"],
            [("START", "ROLE_BIND", "critical"), ("ROLE_BIND", "HANDOFF", "handoff"), ("HANDOFF", "REGROUP", "critical"), ("REGROUP", "HANDOFF", "recovery"), ("REGROUP", "FINISH", "critical")],
            {"START": "spawn", "ROLE_BIND": "role binding", "HANDOFF": "handoff", "REGROUP": "recovery", "FINISH": "terminal"},
        ),
        "narrative_exploration": (
            "hub_and_spoke", "START", ["EXIT"], ["HUB"],
            [("START", "HUB", "critical"), ("HUB", "ARCHIVE", "optional"), ("ARCHIVE", "HUB", "return"), ("HUB", "TOWER", "critical"), ("TOWER", "EXIT", "critical")],
            {"START": "spawn", "HUB": "landmark", "ARCHIVE": "event", "TOWER": "event", "EXIT": "terminal"},
        ),
        "survival": (
            "arena", "PREPARE", ["RESULT"], ["SPECTATE"],
            [("PREPARE", "ARENA", "critical"), ("ARENA", "SPECTATE", "recovery"), ("ARENA", "RESULT", "critical"), ("SPECTATE", "RESULT", "critical")],
            {"PREPARE": "spawn", "ARENA": "risk", "SPECTATE": "spectating", "RESULT": "terminal"},
        ),
        "score_contest": (
            "arena", "START", ["RESULT"], ["RESOURCE"],
            [("START", "RESOURCE", "critical"), ("RESOURCE", "HOTSPOT", "optional"), ("RESOURCE", "SCORE", "critical"), ("HOTSPOT", "SCORE", "critical"), ("SCORE", "RESOURCE", "return"), ("SCORE", "RESULT", "critical")],
            {"START": "spawn", "RESOURCE": "resource", "HOTSPOT": "conflict", "SCORE": "score", "RESULT": "terminal"},
        ),
        "social_showcase": (
            "hub_and_spoke", "START", ["EXIT"], ["CENTER"],
            [("START", "CENTER", "critical"), ("CENTER", "PHOTO", "optional"), ("PHOTO", "CENTER", "return"), ("CENTER", "MUSIC", "optional"), ("MUSIC", "CENTER", "return"), ("CENTER", "EXIT", "critical")],
            {"START": "spawn", "CENTER": "landmark", "PHOTO": "activity", "MUSIC": "activity", "EXIT": "terminal"},
        ),
        "management_simulation": (
            "open_network", "START", ["RESULT"], ["INPUT"],
            [("START", "INPUT", "critical"), ("INPUT", "PROCESS", "critical"), ("PROCESS", "DELIVER", "critical"), ("DELIVER", "INPUT", "return"), ("DELIVER", "UPGRADE", "optional"), ("UPGRADE", "INPUT", "return"), ("DELIVER", "RESULT", "critical")],
            {"START": "spawn", "INPUT": "resource", "PROCESS": "workstation", "DELIVER": "delivery", "UPGRADE": "choice", "RESULT": "terminal"},
        ),
        "rhythm_performance": (
            "linear_chain", "START", ["RESULT"], ["CALIBRATE"],
            [("START", "CALIBRATE", "critical"), ("CALIBRATE", "SEQUENCE", "critical"), ("SEQUENCE", "CALIBRATE", "recovery"), ("SEQUENCE", "RESULT", "critical")],
            {"START": "spawn", "CALIBRATE": "recovery", "SEQUENCE": "performance", "RESULT": "terminal"},
        ),
        "combat_boss": (
            "arena", "START", ["RESULT"], ["SAFE"],
            [("START", "TEACH", "critical"), ("TEACH", "ARENA", "critical"), ("ARENA", "SAFE", "recovery"), ("SAFE", "ARENA", "return"), ("ARENA", "RESULT", "critical")],
            {"START": "spawn", "TEACH": "teaching", "ARENA": "combat", "SAFE": "recovery", "RESULT": "terminal"},
        ),
        "defense_strategy": (
            "open_network", "START", ["RESULT"], ["BUILD"],
            [("START", "BUILD", "critical"), ("BUILD", "LANES", "critical"), ("LANES", "WAVE", "critical"), ("WAVE", "BUILD", "return"), ("WAVE", "RESULT", "critical")],
            {"START": "spawn", "BUILD": "recovery", "LANES": "route", "WAVE": "defense", "RESULT": "terminal"},
        ),
        "stealth_infiltration": (
            "branch_and_rejoin", "START", ["EXIT"], ["ALERT"],
            [("START", "BRIEF", "critical"), ("BRIEF", "ROUTE", "critical"), ("ROUTE", "OBJECTIVE", "critical"), ("ROUTE", "ALERT", "recovery"), ("ALERT", "ROUTE", "return"), ("OBJECTIVE", "EXIT", "critical")],
            {"START": "spawn", "BRIEF": "teaching", "ROUTE": "infiltration", "ALERT": "recovery", "OBJECTIVE": "commit", "EXIT": "terminal"},
        ),
        "turn_based_strategy": (
            "arena", "SETUP", ["RESULT"], ["TURN"],
            [("SETUP", "TURN", "critical"), ("TURN", "RESOLVE", "critical"), ("RESOLVE", "TURN", "return"), ("RESOLVE", "RESULT", "critical")],
            {"SETUP": "spawn", "TURN": "recovery", "RESOLVE": "resolution", "RESULT": "terminal"},
        ),
        "sports_match": (
            "arena", "KICKOFF", ["RESULT"], ["DEADBALL"],
            [("KICKOFF", "FIELD", "critical"), ("FIELD", "DEADBALL", "recovery"), ("DEADBALL", "FIELD", "return"), ("FIELD", "RESULT", "critical")],
            {"KICKOFF": "spawn", "FIELD": "match", "DEADBALL": "recovery", "RESULT": "terminal"},
        ),
        "sandbox_creation": (
            "open_network", "START", ["EXIT"], ["BUILD"],
            [("START", "CATALOG", "critical"), ("CATALOG", "BUILD", "critical"), ("BUILD", "TEST", "critical"), ("TEST", "BUILD", "return"), ("TEST", "SHOWCASE", "optional"), ("SHOWCASE", "BUILD", "return"), ("SHOWCASE", "EXIT", "critical")],
            {"START": "spawn", "CATALOG": "selection", "BUILD": "recovery", "TEST": "test", "SHOWCASE": "showcase", "EXIT": "terminal"},
        ),
        "social_deduction": (
            "open_network", "BRIEF", ["RESULT"], ["MEETING", "AFTERLIFE"],
            [("BRIEF", "FIELD", "critical"), ("FIELD", "TASK", "optional"), ("TASK", "FIELD", "return"), ("FIELD", "MEETING", "handoff"), ("MEETING", "FIELD", "return"), ("FIELD", "AFTERLIFE", "recovery"), ("MEETING", "AFTERLIFE", "recovery"), ("FIELD", "RESULT", "critical"), ("MEETING", "RESULT", "critical"), ("AFTERLIFE", "RESULT", "critical")],
            {"BRIEF": "private role assignment", "FIELD": "social deduction field", "TASK": "task or evidence station", "MEETING": "discussion and vote", "AFTERLIFE": "spectating or bounded afterlife", "RESULT": "terminal"},
        ),
    }
    kind, entry, terminals, recovery, edges, nodes = specs[type_name]
    return {
        "kind": kind,
        "entry": entry,
        "terminals": terminals,
        "recovery_nodes": recovery,
        "nodes": [{"name": name, "role": role} for name, role in nodes.items()],
        "edges": [{"from": source, "to": target, "kind": edge_kind} for source, target, edge_kind in edges],
    }


def _beats_example(type_name: str) -> list[dict[str, Any]]:
    names = {
        "short_race": [("orient", "read start"), ("flow", "move continuously"), ("vary", "adapt route"), ("climax", "combine movement")],
        "chapter_challenge": [("orient", "read chapter goal"), ("chapter1", "learn action"), ("checkpoint", "commit progress"), ("chapter2", "apply variation")],
        "mechanism_puzzle": [("show", "observe result"), ("verify", "operate once"), ("vary", "change one variable"), ("combine", "apply learned rules")],
        "cooperative": [("bind", "learn roles"), ("a_helps", "create opportunity"), ("b_returns", "return help"), ("converge", "finish together")],
        "narrative_exploration": [("orient", "read landmark"), ("discover", "find event"), ("change", "alter world"), ("return", "recognize consequence")],
        "survival": [("prepare", "read danger"), ("teach", "dodge one hazard"), ("escalate", "reposition"), ("terminal", "survive settlement")],
        "score_contest": [("resource", "choose route"), ("conflict", "contest hotspot"), ("score", "deliver legally"), ("settle", "read result")],
        "social_showcase": [("orient", "choose landmark"), ("arrive", "enter activity"), ("express", "use activity"), ("return", "rejoin or exit")],
        "management_simulation": [("input", "acquire resource"), ("process", "operate station"), ("deliver", "complete output"), ("upgrade", "change next loop")],
        "rhythm_performance": [("calibrate", "read timing reference"), ("phrase", "resolve simple notes"), ("variation", "adapt to added note form"), ("finale", "complete the combined sequence")],
        "combat_boss": [("read", "learn one telegraph"), ("counter", "survive and expose weakness"), ("escalate", "combine learned attacks"), ("defeat", "commit the encounter terminal")],
        "defense_strategy": [("build", "choose initial defense"), ("wave", "read lane pressure"), ("adapt", "spend and reposition"), ("hold", "resolve the final wave")],
        "stealth_infiltration": [("observe", "read patrol and cover"), ("cross", "use the first safe gap"), ("objective", "commit the target"), ("exfiltrate", "adapt to the return state")],
        "turn_based_strategy": [("setup", "read board ownership"), ("choose", "commit a legal action"), ("resolve", "understand ordered effects"), ("settle", "reach win or draw")],
        "sports_match": [("kickoff", "reach the play object"), ("contest", "gain or transfer possession"), ("score", "complete a legal play"), ("settle", "resolve regulation or overtime")],
        "sandbox_creation": [("browse", "choose a category"), ("place", "preview and commit"), ("iterate", "move undo or delete"), ("show", "test save or present")],
        "social_deduction": [("brief", "read only permitted role information"), ("field", "act and observe in public space"), ("meeting", "report discuss and commit one vote"), ("resolve", "return to field or settle one alignment terminal")],
    }[type_name]
    seconds_by_type = {
        "short_race": [20, 25, 30, 35],
        "chapter_challenge": [75, 90, 110, 125],
        "mechanism_puzzle": [35, 45, 50, 60],
        "cooperative": [40, 50, 60, 70],
        "narrative_exploration": [70, 85, 100, 125],
        "survival": [20, 25, 30, 35],
        "score_contest": [30, 35, 45, 50],
        "social_showcase": [70, 90, 110, 130],
        "management_simulation": [60, 80, 100, 120],
        "rhythm_performance": [25, 35, 45, 55],
        "combat_boss": [40, 55, 70, 80],
        "defense_strategy": [70, 90, 110, 130],
        "stealth_infiltration": [40, 55, 65, 80],
        "turn_based_strategy": [30, 45, 55, 70],
        "sports_match": [45, 60, 75, 90],
        "sandbox_creation": [80, 100, 120, 140],
        "social_deduction": [45, 120, 90, 60],
    }
    seconds = seconds_by_type[type_name]
    return [
        {
            "name": name,
            "owner": "primary",
            "information": action,
            "action": action,
            "consequence": "advance or use the declared recovery",
            "feedback": "same-source spatial and state feedback",
            "target_seconds": seconds[index],
        }
        for index, (name, action) in enumerate(names)
    ]


def _example_assembly_budget(type_name: str) -> dict[str, Any]:
    expanded_by_type = {
        "short_race": 1200,
        "chapter_challenge": 2600,
        "mechanism_puzzle": 1100,
        "cooperative": 1600,
        "narrative_exploration": 2200,
        "survival": 1000,
        "score_contest": 1000,
        "social_showcase": 2200,
        "management_simulation": 1800,
        "rhythm_performance": 1200,
        "combat_boss": 1400,
        "defense_strategy": 1400,
        "stealth_infiltration": 1500,
        "turn_based_strategy": 1000,
        "sports_match": 1250,
        "sandbox_creation": 1000,
        "social_deduction": 1600,
    }
    expanded = expanded_by_type[type_name]
    density_profile = (
        "multi_scene"
        if type_name in {"chapter_challenge", "narrative_exploration", "social_showcase"}
        else "themed_short"
    )
    layer_weights = {
        "COL": 0.08,
        "MASS": 0.25,
        "MID": 0.35,
        "ROUTE": 0.10,
        "MECH": 0.06,
        "PROP": 0.08,
        "FX": 0.03,
        "LOGIC": 0.02,
    }
    layers = {key: int(expanded * weight) for key, weight in layer_weights.items()}
    layers["SAFE"] = expanded - sum(layers.values())
    return {
        "density_profile": density_profile,
        "density_profile_evidence": (
            "multiple physically distinct chapters or scenes with independent world shells"
            if density_profile == "multi_scene"
            else "one continuous themed play space with a publish-ready world shell"
        ),
        "graybox_total": max(80, int(expanded * 0.10)),
        "expanded_total": expanded,
        "asset_vocabulary_count": 24,
        "layers": layers,
    }


def _world_shell_examples(
    type_name: str, theme: dict[str, Any]
) -> list[dict[str, Any]]:
    topology = _topology_example(type_name)
    all_nodes = [str(item["name"]) for item in topology["nodes"]]
    all_beats = [str(item["name"]) for item in _beats_example(type_name)]
    multi_scene_groups: dict[str, list[tuple[str, list[str], list[str]]]] = {
        "chapter_challenge": [
            ("LOWER_GREENHOUSE", ["START", "CHAPTER1", "CP1"], ["orient", "chapter1", "checkpoint"]),
            ("TITAN_CROWN", ["CP1", "CHAPTER2", "FINISH"], ["chapter2"]),
        ],
        "narrative_exploration": [
            ("FLOODED_CIVIC_HUB", ["START", "HUB", "ARCHIVE"], ["orient", "discover"]),
            ("CLOCK_TOWER_RETURN", ["HUB", "TOWER", "EXIT"], ["change", "return"]),
        ],
        "social_showcase": [
            ("WINTER_MARKET_CENTER", ["START", "CENTER", "PHOTO"], ["orient", "arrive"]),
            ("MUSIC_ISLAND_RETURN", ["CENTER", "MUSIC", "EXIT"], ["express", "return"]),
        ],
    }
    groups = multi_scene_groups.get(
        type_name,
        [(f"{type_name.upper()}_WORLD", all_nodes, all_beats)],
    )
    scale_anchors_by_type = {
        "short_race": ["player-height dock rail", "cargo door and mast hardware"],
        "chapter_challenge": ["walkable greenhouse service door", "titan hand larger than the whole route bay"],
        "mechanism_puzzle": ["waist-height input dais", "archive door with repeated measurement marks"],
        "cooperative": ["two-player handoff terrace", "canal gate sized against the shared bridge"],
        "narrative_exploration": ["street door and public bench", "clock face spanning several roofs"],
        "survival": ["door-and-window scale on paper blocks", "plaza monument visible above every roof"],
        "score_contest": ["courier-height pier rail", "lighthouse beam and dock crane"],
        "social_showcase": ["multi-player photo rail", "market stall door beneath the landmark tree"],
        "management_simulation": ["player-height repair bench", "launch gantry surrounding the whale kite"],
        "rhythm_performance": ["player-height hit-line ring", "antenna star spanning all note lanes"],
        "combat_boss": ["player-height recovery arch", "cathedral bell ribs framing the leviathan"],
        "defense_strategy": ["player-height build pad", "observatory lens wider than all defense lanes"],
        "stealth_infiltration": ["player-height archive shelf", "vault seal visible over multiple cover rows"],
        "turn_based_strategy": ["player podium and board cell", "resolution clock spanning the public board"],
        "sports_match": ["player-height field barrier", "goal ring and stand bay around the whole field"],
        "sandbox_creation": ["player work-grid cell", "launch iris framing the maximum valid build"],
        "social_deduction": ["player-height lab door", "meeting lens visible from branching research wings"],
    }
    theme_families = list(theme["assembly_families"])
    entry = str(topology["entry"])
    terminals = {str(item) for item in topology["terminals"]}
    result: list[dict[str, Any]] = []
    for index, (name, nodes, beats) in enumerate(groups):
        family_start = min(index * 2, max(0, len(theme_families) - 2))
        shell_families = theme_families[family_start : family_start + 3]
        if len(shell_families) < 2:
            shell_families = theme_families[:2]
        view_kind = "spawn" if entry in nodes else "entry"
        views = [
            {
                "name": f"{name}_{view_kind.upper()}",
                "kind": view_kind,
                "camera_intent": "establish the playable place, immediate action, and long-term direction after control is available",
                "must_show": ["main silhouette", "nearest legal action", "one scale anchor"],
            },
            {
                "name": f"{name}_ACTION",
                "kind": "action",
                "camera_intent": "keep the action origin, consequence, and recovery direction readable in the real play camera",
                "must_show": ["contact surface", "action result or threat", "exit or recovery frame"],
            },
        ]
        if terminals & set(nodes):
            views.append(
                {
                    "name": f"{name}_TERMINAL",
                    "kind": "terminal",
                    "camera_intent": "show the authoritative result without losing the world silhouette or voluntary exit",
                    "must_show": ["result focus", "changed world state", "safe exit or restart"],
                }
            )
        else:
            views.append(
                {
                    "name": f"{name}_REVEAL",
                    "kind": "reveal",
                    "camera_intent": "reward progress with the next shell while keeping the current route legible",
                    "must_show": ["new silhouette", "continuing route", "state change"],
                }
            )
        result.append(
            {
                "name": name,
                "topology_nodes": nodes,
                "beats": beats,
                "assembly_zones": [name],
                "silhouette": (
                    theme["memory_silhouette"]
                    if index == len(groups) - 1
                    else f"an approach silhouette that foreshadows {theme['memory_silhouette']}"
                ),
                "enclosure_strategy": (
                    f"{shell_families[0]} defines playable contact and side mass; "
                    f"{shell_families[1]} frames openings, while the memory silhouette remains a non-confusing long-term reference"
                ),
                "depth_layers": {
                    "foreground": f"contact edges and player-scale detail from {shell_families[0]}",
                    "midground": f"the next reachable action framed by {shell_families[1]}",
                    "background": f"a low-cost directional version of {theme['memory_silhouette']}",
                },
                "scale_anchors": scale_anchors_by_type[type_name],
                "assembly_families": shell_families,
                "state_variants": [
                    "baseline state before the local beat commits",
                    str(theme["world_state_change"]),
                ],
                "transition_in": (
                    "control begins in a safe camera pocket"
                    if entry in nodes
                    else "the previous silhouette is occluded only after this shell establishes its next action"
                ),
                "transition_out": (
                    "the authoritative result and safe exit remain readable"
                    if terminals & set(nodes)
                    else "a threshold preserves route language while changing silhouette, scale, or state"
                ),
                "review_views": views,
            }
        )
    return result


def _theme_example(type_name: str) -> dict[str, Any]:
    themes: dict[str, dict[str, Any]] = {
        "short_race": {
            "world_sentence": "A cloud postal harbor reroutes every sail before the storm closes the air lanes.",
            "memory_silhouette": "a giant envelope sail folding over the finish dock",
            "proportion_words": ["airy", "stretched", "layered"],
            "base_shapes": ["thin plate", "beam", "cylinder", "arc"],
            "assembly_families": ["sail bridge bay", "wind mast", "sorting gate", "dock wall bay", "envelope finish"],
            "material_rhythm": "broad canvas planes, dark timber ribs, brass joints, sparse luminous route stitching",
            "color_roles": {"environment": "mist blue", "structure": "ink navy", "route": "amber", "interaction": "teal", "goal": "coral", "hazard": "violet"},
            "world_state_change": "harbor sails rotate with the route, then fold into the finish envelope",
            "banned_list": ["generic floating pads", "unconnected factory conveyors"],
        },
        "chapter_challenge": {
            "world_sentence": "A buried titan greenhouse wakes one climate chamber at a time as the player climbs toward its crown.",
            "memory_silhouette": "a glass flower opening around a colossal stone head",
            "proportion_words": ["colossal", "overgrown", "vertical"],
            "base_shapes": ["box", "prism", "cylinder", "petal arc"],
            "assembly_families": ["root stair flight", "greenhouse rib", "climate gate", "titan facade", "crown platform"],
            "material_rhythm": "weathered stone masses, repeated glass ribs, dense plant seams, warm restored chambers",
            "color_roles": {"environment": "moss gray", "structure": "stone green", "route": "sun gold", "interaction": "aqua", "goal": "white", "hazard": "rust red"},
            "world_state_change": "each completed chapter opens one glass petal and changes the distant crown",
            "banned_list": ["identical chapter corridors", "plants uniformly scattered across jumps"],
        },
        "mechanism_puzzle": {
            "world_sentence": "A tidal observatory must balance moonlight and water routes before its archive resurfaces.",
            "memory_silhouette": "three lunar rings reflected in a rising central pool",
            "proportion_words": ["precise", "concentric", "calm"],
            "base_shapes": ["ring", "channel plate", "cylinder", "wedge"],
            "assembly_families": ["observation cell", "water channel", "lunar input dais", "result iris", "reset dock"],
            "material_rhythm": "quiet stone fields, brass measurement edges, luminous water lines, one bright result surface",
            "color_roles": {"environment": "deep slate", "structure": "pale stone", "route": "moon white", "interaction": "turquoise", "goal": "gold", "hazard": "crimson"},
            "world_state_change": "solved cells lift archive terraces above the waterline",
            "banned_list": ["detached password boards", "random button clusters"],
        },
        "cooperative": {
            "world_sentence": "Two gardeners redirect opposite moonlit canals to grow one bridge across a sleeping valley.",
            "memory_silhouette": "two water spirals meeting beneath a luminous flower bridge",
            "proportion_words": ["paired", "flowing", "terraced"],
            "base_shapes": ["channel plate", "cylinder", "arch", "petal"],
            "assembly_families": ["role garden bay", "canal gate", "shared growth bridge", "handoff terrace", "regroup pavilion"],
            "material_rhythm": "soft garden masses, repeated stone channels, bright role inlays, shared white growth edges",
            "color_roles": {"environment": "night jade", "structure": "warm stone", "route": "white", "interaction": "cyan and magenta shapes", "goal": "gold", "hazard": "dark violet"},
            "world_state_change": "each reciprocal handoff grows a visible span toward the shared pavilion",
            "banned_list": ["two independent colored lanes", "decorative simultaneous buttons"],
        },
        "narrative_exploration": {
            "world_sentence": "A flooded clock city remembers its residents as the player relights public landmarks.",
            "memory_silhouette": "a submerged clock tower projecting a path across empty roofs",
            "proportion_words": ["layered", "melancholic", "civic"],
            "base_shapes": ["facade box", "roof prism", "clock ring", "bridge beam"],
            "assembly_families": ["street facade", "roof crossing", "memory kiosk", "flood gate", "clock tower landmark"],
            "material_rhythm": "dark wet masonry, repeated civic trim, sparse warm interiors, reflective flood seams",
            "color_roles": {"environment": "rain blue", "structure": "charcoal stone", "route": "warm window light", "interaction": "copper", "goal": "clock gold", "hazard": "cold black"},
            "world_state_change": "relit districts regain people, routes, and window patterns when revisited",
            "banned_list": ["story carried only by floating text", "every building using a different asset language"],
        },
        "survival": {
            "world_sentence": "A paper model city absorbs a monsoon along visible folds until only the civic plaza remains dry.",
            "memory_silhouette": "whole paper blocks folding upward around the last dry square",
            "proportion_words": ["folded", "fragile", "graphic"],
            "base_shapes": ["thin plate", "wedge", "box", "rolled cylinder"],
            "assembly_families": ["paper block sector", "drain fold", "roof refuge", "soak state edge", "plaza terminal"],
            "material_rhythm": "large matte paper faces, dark fold lines, sparse printed details, glossy wet-state strips",
            "color_roles": {"environment": "desaturated sky", "structure": "paper cream", "route": "dry orange", "interaction": "blue", "goal": "white", "hazard": "ink navy"},
            "world_state_change": "water follows gutters and fold lines while safe surfaces rise into the final plaza",
            "banned_list": ["untelegraphed random damage", "permanent dry corner"],
        },
        "score_contest": {
            "world_sentence": "Competing lantern couriers cycle through a night harbor as valuable docks migrate with the tide.",
            "memory_silhouette": "two courier trails crossing beneath a moving lighthouse beam",
            "proportion_words": ["circular", "busy", "open"],
            "base_shapes": ["dock plate", "post cylinder", "rope arc", "lantern box"],
            "assembly_families": ["resource pier", "risk shortcut", "neutral delivery gate", "lighthouse hotspot", "team spawn quay"],
            "material_rhythm": "dark timber fields, pale rope edges, compact lantern clusters, one migrating bright beam",
            "color_roles": {"environment": "harbor navy", "structure": "weathered brown", "route": "warm rope", "interaction": "cyan", "goal": "gold", "hazard": "red", "team": "shape plus blue/orange"},
            "world_state_change": "the lighthouse turns and makes a different dock valuable each round",
            "banned_list": ["pickup instantly equals score", "one team color hidden in decoration"],
        },
        "social_showcase": {
            "world_sentence": "A floating winter night market lights one communal scene whenever visitors complete an activity loop.",
            "memory_silhouette": "a glowing tree reflected between three drifting market islands",
            "proportion_words": ["cozy", "layered", "panoramic"],
            "base_shapes": ["snow curve", "timber box", "lantern cylinder", "arch"],
            "assembly_families": ["market facade", "snow garden cluster", "photo pier", "activity pavilion", "return bridge"],
            "material_rhythm": "broad quiet snow, warm timber frames, clustered lights at activities, sparse reflective ice",
            "color_roles": {"environment": "snow blue", "structure": "dark wood", "route": "soft amber", "interaction": "rose", "goal": "warm white", "hazard": "muted violet"},
            "world_state_change": "completed activities add temporary lights to the central tree without blocking other visitors",
            "banned_list": ["a giant empty decoration field", "all activities sharing one occupied control"],
        },
        "management_simulation": {
            "world_sentence": "A cliffside kite hospital diagnoses, repairs, tests, and launches storm-damaged flying machines.",
            "memory_silhouette": "a repaired whale kite leaving the launch gantry above the clouds",
            "proportion_words": ["workshop-like", "windswept", "modular"],
            "base_shapes": ["frame beam", "fabric plate", "spool cylinder", "gantry arc"],
            "assembly_families": ["intake rack", "diagnosis bench", "repair station", "test wind tunnel", "launch gantry"],
            "material_rhythm": "large fabric color fields, repeated timber frames, metal joints at work surfaces, animated streamers only at tests",
            "color_roles": {"environment": "cloud gray", "structure": "dark timber", "route": "white stitching", "interaction": "teal", "goal": "sun yellow", "hazard": "storm purple"},
            "world_state_change": "upgrades visibly widen racks, open a second test lane, and populate the sky with repaired kites",
            "banned_list": ["income rising without visible goods", "upgrade panels that do not change the workplace"],
        },
        "rhythm_performance": {
            "world_sentence": "A constellation radio rebuilds a broken night sky one synchronized phrase at a time.",
            "memory_silhouette": "four note lanes joining into a radiant antenna star",
            "proportion_words": ["radiant", "geometric", "deep"],
            "base_shapes": ["line beam", "ring", "star wedge", "orb"],
            "assembly_families": ["count-in portal", "constellation lane bay", "hit-line ring", "combo antenna", "result observatory"],
            "material_rhythm": "nearly black space, thin stable lane lines, sparse star clusters, broad light only at phrase results",
            "color_roles": {"environment": "space black", "structure": "indigo", "route": "silver", "interaction": "cyan", "goal": "sun gold", "hazard": "magenta"},
            "world_state_change": "successful phrases connect stars into the final antenna constellation",
            "banned_list": ["decorative pulses ahead of gameplay cues", "audio-only timing information"],
        },
        "combat_boss": {
            "world_sentence": "A bell leviathan tears open a sunken cathedral, exposing counterplay through the damage it causes.",
            "memory_silhouette": "a whale-shaped bell suspended above a fractured circular nave",
            "proportion_words": ["monumental", "circular", "submerged"],
            "base_shapes": ["arena wedge", "rib arc", "bell cylinder", "armor plate"],
            "assembly_families": ["arena sector", "cathedral rib", "safe recovery arch", "leviathan shell", "weak-point frame"],
            "material_rhythm": "broad stone sectors, oxidized metal ribs, luminous cracks at true attack states, quiet outer water",
            "color_roles": {"environment": "abyss blue", "structure": "oxidized stone", "route": "pearl", "interaction": "aqua", "goal": "gold", "hazard": "red coral"},
            "world_state_change": "each phase breaks a nave sector and reveals a new traversal or counter window",
            "banned_list": ["permanent safe cover", "visual limbs used as accidental damage authorities"],
        },
        "defense_strategy": {
            "world_sentence": "A snowline observatory routes heat and scouts ink storms before they reach its central lens.",
            "memory_silhouette": "a warm telescope beam cutting across two black storm lanes",
            "proportion_words": ["fortified", "radial", "windswept"],
            "base_shapes": ["lane plate", "tower cylinder", "lens ring", "snow wedge"],
            "assembly_families": ["defense lane bay", "heat conduit", "build pad", "storm source", "lens core fort"],
            "material_rhythm": "heavy snow masses, dark route trenches, repeated copper heat lines, bright state bands at the core",
            "color_roles": {"environment": "snow gray", "structure": "iron blue", "route": "copper", "interaction": "cyan", "goal": "warm white", "hazard": "ink black"},
            "world_state_change": "new lanes darken the horizon while defended heat lines relight the observatory ring",
            "banned_list": ["enemy routes hidden by snow decoration", "background units active without relevance"],
        },
        "stealth_infiltration": {
            "world_sentence": "A moon archive changes guard light and shelf geometry after the player copies a forbidden record.",
            "memory_silhouette": "a narrow lunar beam splitting rows of moving archive towers",
            "proportion_words": ["quiet", "tall", "occluded"],
            "base_shapes": ["shelf box", "light cone", "rail beam", "seal ring"],
            "assembly_families": ["infiltration cell", "shelf cover cluster", "patrol light rail", "record vault", "alternate exfiltration gate"],
            "material_rhythm": "dark continuous shelves, pale floor seams, sparse readable sensor beams, one warm objective seal",
            "color_roles": {"environment": "midnight blue", "structure": "charcoal", "route": "low white", "interaction": "amber", "goal": "moon gold", "hazard": "red with shape pattern"},
            "world_state_change": "copying the record closes the entry route and turns shelf rails into the return puzzle",
            "banned_list": ["decorative cameras contradicting sensors", "black floors that erase route edges"],
        },
        "turn_based_strategy": {
            "world_sentence": "A migrating museum rearranges public exhibits after every resolved turn of a route-building board game.",
            "memory_silhouette": "two track lines meeting beneath a giant mechanical bird-wing clock",
            "proportion_words": ["ceremonial", "gridded", "kinetic"],
            "base_shapes": ["board tile", "rail beam", "display frame", "wing arc"],
            "assembly_families": ["board cell", "turn podium", "action dock", "exhibit wall bay", "resolution clock"],
            "material_rhythm": "quiet stone board, dark museum frames, crisp ownership edges, short kinetic displays during resolution",
            "color_roles": {"environment": "museum gray", "structure": "bronze black", "route": "ivory", "interaction": "teal", "goal": "gold", "hazard": "red", "team": "shape plus blue/orange"},
            "world_state_change": "chapter resolutions rotate one public exhibit and visibly alter the next board layout",
            "banned_list": ["real-time inputs during resolution", "private state facing the public camera"],
        },
        "sports_match": {
            "world_sentence": "Teams redirect one buoyant waterball across a floating club as currents change between legal plays.",
            "memory_silhouette": "the match ball arcing through a ring goal above a crescent pool",
            "proportion_words": ["open", "symmetric", "buoyant"],
            "base_shapes": ["field plate", "goal ring", "float cylinder", "stand arc"],
            "assembly_families": ["field sector", "goal frame", "out-of-bounds edge", "restart raft", "stand bay"],
            "material_rhythm": "broad matte play surface, crisp field lines, soft float edges, concentrated celebration light at legal scores",
            "color_roles": {"environment": "sea blue", "structure": "white float", "route": "sand", "interaction": "yellow", "goal": "white", "hazard": "deep water", "team": "shape plus coral/cyan"},
            "world_state_change": "currents rotate only after dead-ball cleanup and are telegraphed before the next kickoff",
            "banned_list": ["spectator props entering field logic", "score zones without dead-ball reset"],
        },
        "sandbox_creation": {
            "world_sentence": "A salvage starship atelier lets players build, test, snapshot, and exhibit small craft from recovered modules.",
            "memory_silhouette": "a player-built craft framed inside a vast open launch iris",
            "proportion_words": ["modular", "neutral", "spacious"],
            "base_shapes": ["grid plate", "module box", "joint cylinder", "iris ring"],
            "assembly_families": ["catalog pod", "build plot", "tool rail", "test chamber", "snapshot gallery"],
            "material_rhythm": "quiet neutral work surfaces, repeated modular joints, bright validation outlines, dark uncluttered showcase background",
            "color_roles": {"environment": "deep space gray", "structure": "neutral silver", "route": "white", "interaction": "cyan", "goal": "gold", "hazard": "red invalid outline"},
            "world_state_change": "a committed snapshot leaves the work bay and appears as a separate gallery exhibit",
            "banned_list": ["scene shell consuming the player build budget", "showcase state overwriting the editable work"],
        },
        "social_deduction": {
            "world_sentence": "A drifting polar research station loses trust as crews repair public systems while one hidden team redirects the storm.",
            "memory_silhouette": "a circular meeting lens glowing above branching dark research wings",
            "proportion_words": ["isolated", "radial", "institutional"],
            "base_shapes": ["corridor box", "observation ring", "antenna beam", "lab cylinder"],
            "assembly_families": ["task room bay", "evidence threshold", "meeting lens", "afterlife overlook", "storm sabotage wing"],
            "material_rhythm": "quiet pale labs, dark structural ribs, sparse public system lights, private feedback confined to player channels",
            "color_roles": {"environment": "polar blue", "structure": "charcoal steel", "route": "cold white", "interaction": "amber", "goal": "green", "hazard": "storm red", "team": "never exposed before the terminal"},
            "world_state_change": "repairs relight public wings while sabotage changes route access without revealing its author",
            "banned_list": ["role colors visible in shared space", "eliminated players retaining outcome-changing controls"],
        },
    }
    theme = themes[type_name]
    theme["world_shells"] = _world_shell_examples(type_name, theme)
    return theme


def _attach_example_secondary(
    plan: dict[str, Any],
    secondary_type: str,
    hybrid_mode: str | None = None,
) -> None:
    primary_type = str(plan["primary_type"])
    if secondary_type == primary_type:
        raise DesignPlanError("secondary_type must differ from primary_type")
    secondary_profile = _example_profile(secondary_type)
    primary_players = plan["experience"]["player_range"]
    secondary_players = secondary_profile["player_range"]
    player_min = max(primary_players[0], secondary_players[0])
    player_max = min(primary_players[1], secondary_players[1])
    if player_min > player_max:
        raise DesignPlanError(
            f"example player ranges do not overlap for {primary_type} and {secondary_type}"
        )

    if hybrid_mode is not None and hybrid_mode not in HYBRID_MODES:
        raise DesignPlanError(
            f"hybrid_mode must be one of {', '.join(sorted(HYBRID_MODES))}"
        )
    mode = hybrid_mode or RECOMMENDED_HYBRID_MODES.get(
        (primary_type, secondary_type), "local_station"
    )
    target_seconds = max(
        15,
        min(60, int(plan["experience"]["target_duration_seconds"][1] * 0.10)),
    )
    beat_name = f"secondary_{secondary_type}"
    plan["beats"].insert(
        max(1, len(plan["beats"]) - 1),
        {
            "name": beat_name,
            "owner": "secondary",
            "information": f"read the bounded {secondary_type} contract",
            "action": f"complete or leave the {secondary_type} scope",
            "consequence": "return one committed result to the primary loop",
            "feedback": "shared world grammar plus a distinct handoff state",
            "target_seconds": target_seconds,
        },
    )
    forced_seconds = 0 if mode == "optional_branch" else target_seconds
    pause_seconds = target_seconds if mode in {"local_station", "phase_shift"} else 0
    plan["secondary_type"] = secondary_type
    plan["type_modules"][secondary_type] = _module_example(secondary_type)
    handoff_family = f"{secondary_type} handoff bay"
    plan["theme"]["assembly_families"].append(handoff_family)
    handoff_shell = plan["theme"]["world_shells"][-1]
    handoff_shell["beats"].append(beat_name)
    handoff_shell["assembly_families"].append(handoff_family)
    handoff_shell["state_variants"].append(
        f"bounded {secondary_type} handoff committed and cleaned before primary resume"
    )
    handoff_shell["review_views"].append(
        {
            "name": f"{handoff_shell['name']}_SECONDARY_HANDOFF",
            "kind": "action",
            "camera_intent": "show the bounded secondary input, primary-world consequence, and return path in one controllable view",
            "must_show": ["secondary input", "shared world consequence", "primary return frame"],
        }
    )
    plan["hybrid"] = {
        "mode": mode,
        "secondary_purpose": f"change one bounded decision in the {primary_type} loop",
        "secondary_scope": [beat_name],
        "authoritative_terminal": f"the {primary_type} controller owns the only terminal",
        "time_budget": {
            "forced_secondary_seconds_max": forced_seconds,
            "continuous_primary_pause_seconds_max": pause_seconds,
            "measurement": "time entry lock to committed cleanup on the target device",
        },
        "entry_condition": "the current primary generation opens one idempotent entry",
        "exit_condition": "commit one result or take the declared fallback before returning",
        "conflict_priority": "the primary terminal lock wins every simultaneous outcome",
        "simultaneous_failure": "commit the primary failure, discard the secondary result, then clean up",
        "state_handoff": "snapshot only required primary state, commit one secondary result, and resume the same generation",
        "cleanup_owner": "the primary session controller invalidates the secondary generation and releases every temporary object, timer, occupancy, UI, and camera state",
        "shared_visual_grammar": "reuse the same world shell, frame proportions, semantic colors, and interface edges",
        "fallback": "bypass or simplify the secondary scope while preserving the primary terminal and recovery path",
    }

    plan["experience"]["player_range"] = [player_min, player_max]
    plan["verification"]["player_counts"] = [player_min, player_max]
    if forced_seconds:
        plan["experience"]["target_duration_seconds"] = [
            plan["experience"]["target_duration_seconds"][0] + forced_seconds,
            plan["experience"]["target_duration_seconds"][1] + forced_seconds,
        ]
    for key in TYPE_METRICS[secondary_type]:
        plan["verification"]["metrics"].setdefault(
            key,
            {
                "status": "tested",
                "method": "record the bounded secondary scope on the target device",
                "target_or_result": "within the declared hybrid envelope",
            },
        )
    for key in TYPE_SCENARIOS[secondary_type]:
        plan["verification"]["scenarios"].setdefault(
            key,
            {
                "status": "tested",
                "method": "run the named secondary scenario through entry and cleanup",
                "target_or_result": "pass",
            },
        )
    for key in HYBRID_METRICS:
        plan["verification"]["metrics"][key] = {
            "status": "tested",
            "method": "measure the complete secondary entry, result, cleanup, and primary resume transaction",
            "target_or_result": "within the declared hybrid time and residue budget",
        }
    for key in HYBRID_SCENARIOS:
        plan["verification"]["scenarios"][key] = {
            "status": "tested",
            "method": "run the named hybrid boundary scenario through the primary terminal",
            "target_or_result": "one authoritative result with no secondary residue",
        }

    secondary_seed = _example_assembly_budget(secondary_type)["expanded_total"]
    increment = max(200, int(secondary_seed * 0.20))
    weights = {
        "COL": 0.05,
        "MASS": 0.15,
        "MID": 0.30,
        "ROUTE": 0.10,
        "MECH": 0.15,
        "PROP": 0.10,
        "FX": 0.05,
        "LOGIC": 0.05,
    }
    additions = {key: int(increment * weight) for key, weight in weights.items()}
    additions["SAFE"] = increment - sum(additions.values())
    for key, count in additions.items():
        plan["assembly_budget"]["layers"][key] += count
    plan["assembly_budget"]["expanded_total"] += increment
    plan["assembly_budget"]["graybox_total"] += max(20, int(increment * 0.10))
    plan["assembly_budget"]["asset_vocabulary_count"] += 6


def example_plan(
    primary_type: str = "short_race",
    modifier: str | None = None,
    secondary_type: str | None = None,
    hybrid_mode: str | None = None,
) -> dict[str, Any]:
    if hybrid_mode is not None and secondary_type is None:
        raise DesignPlanError("hybrid_mode requires secondary_type")
    profile = _example_profile(primary_type)
    theme = _theme_example(primary_type)
    metrics = {
        key: {"status": "tested", "method": "record target-device playtest", "target_or_result": "within target"}
        for key in sorted(BASE_METRICS | TYPE_METRICS[primary_type])
    }
    scenarios = {
        key: {"status": "tested", "method": "run the named scenario", "target_or_result": "pass"}
        for key in sorted(BASE_SCENARIOS | TYPE_SCENARIOS[primary_type])
    }
    plan = {
        "schema_version": 1,
        "stage": "predeploy",
        "maturity": "final",
        "primary_type": primary_type,
        "secondary_type": None,
        "experience": {
            "audience": "casual players familiar with basic movement",
            "player_range": profile["player_range"],
            "target_duration_seconds": profile["target_duration_seconds"],
            "main_verbs": profile["main_verbs"],
            "memory_image": theme["memory_silhouette"],
            "success": profile["success"],
            "failure_recovery": "return to the latest safe committed state",
            "emotion": "curiosity -> pressure -> relief",
            "theme_promise": theme["world_sentence"],
        },
        "topology": _topology_example(primary_type),
        "beats": _beats_example(primary_type),
        "theme": theme,
        "assembly_budget": _example_assembly_budget(primary_type),
        "complexity_budget": {
            "visual": {
                "visible_peak": 260,
                "collision_peak": 70,
                "shadow_peak": 35,
                "dynamic_peak": 18,
                "transparent_layer_peak": 2,
                "switch_load_peak": 180,
            },
            "logic": {
                "persistent_state_count": 12,
                "event_entry_count": 18,
                "active_timer_peak": 4,
                "action_fanout_peak": 6,
                "spawned_object_peak": 8,
                "reset_item_count": 20,
            },
            "measurement": {
                "visual_method": "count the worst target-device camera view",
                "logic_method": "trace the worst live state and its active systems",
                "worst_case_state": "target player count at the main climax",
            },
            "degradation_order": [
                "remove invisible and distant micro-detail",
                "reduce non-state FX and inactive dynamic systems",
                "simplify focal assembly only after revalidation",
            ],
        },
        "type_modules": {primary_type: _module_example(primary_type)},
        "hybrid": None,
        "modifiers": [],
        "modifier_contracts": {},
        "modifier_interactions": [],
        "evidence": {
            "required_reference_axes": [],
            "references": [],
            "reference_gaps": [],
            "assumptions": [{"text": "the selected loop fits the target audience", "validation": "first-time playtest"}],
            "unknowns": [{"text": "exact device frame time", "impact": "may change distant detail", "validation": "target-device peak-view test", "blocking": False}],
        },
        "verification": {
            "target_device": "recorded target device and game version",
            "player_counts": profile["player_range"],
            "metrics": metrics,
            "scenarios": scenarios,
        },
        "audits": {
            "build_bundle": {"status": "passed"},
            "density": {"status": "passed"},
            "state": {"status": "passed"},
            "parameter_expansion": {"status": "passed"},
            "component_evidence": {"status": "passed"},
            "performance": {"status": "passed"},
            "theme_adaptation": {"status": "passed"},
        },
    }
    if secondary_type is not None:
        _attach_example_secondary(plan, secondary_type, hybrid_mode)
    if modifier is not None:
        _attach_example_modifier(plan, modifier)
    plan["evidence"]["required_reference_axes"] = sorted(
        _expected_reference_axes(plan)
    )
    plan["evidence"]["reference_gaps"] = [
        _reference_gap(axis)
        for axis in plan["evidence"]["required_reference_axes"]
    ]
    return plan


def design_template_plan(
    primary_type: str = "short_race",
    modifier: str | None = None,
    secondary_type: str | None = None,
    hybrid_mode: str | None = None,
) -> dict[str, Any]:
    """Return a valid design-stage template without fabricated test evidence."""
    plan = _clone(example_plan(primary_type, modifier, secondary_type, hybrid_mode))
    plan["stage"] = "design"
    plan["maturity"] = "concept"
    plan["evidence"]["references"] = []
    plan["evidence"]["reference_gaps"] = [
        _reference_gap(axis)
        for axis in plan["evidence"]["required_reference_axes"]
    ]
    plan["evidence"]["unknowns"] = [
        {
            "text": "current-version component capability and target-device peak cost",
            "impact": "may require a graybox downgrade or a different primary contract",
            "validation": "query current evidence, build the minimum loop, and test the worst target-device state",
            "blocking": True,
        }
    ]
    for group in ("metrics", "scenarios"):
        for entry in plan["verification"][group].values():
            entry["status"] = "planned"
            entry["target_or_result"] = "replace with a measurable target, then record the result"
    for name in plan["audits"]:
        plan["audits"][name] = {"status": "planned"}
    return plan


def _expect_invalid(plan: dict[str, Any], needle: str) -> None:
    try:
        validate_design_plan(plan)
    except DesignPlanError as exc:
        if needle not in str(exc):
            raise AssertionError(f"expected {needle!r} in error, got: {exc}") from exc
    else:
        raise AssertionError("invalid plan was accepted")


def _clone(value: Any) -> Any:
    return json.loads(json.dumps(value))


def _self_test() -> None:
    for type_name in sorted(PRIMARY_TYPES):
        summary = validate_design_plan(example_plan(type_name))
        if summary["primary_type"] != type_name:
            raise AssertionError(f"type summary mismatch for {type_name}")
        if summary["assembly"]["expanded_total"] != _example_assembly_budget(type_name)[
            "expanded_total"
        ]:
            raise AssertionError(f"assembly summary mismatch for {type_name}")
        template_summary = validate_design_plan(design_template_plan(type_name))
        if template_summary["stage"] != "design":
            raise AssertionError(f"design template stage mismatch for {type_name}")

    for (primary_type, secondary_type), expected_mode in sorted(
        RECOMMENDED_HYBRID_MODES.items()
    ):
        if primary_type not in PRIMARY_TYPES or secondary_type not in PRIMARY_TYPES:
            raise AssertionError("recommended hybrid mode contains an unknown type")
        if expected_mode not in HYBRID_MODES:
            raise AssertionError("recommended hybrid mode contains an unknown mode")
        hybrid_template = design_template_plan(
            primary_type,
            secondary_type=secondary_type,
        )
        if hybrid_template["hybrid"]["mode"] != expected_mode:
            raise AssertionError(
                f"recommended hybrid mode drift for {primary_type}+{secondary_type}"
            )

    explicit_hybrid_mode = design_template_plan(
        "management_simulation",
        secondary_type="survival",
        hybrid_mode="overlay",
    )
    if explicit_hybrid_mode["hybrid"]["mode"] != "overlay":
        raise AssertionError("explicit hybrid mode did not override the design default")
    try:
        design_template_plan("short_race", hybrid_mode="overlay")
    except DesignPlanError as exc:
        if "requires secondary_type" not in str(exc):
            raise AssertionError(f"unexpected orphan hybrid mode error: {exc}") from exc
    else:
        raise AssertionError("hybrid mode without a secondary type was accepted")

    missing_reference_gap = example_plan()
    missing_reference_gap["evidence"]["reference_gaps"].pop()
    _expect_invalid(missing_reference_gap, "reference_gaps mismatch")

    boundary_as_positive = example_plan()
    boundary_as_positive["evidence"]["references"] = [
        {
            "name": "genre boundary case",
            "status": "verified",
            "used_for": "reject a false genre match",
            "limits": "does not demonstrate the requested loop",
            "supports": [
                {"axis": "primary_loop", "coverage_status": "boundary_only"}
            ],
        }
    ]
    boundary_as_positive["evidence"]["reference_gaps"] = [
        gap
        for gap in boundary_as_positive["evidence"]["reference_gaps"]
        if gap["axis"] != "primary_loop"
    ]
    _expect_invalid(boundary_as_positive, "reference_gaps mismatch")

    bounded_positive = example_plan()
    bounded_positive["evidence"]["references"] = [
        {
            "name": "audited partial case",
            "status": "partial",
            "used_for": "one directly observed primary-loop decision",
            "limits": "recovery and terminal were not observed",
            "supports": [
                {"axis": "primary_loop", "coverage_status": "partial_positive"}
            ],
        }
    ]
    bounded_positive["evidence"]["reference_gaps"] = [
        gap
        for gap in bounded_positive["evidence"]["reference_gaps"]
        if gap["axis"] != "primary_loop"
    ]
    validate_design_plan(bounded_positive)

    disconnected = example_plan()
    disconnected["topology"]["nodes"].append({"name": "ORPHAN", "role": "optional"})
    _expect_invalid(disconnected, "unreachable nodes")

    missing_world_shells = example_plan()
    del missing_world_shells["theme"]["world_shells"]
    _expect_invalid(missing_world_shells, "world_shells")

    unknown_shell_node = example_plan()
    unknown_shell_node["theme"]["world_shells"][0]["topology_nodes"][0] = "UNKNOWN"
    _expect_invalid(unknown_shell_node, "references unknown nodes")

    missing_shell_beat = example_plan()
    missing_shell_beat["theme"]["world_shells"][0]["beats"].pop()
    _expect_invalid(missing_shell_beat, "does not cover beats")

    duplicate_shell_beat = example_plan("chapter_challenge")
    duplicate_shell_beat["theme"]["world_shells"][1]["beats"].append(
        duplicate_shell_beat["theme"]["world_shells"][0]["beats"][0]
    )
    _expect_invalid(duplicate_shell_beat, "assigned to multiple world shells")

    foreign_shell_family = example_plan()
    foreign_shell_family["theme"]["world_shells"][0]["assembly_families"][0] = (
        "unregistered facade family"
    )
    _expect_invalid(foreign_shell_family, "must come from theme.assembly_families")

    missing_terminal_view = example_plan()
    missing_terminal_view["theme"]["world_shells"][0]["review_views"] = [
        view
        for view in missing_terminal_view["theme"]["world_shells"][0][
            "review_views"
        ]
        if view["kind"] != "terminal"
    ]
    _expect_invalid(missing_terminal_view, "has no terminal review view")

    one_scale_anchor = example_plan()
    one_scale_anchor["theme"]["world_shells"][0]["scale_anchors"] = [
        "one ambiguous anchor"
    ]
    _expect_invalid(one_scale_anchor, "scale_anchors must contain at least 2 items")

    missing_shell_zone = example_plan()
    missing_shell_zone["theme"]["world_shells"][0]["assembly_zones"] = []
    _expect_invalid(missing_shell_zone, "assembly_zones cannot be empty")

    collapsed_multi_scene = example_plan("chapter_challenge")
    first_shell, second_shell = collapsed_multi_scene["theme"]["world_shells"]
    first_shell["topology_nodes"] = list(
        dict.fromkeys(first_shell["topology_nodes"] + second_shell["topology_nodes"])
    )
    first_shell["beats"].extend(second_shell["beats"])
    first_shell["review_views"].extend(second_shell["review_views"])
    collapsed_multi_scene["theme"]["world_shells"] = [first_shell]
    _expect_invalid(collapsed_multi_scene, "requires at least 2 theme.world_shells")

    missing_metric = example_plan("survival")
    del missing_metric["verification"]["metrics"]["safe_corner"]
    _expect_invalid(missing_metric, "verification.metrics is missing")

    missing_survival_entry_contract = example_plan("survival")
    del missing_survival_entry_contract["type_modules"]["survival"][
        "start_and_idle_contract"
    ]
    _expect_invalid(missing_survival_entry_contract, "start_and_idle_contract")

    invalid_puzzle_mode = example_plan("mechanism_puzzle")
    invalid_puzzle_mode["type_modules"]["mechanism_puzzle"]["structure_mode"] = (
        "mixed_without_contract"
    )
    _expect_invalid(invalid_puzzle_mode, "structure_mode")

    incomplete_puzzle_unit = example_plan("mechanism_puzzle")
    del incomplete_puzzle_unit["type_modules"]["mechanism_puzzle"]["puzzle_units"][0][
        "local_reset"
    ]
    _expect_invalid(incomplete_puzzle_unit, "local_reset")

    missing_handoff = example_plan("cooperative")
    missing_handoff["type_modules"]["cooperative"]["handoffs"] = []
    _expect_invalid(missing_handoff, "handoffs cannot be empty")

    incomplete_narrative = example_plan("narrative_exploration")
    incomplete_narrative["type_modules"]["narrative_exploration"]["events"][0][
        "atomic_commit"
    ] = ["story beat=ARCHIVE_REVEALED"]
    _expect_invalid(incomplete_narrative, "atomic_commit must contain at least 2 items")

    missing_reorientation = example_plan("narrative_exploration")
    del missing_reorientation["type_modules"]["narrative_exploration"]["events"][0][
        "reorientation"
    ]
    _expect_invalid(missing_reorientation, "reorientation")

    incomplete_management = example_plan("management_simulation")
    del incomplete_management["type_modules"]["management_simulation"][
        "progression_and_terminal"
    ]
    _expect_invalid(incomplete_management, "progression_and_terminal")

    short_product_lifecycle = example_plan("management_simulation")
    short_product_lifecycle["type_modules"]["management_simulation"][
        "product_lifecycle"
    ] = ["INPUT", "OUTPUT", "SOLD"]
    _expect_invalid(short_product_lifecycle, "must contain at least 4 items")

    short_rhythm_channels = example_plan("rhythm_performance")
    short_rhythm_channels["type_modules"]["rhythm_performance"][
        "cue_channels"
    ] = short_rhythm_channels["type_modules"]["rhythm_performance"][
        "cue_channels"
    ][:1]
    _expect_invalid(short_rhythm_channels, "at least 2 items")

    short_boss_phases = example_plan("combat_boss")
    short_boss_phases["type_modules"]["combat_boss"]["boss_phases"] = (
        short_boss_phases["type_modules"]["combat_boss"]["boss_phases"][:1]
    )
    _expect_invalid(short_boss_phases, "at least 2 items")

    short_defense_waves = example_plan("defense_strategy")
    short_defense_waves["type_modules"]["defense_strategy"]["waves"] = (
        short_defense_waves["type_modules"]["defense_strategy"]["waves"][:1]
    )
    _expect_invalid(short_defense_waves, "at least 2 items")

    short_detection_states = example_plan("stealth_infiltration")
    short_detection_states["type_modules"]["stealth_infiltration"][
        "detection_states"
    ] = ["UNSEEN", "SUSPICIOUS", "ALERT"]
    _expect_invalid(short_detection_states, "at least 4 items")

    short_legal_actions = example_plan("turn_based_strategy")
    short_legal_actions["type_modules"]["turn_based_strategy"]["legal_actions"] = (
        short_legal_actions["type_modules"]["turn_based_strategy"]["legal_actions"][:1]
    )
    _expect_invalid(short_legal_actions, "at least 2 items")

    short_sports_teams = example_plan("sports_match")
    short_sports_teams["type_modules"]["sports_match"]["teams"] = (
        short_sports_teams["type_modules"]["sports_match"]["teams"][:1]
    )
    _expect_invalid(short_sports_teams, "at least 2 items")

    short_catalog = example_plan("sandbox_creation")
    short_catalog["type_modules"]["sandbox_creation"]["catalog_categories"] = (
        short_catalog["type_modules"]["sandbox_creation"]["catalog_categories"][:2]
    )
    _expect_invalid(short_catalog, "at least 3 items")

    short_deduction_roles = example_plan("social_deduction")
    short_deduction_roles["type_modules"]["social_deduction"]["role_set"] = (
        short_deduction_roles["type_modules"]["social_deduction"]["role_set"][:1]
    )
    _expect_invalid(short_deduction_roles, "at least 2 items")

    short_deduction_phases = example_plan("social_deduction")
    short_deduction_phases["type_modules"]["social_deduction"]["phase_cycle"] = [
        "FIELD",
        "VOTE",
        "RESULT",
    ]
    _expect_invalid(short_deduction_phases, "at least 4 items")

    one_alignment = example_plan("social_deduction")
    one_alignment["type_modules"]["social_deduction"]["role_set"][1][
        "alignment"
    ] = "crew"
    _expect_invalid(one_alignment, "at least two distinct alignments")

    missing_alignment_terminal = example_plan("social_deduction")
    missing_alignment_terminal["type_modules"]["social_deduction"][
        "win_predicates"
    ][1]["alignment"] = "crew"
    _expect_invalid(missing_alignment_terminal, "missing role alignments")

    duplicate_task = example_plan("social_deduction")
    duplicate_task["type_modules"]["social_deduction"]["tasks_or_evidence"][1][
        "name"
    ] = duplicate_task["type_modules"]["social_deduction"][
        "tasks_or_evidence"
    ][0]["name"]
    _expect_invalid(duplicate_task, "duplicate names")

    redundant_rhythm = example_plan("rhythm_performance", "rhythm")
    _expect_invalid(redundant_rhythm, "already owns the rhythm loop")

    low_count = example_plan()
    low_count["assembly_budget"]["expanded_total"] = 600
    low_count["assembly_budget"]["layers"] = {
        "COL": 60,
        "MASS": 150,
        "MID": 210,
        "ROUTE": 60,
        "MECH": 36,
        "PROP": 48,
        "FX": 18,
        "LOGIC": 12,
        "SAFE": 6,
    }
    _expect_invalid(low_count, "low_count_exception")

    low_count_valid = _clone(low_count)
    low_count_valid["assembly_budget"]["low_count_exception"] = {
        "mode": "deliberate_minimalism",
        "scope_evidence": "one continuous themed route with complete shell coverage at its key review views",
        "layer_coverage": [
            {"layer": "MASS", "handled_by": "four enclosing shell pieces"},
            {"layer": "MID", "handled_by": "door, frame, trim, and support assemblies"},
        ],
        "visual_review_views": ["spawn first screen", "climax return view"],
        "tradeoff": "accept sparse props while retaining the route's macro and mid-level construction",
    }
    low_count_valid["complexity_budget"]["visual"]["visible_peak"] = 160
    low_count_valid["complexity_budget"]["visual"]["switch_load_peak"] = 160
    summary = validate_design_plan(low_count_valid)
    if summary["assembly"]["low_count_exception"] is None:
        raise AssertionError("structured low-count exception was not retained")
    if summary["assembly"]["density_profile"] != "themed_short":
        raise AssertionError("density profile was not retained")

    stale_low_count = example_plan()
    stale_low_count["assembly_budget"]["low_count_exception"] = _clone(
        low_count_valid["assembly_budget"]["low_count_exception"]
    )
    _expect_invalid(stale_low_count, "is only valid when final expanded_total")

    low_count_without_density_audit = _clone(low_count_valid)
    low_count_without_density_audit["audits"]["density"] = {
        "status": "not_applicable",
        "reason": "small plan",
    }
    _expect_invalid(
        low_count_without_density_audit,
        "predeploy requires density status passed",
    )

    missing_low_count_mid = _clone(low_count_valid)
    missing_low_count_mid["assembly_budget"]["low_count_exception"][
        "layer_coverage"
    ] = [{"layer": "MASS", "handled_by": "one enclosing shell"}]
    _expect_invalid(missing_low_count_mid, "at least 2 items")

    missing_complexity = example_plan()
    del missing_complexity["complexity_budget"]
    _expect_invalid(missing_complexity, "complexity_budget is required")

    impossible_peak = example_plan()
    impossible_peak["complexity_budget"]["visual"]["visible_peak"] = (
        impossible_peak["assembly_budget"]["expanded_total"] + 1
    )
    _expect_invalid(impossible_peak, "cannot exceed assembly expanded_total")

    planned = example_plan()
    planned["verification"]["scenarios"]["first_time_player"]["status"] = "planned"
    _expect_invalid(planned, "predeploy still has planned verification")

    planned_audit = example_plan()
    planned_audit["audits"]["state"] = {"status": "planned"}
    _expect_invalid(planned_audit, "predeploy audits still planned")

    for modifier_name in sorted(MODIFIERS):
        modifier_plan = example_plan("short_race", modifier_name)
        summary = validate_design_plan(modifier_plan)
        if modifier_name not in summary["modifiers"]:
            raise AssertionError(f"modifier summary mismatch for {modifier_name}")
        missing_specific = _clone(modifier_plan)
        missing_field = sorted(MODIFIER_SPECIFIC_FIELDS[modifier_name])[0]
        del missing_specific["modifier_contracts"][modifier_name][missing_field]
        _expect_invalid(missing_specific, missing_field)

    short_vehicle_profiles = example_plan("short_race", "vehicles")
    short_vehicle_profiles["modifier_contracts"]["vehicles"][
        "calibration_profiles"
    ] = short_vehicle_profiles["modifier_contracts"]["vehicles"][
        "calibration_profiles"
    ][:2]
    _expect_invalid(short_vehicle_profiles, "at least 3 items")

    short_asym_roles = example_plan("score_contest", "asymmetric_roles")
    short_asym_roles["modifier_contracts"]["asymmetric_roles"]["roles"] = (
        short_asym_roles["modifier_contracts"]["asymmetric_roles"]["roles"][:1]
    )
    _expect_invalid(short_asym_roles, "at least 2 items")

    combined = example_plan("survival", "rising_pressure")
    random_contract = _modifier_example("random_variation")
    combined["modifiers"].append("random_variation")
    combined["modifier_contracts"]["random_variation"] = random_contract
    combined["verification"]["metrics"][random_contract["metric"]] = {
        "status": "tested",
        "method": "test filtered rolls across representative seeds",
        "target_or_result": "pass",
    }
    for scenario in MODIFIER_SCENARIOS["random_variation"]:
        combined["verification"]["scenarios"][scenario] = {
            "status": "tested",
            "method": "run the named random-variation scenario",
            "target_or_result": "pass",
        }
    combined["modifier_interactions"] = [
        {
            "modifiers": ["rising_pressure", "random_variation"],
            "interaction": "Each random layout changes the available pressure margin.",
            "priority": "ROUND terminal and the pressure safety filter win.",
            "worst_case": "slowest valid layout at maximum pressure",
            "cleanup": "clear the random generation before resetting pressure",
        }
    ]
    validate_design_plan(combined)

    missing_interaction = _clone(combined)
    missing_interaction["modifier_interactions"] = []
    _expect_invalid(missing_interaction, "modifier_interactions")

    growth = example_plan("chapter_challenge", "cumulative_growth")
    validate_design_plan(growth)

    missing_growth_cap = _clone(growth)
    del missing_growth_cap["modifier_contracts"]["cumulative_growth"]["clamp_or_cap"]
    _expect_invalid(missing_growth_cap, "clamp_or_cap")

    destructible = example_plan("chapter_challenge", "destructible_world")
    validate_design_plan(destructible)

    short_destructible_states = _clone(destructible)
    short_destructible_states["modifier_contracts"]["destructible_world"][
        "target_states"
    ] = short_destructible_states["modifier_contracts"]["destructible_world"][
        "target_states"
    ][:3]
    _expect_invalid(short_destructible_states, "at least 4 items")

    missing_dependency_group = _clone(destructible)
    missing_dependency_group["modifier_contracts"]["destructible_world"][
        "dependency_groups"
    ] = []
    _expect_invalid(missing_dependency_group, "cannot be empty")

    invalid_debris_peak = _clone(destructible)
    invalid_debris_peak["modifier_contracts"]["destructible_world"][
        "debris_budget"
    ]["spawned_peak"] = -1
    _expect_invalid(invalid_debris_peak, "spawned_peak")

    for primary_type in sorted(PRIMARY_TYPES):
        for secondary_type in sorted(PRIMARY_TYPES - {primary_type}):
            generated_hybrid = example_plan(
                primary_type, secondary_type=secondary_type
            )
            generated_summary = validate_design_plan(generated_hybrid)
            if generated_summary["secondary_type"] != secondary_type:
                raise AssertionError(
                    f"hybrid summary mismatch for {primary_type} x {secondary_type}"
                )

    hybrid = example_plan("short_race", secondary_type="mechanism_puzzle")
    summary = validate_design_plan(hybrid)
    if summary["secondary_type"] != "mechanism_puzzle":
        raise AssertionError("hybrid summary mismatch")

    missing_hybrid_cleanup = _clone(hybrid)
    del missing_hybrid_cleanup["hybrid"]["cleanup_owner"]
    _expect_invalid(missing_hybrid_cleanup, "cleanup_owner")

    missing_hybrid_scenario = _clone(hybrid)
    del missing_hybrid_scenario["verification"]["scenarios"][
        "hybrid_simultaneous_failure"
    ]
    _expect_invalid(missing_hybrid_scenario, "verification.scenarios is missing")

    primary_beat_scope = _clone(hybrid)
    primary_beat_scope["hybrid"]["secondary_scope"] = [
        primary_beat_scope["beats"][0]["name"]
    ]
    _expect_invalid(primary_beat_scope, "primary-only beats")

    optional_hybrid = example_plan(
        "sandbox_creation", secondary_type="social_showcase"
    )
    optional_hybrid["hybrid"]["time_budget"][
        "forced_secondary_seconds_max"
    ] = 1
    _expect_invalid(optional_hybrid, "optional_branch")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit experience, topology, type contracts, density, evidence, and verification coverage."
    )
    parser.add_argument("plan", nargs="?", type=Path, help="design plan JSON")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--example", action="store_true")
    parser.add_argument("--type", choices=sorted(PRIMARY_TYPES), default="short_race")
    parser.add_argument("--secondary", choices=sorted(PRIMARY_TYPES))
    parser.add_argument("--hybrid-mode", choices=sorted(HYBRID_MODES))
    parser.add_argument("--modifier", choices=sorted(MODIFIERS))
    parser.add_argument("--json", action="store_true", help="emit the validation summary as JSON")
    args = parser.parse_args()
    if args.self_test:
        _self_test()
        print("self-test passed")
        return 0
    if args.example:
        if args.secondary == args.type:
            parser.error("--secondary must differ from --type")
        if args.hybrid_mode and not args.secondary:
            parser.error("--hybrid-mode requires --secondary")
        template = design_template_plan(
            args.type, args.modifier, args.secondary, args.hybrid_mode
        )
        validate_design_plan(template)
        print(json.dumps(template, ensure_ascii=False, indent=2))
        return 0
    if args.secondary is not None:
        parser.error("--secondary is only used with --example")
    if args.hybrid_mode is not None:
        parser.error("--hybrid-mode is only used with --example and --secondary")
    if args.plan is None:
        parser.error("plan is required unless --self-test or --example is used")
    try:
        plan = json.loads(args.plan.read_text(encoding="utf-8"))
        summary = validate_design_plan(plan)
    except (OSError, json.JSONDecodeError, DesignPlanError) as exc:
        print(f"invalid design plan: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(
            "design plan valid: "
            f"type={summary['primary_type']}, "
            f"maturity={summary['maturity']}, "
            f"beats={summary['beat_count']}, "
            f"density_profile={summary['assembly']['density_profile']}, "
            f"expanded={summary['assembly']['expanded_total']}"
        )
        for warning in summary["warnings"]:
            print(f"warning: {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

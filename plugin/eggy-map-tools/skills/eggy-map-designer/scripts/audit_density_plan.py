#!/usr/bin/env python3
"""Validate expanded-instance arithmetic for an Eggy map design ledger."""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import sys
from typing import Any


ALLOWED_LAYERS = {
    "COL",
    "MASS",
    "MID",
    "ROUTE",
    "MECH",
    "PROP",
    "FX",
    "LOGIC",
    "SAFE",
}
DENSITY_PROFILE_MINIMUMS = {
    "micro_space": 300,
    "themed_short": 800,
    "multi_scene": 2000,
    "long_world": 5000,
}
LOW_COUNT_MODES = {"micro_space", "deliberate_minimalism", "large_asset_led"}


class PlanError(ValueError):
    pass


def _mapping(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PlanError(f"{path} must be an object")
    return value


def _list(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise PlanError(f"{path} must be an array")
    return value


def _string(value: Any, path: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise PlanError(f"{path} must be a non-empty string")
    return value.strip()


def _integer(value: Any, path: str, *, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise PlanError(f"{path} must be an integer")
    if minimum is not None and value < minimum:
        raise PlanError(f"{path} must be >= {minimum}")
    return value


def _count_map(
    value: Any,
    path: str,
    *,
    allowed_keys: set[str] | None = None,
) -> dict[str, int]:
    raw = _mapping(value, path)
    result: dict[str, int] = {}
    for key, count in raw.items():
        name = _string(key, f"{path} key")
        if allowed_keys is not None and name not in allowed_keys:
            allowed = ", ".join(sorted(allowed_keys))
            raise PlanError(f"{path}.{name} is not an allowed layer ({allowed})")
        number = _integer(count, f"{path}.{name}", minimum=0)
        if number:
            result[name] = number
    return result


def _add_counts(target: defaultdict[str, int], source: dict[str, int]) -> None:
    for key, value in source.items():
        target[key] += value


def _compare_counts(
    declared: dict[str, int],
    computed: dict[str, int],
    path: str,
) -> None:
    if declared == computed:
        return
    keys = sorted(set(declared) | set(computed))
    differences = [
        f"{key}: declared={declared.get(key, 0)}, computed={computed.get(key, 0)}"
        for key in keys
        if declared.get(key, 0) != computed.get(key, 0)
    ]
    raise PlanError(f"{path} mismatch ({'; '.join(differences)})")


def _validate_low_count_exception(value: Any, path: str) -> dict[str, Any]:
    exception = _mapping(value, path)
    required = {
        "mode",
        "scope_evidence",
        "layer_coverage",
        "visual_review_views",
        "tradeoff",
    }
    missing = sorted(required - set(exception))
    if missing:
        raise PlanError(f"{path} missing required fields: {', '.join(missing)}")
    mode = _string(exception["mode"], f"{path}.mode")
    if mode not in LOW_COUNT_MODES:
        raise PlanError(
            f"{path}.mode must be one of {', '.join(sorted(LOW_COUNT_MODES))}"
        )
    coverage_raw = _list(exception["layer_coverage"], f"{path}.layer_coverage")
    if len(coverage_raw) < 2:
        raise PlanError(f"{path}.layer_coverage must contain at least 2 items")
    coverage: list[dict[str, str]] = []
    seen_layers: set[str] = set()
    for index, raw_item in enumerate(coverage_raw):
        item_path = f"{path}.layer_coverage[{index}]"
        item = _mapping(raw_item, item_path)
        item_missing = sorted({"layer", "handled_by"} - set(item))
        if item_missing:
            raise PlanError(
                f"{item_path} missing required fields: {', '.join(item_missing)}"
            )
        layer = _string(item["layer"], f"{item_path}.layer")
        if layer not in ALLOWED_LAYERS:
            raise PlanError(
                f"{item_path}.layer must be one of "
                + ", ".join(sorted(ALLOWED_LAYERS))
            )
        if layer in seen_layers:
            raise PlanError(f"{path}.layer_coverage has duplicate layer {layer}")
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
        raise PlanError(
            f"{path}.layer_coverage must explain MASS and MID; missing "
            + ", ".join(missing_core)
        )
    views_raw = _list(exception["visual_review_views"], f"{path}.visual_review_views")
    if len(views_raw) < 2:
        raise PlanError(f"{path}.visual_review_views must contain at least 2 items")
    views = [
        _string(item, f"{path}.visual_review_views[{index}]")
        for index, item in enumerate(views_raw)
    ]
    return {
        "mode": mode,
        "scope_evidence": _string(
            exception["scope_evidence"], f"{path}.scope_evidence"
        ),
        "layer_coverage": coverage,
        "visual_review_views": views,
        "tradeoff": _string(exception["tradeoff"], f"{path}.tradeoff"),
    }


def validate_plan(plan: Any) -> dict[str, Any]:
    root = _mapping(plan, "plan")
    version = _integer(root.get("schema_version"), "schema_version", minimum=1)
    if version != 1:
        raise PlanError(f"unsupported schema_version {version}; expected 1")

    stage = _string(root.get("stage"), "stage")
    if stage not in {"graybox", "final"}:
        raise PlanError("stage must be 'graybox' or 'final'")

    density_profile = _string(root.get("density_profile"), "density_profile")
    if density_profile not in DENSITY_PROFILE_MINIMUMS:
        raise PlanError(
            "density_profile must be one of "
            + ", ".join(sorted(DENSITY_PROFILE_MINIMUMS))
        )
    density_floor = DENSITY_PROFILE_MINIMUMS[density_profile]
    density_profile_evidence = _string(
        root.get("density_profile_evidence"), "density_profile_evidence"
    )

    graybox_total = _integer(root.get("graybox_total"), "graybox_total", minimum=0)
    vocabulary = _integer(
        root.get("asset_vocabulary_count"),
        "asset_vocabulary_count",
        minimum=1,
    )

    zones: defaultdict[str, int] = defaultdict(int)
    layers: defaultdict[str, int] = defaultdict(int)
    names: set[str] = set()
    assembly_total = 0

    assemblies = _list(root.get("assemblies", []), "assemblies")
    for index, raw_item in enumerate(assemblies):
        path = f"assemblies[{index}]"
        item = _mapping(raw_item, path)
        name = _string(item.get("name"), f"{path}.name")
        if name in names:
            raise PlanError(f"duplicate ledger item name: {name}")
        names.add(name)

        pieces = _integer(
            item.get("pieces_per_instance"),
            f"{path}.pieces_per_instance",
            minimum=1,
        )
        placements = _integer(
            item.get("placements"), f"{path}.placements", minimum=1
        )
        adjustment = _integer(item.get("adjustment", 0), f"{path}.adjustment")
        expanded = pieces * placements + adjustment
        if expanded <= 0:
            raise PlanError(
                f"{path} expands to {expanded}; adjustment cannot remove the whole assembly"
            )

        item_zones = _count_map(item.get("zones"), f"{path}.zones")
        item_layers = _count_map(
            item.get("layers"),
            f"{path}.layers",
            allowed_keys=ALLOWED_LAYERS,
        )
        if sum(item_zones.values()) != expanded:
            raise PlanError(
                f"{path}.zones sums to {sum(item_zones.values())}, expected {expanded}"
            )
        if sum(item_layers.values()) != expanded:
            raise PlanError(
                f"{path}.layers sums to {sum(item_layers.values())}, expected {expanded}"
            )
        _add_counts(zones, item_zones)
        _add_counts(layers, item_layers)
        assembly_total += expanded

    independent_total = 0
    independent = _list(root.get("independent", []), "independent")
    for index, raw_item in enumerate(independent):
        path = f"independent[{index}]"
        item = _mapping(raw_item, path)
        name = _string(item.get("name"), f"{path}.name")
        if name in names:
            raise PlanError(f"duplicate ledger item name: {name}")
        names.add(name)
        count = _integer(item.get("count"), f"{path}.count", minimum=1)
        zone = _string(item.get("zone"), f"{path}.zone")
        layer = _string(item.get("layer"), f"{path}.layer")
        if layer not in ALLOWED_LAYERS:
            allowed = ", ".join(sorted(ALLOWED_LAYERS))
            raise PlanError(f"{path}.layer must be one of {allowed}")
        zones[zone] += count
        layers[layer] += count
        independent_total += count

    total = assembly_total + independent_total
    if vocabulary > total:
        raise PlanError(
            f"asset_vocabulary_count {vocabulary} exceeds expanded total {total}"
        )

    declared = _mapping(root.get("declared"), "declared")
    declared_total = _integer(
        declared.get("expanded_total"), "declared.expanded_total", minimum=0
    )
    if declared_total != total:
        raise PlanError(
            f"declared.expanded_total={declared_total}, computed expanded total={total}"
        )

    declared_zones = _count_map(declared.get("zones"), "declared.zones")
    declared_layers = _count_map(
        declared.get("layers"),
        "declared.layers",
        allowed_keys=ALLOWED_LAYERS,
    )
    computed_zones = dict(sorted(zones.items()))
    computed_layers = dict(sorted(layers.items()))
    _compare_counts(declared_zones, computed_zones, "declared.zones")
    _compare_counts(declared_layers, computed_layers, "declared.layers")

    warnings: list[str] = []
    low_count_exception: dict[str, Any] | None = None
    if stage == "final" and total < density_floor:
        low_count_exception = _validate_low_count_exception(
            root.get("low_count_exception"), "low_count_exception"
        )
        if (
            low_count_exception["mode"] == "micro_space"
            and density_profile != "micro_space"
        ):
            raise PlanError(
                "low_count_exception.mode='micro_space' requires "
                "density_profile='micro_space'"
            )
        warnings.append(
            "below-profile final accepted only as a structured exception pending visual review "
            f"(profile={density_profile}, floor={density_floor}, expanded={total})"
        )
    elif "low_count_exception" in root:
        raise PlanError(
            "low_count_exception is only valid when final expanded_total is below "
            f"the {density_profile} density profile floor {density_floor}"
        )
    if stage == "final" and not assemblies:
        warnings.append("final plan has no assembly families")
    for layer in ("MASS", "MID"):
        if stage == "final" and computed_layers.get(layer, 0) == 0:
            warnings.append(f"final plan has no {layer} instances; verify the exception")
    if stage == "final" and graybox_total >= total:
        warnings.append("graybox_total is not lower than final expanded total")

    return {
        "schema_version": version,
        "stage": stage,
        "density_profile": density_profile,
        "density_floor": density_floor,
        "density_profile_evidence": density_profile_evidence,
        "asset_vocabulary_count": vocabulary,
        "graybox_total": graybox_total,
        "assembly_total": assembly_total,
        "independent_total": independent_total,
        "expanded_total": total,
        "zones": computed_zones,
        "layers": computed_layers,
        "low_count_exception": low_count_exception,
        "warnings": warnings,
    }


def _self_test() -> None:
    valid = {
        "schema_version": 1,
        "stage": "final",
        "density_profile": "themed_short",
        "density_profile_evidence": "one continuous themed route with a complete world shell",
        "graybox_total": 20,
        "asset_vocabulary_count": 8,
        "assemblies": [
            {
                "name": "PLATFORM_BAY",
                "pieces_per_instance": 20,
                "placements": 12,
                "adjustment": -4,
                "zones": {"RUN": 236},
                "layers": {"COL": 12, "MASS": 72, "MID": 116, "ROUTE": 36},
            }
        ],
        "independent": [
            {"name": "FINISH_FX", "count": 24, "zone": "FINISH", "layer": "FX"}
        ],
        "declared": {
            "expanded_total": 260,
            "zones": {"RUN": 236, "FINISH": 24},
            "layers": {
                "COL": 12,
                "MASS": 72,
                "MID": 116,
                "ROUTE": 36,
                "FX": 24,
            },
        },
        "low_count_exception": {
            "mode": "deliberate_minimalism",
            "scope_evidence": "one continuous themed route with complete shell coverage at both review views",
            "layer_coverage": [
                {"layer": "MASS", "handled_by": "the enclosing shell"},
                {"layer": "MID", "handled_by": "the platform and frame assemblies"},
            ],
            "visual_review_views": ["spawn first screen", "finish return view"],
            "tradeoff": "sparse props preserve the route silhouette while retaining macro and mid layers",
        },
    }
    result = validate_plan(valid)
    if result["expanded_total"] != 260:
        raise AssertionError("valid plan total mismatch")
    if result["density_floor"] != 800:
        raise AssertionError("density profile floor mismatch")

    mismatched_exception_mode = json.loads(json.dumps(valid))
    mismatched_exception_mode["low_count_exception"]["mode"] = "micro_space"
    try:
        validate_plan(mismatched_exception_mode)
    except PlanError as exc:
        if "requires density_profile='micro_space'" not in str(exc):
            raise AssertionError(f"unexpected exception mode error: {exc}") from exc
    else:
        raise AssertionError("micro-space exception was accepted for a themed-short profile")

    invalid = json.loads(json.dumps(valid))
    invalid["declared"]["expanded_total"] = 259
    try:
        validate_plan(invalid)
    except PlanError:
        pass
    else:
        raise AssertionError("mismatched plan was not rejected")

    missing_exception = json.loads(json.dumps(valid))
    missing_exception.pop("low_count_exception")
    try:
        validate_plan(missing_exception)
    except PlanError as exc:
        if "low_count_exception" not in str(exc):
            raise AssertionError(f"unexpected low-count error: {exc}") from exc
    else:
        raise AssertionError("low-count final without a structured exception was accepted")

    stale_exception = json.loads(json.dumps(valid))
    stale_exception["density_profile"] = "micro_space"
    stale_exception["independent"].append(
        {"name": "EXTRA_MID", "count": 100, "zone": "RUN", "layer": "MID"}
    )
    stale_exception["declared"]["expanded_total"] = 360
    stale_exception["declared"]["zones"]["RUN"] = 336
    stale_exception["declared"]["layers"]["MID"] = 216
    try:
        validate_plan(stale_exception)
    except PlanError as exc:
        if "is only valid when final expanded_total" not in str(exc):
            raise AssertionError(f"unexpected stale exception error: {exc}") from exc
    else:
        raise AssertionError("stale below-profile exception was accepted")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit assembly, zone, and layer totals in a density ledger JSON."
    )
    parser.add_argument("plan", nargs="?", type=Path, help="density ledger JSON")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--json", action="store_true", help="emit the summary as JSON")
    args = parser.parse_args()

    if args.self_test:
        _self_test()
        print("self-test passed")
        return 0
    if args.plan is None:
        parser.error("plan is required unless --self-test is used")

    try:
        plan = json.loads(args.plan.read_text(encoding="utf-8"))
        summary = validate_plan(plan)
    except (OSError, json.JSONDecodeError, PlanError) as exc:
        print(f"invalid density plan: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(
            "density plan valid: "
            f"profile={summary['density_profile']}, "
            f"floor={summary['density_floor']}, "
            f"expanded={summary['expanded_total']}, "
            f"assemblies={summary['assembly_total']}, "
            f"independent={summary['independent_total']}, "
            f"assets={summary['asset_vocabulary_count']}"
        )
        for warning in summary["warnings"]:
            print(f"warning: {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

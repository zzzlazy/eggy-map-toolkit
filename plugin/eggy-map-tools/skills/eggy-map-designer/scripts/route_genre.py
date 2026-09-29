#!/usr/bin/env python3
"""Route community map names to Eggy design contracts without guessing a loop.

The source of truth stays in ``references/genre-routing-catalog.md``.  This
helper parses that maintained table, validates every machine-readable ID, and
returns likely rows plus the authority question that must resolve ambiguity.
It never commits a primary type from a title or theme word alone.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
from typing import Any

from audit_design_plan import HYBRID_MODES, MODIFIERS, PRIMARY_TYPES


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = ROOT / "references" / "genre-routing-catalog.md"
CODE_RE = re.compile(r"`([^`]+)`")
SEPARATOR_RE = re.compile(r"[、,/，；;]+")
NORMALIZE_RE = re.compile(r"[^0-9a-z\u3400-\u9fff]+")


class RoutingError(ValueError):
    pass


def _normalize(text: str) -> str:
    return NORMALIZE_RE.sub("", text.lower())


def _ngrams(text: str, size: int) -> set[str]:
    if len(text) < size:
        return {text} if text else set()
    return {text[index : index + size] for index in range(len(text) - size + 1)}


def _similarity(query: str, alias: str) -> float:
    query_n = _normalize(query)
    alias_n = _normalize(alias.removesuffix("等"))
    if not query_n or not alias_n:
        return 0.0
    if query_n == alias_n:
        return 1.0
    if alias_n in query_n or query_n in alias_n:
        ratio = min(len(query_n), len(alias_n)) / max(len(query_n), len(alias_n))
        # A two-character word embedded in a longer title is often only a
        # theme noun (for example 工厂), so it must remain exploratory.
        ceiling = 0.72 if min(len(query_n), len(alias_n)) <= 2 else 0.96
        return min(ceiling, 0.78 + 0.18 * ratio)
    query_bigrams = _ngrams(query_n, 2)
    alias_bigrams = _ngrams(alias_n, 2)
    bigram_dice = (
        2 * len(query_bigrams & alias_bigrams)
        / (len(query_bigrams) + len(alias_bigrams))
        if query_bigrams and alias_bigrams
        else 0.0
    )
    query_chars = set(query_n)
    alias_chars = set(alias_n)
    char_jaccard = len(query_chars & alias_chars) / len(query_chars | alias_chars)
    return round(0.72 * bigram_dice + 0.28 * char_jaccard, 6)


def _aliases(label: str) -> list[str]:
    candidates = [label, *SEPARATOR_RE.split(label)]
    result: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        candidate = candidate.strip()
        normalized = _normalize(candidate)
        if candidate and normalized and normalized not in seen:
            seen.add(normalized)
            result.append(candidate)
    return result


def _code_ids(text: str) -> list[str]:
    return CODE_RE.findall(text)


def parse_catalog(path: Path = DEFAULT_CATALOG) -> list[dict[str, Any]]:
    if not path.is_file():
        raise RoutingError(f"genre routing catalog does not exist: {path}")
    rows: list[dict[str, Any]] = []
    in_table = False
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), 1
    ):
        if line.startswith("| 常见叫法 |"):
            in_table = True
            continue
        if not in_table:
            continue
        if line.startswith("|---"):
            continue
        if not line.startswith("|"):
            break
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 5:
            raise RoutingError(
                f"catalog row {line_number} must contain five cells, got {len(cells)}"
            )
        label, primary_text, secondary_text, decision_question, common_trap = cells
        primary_codes = _code_ids(primary_text)
        secondary_codes = _code_ids(secondary_text)
        invalid_primary = set(primary_codes) - PRIMARY_TYPES
        if invalid_primary:
            raise RoutingError(
                f"catalog row {line_number} has invalid primary IDs: "
                f"{sorted(invalid_primary)}"
            )
        if not primary_codes:
            raise RoutingError(f"catalog row {line_number} has no primary type ID")
        valid_secondary = PRIMARY_TYPES | MODIFIERS | HYBRID_MODES
        invalid_secondary = set(secondary_codes) - valid_secondary
        if invalid_secondary:
            raise RoutingError(
                f"catalog row {line_number} has invalid secondary IDs: "
                f"{sorted(invalid_secondary)}"
            )
        rows.append(
            {
                "row": line_number,
                "community_terms": label,
                "aliases": _aliases(label),
                "primary_text": primary_text,
                "primary_candidates": list(dict.fromkeys(primary_codes)),
                "secondary_text": secondary_text,
                "secondary_candidates": [
                    item for item in secondary_codes if item in PRIMARY_TYPES
                ],
                "modifiers": [item for item in secondary_codes if item in MODIFIERS],
                "hybrid_modes": [
                    item for item in secondary_codes if item in HYBRID_MODES
                ],
                "authority_question": decision_question,
                "common_misclassification": common_trap,
            }
        )
    if not rows:
        raise RoutingError("genre routing catalog table is empty")
    return rows


def _scored_rows(query: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    scored: list[dict[str, Any]] = []
    for row in rows:
        alias_scores = [(_similarity(query, alias), alias) for alias in row["aliases"]]
        score, alias = max(alias_scores, key=lambda item: item[0])
        if score < 0.32:
            continue
        item = {key: value for key, value in row.items() if key != "aliases"}
        item["matched_alias"] = alias
        item["score"] = round(score, 6)
        scored.append(item)
    return sorted(scored, key=lambda item: (-item["score"], item["row"]))


def route_query(
    query: str,
    rows: list[dict[str, Any]],
    *,
    limit: int = 5,
) -> dict[str, Any]:
    if not _normalize(query):
        raise RoutingError("query must contain a map genre or community term")
    matches = _scored_rows(query, rows)[:limit]
    if not matches:
        return {
            "schema_version": 1,
            "route_kind": "eggy_community_genre_route",
            "query": query,
            "confidence": "no_match",
            "matches": [],
            "provisional_primary_candidates": [],
            "needs_authority_answer": True,
            "needs_lexical_disambiguation": True,
            "next_question": (
                "玩家反复做什么，哪个状态决定胜负或完成，失败后回哪里？"
            ),
            "committed_primary_type": None,
            "policy": "A title or visual theme never commits a primary type.",
        }

    top = matches[0]
    second_score = matches[1]["score"] if len(matches) > 1 else 0.0
    close_competitor = second_score >= top["score"] - 0.08
    ambiguous_primary = len(top["primary_candidates"]) != 1
    weak = top["score"] < 0.82
    needs_lexical_disambiguation = weak or close_competitor or ambiguous_primary
    confidence = "exact_term" if top["score"] == 1.0 else (
        "likely_term" if not weak else "exploratory"
    )
    candidates: list[str] = []
    for match in matches:
        if match["score"] < top["score"] - 0.08:
            continue
        for candidate in match["primary_candidates"]:
            if candidate not in candidates:
                candidates.append(candidate)

    return {
        "schema_version": 1,
        "route_kind": "eggy_community_genre_route",
        "query": query,
        "confidence": confidence,
        "matches": matches,
        "provisional_primary_candidates": candidates,
        # This helper sees only a community term, never the experience
        # contract, so even an exact lexical match still needs confirmation of
        # the repeated action and terminal owner.
        "needs_authority_answer": True,
        "needs_lexical_disambiguation": needs_lexical_disambiguation,
        "next_question": top["authority_question"],
        # Even a confident lexical match is a proposal until the experience
        # contract confirms the repeated verb and authoritative terminal.
        "committed_primary_type": None,
        "policy": (
            "Confirm repeated action, authoritative terminal, recovery, and the "
            "theme-removal test before committing one primary type."
        ),
    }


def catalog_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    primary_counts: Counter[str] = Counter()
    modifier_counts: Counter[str] = Counter()
    hybrid_counts: Counter[str] = Counter()
    for row in rows:
        primary_counts.update(row["primary_candidates"])
        modifier_counts.update(row["modifiers"])
        hybrid_counts.update(row["hybrid_modes"])
    return {
        "schema_version": 1,
        "report_kind": "eggy_genre_catalog_summary",
        "row_count": len(rows),
        "primary_type_coverage": {
            type_name: primary_counts[type_name] for type_name in sorted(PRIMARY_TYPES)
        },
        "modifier_coverage": {
            modifier: modifier_counts[modifier] for modifier in sorted(MODIFIERS)
        },
        "hybrid_mode_mentions": dict(sorted(hybrid_counts.items())),
    }


def _self_test(path: Path) -> None:
    rows = parse_catalog(path)
    summary = catalog_summary(rows)
    uncovered_types = [
        key for key, count in summary["primary_type_coverage"].items() if count == 0
    ]
    uncovered_modifiers = [
        key for key, count in summary["modifier_coverage"].items() if count == 0
    ]
    if uncovered_types:
        raise AssertionError(f"catalog misses primary types: {uncovered_types}")
    if uncovered_modifiers:
        raise AssertionError(f"catalog misses modifiers: {uncovered_modifiers}")

    deduction = route_query("狼人杀", rows)
    if deduction["matches"][0]["primary_candidates"] != ["social_deduction"]:
        raise AssertionError("狼人杀 did not route to social deduction")
    vehicle = route_query("赛车", rows)
    if set(vehicle["provisional_primary_candidates"]) != {
        "short_race",
        "chapter_challenge",
    }:
        raise AssertionError("赛车 must preserve short/long route ambiguity")
    if not vehicle["needs_authority_answer"]:
        raise AssertionError("赛车 must ask which route loop owns the terminal")
    if not vehicle["needs_lexical_disambiguation"]:
        raise AssertionError("赛车 must preserve its two lexical candidates")
    themed_title = route_query("目标地图", rows)
    if not themed_title["needs_authority_answer"]:
        raise AssertionError("a themed title must never auto-commit management")
    if themed_title["committed_primary_type"] is not None:
        raise AssertionError("router committed a primary type from a title")
    mixed = route_query("恐怖逃生", rows)
    if not mixed["needs_authority_answer"]:
        raise AssertionError("恐怖逃生 must preserve loop ambiguity")
    if not deduction["needs_authority_answer"]:
        raise AssertionError("an exact community term still needs loop confirmation")
    if any(route_query(term, rows)["committed_primary_type"] for term in ("塔防", "音游", "足球")):
        raise AssertionError("lexical routing must remain provisional")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Route community Eggy map names to provisional design contracts."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--query")
    mode.add_argument("--all-summary", action="store_true")
    mode.add_argument("--self-test", action="store_true")
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()
    if args.limit < 1 or args.limit > 20:
        parser.error("--limit must be between 1 and 20")
    try:
        rows = parse_catalog(args.catalog)
        if args.self_test:
            _self_test(args.catalog)
            print("self-test passed")
            return
        payload = (
            catalog_summary(rows)
            if args.all_summary
            else route_query(args.query, rows, limit=args.limit)
        )
    except (RoutingError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

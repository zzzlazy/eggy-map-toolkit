#!/usr/bin/env python3
"""Expand parametric Eggy design assemblies into explicit world-basis instances.

This script validates design-space arithmetic only. It deliberately emits an
orthonormal world basis rather than guessing the game's Euler convention,
component pivot, or scale semantics.
"""

from __future__ import annotations

import argparse
import ast
from collections import Counter
import json
import math
from pathlib import Path
import re
import sys
from typing import Any


IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
LAYERS = {"COL", "MASS", "MID", "ROUTE", "MECH", "PROP", "FX", "LOGIC", "SAFE"}
COST_ROLES = {
    "VIS_STATIC",
    "COL_PROXY",
    "FOCAL_SHADOW",
    "DYNAMIC_MECH",
    "TRANSPARENT",
    "LIGHT_FX",
    "LOGIC_TIMER",
    "SPAWNED",
}
CONSTRUCTION_KINDS = {
    "BASIC_PRIMITIVE",
    "COLLISION_PROXY",
    "FX_LIGHT_AUDIO",
    "GAMEPLAY_DEVICE",
    "LOGIC_ONLY",
    "THEME_ASSET",
}
DESIGN_ROLES = {
    "ATMOSPHERE",
    "COLLISION",
    "CONTACT",
    "DANGER",
    "ENCLOSURE",
    "GOAL",
    "INTERACTION",
    "LOGIC",
    "NAVIGATION",
    "SCALE_REFERENCE",
    "SILHOUETTE",
    "STATE_FEEDBACK",
    "STRUCTURE",
    "SURFACE_DETAIL",
}
VISIBLE_DESIGN_ROLES = DESIGN_ROLES - {"COLLISION", "LOGIC"}
LAYOUTS = {
    "linear",
    "polyline",
    "grid",
    "arc",
    "radial",
    "vertical",
    "explicit",
}
EPSILON = 1e-6
MAX_ABS_VALUE = 1e9
DEFAULT_MAX_EXPANDED = 250_000
HARD_MAX_EXPANDED = 1_000_000
MAX_GENERATED_PLACEMENTS = 250_000

Vector = tuple[float, float, float]
Basis = tuple[Vector, Vector, Vector]


class ExpansionError(ValueError):
    pass


def _mapping(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ExpansionError(f"{path} must be an object")
    return value


def _list(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise ExpansionError(f"{path} must be an array")
    return value


def _string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ExpansionError(f"{path} must be a non-empty string")
    return value.strip()


def _identifier(value: Any, path: str) -> str:
    result = _string(value, path)
    if not IDENTIFIER.fullmatch(result):
        raise ExpansionError(
            f"{path} must use only letters, digits, '_' or '-', and start alphanumeric"
        )
    return result


def _integer(value: Any, path: str, *, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ExpansionError(f"{path} must be an integer")
    if minimum is not None and value < minimum:
        raise ExpansionError(f"{path} must be >= {minimum}")
    return value


def _number(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ExpansionError(f"{path} must be a finite number")
    result = float(value)
    if not math.isfinite(result) or abs(result) > MAX_ABS_VALUE:
        raise ExpansionError(f"{path} must be finite with abs(value) <= {MAX_ABS_VALUE:g}")
    return result


def _vector(value: Any, path: str) -> Vector:
    raw = _list(value, path)
    if len(raw) != 3:
        raise ExpansionError(f"{path} must contain exactly 3 numbers")
    return tuple(_number(part, f"{path}[{index}]") for index, part in enumerate(raw))  # type: ignore[return-value]


def _add(a: Vector, b: Vector) -> Vector:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _scale(a: Vector, scalar: float) -> Vector:
    return (a[0] * scalar, a[1] * scalar, a[2] * scalar)


def _dot(a: Vector, b: Vector) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: Vector, b: Vector) -> Vector:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _length(a: Vector) -> float:
    return math.sqrt(_dot(a, a))


def _normalize(a: Vector, path: str) -> Vector:
    length = _length(a)
    if length <= EPSILON:
        raise ExpansionError(f"{path} must not be a zero-length vector")
    return _scale(a, 1.0 / length)


def _distance(a: Vector, b: Vector) -> float:
    return _length((a[0] - b[0], a[1] - b[1], a[2] - b[2]))


def _basis(value: Any, path: str) -> Basis:
    raw = _mapping(value, path)
    u = _vector(raw.get("u"), f"{path}.u")
    v = _vector(raw.get("v"), f"{path}.v")
    f = _vector(raw.get("f"), f"{path}.f")
    for name, vector in (("u", u), ("v", v), ("f", f)):
        if abs(_length(vector) - 1.0) > EPSILON:
            raise ExpansionError(f"{path}.{name} must be unit length")
    for left_name, left, right_name, right in (
        ("u", u, "v", v),
        ("u", u, "f", f),
        ("v", v, "f", f),
    ):
        if abs(_dot(left, right)) > EPSILON:
            raise ExpansionError(f"{path}.{left_name} and {right_name} must be orthogonal")
    if _distance(_cross(u, v), f) > EPSILON:
        raise ExpansionError(f"{path} must be right-handed: cross(u, v) == f")
    return (u, v, f)


IDENTITY_BASIS: Basis = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))


def _basis_from_forward(forward: Vector, up_hint: Vector, path: str) -> Basis:
    """Build a right-handed frame while allowing a sloped forward vector."""
    f = _normalize(forward, f"{path}.forward")
    up = _normalize(up_hint, f"{path}.up")
    lateral = _cross(up, f)
    if _length(lateral) <= EPSILON:
        raise ExpansionError(f"{path}.forward must not be parallel to up")
    u = _normalize(lateral, f"{path}.lateral")
    v = _normalize(_cross(f, u), f"{path}.resolved_up")
    return (u, v, f)


def _rotate_basis_about_v(basis: Basis, angle: float) -> Basis:
    """Rotate local right/forward axes around the frame's up axis."""
    u, v, f = basis
    cosine = math.cos(angle)
    sine = math.sin(angle)
    return (
        _add(_scale(u, cosine), _scale(f, -sine)),
        v,
        _add(_scale(u, sine), _scale(f, cosine)),
    )


def _transform_vector(basis: Basis, local: Vector) -> Vector:
    u, v, f = basis
    return _add(_add(_scale(u, local[0]), _scale(v, local[1])), _scale(f, local[2]))


def _compose_basis(parent: Basis, local: Basis) -> Basis:
    return tuple(_transform_vector(parent, axis) for axis in local)  # type: ignore[return-value]


def _round(value: float) -> float:
    result = round(value, 9)
    return 0.0 if result == -0.0 else result


def _vector_json(value: Vector) -> list[float]:
    return [_round(part) for part in value]


def _basis_json(value: Basis) -> dict[str, list[float]]:
    return {name: _vector_json(axis) for name, axis in zip(("u", "v", "f"), value)}


def _eval_node(node: ast.AST, variables: dict[str, float], path: str) -> float:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ExpansionError(f"{path} contains a non-numeric constant")
        return _number(node.value, path)
    if isinstance(node, ast.Name):
        if node.id not in variables:
            raise ExpansionError(f"{path} references unknown parameter {node.id!r}")
        return variables[node.id]
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _eval_node(node.operand, variables, path)
        return value if isinstance(node.op, ast.UAdd) else -value
    if isinstance(node, ast.BinOp) and isinstance(
        node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)
    ):
        left = _eval_node(node.left, variables, path)
        right = _eval_node(node.right, variables, path)
        if isinstance(node.op, ast.Add):
            result = left + right
        elif isinstance(node.op, ast.Sub):
            result = left - right
        elif isinstance(node.op, ast.Mult):
            result = left * right
        else:
            if abs(right) <= EPSILON:
                raise ExpansionError(f"{path} divides by zero")
            result = left / right
        return _number(result, path)
    raise ExpansionError(f"{path} may use only numbers, parameters, +, -, * and /")


def _expression(value: Any, variables: dict[str, float], path: str) -> float:
    if isinstance(value, bool):
        raise ExpansionError(f"{path} must be a number or arithmetic expression")
    if isinstance(value, (int, float)):
        return _number(value, path)
    if not isinstance(value, str) or not value.strip():
        raise ExpansionError(f"{path} must be a number or arithmetic expression")
    try:
        tree = ast.parse(value, mode="eval")
    except SyntaxError as exc:
        raise ExpansionError(f"{path} is not a valid expression: {exc.msg}") from exc
    return _number(_eval_node(tree.body, variables, path), path)


def _expression_vector(value: Any, variables: dict[str, float], path: str) -> Vector:
    raw = _list(value, path)
    if len(raw) != 3:
        raise ExpansionError(f"{path} must contain exactly 3 values")
    return tuple(
        _expression(part, variables, f"{path}[{index}]")
        for index, part in enumerate(raw)
    )  # type: ignore[return-value]


def _parameters(value: Any, path: str) -> dict[str, float]:
    raw = _mapping(value, path)
    result: dict[str, float] = {}
    for key, number in raw.items():
        name = _identifier(key, f"{path} key")
        result[name] = _number(number, f"{path}.{name}")
    return result


def _variant_sequence(value: Any, allowed: set[str], path: str) -> list[str]:
    raw = _list(value, path)
    if not raw:
        raise ExpansionError(f"{path} cannot be empty")
    result = [_identifier(item, f"{path}[{index}]") for index, item in enumerate(raw)]
    unknown = sorted(set(result) - allowed)
    if unknown:
        raise ExpansionError(f"{path} contains unknown variants: {', '.join(unknown)}")
    return result


def _parse_families(value: Any) -> dict[str, dict[str, Any]]:
    families: dict[str, dict[str, Any]] = {}
    for family_index, raw_family in enumerate(_list(value, "families")):
        path = f"families[{family_index}]"
        family = _mapping(raw_family, path)
        name = _identifier(family.get("name"), f"{path}.name")
        if name in families:
            raise ExpansionError(f"duplicate family name {name}")
        params = _parameters(family.get("parameters", {}), f"{path}.parameters")
        variants_raw = family.get("variants", ["A"])
        variants = _variant_sequence(variants_raw, {
            _identifier(item, f"{path}.variants item")
            for item in _list(variants_raw, f"{path}.variants")
        }, f"{path}.variants")
        if len(set(variants)) != len(variants):
            raise ExpansionError(f"{path}.variants contains duplicates")
        variant_set = set(variants)
        pieces: list[dict[str, Any]] = []
        piece_names: set[str] = set()
        for piece_index, raw_piece in enumerate(_list(family.get("pieces"), f"{path}.pieces")):
            piece_path = f"{path}.pieces[{piece_index}]"
            piece = _mapping(raw_piece, piece_path)
            piece_name = _identifier(piece.get("name"), f"{piece_path}.name")
            if piece_name in piece_names:
                raise ExpansionError(f"duplicate piece name {name}.{piece_name}")
            piece_names.add(piece_name)
            layer = _string(piece.get("layer"), f"{piece_path}.layer")
            if layer not in LAYERS:
                raise ExpansionError(f"{piece_path}.layer must be one of {', '.join(sorted(LAYERS))}")
            cost_role = _string(piece.get("cost_role"), f"{piece_path}.cost_role")
            if cost_role not in COST_ROLES:
                raise ExpansionError(
                    f"{piece_path}.cost_role must be one of {', '.join(sorted(COST_ROLES))}"
                )
            construction_kind = _string(
                piece.get("construction_kind"),
                f"{piece_path}.construction_kind",
            )
            if construction_kind not in CONSTRUCTION_KINDS:
                raise ExpansionError(
                    f"{piece_path}.construction_kind must be one of "
                    f"{', '.join(sorted(CONSTRUCTION_KINDS))}"
                )
            if construction_kind == "COLLISION_PROXY" and cost_role != "COL_PROXY":
                raise ExpansionError(
                    f"{piece_path} COLLISION_PROXY must use cost_role COL_PROXY"
                )
            if construction_kind == "LOGIC_ONLY" and cost_role != "LOGIC_TIMER":
                raise ExpansionError(
                    f"{piece_path} LOGIC_ONLY must use cost_role LOGIC_TIMER"
                )
            design_roles_raw = _list(
                piece.get("design_roles"), f"{piece_path}.design_roles"
            )
            if not design_roles_raw:
                raise ExpansionError(f"{piece_path}.design_roles cannot be empty")
            design_roles = [
                _string(role, f"{piece_path}.design_roles[{role_index}]")
                for role_index, role in enumerate(design_roles_raw)
            ]
            if len(design_roles) != len(set(design_roles)):
                raise ExpansionError(f"{piece_path}.design_roles contains duplicates")
            unknown_design_roles = sorted(set(design_roles) - DESIGN_ROLES)
            if unknown_design_roles:
                raise ExpansionError(
                    f"{piece_path}.design_roles contains unknown roles: "
                    + ", ".join(unknown_design_roles)
                )
            if construction_kind == "COLLISION_PROXY" and "COLLISION" not in design_roles:
                raise ExpansionError(
                    f"{piece_path} COLLISION_PROXY must include design role COLLISION"
                )
            if construction_kind == "LOGIC_ONLY" and "LOGIC" not in design_roles:
                raise ExpansionError(
                    f"{piece_path} LOGIC_ONLY must include design role LOGIC"
                )
            if (
                construction_kind in {"BASIC_PRIMITIVE", "FX_LIGHT_AUDIO", "THEME_ASSET"}
                and not (set(design_roles) & VISIBLE_DESIGN_ROLES)
            ):
                raise ExpansionError(
                    f"{piece_path} visible construction must include a visible design role"
                )
            include = set(_variant_sequence(
                piece.get("include_variants", variants), variant_set, f"{piece_path}.include_variants"
            ))
            exclude = set(_variant_sequence(
                piece.get("exclude_variants", []), variant_set, f"{piece_path}.exclude_variants"
            )) if piece.get("exclude_variants", []) else set()
            if include & exclude:
                overlap = ", ".join(sorted(include & exclude))
                raise ExpansionError(f"{piece_path} includes and excludes variants: {overlap}")
            pieces.append({
                "name": piece_name,
                "component_role": _string(piece.get("component_role"), f"{piece_path}.component_role"),
                "layer": layer,
                "cost_role": cost_role,
                "construction_kind": construction_kind,
                "design_roles": design_roles,
                "local_position": piece.get("local_position"),
                "local_size": piece.get("local_size"),
                "local_basis": _basis(piece.get("local_basis", {
                    "u": [1, 0, 0], "v": [0, 1, 0], "f": [0, 0, 1]
                }), f"{piece_path}.local_basis"),
                "include": include,
                "exclude": exclude,
            })
        if not pieces:
            raise ExpansionError(f"{path}.pieces cannot be empty")
        families[name] = {
            "name": name,
            "parameters": params,
            "variants": variants,
            "variant_set": variant_set,
            "pieces": pieces,
        }
    if not families:
        raise ExpansionError("families cannot be empty")
    return families


def _placement_basis(value: Any, path: str) -> Basis:
    return _basis(value, path)


def _generated_placements(
    raw: Any,
    path: str,
    family: dict[str, Any],
) -> list[dict[str, Any]]:
    item = _mapping(raw, path)
    layout = _string(item.get("layout"), f"{path}.layout")
    if layout not in LAYOUTS:
        raise ExpansionError(f"{path}.layout must be one of {', '.join(sorted(LAYOUTS))}")
    generator_name = _identifier(item.get("name"), f"{path}.name")
    zone = _identifier(item.get("zone"), f"{path}.zone")
    variants = _variant_sequence(
        item.get("variant_sequence", [family["variants"][0]]),
        family["variant_set"],
        f"{path}.variant_sequence",
    )
    override = _parameters(item.get("parameters", {}), f"{path}.parameters")
    params = dict(family["parameters"])
    params.update(override)
    result: list[dict[str, Any]] = []

    def append(name: str, origin: Vector, basis: Basis, index: int, variant: str | None = None) -> None:
        result.append({
            "name": _identifier(name, f"{path} generated name"),
            "generator": generator_name,
            "zone": zone,
            "origin": origin,
            "basis": basis,
            "variant": variant or variants[index % len(variants)],
            "parameters": params,
        })

    if layout == "linear":
        origin = _vector(item.get("origin"), f"{path}.origin")
        basis = _placement_basis(item.get("basis"), f"{path}.basis")
        count = _integer(item.get("count"), f"{path}.count", minimum=1)
        if count > MAX_GENERATED_PLACEMENTS:
            raise ExpansionError(
                f"{path}.count exceeds {MAX_GENERATED_PLACEMENTS} placements"
            )
        step = _number(item.get("step"), f"{path}.step")
        rise = _number(item.get("rise_per_step", 0), f"{path}.rise_per_step")
        for index in range(count):
            offset = _add(_scale(basis[2], step * index), _scale(basis[1], rise * index))
            append(f"{generator_name}_{index + 1:03d}", _add(origin, offset), basis, index)
    elif layout == "polyline":
        raw_points = _list(item.get("points"), f"{path}.points")
        if len(raw_points) < 2:
            raise ExpansionError(f"{path}.points must contain at least 2 stations")
        if len(raw_points) > MAX_GENERATED_PLACEMENTS:
            raise ExpansionError(
                f"{path}.points exceeds {MAX_GENERATED_PLACEMENTS} placements"
            )
        points = [
            _vector(raw_point, f"{path}.points[{index}]")
            for index, raw_point in enumerate(raw_points)
        ]
        up_hint = _vector(item.get("up", [0, 1, 0]), f"{path}.up")
        for index, origin in enumerate(points):
            if index < len(points) - 1:
                forward = (
                    points[index + 1][0] - origin[0],
                    points[index + 1][1] - origin[1],
                    points[index + 1][2] - origin[2],
                )
            else:
                forward = (
                    origin[0] - points[index - 1][0],
                    origin[1] - points[index - 1][1],
                    origin[2] - points[index - 1][2],
                )
            basis = _basis_from_forward(
                forward,
                up_hint,
                f"{path}.points[{index}]",
            )
            append(f"{generator_name}_{index + 1:03d}", origin, basis, index)
    elif layout == "grid":
        origin = _vector(item.get("origin"), f"{path}.origin")
        basis = _placement_basis(item.get("basis"), f"{path}.basis")
        count_u = _integer(item.get("count_u"), f"{path}.count_u", minimum=1)
        count_f = _integer(item.get("count_f"), f"{path}.count_f", minimum=1)
        if count_u * count_f > MAX_GENERATED_PLACEMENTS:
            raise ExpansionError(
                f"{path} grid exceeds {MAX_GENERATED_PLACEMENTS} placements"
            )
        step_u = _number(item.get("step_u"), f"{path}.step_u")
        step_f = _number(item.get("step_f"), f"{path}.step_f")
        index = 0
        for row in range(count_f):
            for column in range(count_u):
                offset = _add(_scale(basis[0], step_u * column), _scale(basis[2], step_f * row))
                append(
                    f"{generator_name}_{column + 1:03d}_{row + 1:03d}",
                    _add(origin, offset),
                    basis,
                    index,
                )
                index += 1
    elif layout == "arc":
        center = _vector(item.get("center"), f"{path}.center")
        radius = _number(item.get("radius"), f"{path}.radius")
        if radius <= 0:
            raise ExpansionError(f"{path}.radius must be > 0")
        count = _integer(item.get("count"), f"{path}.count", minimum=1)
        if count > MAX_GENERATED_PLACEMENTS:
            raise ExpansionError(
                f"{path}.count exceeds {MAX_GENERATED_PLACEMENTS} placements"
            )
        start = math.radians(_number(item.get("start_angle_deg", 0), f"{path}.start_angle_deg"))
        step = math.radians(_number(item.get("step_angle_deg"), f"{path}.step_angle_deg"))
        rise = _number(item.get("rise_per_step", 0), f"{path}.rise_per_step")
        up = _vector(item.get("up"), f"{path}.up")
        radial0 = _vector(item.get("radial0"), f"{path}.radial0")
        if abs(_length(up) - 1.0) > EPSILON or abs(_length(radial0) - 1.0) > EPSILON:
            raise ExpansionError(f"{path}.up and radial0 must be unit length")
        if abs(_dot(up, radial0)) > EPSILON:
            raise ExpansionError(f"{path}.up and radial0 must be orthogonal")
        tangent0 = _cross(radial0, up)
        for index in range(count):
            angle = start + step * index
            radial = _add(_scale(radial0, math.cos(angle)), _scale(tangent0, math.sin(angle)))
            tangent = _add(_scale(radial0, -math.sin(angle)), _scale(tangent0, math.cos(angle)))
            basis = (radial, up, tangent)
            origin = _add(_add(center, _scale(radial, radius)), _scale(up, rise * index))
            append(f"{generator_name}_{index + 1:03d}", origin, basis, index)
    elif layout == "radial":
        center = _vector(item.get("center"), f"{path}.center")
        radius = _number(item.get("radius"), f"{path}.radius")
        if radius <= 0:
            raise ExpansionError(f"{path}.radius must be > 0")
        count = _integer(item.get("count"), f"{path}.count", minimum=1)
        if count > MAX_GENERATED_PLACEMENTS:
            raise ExpansionError(
                f"{path}.count exceeds {MAX_GENERATED_PLACEMENTS} placements"
            )
        start = math.radians(
            _number(item.get("start_angle_deg", 0), f"{path}.start_angle_deg")
        )
        step = math.radians(
            _number(item.get("step_angle_deg"), f"{path}.step_angle_deg")
        )
        rise = _number(item.get("rise_per_step", 0), f"{path}.rise_per_step")
        up = _normalize(_vector(item.get("up"), f"{path}.up"), f"{path}.up")
        radial0 = _normalize(
            _vector(item.get("radial0"), f"{path}.radial0"),
            f"{path}.radial0",
        )
        if abs(_dot(up, radial0)) > EPSILON:
            raise ExpansionError(f"{path}.up and radial0 must be orthogonal")
        facing = _string(item.get("facing", "outward"), f"{path}.facing")
        if facing not in {"outward", "inward"}:
            raise ExpansionError(f"{path}.facing must be outward or inward")
        tangent0 = _cross(radial0, up)
        for index in range(count):
            angle = start + step * index
            radial = _add(
                _scale(radial0, math.cos(angle)),
                _scale(tangent0, math.sin(angle)),
            )
            forward = radial if facing == "outward" else _scale(radial, -1)
            basis = _basis_from_forward(forward, up, f"{path}[{index}]")
            origin = _add(
                _add(center, _scale(radial, radius)),
                _scale(up, rise * index),
            )
            append(f"{generator_name}_{index + 1:03d}", origin, basis, index)
    elif layout == "vertical":
        origin = _vector(item.get("origin"), f"{path}.origin")
        base_basis = _placement_basis(item.get("basis"), f"{path}.basis")
        count = _integer(item.get("count"), f"{path}.count", minimum=1)
        if count > MAX_GENERATED_PLACEMENTS:
            raise ExpansionError(
                f"{path}.count exceeds {MAX_GENERATED_PLACEMENTS} placements"
            )
        step_u = _number(item.get("step_u", 0), f"{path}.step_u")
        step_v = _number(item.get("step_v"), f"{path}.step_v")
        step_f = _number(item.get("step_f", 0), f"{path}.step_f")
        if abs(step_v) <= EPSILON:
            raise ExpansionError(f"{path}.step_v must be non-zero")
        twist = math.radians(
            _number(
                item.get("twist_deg_per_step", 0),
                f"{path}.twist_deg_per_step",
            )
        )
        for index in range(count):
            offset = _add(
                _add(
                    _scale(base_basis[0], step_u * index),
                    _scale(base_basis[1], step_v * index),
                ),
                _scale(base_basis[2], step_f * index),
            )
            basis = _rotate_basis_about_v(base_basis, twist * index)
            append(
                f"{generator_name}_{index + 1:03d}",
                _add(origin, offset),
                basis,
                index,
            )
    else:
        instances = _list(item.get("instances"), f"{path}.instances")
        if not instances:
            raise ExpansionError(f"{path}.instances cannot be empty")
        if len(instances) > MAX_GENERATED_PLACEMENTS:
            raise ExpansionError(
                f"{path}.instances exceeds {MAX_GENERATED_PLACEMENTS} placements"
            )
        for index, raw_instance in enumerate(instances):
            instance_path = f"{path}.instances[{index}]"
            instance = _mapping(raw_instance, instance_path)
            instance_variant = _identifier(
                instance.get("variant", variants[index % len(variants)]),
                f"{instance_path}.variant",
            )
            if instance_variant not in family["variant_set"]:
                raise ExpansionError(f"{instance_path}.variant is unknown")
            append(
                _identifier(instance.get("name"), f"{instance_path}.name"),
                _vector(instance.get("origin"), f"{instance_path}.origin"),
                _placement_basis(instance.get("basis"), f"{instance_path}.basis"),
                index,
                instance_variant,
            )
    if len(result) > MAX_GENERATED_PLACEMENTS:
        raise ExpansionError(
            f"{path} generates more than {MAX_GENERATED_PLACEMENTS} placements"
        )
    frames: set[tuple[float, ...]] = set()
    for generated in result:
        frame = tuple(
            _round(value)
            for vector in (generated["origin"], *generated["basis"])
            for value in vector
        )
        if frame in frames:
            raise ExpansionError(f"{path} generates duplicate placement frames")
        frames.add(frame)
    return result


def expand_plan(plan: Any) -> dict[str, Any]:
    root = _mapping(plan, "plan")
    version = _integer(root.get("schema_version"), "schema_version", minimum=1)
    if version != 1:
        raise ExpansionError(f"unsupported schema_version {version}; expected 1")
    prefix = _identifier(root.get("name_prefix"), "name_prefix")
    max_expanded = _integer(
        root.get("max_expanded", DEFAULT_MAX_EXPANDED),
        "max_expanded",
        minimum=1,
    )
    if max_expanded > HARD_MAX_EXPANDED:
        raise ExpansionError(
            f"max_expanded cannot exceed safety limit {HARD_MAX_EXPANDED}"
        )
    families = _parse_families(root.get("families"))
    placement_names: set[str] = set()
    instances: list[dict[str, Any]] = []
    counters = {
        "zones": Counter(),
        "families": Counter(),
        "layers": Counter(),
        "cost_roles": Counter(),
        "construction_kinds": Counter(),
        "design_roles": Counter(),
    }

    placements = _list(root.get("placements"), "placements")
    if not placements:
        raise ExpansionError("placements cannot be empty")
    for placement_index, raw_placement in enumerate(placements):
        path = f"placements[{placement_index}]"
        placement = _mapping(raw_placement, path)
        family_name = _identifier(placement.get("family"), f"{path}.family")
        if family_name not in families:
            raise ExpansionError(f"{path}.family references unknown family {family_name}")
        family = families[family_name]
        generated = _generated_placements(placement, path, family)
        for generated_item in generated:
            placement_name = generated_item["name"]
            if placement_name in placement_names:
                raise ExpansionError(f"duplicate generated placement name {placement_name}")
            placement_names.add(placement_name)
            variant = generated_item["variant"]
            params = generated_item["parameters"]
            for piece_index, piece in enumerate(family["pieces"]):
                if variant not in piece["include"] or variant in piece["exclude"]:
                    continue
                piece_path = f"{path} generated {placement_name}.{piece['name']}"
                local_position = _expression_vector(piece["local_position"], params, f"{piece_path}.local_position")
                local_size = _expression_vector(piece["local_size"], params, f"{piece_path}.local_size")
                if any(value <= 0 for value in local_size):
                    raise ExpansionError(f"{piece_path}.local_size values must be > 0")
                world_position = _add(
                    generated_item["origin"],
                    _transform_vector(generated_item["basis"], local_position),
                )
                world_basis = _compose_basis(generated_item["basis"], piece["local_basis"])
                logical_name = "_".join((
                    prefix,
                    generated_item["zone"],
                    family_name,
                    placement_name,
                    variant,
                    piece["name"],
                ))
                instance = {
                    "name": logical_name,
                    "zone": generated_item["zone"],
                    "family": family_name,
                    "generator": generated_item["generator"],
                    "placement": placement_name,
                    "variant": variant,
                    "piece": piece["name"],
                    "component_role": piece["component_role"],
                    "layer": piece["layer"],
                    "cost_role": piece["cost_role"],
                    "construction_kind": piece["construction_kind"],
                    "design_roles": piece["design_roles"],
                    "world_position": _vector_json(world_position),
                    "world_basis": _basis_json(world_basis),
                    "target_size_local": _vector_json(local_size),
                }
                instances.append(instance)
                counters["zones"][instance["zone"]] += 1
                counters["families"][instance["family"]] += 1
                counters["layers"][instance["layer"]] += 1
                counters["cost_roles"][instance["cost_role"]] += 1
                counters["construction_kinds"][instance["construction_kind"]] += 1
                for design_role in instance["design_roles"]:
                    counters["design_roles"][design_role] += 1
                if len(instances) > max_expanded:
                    raise ExpansionError(
                        f"expanded instance count exceeds max_expanded={max_expanded}"
                    )

    logical_names = [item["name"] for item in instances]
    if len(logical_names) != len(set(logical_names)):
        raise ExpansionError("expanded logical names are not unique")
    expected_total = root.get("expected_total")
    if expected_total is not None:
        expected = _integer(expected_total, "expected_total", minimum=0)
        if expected != len(instances):
            raise ExpansionError(
                f"expected_total={expected}, expanded total={len(instances)}"
            )
    summary = {
        "schema_version": version,
        "expanded_total": len(instances),
        "placement_total": len(placement_names),
        "zones": dict(sorted(counters["zones"].items())),
        "families": dict(sorted(counters["families"].items())),
        "layers": dict(sorted(counters["layers"].items())),
        "cost_roles": dict(sorted(counters["cost_roles"].items())),
        "construction_kinds": dict(sorted(counters["construction_kinds"].items())),
        "design_roles": dict(sorted(counters["design_roles"].items())),
    }
    return {"summary": summary, "instances": instances}


def example_plan() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "name_prefix": "DEMO",
        "expected_total": 10,
        "construction_strategy": {
            "mode": "primitive_led",
            "primitive_visible_share_min": 0.7,
            "rationale": "Basic boxes carry the wall silhouette; the sign is a sparse semantic asset.",
        },
        "quality_contract": {
            "build_bounds": {"min": [-6, -1, -2], "max": [6, 8, 26]},
            "minimum_world_visible_share": 0.8,
            "required_completion_layers": ["MASS", "MID", "ROUTE"],
            "required_design_roles": ["SILHOUETTE", "STRUCTURE", "NAVIGATION"],
            "minimum_design_role_counts": {
                "SILHOUETTE": 8,
                "STRUCTURE": 8,
                "NAVIGATION": 2,
            },
            "zone_targets": {
                "RUN": {
                    "bounds": {"min": [-6, -1, -2], "max": [6, 8, 26]},
                    "minimum_world_visible_instances": 10,
                    "minimum_family_count": 1,
                    "minimum_extent": [8, 5, 20],
                    "required_layers": ["MASS", "MID", "ROUTE"],
                    "required_design_roles": [
                        "SILHOUETTE",
                        "STRUCTURE",
                        "NAVIGATION",
                    ],
                    "minimum_design_role_counts": {
                        "SILHOUETTE": 8,
                        "STRUCTURE": 8,
                        "NAVIGATION": 2,
                    },
                }
            },
            "uniform_family_exceptions": [],
            "rationale": "The test corridor must occupy a real volume, use all promised completion layers, and contain no padded duplicates.",
        },
        "families": [
            {
                "name": "WALL_BAY",
                "parameters": {"W": 10, "H": 6, "D": 1},
                "variants": ["A", "B"],
                "pieces": [
                    {
                        "name": "PILLAR_L",
                        "component_role": "basic_box",
                        "layer": "MASS",
                        "cost_role": "VIS_STATIC",
                        "construction_kind": "BASIC_PRIMITIVE",
                        "design_roles": ["SILHOUETTE", "ENCLOSURE", "STRUCTURE"],
                        "local_position": ["-0.42*W", "0.5*H", 0],
                        "local_size": ["0.12*W", "H", "D"],
                    },
                    {
                        "name": "PILLAR_R",
                        "component_role": "basic_box",
                        "layer": "MID",
                        "cost_role": "VIS_STATIC",
                        "construction_kind": "BASIC_PRIMITIVE",
                        "design_roles": ["SILHOUETTE", "ENCLOSURE", "STRUCTURE"],
                        "local_position": ["0.42*W", "0.5*H", 0],
                        "local_size": ["0.12*W", "H", "D"],
                    },
                    {
                        "name": "SIGN_B",
                        "component_role": "route_sign",
                        "layer": "ROUTE",
                        "cost_role": "FOCAL_SHADOW",
                        "construction_kind": "THEME_ASSET",
                        "design_roles": ["NAVIGATION", "STATE_FEEDBACK"],
                        "local_position": [0, "0.75*H", 0],
                        "local_size": ["0.35*W", "0.15*H", "0.2*D"],
                        "include_variants": ["B"],
                    },
                ],
            }
        ],
        "placements": [
            {
                "name": "CORRIDOR",
                "zone": "RUN",
                "family": "WALL_BAY",
                "layout": "linear",
                "origin": [0, 0, 0],
                "basis": {
                    "u": [1, 0, 0],
                    "v": [0, 1, 0],
                    "f": [0, 0, 1],
                },
                "count": 4,
                "step": 8,
                "variant_sequence": ["A", "B"],
            }
        ],
    }


def layout_example_plan(layout: str) -> dict[str, Any]:
    """Return a small design-space-only example for one placement generator."""
    if layout not in LAYOUTS:
        raise ExpansionError(f"unknown example layout {layout}")
    plan = json.loads(json.dumps(example_plan()))
    plan.pop("construction_strategy", None)
    plan.pop("quality_contract", None)
    plan["seed_status"] = (
        "design-space example only; add a real quality contract, component evidence, "
        "and game-axis conversion before deployment"
    )
    examples: dict[str, tuple[int, dict[str, Any]]] = {
        "linear": (10, plan["placements"][0]),
        "polyline": (
            7,
            {
                "name": "RIDGE",
                "zone": "RUN",
                "family": "WALL_BAY",
                "layout": "polyline",
                "points": [[0, 0, 0], [0, 0, 8], [8, 1, 8]],
                "up": [0, 1, 0],
                "variant_sequence": ["A", "B", "A"],
            },
        ),
        "grid": (
            10,
            {
                "name": "ROOM_GRID",
                "zone": "RUN",
                "family": "WALL_BAY",
                "layout": "grid",
                "origin": [0, 0, 0],
                "basis": {"u": [1, 0, 0], "v": [0, 1, 0], "f": [0, 0, 1]},
                "count_u": 2,
                "count_f": 2,
                "step_u": 12,
                "step_f": 8,
                "variant_sequence": ["A", "B"],
            },
        ),
        "arc": (
            10,
            {
                "name": "RING",
                "zone": "RUN",
                "family": "WALL_BAY",
                "layout": "arc",
                "center": [0, 0, 0],
                "radius": 12,
                "up": [0, 1, 0],
                "radial0": [1, 0, 0],
                "count": 4,
                "step_angle_deg": 90,
                "variant_sequence": ["A", "B"],
            },
        ),
        "radial": (
            10,
            {
                "name": "SPOKES",
                "zone": "RUN",
                "family": "WALL_BAY",
                "layout": "radial",
                "center": [0, 0, 0],
                "radius": 12,
                "up": [0, 1, 0],
                "radial0": [1, 0, 0],
                "count": 4,
                "step_angle_deg": 90,
                "facing": "outward",
                "variant_sequence": ["A", "B"],
            },
        ),
        "vertical": (
            7,
            {
                "name": "TOWER",
                "zone": "RUN",
                "family": "WALL_BAY",
                "layout": "vertical",
                "origin": [0, 0, 0],
                "basis": {"u": [1, 0, 0], "v": [0, 1, 0], "f": [0, 0, 1]},
                "count": 3,
                "step_v": 7,
                "twist_deg_per_step": 45,
                "variant_sequence": ["A", "B", "A"],
            },
        ),
        "explicit": (
            5,
            {
                "name": "LANDMARKS",
                "zone": "RUN",
                "family": "WALL_BAY",
                "layout": "explicit",
                "variant_sequence": ["A", "B"],
                "instances": [
                    {
                        "name": "ENTRY_FRAME",
                        "origin": [0, 0, 0],
                        "basis": {
                            "u": [1, 0, 0],
                            "v": [0, 1, 0],
                            "f": [0, 0, 1],
                        },
                        "variant": "A",
                    },
                    {
                        "name": "TURN_FRAME",
                        "origin": [12, 0, 8],
                        "basis": {
                            "u": [0, 0, -1],
                            "v": [0, 1, 0],
                            "f": [1, 0, 0],
                        },
                        "variant": "B",
                    },
                ],
            },
        ),
    }
    expected_total, placement = examples[layout]
    plan["expected_total"] = expected_total
    plan["placements"] = [placement]
    return plan


def _expect_invalid(plan: dict[str, Any], needle: str) -> None:
    try:
        expand_plan(plan)
    except ExpansionError as exc:
        if needle not in str(exc):
            raise AssertionError(f"expected {needle!r} in error, got: {exc}") from exc
    else:
        raise AssertionError("invalid plan was accepted")


def _self_test() -> None:
    for layout in sorted(LAYOUTS):
        try:
            expand_plan(layout_example_plan(layout))
        except ExpansionError as exc:
            raise AssertionError(f"{layout} example did not expand: {exc}") from exc

    result = expand_plan(example_plan())
    if result["summary"]["expanded_total"] != 10:
        raise AssertionError("linear/variant expansion total mismatch")
    positions = [item["world_position"] for item in result["instances"] if item["piece"] == "PILLAR_L"]
    if positions != [[-4.2, 3.0, 0.0], [-4.2, 3.0, 8.0], [-4.2, 3.0, 16.0], [-4.2, 3.0, 24.0]]:
        raise AssertionError(f"linear positions mismatch: {positions}")

    grid = example_plan()
    grid["expected_total"] = 8
    grid["placements"][0] = {
        "name": "GRID",
        "zone": "ROOM",
        "family": "WALL_BAY",
        "layout": "grid",
        "origin": [0, 0, 0],
        "basis": {"u": [1, 0, 0], "v": [0, 1, 0], "f": [0, 0, 1]},
        "count_u": 2,
        "count_f": 2,
        "step_u": 10,
        "step_f": 8,
        "variant_sequence": ["A"],
    }
    if expand_plan(grid)["summary"]["expanded_total"] != 8:
        raise AssertionError("grid expansion mismatch")

    polyline = example_plan()
    polyline["expected_total"] = 6
    polyline["placements"][0] = {
        "name": "RIDGE",
        "zone": "ROUTE",
        "family": "WALL_BAY",
        "layout": "polyline",
        "points": [[0, 0, 0], [0, 0, 8], [8, 0, 8]],
        "up": [0, 1, 0],
        "variant_sequence": ["A"],
    }
    polyline_result = expand_plan(polyline)
    polyline_forward = [
        item["world_basis"]["f"]
        for item in polyline_result["instances"]
        if item["piece"] == "PILLAR_L"
    ]
    if polyline_forward != [[0.0, 0.0, 1.0], [1.0, 0.0, 0.0], [1.0, 0.0, 0.0]]:
        raise AssertionError(f"polyline tangent mismatch: {polyline_forward}")

    arc = example_plan()
    arc["expected_total"] = 8
    arc["placements"][0] = {
        "name": "RING",
        "zone": "ARENA",
        "family": "WALL_BAY",
        "layout": "arc",
        "center": [0, 0, 0],
        "radius": 10,
        "up": [0, 1, 0],
        "radial0": [1, 0, 0],
        "count": 4,
        "step_angle_deg": 90,
        "variant_sequence": ["A"],
    }
    arc_result = expand_plan(arc)
    arc_origins = {
        tuple(item["world_position"])
        for item in arc_result["instances"]
        if item["piece"] == "PILLAR_L"
    }
    expected_arc = {(5.8, 3.0, 0.0), (0.0, 3.0, 5.8), (-5.8, 3.0, 0.0), (0.0, 3.0, -5.8)}
    if arc_origins != expected_arc:
        raise AssertionError(f"arc expansion mismatch: {arc_origins}")

    radial = example_plan()
    radial["expected_total"] = 8
    radial["placements"][0] = {
        "name": "SPOKES",
        "zone": "HUB",
        "family": "WALL_BAY",
        "layout": "radial",
        "center": [0, 0, 0],
        "radius": 10,
        "up": [0, 1, 0],
        "radial0": [1, 0, 0],
        "count": 4,
        "step_angle_deg": 90,
        "facing": "outward",
        "variant_sequence": ["A"],
    }
    radial_result = expand_plan(radial)
    radial_forward = {
        tuple(item["world_basis"]["f"])
        for item in radial_result["instances"]
        if item["piece"] == "PILLAR_L"
    }
    expected_radial_forward = {
        (1.0, 0.0, 0.0),
        (0.0, 0.0, 1.0),
        (-1.0, 0.0, 0.0),
        (0.0, 0.0, -1.0),
    }
    if radial_forward != expected_radial_forward:
        raise AssertionError(f"radial facing mismatch: {radial_forward}")

    vertical = example_plan()
    vertical["expected_total"] = 6
    vertical["placements"][0] = {
        "name": "TOWER",
        "zone": "STACK",
        "family": "WALL_BAY",
        "layout": "vertical",
        "origin": [0, 0, 0],
        "basis": {"u": [1, 0, 0], "v": [0, 1, 0], "f": [0, 0, 1]},
        "count": 3,
        "step_v": 7,
        "twist_deg_per_step": 90,
        "variant_sequence": ["A"],
    }
    vertical_result = expand_plan(vertical)
    vertical_left = [
        item
        for item in vertical_result["instances"]
        if item["piece"] == "PILLAR_L"
    ]
    if [item["world_position"][1] for item in vertical_left] != [3.0, 10.0, 17.0]:
        raise AssertionError(f"vertical elevations mismatch: {vertical_left}")
    if [item["world_basis"]["f"] for item in vertical_left] != [
        [0.0, 0.0, 1.0],
        [1.0, 0.0, 0.0],
        [0.0, 0.0, -1.0],
    ]:
        raise AssertionError(f"vertical twist mismatch: {vertical_left}")

    unsafe = example_plan()
    unsafe["families"][0]["pieces"][0]["local_position"][0] = "__import__('os')"
    _expect_invalid(unsafe, "may use only")

    left_handed = example_plan()
    left_handed["placements"][0]["basis"]["f"] = [0, 0, -1]
    _expect_invalid(left_handed, "right-handed")

    overlap = example_plan()
    overlap["placements"][0]["step"] = 0
    _expect_invalid(overlap, "duplicate placement frames")

    duplicate_polyline_station = example_plan()
    duplicate_polyline_station["placements"][0] = {
        "name": "BAD_PATH",
        "zone": "RUN",
        "family": "WALL_BAY",
        "layout": "polyline",
        "points": [[0, 0, 0], [0, 0, 0]],
    }
    _expect_invalid(duplicate_polyline_station, "zero-length vector")

    invalid_radial_facing = example_plan()
    invalid_radial_facing["placements"][0] = {
        "name": "BAD_HUB",
        "zone": "HUB",
        "family": "WALL_BAY",
        "layout": "radial",
        "center": [0, 0, 0],
        "radius": 10,
        "up": [0, 1, 0],
        "radial0": [1, 0, 0],
        "count": 3,
        "step_angle_deg": 120,
        "facing": "sideways",
    }
    _expect_invalid(invalid_radial_facing, "must be outward or inward")

    flat_vertical = example_plan()
    flat_vertical["placements"][0] = {
        "name": "BAD_STACK",
        "zone": "STACK",
        "family": "WALL_BAY",
        "layout": "vertical",
        "origin": [0, 0, 0],
        "basis": {"u": [1, 0, 0], "v": [0, 1, 0], "f": [0, 0, 1]},
        "count": 3,
        "step_v": 0,
    }
    _expect_invalid(flat_vertical, "step_v must be non-zero")

    unclassified = example_plan()
    unclassified["families"][0]["pieces"][0].pop("construction_kind")
    _expect_invalid(unclassified, "construction_kind")

    unvalued = example_plan()
    unvalued["families"][0]["pieces"][0].pop("design_roles")
    _expect_invalid(unvalued, "design_roles")

    unknown_value = example_plan()
    unknown_value["families"][0]["pieces"][0]["design_roles"] = ["DECORATION"]
    _expect_invalid(unknown_value, "unknown roles")

    bad_proxy = example_plan()
    bad_proxy["families"][0]["pieces"][0]["construction_kind"] = "COLLISION_PROXY"
    _expect_invalid(bad_proxy, "must use cost_role COL_PROXY")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Expand assembly families and linear/polyline/grid/arc/radial/"
            "vertical/explicit placements into unique world-basis component records."
        )
    )
    parser.add_argument("plan", nargs="?", type=Path, help="parametric layout JSON")
    parser.add_argument("--output", type=Path, help="write expanded JSON to this path")
    parser.add_argument("--example", action="store_true", help="print an example plan")
    parser.add_argument(
        "--example-layout",
        choices=sorted(LAYOUTS),
        help="print a design-space example for one placement generator",
    )
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="print only the expansion summary",
    )
    args = parser.parse_args()

    if args.example:
        print(json.dumps(example_plan(), ensure_ascii=False, indent=2))
        return 0
    if args.example_layout:
        print(json.dumps(layout_example_plan(args.example_layout), ensure_ascii=False, indent=2))
        return 0
    if args.self_test:
        _self_test()
        print("self-test passed")
        return 0
    if args.plan is None:
        parser.error(
            "plan is required unless --example, --example-layout or --self-test is used"
        )
    try:
        plan = json.loads(args.plan.read_text(encoding="utf-8"))
        result = expand_plan(plan)
        if args.output is not None:
            args.output.write_text(
                json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
    except (OSError, json.JSONDecodeError, ExpansionError) as exc:
        print(f"invalid parametric plan: {exc}", file=sys.stderr)
        return 2

    payload = result["summary"] if args.summary_only or args.output is not None else result
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

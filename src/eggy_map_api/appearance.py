from __future__ import annotations

from .errors import CapabilityError
from .models import Color


def validate_color(value: Color) -> None:
    if len(value) != 3 or any(
        type(channel) is not int or not 0 <= channel <= 255 for channel in value
    ):
        raise CapabilityError("color must be an integer RGB triple in the range 0..255")


def set_property(unit_id: int, property_key: str, value: object) -> None:
    if property_key == "paint_area1":
        validate_color(value)  # type: ignore[arg-type]
    raise CapabilityError(
        f"unit {unit_id}: property {property_key!r} has no matched byte-complete projection profile"
    )

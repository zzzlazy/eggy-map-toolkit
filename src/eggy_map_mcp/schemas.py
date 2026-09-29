from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class TransformInput(StrictModel):
    center: tuple[float, float, float]
    size: tuple[float, float, float]
    rotation_deg: tuple[float, float, float] = (0.0, 0.0, 0.0)
    forward_axis: Literal["+x", "-x", "+z", "-z"] | None = None

    @field_validator("center", "rotation_deg")
    @classmethod
    def finite(cls, value: tuple[float, float, float]) -> tuple[float, float, float]:
        if not all(math.isfinite(item) for item in value):
            raise ValueError("transform values must be finite")
        return value

    @field_validator("size")
    @classmethod
    def positive_size(
        cls, value: tuple[float, float, float]
    ) -> tuple[float, float, float]:
        if not all(math.isfinite(item) and item > 0 for item in value):
            raise ValueError("transform size must contain finite positive values")
        return value


class ReconcileComponentInput(StrictModel):
    logical_name: str = Field(min_length=1, max_length=255)
    component_ref: str
    transform: TransformInput
    color: tuple[int, int, int] | None = None
    properties: dict[str, Any] = Field(default_factory=dict)
    role: str = "obstacle"

    @field_validator("color")
    @classmethod
    def rgb(cls, value: tuple[int, int, int] | None) -> tuple[int, int, int] | None:
        if value is not None and any(
            type(item) is not int or not 0 <= item <= 255 for item in value
        ):
            raise ValueError("color must be an integer RGB triple in 0..255")
        return value

    @field_validator("logical_name")
    @classmethod
    def valid_logical_name(cls, value: str) -> str:
        if "\x00" in value or len(value.encode("utf-8")) > 255:
            raise ValueError(
                "logical_name must fit in 255 UTF-8 bytes and contain no NUL"
            )
        return value


class ReconcileManifestInput(StrictModel):
    schema_version: Literal[1] = 1
    map_ref: str = Field(min_length=1)
    components: list[ReconcileComponentInput]
    cleanup_policy: Literal["managed_only", "whitelist"] = "managed_only"
    managed_prefix: str | None = None
    map_settings: dict[str, Any] = Field(default_factory=dict)
    constraints: dict[str, Any] = Field(default_factory=dict)

    @field_validator("managed_prefix")
    @classmethod
    def valid_prefix(cls, value: str | None) -> str | None:
        if value is not None and (not value or "\x00" in value):
            raise ValueError("managed_prefix must be non-empty and contain no NUL")
        return value

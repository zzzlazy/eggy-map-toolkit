from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class EggyMapError(RuntimeError):
    """Base error with a stable machine-readable code and safe context."""

    code = "EGGY_MAP_ERROR"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.error_code = code or self.code
        self.context = dict(context or {})

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "code": self.error_code,
            "message": self.message,
        }
        if self.context:
            result["context"] = self.context
        return result


class SnapshotError(EggyMapError):
    """The input snapshot is incomplete, ambiguous, or malformed."""

    code = "SNAPSHOT_INVALID"


class CatalogError(EggyMapError):
    """The package catalog is missing or inconsistent."""

    code = "CATALOG_INVALID"


class CapabilityError(EggyMapError):
    """A requested mutation lacks a byte-complete, version-matched profile."""

    code = "COMPONENT_NOT_WRITABLE"


class ValidationError(EggyMapError):
    """A structural or business invariant failed."""

    code = "VALIDATION_FAILED"


class DeploymentError(EggyMapError):
    """Deployment could not be completed without risking the target."""

    code = "DEPLOYMENT_FAILED"


class DeviceError(EggyMapError):
    """Device, package, process, or map discovery was not unique and stable."""

    code = "DEVICE_INVALID"


class StateError(EggyMapError):
    """An opaque reference or persisted deployment state is invalid."""

    code = "STATE_INVALID"

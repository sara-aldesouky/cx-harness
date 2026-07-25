"""Provider-independent result contracts for future business tools."""

from __future__ import annotations

from enum import Enum
from typing import Generic, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


class ToolStatus(str, Enum):
    """Stable outcomes shared by every business tool."""

    SUCCESS = "success"
    FAILURE = "failure"


class ToolError(BaseModel):
    """A safe business failure suitable for callers and audit surfaces.

    Expected failures such as an unknown order, an already-refunded payment,
    or an unauthorized customer are normal tool outcomes. They should return a
    safe code and public message rather than raise a Python exception. Internal
    exceptions, stack traces, SQL errors, and provider details never belong in
    this model; unexpected system failures are handled by later infrastructure.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    error_code: str
    public_message: str

    @field_validator("error_code", "public_message")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        """Normalize safe error text and reject empty values."""

        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be empty or whitespace")
        return normalized


OutputModelT = TypeVar("OutputModelT", bound=BaseModel)


class ToolResult(BaseModel, Generic[OutputModelT]):
    """Immutable success-or-business-failure result returned by every tool."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: ToolStatus
    data: Optional[OutputModelT] = None
    error: Optional[ToolError] = None

    @model_validator(mode="after")
    def validate_status_payload(self) -> ToolResult[OutputModelT]:
        """Require exactly one payload appropriate to the declared status."""

        if self.status is ToolStatus.SUCCESS:
            if self.data is None:
                raise ValueError("successful tool results require data")
            if self.error is not None:
                raise ValueError("successful tool results must not include an error")
        else:
            if self.data is not None:
                raise ValueError("failed tool results must not include data")
            if self.error is None:
                raise ValueError("failed tool results require an error")
        return self

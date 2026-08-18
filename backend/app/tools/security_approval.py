"""Trusted execution-local proof produced by the Stage 11 gateway."""

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator, Optional

from pydantic import BaseModel, ConfigDict


class ToolExecutionSecurityApproval(BaseModel):
    """Immutable proof of the security gates passed for one tool call."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    authenticated: bool
    role_policy_allowed: bool
    tool_authorized: bool
    ownership_authorized: bool

    @property
    def fully_authorized(self) -> bool:
        return all(
            (
                self.authenticated,
                self.role_policy_allowed,
                self.tool_authorized,
                self.ownership_authorized,
            )
        )


_CURRENT_APPROVAL: ContextVar[Optional[ToolExecutionSecurityApproval]] = ContextVar(
    "tool_execution_security_approval", default=None
)


@contextmanager
def approved_tool_execution(
    approval: ToolExecutionSecurityApproval,
) -> Iterator[None]:
    """Scope trusted approval to one synchronous executor invocation."""

    if not isinstance(approval, ToolExecutionSecurityApproval):
        raise TypeError("approval must be ToolExecutionSecurityApproval")
    token = _CURRENT_APPROVAL.set(approval)
    try:
        yield
    finally:
        _CURRENT_APPROVAL.reset(token)


def current_tool_execution_approval() -> Optional[ToolExecutionSecurityApproval]:
    """Return current trusted approval, never model-controlled arguments."""

    return _CURRENT_APPROVAL.get()

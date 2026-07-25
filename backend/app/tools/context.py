"""Trusted runtime context kept separate from model-generated tool arguments."""

from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator


class ExecutionContext(BaseModel):
    """Immutable identity and correlation data established by trusted systems.

    Trusted means that values are supplied by authentication, the backend, the
    harness, or an experiment runner. They must never be copied from an LLM's
    tool arguments. For example, ``customer_id`` belongs here while a proposed
    ``order_id`` belongs in the tool's separately validated input model.

    ExecutionContext is not tool input: it carries authority and correlation,
    while tool arguments carry the model-requested operation parameters.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    trace_id: UUID
    execution_id: UUID
    conversation_id: Optional[UUID] = None
    model_run_id: Optional[UUID] = None
    customer_id: Optional[UUID] = None
    model_name: Optional[str] = None
    experiment_id: Optional[str] = None
    use_case_id: Optional[str] = None

    @field_validator("model_name", "experiment_id", "use_case_id")
    @classmethod
    def normalize_optional_identifier(cls, value: Optional[str]) -> Optional[str]:
        """Normalize optional labels and reject labels without content."""

        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be empty or whitespace")
        return normalized

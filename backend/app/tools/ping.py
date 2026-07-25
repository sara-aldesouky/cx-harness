"""Minimal demonstration declaration for the provider-neutral tool system."""

from pydantic import BaseModel, ConfigDict, field_validator

from app.tools.context import ExecutionContext
from app.tools.contracts import BaseTool, ToolCategory, ToolMetadata
from app.tools.result import ToolResult, ToolStatus


class PingInput(BaseModel):
    """Validated input accepted by the demonstration ping capability."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    message: str

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("message must not be empty")
        return normalized


class PingOutput(BaseModel):
    """Deterministic output schema declared by the demonstration tool."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    pong: str


class PingTool(BaseTool[PingInput, PingOutput]):
    """Demonstrate a complete declaration without runtime registry execution.

    The method satisfies the existing tool interface, but Stage 8.1 only
    registers and discovers this class; the registry never invokes it.
    """

    metadata = ToolMetadata(
        name="ping",
        version="1.0.0",
        description="Return a deterministic pong response for contract verification.",
        category=ToolCategory.SYSTEM,
        supported_use_cases=("tool_contract_verification",),
        requires_customer_identity=False,
        requires_order_ownership=False,
        requires_policy_check=False,
        is_read_only=True,
        is_enabled=True,
    )
    input_schema = PingInput
    output_schema = PingOutput

    def execute(
        self,
        context: ExecutionContext,
        input_model: PingInput,
    ) -> ToolResult[PingOutput]:
        """Return the declared demo response when a future caller executes it."""

        return ToolResult[PingOutput](
            status=ToolStatus.SUCCESS,
            data=PingOutput(pong="pong"),
        )

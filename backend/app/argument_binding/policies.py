"""Declarative trusted-argument binding policies."""

from __future__ import annotations

from typing import Optional

from pydantic import field_validator, model_validator

from app.argument_binding.contracts import (
    ArgumentSource,
    ModelValueBehavior,
    UnknownArgumentBehavior,
    _BindingModel,
)


class BindingRequirement(_BindingModel):
    argument_name: str
    required: bool
    protected: bool
    permitted_sources: tuple[ArgumentSource, ...]
    model_value_behavior: ModelValueBehavior
    resolution_key: Optional[str] = None
    include_in_tool_arguments: bool = True

    @field_validator("argument_name", "resolution_key")
    @classmethod
    def normalize_text(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be empty")
        return normalized

    @field_validator("permitted_sources")
    @classmethod
    def validate_sources(cls, values: tuple[ArgumentSource, ...]) -> tuple[ArgumentSource, ...]:
        if not values or len(set(values)) != len(values):
            raise ValueError("permitted_sources must be non-empty and unique")
        return values

    @model_validator(mode="after")
    def validate_trust_rules(self) -> BindingRequirement:
        if self.protected and ArgumentSource.MODEL_SUGGESTED in self.permitted_sources:
            raise ValueError("protected arguments cannot permit model-suggested values")
        if self.protected and self.model_value_behavior is not ModelValueBehavior.DISCARD:
            raise ValueError("protected arguments must discard model values")
        if not self.protected and self.model_value_behavior is ModelValueBehavior.DISCARD:
            raise ValueError("unprotected declared arguments must permit model values")
        if not self.protected and self.resolution_key is not None:
            raise ValueError("unprotected arguments cannot declare a resolution key")
        return self


class ArgumentBindingPolicy(BindingRequirement):
    """Named policy contract retained for clear public API terminology."""


class ToolBindingPolicy(_BindingModel):
    tool_name: str
    argument_policies: tuple[ArgumentBindingPolicy, ...]
    unknown_argument_behavior: UnknownArgumentBehavior = UnknownArgumentBehavior.REJECT
    requires_order_resolution: bool = False
    executable_when_bound: bool = True

    @field_validator("tool_name")
    @classmethod
    def normalize_tool_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("tool_name must not be empty")
        return normalized

    @model_validator(mode="after")
    def validate_policy(self) -> ToolBindingPolicy:
        names = tuple(policy.argument_name for policy in self.argument_policies)
        if not names or len(set(names)) != len(names):
            raise ValueError("argument policies must be non-empty and unique")
        has_resolution = any(policy.resolution_key for policy in self.argument_policies)
        if has_resolution != self.requires_order_resolution:
            raise ValueError("resolution requirements must match resolver configuration")
        if not self.executable_when_bound:
            raise ValueError("registered binding policies must be executable when bound")
        return self


def _order_policy() -> ArgumentBindingPolicy:
    return ArgumentBindingPolicy(
        argument_name="order_number",
        required=True,
        protected=True,
        permitted_sources=(ArgumentSource.VERIFIED_ENTITY_RESOLUTION,),
        model_value_behavior=ModelValueBehavior.DISCARD,
        resolution_key="order",
    )


def _trusted_context_policy(name: str) -> ArgumentBindingPolicy:
    return ArgumentBindingPolicy(
        argument_name=name,
        required=True,
        protected=True,
        permitted_sources=(ArgumentSource.EXECUTION_CONTEXT,),
        model_value_behavior=ModelValueBehavior.DISCARD,
        include_in_tool_arguments=False,
    )


def _model_policy(name: str, *, required: bool = True) -> ArgumentBindingPolicy:
    return ArgumentBindingPolicy(
        argument_name=name,
        required=required,
        protected=False,
        permitted_sources=(ArgumentSource.MODEL_SUGGESTED,),
        model_value_behavior=ModelValueBehavior.ALLOW,
    )


def write_tool_binding_policies() -> tuple[ToolBindingPolicy, ...]:
    identity = (_trusted_context_policy("customer_id"), _trusted_context_policy("conversation_id"))
    return (
        ToolBindingPolicy(
            tool_name="cancel_order",
            argument_policies=(_order_policy(), *identity),
            requires_order_resolution=True,
        ),
        ToolBindingPolicy(
            tool_name="update_delivery_address",
            argument_policies=(_order_policy(), _model_policy("delivery_address"), *identity),
            requires_order_resolution=True,
        ),
        ToolBindingPolicy(
            tool_name="initiate_refund",
            argument_policies=(_order_policy(), *identity),
            requires_order_resolution=True,
        ),
        ToolBindingPolicy(
            tool_name="create_support_ticket",
            argument_policies=(
                _order_policy(),
                _model_policy("category"),
                _model_policy("issue_description"),
                _model_policy("escalation_reason"),
                *identity,
            ),
            requires_order_resolution=True,
        ),
    )

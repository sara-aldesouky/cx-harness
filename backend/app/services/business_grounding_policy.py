"""Deterministic, capability-based grounding for critical customer facts."""

from __future__ import annotations

from dataclasses import dataclass, replace

from app.harness.context import ConversationContext, ConversationRole
from app.tools.contracts import GroundingCapability, ToolMetadata


@dataclass(frozen=True)
class CapabilityGroundingRule:
    """Map provider-neutral request language to one evidence capability."""

    capability: GroundingCapability
    terms: tuple[str, ...]


DEFAULT_CAPABILITY_RULES = (
    CapabilityGroundingRule(
        GroundingCapability.ORDER,
        ("order", "package"),
    ),
    CapabilityGroundingRule(
        GroundingCapability.DELIVERY,
        ("delivery", "delivered", "shipping", "shipment", "tracking"),
    ),
    CapabilityGroundingRule(
        GroundingCapability.PAYMENT,
        ("payment", "billing", "charge", "transaction", "balance"),
    ),
    CapabilityGroundingRule(
        GroundingCapability.REFUND,
        ("refund",),
    ),
    CapabilityGroundingRule(
        GroundingCapability.KNOWLEDGE,
        (
            "policy",
            "faq",
            "accepted",
            "allowed",
            "hours",
            "can i",
            "may i",
            "what happens if",
            "how long do",
            "how long",
            "what happened",
            "change my address",
            "changed my address",
            "normally",
            "generally",
        ),
    ),
    CapabilityGroundingRule(
        GroundingCapability.CUSTOMER,
        (
            "account",
            "customer data",
            "profile",
            "phone",
            "email",
            "address",
            "personal information",
        ),
    ),
)


@dataclass(frozen=True)
class BusinessGroundingPolicy:
    """Require registered capability evidence for business-critical facts.

    Tool identity is used only to locate its immutable registry metadata. The
    grounding decision is made entirely from ``grounding_capabilities``; the
    policy has no knowledge of concrete business tool names.
    """

    capability_rules: tuple[CapabilityGroundingRule, ...] = (
        DEFAULT_CAPABILITY_RULES
    )
    registered_metadata: tuple[ToolMetadata, ...] = ()
    transactional_fact_terms: tuple[str, ...] = (
        "status",
        "approved",
        "rejected",
        "pending",
        "delayed",
        "failed",
        "deducted",
        "arrived",
        "missing",
        "changed",
        "arriving",
        "arrive",
        "where is",
        "when will",
        "has my",
        "have i",
        "was my",
    )

    def with_registered_metadata(
        self, metadata: tuple[ToolMetadata, ...]
    ) -> "BusinessGroundingPolicy":
        """Return a policy bound to one runtime's enabled registry snapshot."""

        if not isinstance(metadata, tuple) or any(
            not isinstance(item, ToolMetadata) for item in metadata
        ):
            raise TypeError("metadata must be a tuple of ToolMetadata values")
        return replace(self, registered_metadata=metadata)

    @property
    def critical_terms(self) -> tuple[str, ...]:
        """Expose the declarative critical-language vocabulary deterministically."""

        return tuple(term for rule in self.capability_rules for term in rule.terms)

    def requires_tool_evidence(self, context: ConversationContext) -> bool:
        """Classify the current user request without trusting provider output."""

        return bool(self._required_capabilities(context))

    def is_satisfied(
        self,
        context: ConversationContext,
        executed_tool_names: frozenset[str],
    ) -> bool:
        """Check successful executions against registered capability metadata."""

        required = self._required_capabilities(context)
        if not required:
            return True

        registered_by_name = {
            metadata.name: metadata
            for metadata in self.registered_metadata
            if metadata.is_enabled
        }
        executed_metadata = tuple(
            registered_by_name[tool_name]
            for tool_name in executed_tool_names
            if tool_name in registered_by_name
        )
        provided = frozenset(
            capability
            for metadata in executed_metadata
            for capability in metadata.grounding_capabilities
        )
        return required <= provided

    def _required_capabilities(
        self, context: ConversationContext
    ) -> frozenset[GroundingCapability]:
        user_messages = tuple(
            message.content.lower()
            for message in context.messages
            if message.role is ConversationRole.USER
        )
        if not user_messages:
            return frozenset()
        current_request = user_messages[-1]
        matched = frozenset(
            rule.capability
            for rule in self.capability_rules
            if any(term in current_request for term in rule.terms)
        )
        if (
            GroundingCapability.KNOWLEDGE in matched
            and not any(term in current_request for term in self.transactional_fact_terms)
        ):
            return frozenset((GroundingCapability.KNOWLEDGE,))
        return matched

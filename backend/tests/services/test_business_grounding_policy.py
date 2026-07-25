"""Regression tests for declarative business-capability grounding."""

from __future__ import annotations

import pytest

from app.harness.context import ConversationContext, ConversationMessage, ConversationRole
from app.services.business_grounding_policy import BusinessGroundingPolicy
from app.tools import (
    GetCustomerProfileTool,
    GetCustomerSummaryTool,
    GetDeliveryEtaTool,
    GetDeliveryHistoryTool,
    GetDeliveryStatusTool,
    GetDeliveryWindowTool,
    GetLatestDeliveryEventTool,
    GetOrderDetailsTool,
    GetOrderItemsTool,
    GetOrderStatusTool,
    GetLatestPaymentEventTool,
    GetPaymentHistoryTool,
    GetPaymentMethodTool,
    GetPaymentStatusTool,
    GetPaymentSummaryTool,
    CheckRefundEligibilityTool,
    GetLatestRefundEventTool,
    GetRefundHistoryTool,
    GetRefundStatusTool,
    GetRefundSummaryTool,
    ListCurrentOrdersTool,
    ListOrderHistoryTool,
    GetFaqAnswerTool,
    GetPolicyTool,
    ListRelatedArticlesTool,
    SearchKnowledgeTool,
)
from app.tools.contracts import GroundingCapability, ToolMetadata


RUNTIME_METADATA = tuple(
    tool.metadata
    for tool in (
        GetCustomerProfileTool,
        GetCustomerSummaryTool,
        GetOrderStatusTool,
        ListCurrentOrdersTool,
        GetOrderDetailsTool,
        ListOrderHistoryTool,
        GetOrderItemsTool,
        GetDeliveryStatusTool,
        GetDeliveryEtaTool,
        GetDeliveryWindowTool,
        GetLatestDeliveryEventTool,
        GetDeliveryHistoryTool,
        GetPaymentStatusTool,
        GetPaymentMethodTool,
        GetPaymentSummaryTool,
        GetPaymentHistoryTool,
        GetLatestPaymentEventTool,
        GetRefundStatusTool,
        GetRefundSummaryTool,
        GetRefundHistoryTool,
        GetLatestRefundEventTool,
        CheckRefundEligibilityTool,
        SearchKnowledgeTool,
        GetPolicyTool,
        GetFaqAnswerTool,
        ListRelatedArticlesTool,
    )
)


def context(message: str) -> ConversationContext:
    return ConversationContext(
        system_instructions="Use registered business capabilities.",
        messages=(
            ConversationMessage(role=ConversationRole.USER, content=message),
        ),
    )


def policy(*metadata: ToolMetadata) -> BusinessGroundingPolicy:
    return BusinessGroundingPolicy().with_registered_metadata(tuple(metadata))


@pytest.mark.parametrize(
    ("metadata", "message"),
    [
        (GetOrderStatusTool.metadata, "Where is my order delivery?"),
        (GetCustomerProfileTool.metadata, "Show my customer profile."),
        (GetCustomerSummaryTool.metadata, "Summarize my account and orders."),
        (ListCurrentOrdersTool.metadata, "List my current orders."),
        (GetOrderDetailsTool.metadata, "Show this order's payment details."),
        (ListOrderHistoryTool.metadata, "Show my order history."),
        (GetOrderItemsTool.metadata, "Which items are in my order?"),
        (GetDeliveryStatusTool.metadata, "Is my delivery delayed?"),
        (GetDeliveryEtaTool.metadata, "When is my delivery?"),
        (GetDeliveryWindowTool.metadata, "What is my delivery window?"),
        (GetLatestDeliveryEventTool.metadata, "Latest delivery update?"),
        (GetDeliveryHistoryTool.metadata, "Show delivery history."),
        (GetPaymentStatusTool.metadata, "Was my order payment successful?"),
        (GetPaymentMethodTool.metadata, "How did I pay for my order?"),
        (GetPaymentSummaryTool.metadata, "Show my order payment summary."),
        (GetPaymentHistoryTool.metadata, "Show my order payment events."),
        (GetLatestPaymentEventTool.metadata, "Latest order payment event?"),
        (GetPaymentStatusTool.metadata, "Was my order refunded?"),
        (GetRefundStatusTool.metadata, "Is my refund pending?"),
        (GetRefundSummaryTool.metadata, "How much was refunded?"),
        (GetRefundHistoryTool.metadata, "Show my refund history."),
        (GetLatestRefundEventTool.metadata, "What is the latest refund event?"),
        (CheckRefundEligibilityTool.metadata, "Am I eligible for a refund?"),
        (GetPolicyTool.metadata, "What is the refund policy?"),
        (GetFaqAnswerTool.metadata, "What delivery hours are allowed?"),
        (SearchKnowledgeTool.metadata, "Which payment methods are accepted?"),
        (ListRelatedArticlesTool.metadata, "Show related FAQ articles."),
    ],
)
def test_registered_business_tools_ground_from_capabilities(
    metadata: ToolMetadata, message: str
) -> None:
    grounding = policy(metadata)

    assert grounding.requires_tool_evidence(context(message))
    assert grounding.is_satisfied(context(message), frozenset((metadata.name,)))


def test_multiple_capabilities_can_be_satisfied_by_multiple_tools() -> None:
    grounding = policy(GetCustomerProfileTool.metadata, ListCurrentOrdersTool.metadata)
    request = context("Show my customer profile and current orders.")

    assert grounding.is_satisfied(
        request,
        frozenset(
            (
                GetCustomerProfileTool.metadata.name,
                ListCurrentOrdersTool.metadata.name,
            )
        ),
    )
    assert not grounding.is_satisfied(
        request, frozenset((GetCustomerProfileTool.metadata.name,))
    )


def test_capability_not_concrete_name_drives_grounding() -> None:
    declaration = GetOrderStatusTool.metadata.model_copy(
        update={"name": "future_order_reader"}
    )

    assert policy(declaration).is_satisfied(
        context("Check my order delivery."), frozenset(("future_order_reader",))
    )


def test_unregistered_tool_is_never_grounding_evidence() -> None:
    assert not policy(*RUNTIME_METADATA).is_satisfied(
        context("Show my customer profile."),
        frozenset(("unregistered_profile_reader",)),
    )


def test_technical_or_business_failure_without_success_is_not_grounded() -> None:
    grounding = policy(*RUNTIME_METADATA)
    request = context("Check my order status.")

    # The loop supplies only successfully executed tools. Both failure classes
    # therefore reach the policy as an empty evidence set.
    assert not grounding.is_satisfied(request, frozenset())


def test_metadata_without_grounding_capability_cannot_ground_business_facts() -> None:
    non_business = GetOrderStatusTool.metadata.model_copy(
        update={"name": "diagnostic_reader", "grounding_capabilities": ()}
    )

    assert not policy(non_business).is_satisfied(
        context("Check my order."), frozenset(("diagnostic_reader",))
    )


def test_policy_metadata_snapshot_is_immutable() -> None:
    grounding = policy(*RUNTIME_METADATA)

    assert isinstance(grounding.registered_metadata, tuple)
    with pytest.raises(AttributeError):
        grounding.registered_metadata = ()


def test_policy_evidence_cannot_satisfy_transactional_customer_facts() -> None:
    grounding = policy(GetPolicyTool.metadata, GetRefundStatusTool.metadata)

    assert grounding.is_satisfied(
        context("What is the refund policy?"), frozenset(("get_policy",))
    )
    assert not grounding.is_satisfied(
        context("Has my refund been approved?"), frozenset(("get_policy",))
    )
    assert grounding.is_satisfied(
        context("Has my refund been approved?"),
        frozenset(("get_refund_status",)),
    )

    assert GetPolicyTool.metadata.grounding_capabilities == (
        GroundingCapability.KNOWLEDGE,
    )


def test_mixed_policy_and_transactional_request_requires_both_evidence_types() -> None:
    grounding = policy(GetPolicyTool.metadata, GetRefundStatusTool.metadata)
    request = context("Under the refund policy, has my refund been approved?")

    assert not grounding.is_satisfied(request, frozenset(("get_policy",)))
    assert not grounding.is_satisfied(request, frozenset(("get_refund_status",)))
    assert grounding.is_satisfied(
        request, frozenset(("get_policy", "get_refund_status"))
    )

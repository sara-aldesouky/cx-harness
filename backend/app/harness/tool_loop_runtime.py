"""Composition root for the real local Ollama bounded tool loop."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Optional

import httpx
from sqlalchemy.orm import Session, sessionmaker

from app.config.settings import Settings, settings
from app.authorization import (
    OwnershipAuthorizationService,
    SQLAlchemyBusinessResourceOwnershipResolver,
)
from app.role_policy import CapabilityRolePolicyService
from app.tool_authorization import (
    CentralToolAuthorizationService,
    ToolPolicyRegistry,
)
from app.database.repositories.tool_call_audit_repository import ToolCallAuditRepository
from app.database.session import get_session_factory
from app.argument_binding import TrustedArgumentBinder
from app.conversation_state import (
    ConversationStateService,
    InMemoryConversationStateStore,
)
from app.conversation_continuity import (
    TrustedConversationEntityContinuityService,
)
from app.entity_resolution import OrderEntityResolver
from app.providers.ollama_qwen import (
    OllamaProviderContinuationAdapter,
    OllamaQwenProvider,
)
from app.providers.registry import ProviderRegistry
from app.services.model_tool_loop_service import BoundedModelToolLoopService
from app.services.trusted_argument_binding_runtime import (
    TrustedSelectionPipeline,
    build_runtime_binding_policy_registry,
    validate_runtime_binding_configuration,
)
from app.services.order_resolution_runtime_repository import (
    SessionFactoryOrderResolutionRepository,
)
from app.services.business_grounding_policy import BusinessGroundingPolicy
from app.services.orchestration_boundaries import (
    OrchestrationBoundaryValidator,
    OrchestrationRuntimeLimits,
)
from app.tools.continuation_adapter_registry import ProviderContinuationAdapterRegistry
from app.tools.customer_capabilities import (
    GetCustomerProfileTool,
    GetCustomerSummaryTool,
)
from app.tools.delivery_capabilities import (
    GetDeliveryEtaTool,
    GetDeliveryHistoryTool,
    GetDeliveryStatusTool,
    GetDeliveryWindowTool,
    GetLatestDeliveryEventTool,
)
from app.tools.get_order_status import GetOrderStatusTool
from app.tools.order_capabilities import (
    GetOrderDetailsTool,
    GetOrderItemsTool,
    ListCurrentOrdersTool,
    ListOrderHistoryTool,
)
from app.tools.knowledge_capabilities import (
    GetFaqAnswerTool,
    GetPolicyTool,
    ListRelatedArticlesTool,
    SearchKnowledgeTool,
)
from app.tools.payment_capabilities import (
    GetLatestPaymentEventTool,
    GetPaymentHistoryTool,
    GetPaymentMethodTool,
    GetPaymentStatusTool,
    GetPaymentSummaryTool,
)
from app.tools.refund_capabilities import (
    CheckRefundEligibilityTool,
    GetLatestRefundEventTool,
    GetRefundHistoryTool,
    GetRefundStatusTool,
    GetRefundSummaryTool,
)
from app.tools.registry import ToolClass, ToolRegistry
from app.tools.selection import ToolSelectionResolver
from app.tools.tool_runtime import build_tool_continuation_runtime
from app.tools.write_capabilities import WRITE_TOOL_CLASSES, WriteToolFactory


class ModelToolLoopStartupError(RuntimeError):
    """Raised when the local bounded-loop dependency graph cannot be composed."""


DEFAULT_BUSINESS_TOOL_CLASSES: tuple[ToolClass, ...] = (
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
    *WRITE_TOOL_CLASSES,
)


def build_model_tool_loop(
    *,
    app_settings: Settings = settings,
    database_session_factory: Optional[sessionmaker[Session]] = None,
    tool_classes: Iterable[ToolClass] = DEFAULT_BUSINESS_TOOL_CLASSES,
    ollama_client: Optional[httpx.Client] = None,
    continuity_service: Optional[
        TrustedConversationEntityContinuityService
    ] = None,
) -> BoundedModelToolLoopService:
    """Return the configured Ollama loop without performing network requests."""

    if not isinstance(app_settings, Settings):
        raise TypeError("app_settings must be a Settings instance")
    session_factory = database_session_factory or get_session_factory()

    tool_registry = ToolRegistry()
    configured_tools = tuple(tool_classes)
    if len(configured_tools) > app_settings.max_tools_exposed:
        raise ModelToolLoopStartupError(
            "configured tools exceed MAX_TOOLS_EXPOSED"
        )
    for tool_class in configured_tools:
        tool_registry.register(tool_class)

    base_continuity = continuity_service or TrustedConversationEntityContinuityService()
    order_tool_names = tuple(
        tool_class.metadata.name
        for tool_class in tool_registry.list()
        if {"order_number", "order_id"} & set(tool_class.input_schema.model_fields)
    )
    configured_continuity = base_continuity.for_order_tools(order_tool_names)

    binding_policies = build_runtime_binding_policy_registry(tool_registry)
    validate_runtime_binding_configuration(tool_registry, binding_policies)
    order_resolver = OrderEntityResolver(
        SessionFactoryOrderResolutionRepository(session_factory)
    )
    read_order_tool_names = tuple(
        tool_class.metadata.name
        for tool_class in tool_registry.list()
        if tool_class.metadata.is_read_only
        and {"order_number", "order_id"} & set(tool_class.input_schema.model_fields)
    )
    read_order_arguments = {
        tool_class.metadata.name: (
            "order_number"
            if "order_number" in tool_class.input_schema.model_fields
            else "order_id"
        )
        for tool_class in tool_registry.list()
        if tool_class.metadata.name in read_order_tool_names
    }
    trusted_selection_pipeline = TrustedSelectionPipeline(
        TrustedArgumentBinder(
            binding_policies,
            order_resolver,
            known_tool_names=(
                tool.metadata.name for tool in tool_registry.list()
            ),
        ),
        ToolSelectionResolver(tool_registry),
        conversation_state_service=ConversationStateService(
            InMemoryConversationStateStore()
        ),
        continuity_service=configured_continuity,
        continuity_order_resolver=order_resolver,
        continuity_read_order_tools=read_order_tool_names,
        continuity_read_order_arguments=read_order_arguments,
    )

    continuation_adapters = ProviderContinuationAdapterRegistry()
    continuation_adapters.register("ollama", OllamaProviderContinuationAdapter())
    tool_runtime = build_tool_continuation_runtime(
        tool_registry=tool_registry,
        continuation_adapter_registry=continuation_adapters,
        audit_repository=ToolCallAuditRepository(session_factory),
        audit_payload_max_bytes=app_settings.audit_payload_max_bytes,
        authorization_service=OwnershipAuthorizationService(
            SQLAlchemyBusinessResourceOwnershipResolver(session_factory)
        ),
        role_policy_service=CapabilityRolePolicyService(),
        tool_authorization_service=CentralToolAuthorizationService(
            ToolPolicyRegistry.for_runtime(tool_registry)
        ),
        tool_factory=WriteToolFactory(session_factory),
        completion_observer=configured_continuity.record_success,
    )

    provider_registry = ProviderRegistry()
    provider_registry.register(
        OllamaQwenProvider(
            base_url=app_settings.ollama_base_url,
            model_name=app_settings.ollama_model_name,
            connect_timeout_seconds=app_settings.ollama_connect_timeout_seconds,
            read_timeout_seconds=app_settings.ollama_read_timeout_seconds,
            client=ollama_client,
            tool_definitions=tool_registry.definitions(),
            max_response_bytes=app_settings.max_provider_response_bytes,
            context_size=app_settings.ollama_context_size,
            max_output_tokens=app_settings.ollama_max_output_tokens,
            keep_alive=app_settings.ollama_keep_alive,
            tool_thinking_enabled=app_settings.ollama_tool_thinking_enabled,
        )
    )
    return BoundedModelToolLoopService(
        provider_registry=provider_registry,
        trusted_selection_pipeline=trusted_selection_pipeline,
        tool_runtime=tool_runtime,
        max_model_turns=app_settings.max_model_turns,
        timeout_seconds=app_settings.ollama_read_timeout_seconds,
        grounding_policy=BusinessGroundingPolicy().with_registered_metadata(
            tool_registry.metadata(enabled_only=True)
        ),
        boundary_validator=OrchestrationBoundaryValidator(
            OrchestrationRuntimeLimits.from_settings(app_settings)
        ),
    )

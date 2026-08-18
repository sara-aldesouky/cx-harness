"""Real PostgreSQL verification of the model-callable Stage 12 bridge."""

from datetime import datetime, timezone
from collections import deque
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select

from app.authorization import (
    OwnershipAuthorizationService,
    SQLAlchemyBusinessResourceOwnershipResolver,
)
from app.harness.context import ConversationContext, ConversationMessage, ConversationRole
from app.providers.base import (
    ModelProvider,
    ModelRequest,
    ModelResponse,
    ModelToolLoopTurnResponse,
    ProviderCapabilities,
)
from app.providers.registry import ProviderRegistry
from app.database.models import Customer, Order, Refund, RefundEvent, SupportTicket
from app.role_policy import CapabilityRolePolicyService
from app.services.business_grounding_policy import BusinessGroundingPolicy
from app.services.model_tool_loop_service import (
    BoundedModelToolLoopService,
    ModelToolLoopTermination,
)
from app.argument_binding import TrustedArgumentBinder
from app.entity_resolution import OrderEntityResolver
from app.services.order_resolution_runtime_repository import (
    SessionFactoryOrderResolutionRepository,
)
from app.services.trusted_argument_binding_runtime import (
    TrustedSelectionPipeline,
    build_runtime_binding_policy_registry,
)
from app.tool_authorization import (
    CentralToolAuthorizationService,
    ToolPolicyRegistry,
)
from app.tools.context import ExecutionContext
from app.tools.continuation_adapter import MockProviderContinuationAdapter
from app.tools.continuation_adapter_registry import ProviderContinuationAdapterRegistry
from app.tools.execution_gateway import SingleToolExecutionGateway
from app.tools.execution_request import ToolExecutionRequestFactory
from app.tools.executor import ToolExecutor
from app.tools.registry import ToolRegistry
from app.tools.result import ToolStatus
from app.tools.selection import (
    InvalidToolArgumentsError,
    ToolSelectionRequest,
    ToolSelectionResolver,
)
from app.tools.tool_runtime import build_tool_continuation_runtime
from app.tools.write_capabilities import WRITE_TOOL_CLASSES, WriteToolFactory
from tests.models.factories import (
    create_customer,
    create_order,
    create_payment,
    create_refund_eligibility,
)
from tests.tools.audit_fakes import RecordingAuditRepository


pytestmark = pytest.mark.integration


class RecordingWriteAudit:
    def __init__(self):
        self.events = []

    def record(self, event):
        self.events.append(event)


def execution_context(customer_id):
    return ExecutionContext(
        trace_id=uuid4(),
        execution_id=uuid4(),
        conversation_id=uuid4(),
        customer_id=customer_id,
        principal_role="customer",
        model_name="mock-model",
    )


def runtime(test_session_factory):
    registry = ToolRegistry()
    for tool_class in WRITE_TOOL_CLASSES:
        registry.register(tool_class)
    tool_call_audit = RecordingAuditRepository()
    write_audit = RecordingWriteAudit()
    executor = ToolExecutor(
        registry,
        tool_call_audit,
        tool_factory=WriteToolFactory(test_session_factory, write_audit),
    )
    gateway = SingleToolExecutionGateway(
        registry,
        executor,
        authorization_service=OwnershipAuthorizationService(
            SQLAlchemyBusinessResourceOwnershipResolver(test_session_factory)
        ),
        role_policy_service=CapabilityRolePolicyService(),
        tool_authorization_service=CentralToolAuthorizationService(
            ToolPolicyRegistry.for_runtime(registry)
        ),
    )
    return registry, gateway, tool_call_audit, write_audit


def invoke(registry, gateway, context, name, arguments, call_id=None):
    selection = ToolSelectionResolver(registry).resolve(
        ToolSelectionRequest(
            call_id=call_id or f"call-{uuid4().hex}",
            tool_name=name,
            tool_version="1.0.0",
            arguments=arguments,
        )
    )
    request = ToolExecutionRequestFactory().create(selection, context)
    return gateway.execute(request)


class ScriptedWriteProvider(ModelProvider):
    def __init__(self, turns):
        self.turns = deque(turns)
        self.requests = []

    @property
    def provider_name(self) -> str:
        return "mock"

    @property
    def model_name(self) -> str:
        return "mock-model"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(tool_calling=True)

    def generate(self, request: ModelRequest) -> ModelResponse:
        raise AssertionError("bounded runtime must use run_tool_loop_turn")

    def run_tool_loop_turn(self, request):
        self.requests.append(request)
        return self.turns.popleft()


def tool_turn(name, arguments):
    return ModelToolLoopTurnResponse(
        tool_calls=(
            ToolSelectionRequest(
                call_id=f"call-{name}",
                tool_name=name,
                tool_version="1.0.0",
                arguments=arguments,
            ),
        ),
        assistant_content="هراجع الطلب من خلال الأداة المعتمدة.",
    )


def final_turn(content):
    return ModelToolLoopTurnResponse(
        final_response=ModelResponse(
            content=content,
            provider_name="mock",
            model_name="mock-model",
        )
    )


def build_scripted_loop(test_session_factory, name, arguments, final_content):
    registry = ToolRegistry()
    for tool_class in WRITE_TOOL_CLASSES:
        registry.register(tool_class)
    provider = ScriptedWriteProvider(
        (tool_turn(name, arguments), final_turn(final_content))
    )
    providers = ProviderRegistry()
    providers.register(provider)
    continuations = ProviderContinuationAdapterRegistry()
    continuations.register("mock", MockProviderContinuationAdapter())
    tool_audit = RecordingAuditRepository()
    write_audit = RecordingWriteAudit()
    runtime_graph = build_tool_continuation_runtime(
        tool_registry=registry,
        continuation_adapter_registry=continuations,
        audit_repository=tool_audit,
        authorization_service=OwnershipAuthorizationService(
            SQLAlchemyBusinessResourceOwnershipResolver(test_session_factory)
        ),
        role_policy_service=CapabilityRolePolicyService(),
        tool_authorization_service=CentralToolAuthorizationService(
            ToolPolicyRegistry.for_runtime(registry)
        ),
        tool_factory=WriteToolFactory(test_session_factory, write_audit),
    )
    loop = BoundedModelToolLoopService(
        provider_registry=providers,
        trusted_selection_pipeline=TrustedSelectionPipeline(
            TrustedArgumentBinder(
                build_runtime_binding_policy_registry(registry),
                OrderEntityResolver(
                    SessionFactoryOrderResolutionRepository(test_session_factory)
                ),
                known_tool_names=(
                    tool.metadata.name for tool in registry.list()
                ),
            ),
            ToolSelectionResolver(registry),
        ),
        tool_runtime=runtime_graph,
        grounding_policy=BusinessGroundingPolicy().with_registered_metadata(
            registry.metadata(enabled_only=True)
        ),
    )
    return loop, provider, tool_audit, write_audit


@pytest.fixture
def write_records(test_session_factory):
    suffix = uuid4().hex[:10].upper()
    order_base = 10000 + (int(uuid4().hex[:8], 16) % 89990)
    with test_session_factory() as setup:
        customer = create_customer(
            setup,
            email=f"write-runtime-{suffix.lower()}@example.test",
            phone=f"+208{suffix.lower()}",
        )
        other = create_customer(
            setup,
            email=f"write-runtime-other-{suffix.lower()}@example.test",
            phone=f"+209{suffix.lower()}",
        )
        cancel = create_order(
            setup, customer, order_number=f"ORD-{order_base:05d}",
            status="confirmed",
        )
        address = create_order(
            setup, customer, order_number=f"ORD-{order_base + 1:05d}",
            status="preparing", delivery_address="1 Old Street, Cairo",
        )
        refund = create_order(
            setup, customer, order_number=f"ORD-{order_base + 2:05d}",
            status="delivered", payment_status="paid",
        )
        payment = create_payment(setup, refund, status="succeeded", currency="EGP")
        create_refund_eligibility(setup, refund, status="eligible")
        ticket = create_order(
            setup, customer, order_number=f"ORD-{order_base + 3:05d}",
            status="pending",
        )
        foreign = create_order(
            setup, other, order_number=f"ORD-{order_base + 4:05d}", status="pending"
        )
        values = {
            "customer_id": customer.id,
            "other_id": other.id,
            "order_ids": (cancel.id, address.id, refund.id, ticket.id, foreign.id),
            "cancel": cancel.order_number,
            "address": address.order_number,
            "refund": refund.order_number,
            "payment_id": payment.id,
            "ticket": ticket.order_number,
            "foreign": foreign.order_number,
        }
        setup.commit()
    try:
        yield values
    finally:
        with test_session_factory.begin() as cleanup:
            cleanup.execute(
                delete(SupportTicket).where(
                    SupportTicket.customer_id.in_(
                        (values["customer_id"], values["other_id"])
                    )
                )
            )
            cleanup.execute(delete(Order).where(Order.id.in_(values["order_ids"])))
            cleanup.execute(
                delete(Customer).where(
                    Customer.id.in_((values["customer_id"], values["other_id"]))
                )
            )


def test_all_model_callable_writes_commit_and_retries_do_not_duplicate(
    test_session_factory, write_records
) -> None:
    r = write_records
    registry, gateway, tool_audit, write_audit = runtime(test_session_factory)
    context = execution_context(r["customer_id"])
    calls = (
        ("cancel_order", {"order_number": r["cancel"]}),
        (
            "update_delivery_address",
            {
                "order_number": r["address"],
                "delivery_address": "٢٢ شارع النيل, الجيزة",
            },
        ),
        ("initiate_refund", {"order_number": r["refund"]}),
        (
            "create_support_ticket",
            {
                "category": "order_issue",
                "issue_description": "el item na2es w el moshkela mat7aletsh l7ad دلوقتي",
                "escalation_reason": "unresolved_issue",
                "order_number": r["ticket"],
            },
        ),
    )

    first = [invoke(registry, gateway, context, name, args) for name, args in calls]
    repeated = [invoke(registry, gateway, context, name, args) for name, args in calls]

    assert all(result.status is ToolStatus.SUCCESS for result in first)
    assert all(result.data.business_change_applied for result in first)
    assert all(result.status is ToolStatus.FAILURE for result in repeated)
    assert [result.error.error_code for result in repeated] == [
        "order_already_cancelled",
        "address_already_up_to_date",
        "refund_already_requested",
        "support_ticket_already_exists",
    ]
    assert len(tool_audit.started) == len(tool_audit.finalized) == 8
    assert len(write_audit.events) == 8
    assert sum(event.business_change_applied is True for event in write_audit.events) == 4

    with test_session_factory() as verify:
        assert verify.scalar(
            select(Order.status).where(Order.order_number == r["cancel"])
        ) == "cancelled"
        assert verify.scalar(
            select(Order.delivery_address).where(Order.order_number == r["address"])
        ) == "٢٢ شارع النيل, الجيزة"
        assert verify.scalar(
            select(func.count()).select_from(Refund).where(
                Refund.payment_id == r["payment_id"]
            )
        ) == 1
        assert verify.scalar(
            select(func.count()).select_from(RefundEvent)
            .join(RefundEvent.refund).where(Refund.payment_id == r["payment_id"])
        ) == 1
        assert verify.scalar(
            select(func.count()).select_from(SupportTicket).where(
                SupportTicket.customer_id == r["customer_id"]
            )
        ) == 1


@pytest.mark.parametrize(
    "tool_name",
    ("cancel_order", "update_delivery_address", "initiate_refund", "create_support_ticket"),
)
def test_cross_customer_order_is_denied_before_write_execution(
    test_session_factory, write_records, tool_name
) -> None:
    r = write_records
    registry, gateway, tool_audit, write_audit = runtime(test_session_factory)
    arguments = {"order_number": r["foreign"]}
    if tool_name == "update_delivery_address":
        arguments["delivery_address"] = "10 Safe Street, Cairo"
    elif tool_name == "create_support_ticket":
        arguments.update(
            category="order_issue",
            issue_description="This foreign order must never receive a ticket.",
            escalation_reason="unresolved_issue",
        )
    result = invoke(
        registry, gateway, execution_context(r["customer_id"]), tool_name, arguments
    )
    assert result.status is ToolStatus.FAILURE
    assert result.error.error_code == "resource_not_found"
    assert tool_audit.started == []
    assert write_audit.events == []


def test_malformed_and_identity_injected_calls_fail_before_execution(
    test_session_factory, write_records
) -> None:
    registry, gateway, tool_audit, write_audit = runtime(test_session_factory)
    resolver = ToolSelectionResolver(registry)
    with pytest.raises(InvalidToolArgumentsError):
        resolver.resolve(
            ToolSelectionRequest(
                call_id="bad-identity",
                tool_name="cancel_order",
                arguments={
                    "order_number": write_records["cancel"],
                    "customer_id": str(write_records["other_id"]),
                },
            )
        )
    assert tool_audit.started == []
    assert write_audit.events == []


@pytest.mark.parametrize(
    ("tool_name", "arguments_factory", "customer_message", "final_response"),
    [
        (
            "cancel_order",
            lambda r: {"order_number": r["cancel"]},
            "عايز ألغي الأوردر ده لو سمحت",
            "تمام، الأوردر اتلغى بنجاح.",
        ),
        (
            "update_delivery_address",
            lambda r: {
                "order_number": r["address"],
                "delivery_address": "٣٠ شارع التحرير, الجيزة",
            },
            "3ayz a8ayar 3onwan el delivery",
            "تمام، 3onwan el delivery et8ayar بنجاح.",
        ),
        (
            "initiate_refund",
            lambda r: {"order_number": r["refund"]},
            "عايز أعمل استرجاع للأوردر ده",
            "تمام، طلب الاسترجاع اتسجل بنجاح.",
        ),
        (
            "create_support_ticket",
            lambda r: {
                "category": "order_issue",
                "issue_description": "el moshkela mat7aletsh w 3ayz akalem support",
                "escalation_reason": "unresolved_issue",
                "order_number": r["ticket"],
            },
            "el moshkela mat7aletsh w 3ayz akalem support",
            "تمام، عملتلك تذكرة للدعم وهما هيتابعوا معاك.",
        ),
    ],
)
def test_scripted_provider_completes_real_write_runtime_cycle(
    test_session_factory,
    write_records,
    tool_name,
    arguments_factory,
    customer_message,
    final_response,
) -> None:
    arguments = arguments_factory(write_records)
    loop, provider, tool_audit, write_audit = build_scripted_loop(
        test_session_factory, tool_name, arguments, final_response
    )
    result = loop.run(
        provider_name="mock",
        model_name="mock-model",
        context=ConversationContext(
            system_instructions=(
                "استخدم أدوات العمل المعتمدة، وما تفترضش أي بيانات عن العميل."
            ),
            messages=(
                    ConversationMessage(
                        role=ConversationRole.USER,
                        content=f"{customer_message} {arguments['order_number']}",
                    ),
            ),
            provider_name="mock",
            model_name="mock-model",
        ),
        execution_context=execution_context(write_records["customer_id"]),
    )

    assert result.termination_reason is ModelToolLoopTermination.FINAL_RESPONSE
    assert result.provider_turns == 2
    assert result.tools_executed == 1
    assert result.tool_cycles[0].selection.tool_name == tool_name
    assert result.tool_cycles[0].execution_outcome.status is ToolStatus.SUCCESS
    assert result.final_response.content == final_response
    assert len(provider.requests) == 2
    assert len(provider.requests[1].tool_results) == 1
    assert len(tool_audit.started) == len(tool_audit.finalized) == 1
    assert len(write_audit.events) == 1
    assert write_audit.events[0].business_change_applied is True


def test_safe_write_rejection_uses_existing_stage9_termination_policy(
    test_session_factory, write_records
) -> None:
    unknown = "ORD-99999"
    loop, provider, tool_audit, write_audit = build_scripted_loop(
        test_session_factory,
        "cancel_order",
        {"order_number": unknown},
        "مش لاقي الأوردر ده في حسابك، اتأكد من الرقم وجرب تاني.",
    )
    result = loop.run(
        provider_name="mock",
        model_name="mock-model",
        context=ConversationContext(
            system_instructions="ما تفترضش بيانات واستخدم الأدوات المعتمدة.",
            messages=(
                ConversationMessage(
                    role=ConversationRole.USER,
                    content="3ayz al8y order ra2mo ORD-99999",
                ),
            ),
            provider_name="mock",
            model_name="mock-model",
        ),
        execution_context=execution_context(write_records["customer_id"]),
    )
    assert result.termination_reason is ModelToolLoopTermination.INVALID_TOOL_CALL
    assert result.provider_turns == 1
    assert result.tool_cycles == ()
    assert result.error_code == "order_not_found"
    assert result.final_response.content == "I couldn't find that order for your account."
    assert len(provider.requests) == 1
    assert tool_audit.started == []
    assert write_audit.events == []

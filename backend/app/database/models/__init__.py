"""Model registration for SQLAlchemy and Alembic."""

from app.database.models.customer import Customer
from app.database.models.delivery import Delivery, DeliveryEvent
from app.database.models.evaluation import Evaluation
from app.database.models.conversation import Conversation
from app.database.models.message import Message
from app.database.models.knowledge import KnowledgeArticle, KnowledgeArticleVersion
from app.database.models.model_run import ModelRun
from app.database.models.order import Order
from app.database.models.order_item import OrderItem
from app.database.models.payment import Payment, PaymentEvent
from app.database.models.refund import Refund, RefundEligibility, RefundEvent
from app.database.models.tool_call import ToolCall

__all__ = [
    "Conversation",
    "Customer",
    "Delivery",
    "DeliveryEvent",
    "Evaluation",
    "Message",
    "KnowledgeArticle",
    "KnowledgeArticleVersion",
    "ModelRun",
    "Order",
    "OrderItem",
    "Payment",
    "PaymentEvent",
    "Refund",
    "RefundEligibility",
    "RefundEvent",
    "ToolCall",
]

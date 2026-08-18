"""Versioned API router registration."""

from fastapi import APIRouter

from app.api.routes import (
    benchmark_reporting,
    conversations,
    customers,
    evaluations,
    messages,
    model_invocation,
    model_runs,
    order_items,
    orders,
    overview,
    tool_calls,
)


api_router = APIRouter(prefix="/api/v1")
api_router.include_router(benchmark_reporting.router)
api_router.include_router(customers.router)
api_router.include_router(orders.router)
api_router.include_router(order_items.router)
api_router.include_router(conversations.router)
api_router.include_router(messages.router)
api_router.include_router(model_invocation.router)
api_router.include_router(model_runs.router)
api_router.include_router(tool_calls.router)
api_router.include_router(evaluations.router)
api_router.include_router(overview.router)

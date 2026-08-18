"""Deterministic Decimal API-cost calculation."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from app.benchmark_analytics.contracts import DeploymentMode, PricingSnapshot
from app.benchmark_ingestion.errors import IngestionPricingError


@dataclass(frozen=True)
class CostCalculation:
    amount: Optional[Decimal]
    currency_code: Optional[str]
    evidence: dict[str, object]


class BenchmarkCostCalculator:
    def calculate(
        self, pricing: PricingSnapshot, input_tokens: int, output_tokens: int,
        request_count: int, deployment_mode: DeploymentMode,
    ) -> CostCalculation:
        if min(input_tokens, output_tokens, request_count) < 0:
            raise IngestionPricingError("cost inputs must be non-negative")
        if deployment_mode in {DeploymentMode.LOCAL, DeploymentMode.SELF_HOSTED}:
            return CostCalculation(None, None, {"reason": "self_hosted_allocation_unavailable"})
        unit = pricing.assumptions.get("pricing_unit", "per_million")
        if unit not in {"per_thousand", "per_million"}:
            raise IngestionPricingError("unsupported pricing unit")
        divisor = Decimal(1_000 if unit == "per_thousand" else 1_000_000)
        prices = (pricing.input_cost_per_million_tokens, pricing.output_cost_per_million_tokens)
        if all(value is None for value in prices) and pricing.request_cost is None:
            return CostCalculation(None, None, {"reason": "pricing_unavailable"})
        input_rate = pricing.input_cost_per_million_tokens or Decimal("0")
        output_rate = pricing.output_cost_per_million_tokens or Decimal("0")
        request_rate = pricing.request_cost or Decimal("0")
        amount = (
            Decimal(input_tokens) * input_rate / divisor
            + Decimal(output_tokens) * output_rate / divisor
            + Decimal(request_count) * request_rate
        )
        return CostCalculation(
            amount=amount, currency_code=pricing.currency_code,
            evidence={"pricing_unit": unit, "request_count": request_count},
        )

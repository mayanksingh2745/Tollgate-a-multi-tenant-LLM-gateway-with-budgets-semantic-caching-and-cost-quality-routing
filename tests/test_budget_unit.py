from uuid import uuid4

import pytest
from gateway.src.budgets.estimation import estimate_prompt_tokens, estimate_request_cost
from gateway.src.budgets.manager import (
    BudgetLimits,
    InMemoryBudgetBackend,
)
from gateway.src.budgets.pricing import (
    ModelPricing,
    PricingService,
)
from gateway.src.schemas.chat import ChatCompletionRequest, ChatMessage


def test_pricing_calculation_exact_microdollars():
    # $1.50 per 1M in, $3.00 per 1M out
    pricing = ModelPricing(
        input_microdollars_per_million=1_500_000,
        output_microdollars_per_million=3_000_000,
    )

    # 1,000 in, 500 out
    # in: 1,000 * 1,500,000 / 1,000,000 = 1,500 microdollars ($0.0015)
    # out: 500 * 3,000,000 / 1,000,000 = 1,500 microdollars ($0.0015)
    cost = pricing.calculate_cost(input_tokens=1000, output_tokens=500)
    assert cost == 3000  # 1500 + 1500 microdollars ($0.003)

    # Exactly 1,000,000 input tokens = exactly 1,500,000 microdollars
    cost_million = pricing.calculate_cost(input_tokens=1_000_000, output_tokens=0)
    assert cost_million == 1_500_000


def test_pricing_service_registration():
    service = PricingService()
    custom_model = "custom-enterprise-llm"
    service.register_pricing(
        custom_model,
        ModelPricing(
            input_microdollars_per_million=5_000_000,
            output_microdollars_per_million=15_000_000,
        ),
    )
    p = service.get_pricing(custom_model)
    assert p.input_microdollars_per_million == 5_000_000
    assert p.output_microdollars_per_million == 15_000_000


def test_token_estimation_deterministic():
    messages = [
        ChatMessage(role="system", content="You are a helpful assistant."),
        ChatMessage(role="user", content="Hello world!"),
    ]
    tokens_1 = estimate_prompt_tokens(messages)
    tokens_2 = estimate_prompt_tokens(messages)
    assert tokens_1 == tokens_2
    assert tokens_1 > 10


def test_estimate_request_cost_bounds():
    req = ChatCompletionRequest(
        model="mock-model",
        messages=[ChatMessage(role="user", content="Hi")],
        max_tokens=100,
    )
    cost = estimate_request_cost(req)
    assert cost > 0
    # mock-model is $1/M in, $2/M out -> ~100 tokens out is ~200 microdollars
    assert cost < 500


@pytest.mark.asyncio
async def test_settlement_refund_calculation():
    backend = InMemoryBudgetBackend()
    t_id = uuid4()
    p_id = uuid4()

    # Reserve $0.05 (50,000 microdollars)
    res = await backend.reserve(
        tenant_id=t_id,
        project_id=p_id,
        estimated_cost=50_000,
        limits=BudgetLimits(tenant_monthly_limit=100_000),
    )
    assert res.allowed is True

    # Actual cost $0.031 (31,000 microdollars)
    # Expected refund $0.019 (19,000 microdollars)
    settle_res = await backend.settle(
        reservation_id=res.reservation_id,
        actual_cost=31_000,
    )
    assert settle_res.success is True
    assert settle_res.actual_cost == 31_000
    assert settle_res.refund == 19_000
    assert settle_res.status == "settled"


@pytest.mark.asyncio
async def test_settlement_idempotent():
    backend = InMemoryBudgetBackend()
    t_id = uuid4()
    p_id = uuid4()

    res = await backend.reserve(
        tenant_id=t_id,
        project_id=p_id,
        estimated_cost=20_000,
        limits=BudgetLimits(tenant_monthly_limit=50_000),
    )

    # First settle
    s1 = await backend.settle(reservation_id=res.reservation_id, actual_cost=15_000)
    assert s1.success is True
    assert s1.status == "settled"

    # Second settle (must be idempotent, no double-charge)
    s2 = await backend.settle(reservation_id=res.reservation_id, actual_cost=15_000)
    assert s2.success is True
    assert s2.status == "already_settled"


@pytest.mark.asyncio
async def test_cannot_release_settled_reservation():
    backend = InMemoryBudgetBackend()
    t_id = uuid4()
    p_id = uuid4()

    res = await backend.reserve(
        tenant_id=t_id,
        project_id=p_id,
        estimated_cost=10_000,
        limits=BudgetLimits(),
    )
    await backend.settle(reservation_id=res.reservation_id, actual_cost=8_000)

    # Attempting to release a settled reservation must fail
    released = await backend.release(reservation_id=res.reservation_id)
    assert released is False

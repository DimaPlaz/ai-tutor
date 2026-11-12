from decimal import Decimal

import pytest

from tutor_bot.llm.pricing import TokenUsage, UnknownModelPriceError, total_cost, usage_cost


def test_usage_cost_input_and_output() -> None:
    usage = TokenUsage("claude-opus-5-5", input_tokens=1_000_000, output_tokens=1_000_000)

    assert usage_cost(usage) == Decimal("24")


def test_usage_cost_counts_cache() -> None:
    usage = TokenUsage(
        "claude-opus-5-5",
        input_tokens=0,
        output_tokens=0,
        cache_read_tokens=1_000_000,
        cache_write_tokens=1_000_000,
    )

    # чтение $0.20 + запись 1.25 × $4
    assert usage_cost(usage) == Decimal("5.20")


def test_small_request_cost() -> None:
    usage = TokenUsage("claude-opus-5-5", input_tokens=2_000, output_tokens=1_500)

    assert usage_cost(usage) == Decimal("0.038")


def test_total_cost_sums_fallback_attempts() -> None:
    usages = [
        TokenUsage("claude-opus-5-5", input_tokens=1_000, output_tokens=0),
        TokenUsage("claude-opus-4-8", input_tokens=1_000, output_tokens=1_000),
    ]

    assert total_cost(usages) == Decimal("0.004") + Decimal("0.030")


def test_unknown_model_raises() -> None:
    with pytest.raises(UnknownModelPriceError):
        usage_cost(TokenUsage("claude-unknown", input_tokens=1, output_tokens=1))

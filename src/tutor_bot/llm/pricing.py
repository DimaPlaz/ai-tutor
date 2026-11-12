from dataclasses import dataclass
from decimal import Decimal

MILLION = Decimal(1_000_000)


@dataclass(frozen=True, slots=True)
class ModelPrice:
    """Цены в $ за 1M токенов."""

    input: Decimal
    output: Decimal
    cache_read: Decimal

    @property
    def cache_write(self) -> Decimal:
        # Запись в 5-минутный кэш стоит 1.25× обычного входа
        return self.input * Decimal("1.25")


# Включены и модели, на которые API может переключить запрос при отказе (fallbacks)
PRICES: dict[str, ModelPrice] = {
    "claude-opus-5-5": ModelPrice(Decimal("4"), Decimal("20"), Decimal("0.20")),
    "claude-opus-5": ModelPrice(Decimal("5"), Decimal("25"), Decimal("0.50")),
    "claude-opus-4-8": ModelPrice(Decimal("5"), Decimal("25"), Decimal("0.50")),
    "claude-sonnet-5-5": ModelPrice(Decimal("2"), Decimal("10"), Decimal("0.20")),
    "claude-haiku-5-5": ModelPrice(Decimal("0.10"), Decimal("0.50"), Decimal("0.01")),
}


@dataclass(frozen=True, slots=True)
class TokenUsage:
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


class UnknownModelPriceError(KeyError):
    pass


def usage_cost(usage: TokenUsage) -> Decimal:
    price = PRICES.get(usage.model)
    if price is None:
        raise UnknownModelPriceError(usage.model)
    total = (
        usage.input_tokens * price.input
        + usage.output_tokens * price.output
        + usage.cache_read_tokens * price.cache_read
        + usage.cache_write_tokens * price.cache_write
    )
    return total / MILLION


def total_cost(usages: list[TokenUsage]) -> Decimal:
    return sum((usage_cost(u) for u in usages), Decimal(0))

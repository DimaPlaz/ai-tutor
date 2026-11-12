import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ValidationError

from tutor_bot.llm.client import ImageInput, JsonCompleter, LLMUnavailableError
from tutor_bot.llm.pricing import TokenUsage, UnknownModelPriceError, total_cost

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class LLMCall:
    """Учёт одного вызова: модель, токены по попыткам, стоимость."""

    model: str
    usages: list[TokenUsage]
    cost_usd: Decimal | None


async def call_json[T: BaseModel](
    llm: JsonCompleter,
    kind: str,
    system: str,
    text: str,
    schema: dict[str, Any],
    payload_type: type[T],
    image: ImageInput | None = None,
) -> tuple[T, LLMCall]:
    response = await llm.complete_json(system=system, text=text, schema=schema, image=image)
    try:
        payload = payload_type.model_validate_json(response.text)
    except ValidationError as e:
        logger.error("LLM returned invalid %s JSON request_id=%s", kind, response.request_id)
        raise LLMUnavailableError(f"invalid {kind} payload") from e

    cost = _safe_cost(response.usages)
    logger.info(
        "llm_call kind=%s model=%s tokens_in=%s tokens_out=%s cost_usd=%s request_id=%s",
        kind,
        response.model,
        sum(u.input_tokens for u in response.usages),
        sum(u.output_tokens for u in response.usages),
        cost,
        response.request_id,
    )
    return payload, LLMCall(model=response.model, usages=response.usages, cost_usd=cost)


def _safe_cost(usages: list[TokenUsage]) -> Decimal | None:
    # Неизвестная цена не должна ломать ответ ученику — только предупреждение в лог
    try:
        return total_cost(usages)
    except UnknownModelPriceError as e:
        logger.warning("No price for model %s, cost not calculated", e.args[0])
        return None

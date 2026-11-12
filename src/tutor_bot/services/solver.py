import logging
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ValidationError

from tutor_bot.llm.client import ImageInput, JsonCompleter, LLMResponse, LLMUnavailableError
from tutor_bot.llm.pricing import TokenUsage, UnknownModelPriceError, total_cost
from tutor_bot.llm.prompts import SOLVE_PHOTO_INSTRUCTION, solve_system_prompt

logger = logging.getLogger(__name__)


class SolutionStatus(StrEnum):
    OK = "ok"
    NOT_A_PROBLEM = "not_a_problem"
    UNREADABLE = "unreadable"


class SolutionPayload(BaseModel):
    status: SolutionStatus
    problem: str
    steps: list[str]
    answer: str


SOLUTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": [s.value for s in SolutionStatus]},
        "problem": {"type": "string"},
        "steps": {"type": "array", "items": {"type": "string"}},
        "answer": {"type": "string"},
    },
    "required": ["status", "problem", "steps", "answer"],
    "additionalProperties": False,
}


@dataclass(frozen=True, slots=True)
class Solution:
    status: SolutionStatus
    problem: str
    steps: list[str]
    answer: str
    model: str
    usages: list[TokenUsage]
    cost_usd: Decimal | None


class Solver:
    def __init__(self, llm: JsonCompleter) -> None:
        self._llm = llm

    async def solve(
        self, language: str, text: str | None = None, image: ImageInput | None = None
    ) -> Solution:
        if not text and image is None:
            raise ValueError("nothing to solve: no text and no image")

        user_text = text or SOLVE_PHOTO_INSTRUCTION
        response = await self._llm.complete_json(
            system=solve_system_prompt(language),
            text=user_text,
            schema=SOLUTION_SCHEMA,
            image=image,
        )
        payload = _parse_payload(response)
        cost = _safe_cost(response.usages)
        logger.info(
            "solved status=%s model=%s tokens_in=%s tokens_out=%s cost_usd=%s request_id=%s",
            payload.status.value,
            response.model,
            sum(u.input_tokens for u in response.usages),
            sum(u.output_tokens for u in response.usages),
            cost,
            response.request_id,
        )
        return Solution(
            status=payload.status,
            problem=payload.problem,
            steps=payload.steps,
            answer=payload.answer,
            model=response.model,
            usages=response.usages,
            cost_usd=cost,
        )


def _parse_payload(response: LLMResponse) -> SolutionPayload:
    try:
        payload = SolutionPayload.model_validate_json(response.text)
    except ValidationError as e:
        logger.error("LLM returned invalid JSON request_id=%s", response.request_id)
        raise LLMUnavailableError("invalid solution payload") from e
    if payload.status is SolutionStatus.OK and not (payload.steps and payload.answer):
        logger.error("LLM returned empty solution request_id=%s", response.request_id)
        raise LLMUnavailableError("empty solution")
    return payload


def _safe_cost(usages: list[TokenUsage]) -> Decimal | None:
    # Неизвестная цена не должна ломать ответ ученику — только предупреждение в лог
    try:
        return total_cost(usages)
    except UnknownModelPriceError as e:
        logger.warning("No price for model %s, cost not calculated", e.args[0])
        return None

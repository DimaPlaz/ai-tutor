import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pydantic import BaseModel

from tutor_bot.llm.client import ImageInput, JsonCompleter, LLMUnavailableError
from tutor_bot.llm.prompts import SOLVE_PHOTO_INSTRUCTION, solve_system_prompt
from tutor_bot.services.llm_json import LLMCall, call_json

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
    call: LLMCall


class Solver:
    def __init__(self, llm: JsonCompleter) -> None:
        self._llm = llm

    async def solve(
        self, language: str, text: str | None = None, image: ImageInput | None = None
    ) -> Solution:
        if not text and image is None:
            raise ValueError("nothing to solve: no text and no image")

        payload, call = await call_json(
            self._llm,
            kind="solve",
            system=solve_system_prompt(language),
            text=text or SOLVE_PHOTO_INSTRUCTION,
            schema=SOLUTION_SCHEMA,
            payload_type=SolutionPayload,
            image=image,
        )
        if payload.status is SolutionStatus.OK and not (payload.steps and payload.answer):
            logger.error("LLM returned empty solution")
            raise LLMUnavailableError("empty solution", call.usages)
        return Solution(
            status=payload.status,
            problem=payload.problem,
            steps=payload.steps,
            answer=payload.answer,
            call=call,
        )

"""Уточнения по текущей задаче: «объясни проще», проверка ответа, свободные вопросы."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pydantic import BaseModel

from tutor_bot.llm.client import JsonCompleter
from tutor_bot.llm.prompts import (
    CHECK_ANSWER_INSTRUCTION,
    QUESTION_INSTRUCTION,
    SIMPLER_INSTRUCTION,
    followup_system_prompt,
    render_task_context,
)
from tutor_bot.services.llm_json import LLMCall, call_json
from tutor_bot.services.tasks import TaskContext


class FollowUpLimitError(Exception):
    """Уточнения по задаче закончились — в Claude не обращаемся."""


class Verdict(StrEnum):
    CORRECT = "correct"
    PARTIAL = "partial"
    INCORRECT = "incorrect"


class _SimplerPayload(BaseModel):
    explanation: str


class _CheckPayload(BaseModel):
    verdict: Verdict
    explanation: str


class _QuestionPayload(BaseModel):
    is_new_problem: bool
    reply: str


def _schema(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


SIMPLER_SCHEMA = _schema({"explanation": {"type": "string"}})
CHECK_SCHEMA = _schema(
    {
        "verdict": {"type": "string", "enum": [v.value for v in Verdict]},
        "explanation": {"type": "string"},
    }
)
QUESTION_SCHEMA = _schema({"is_new_problem": {"type": "boolean"}, "reply": {"type": "string"}})


@dataclass(frozen=True, slots=True)
class FollowUpReply:
    text: str
    task: TaskContext  # задача с новой записью в истории — её нужно сохранить
    call: LLMCall
    verdict: Verdict | None = None


@dataclass(frozen=True, slots=True)
class NewProblemDetected:
    """Ученик прислал другую задачу вместо уточнения — её надо решать как новую."""

    call: LLMCall


class Tutor:
    def __init__(self, llm: JsonCompleter) -> None:
        self._llm = llm

    async def explain_simpler(self, language: str, task: TaskContext) -> FollowUpReply:
        payload, call = await self._ask(
            "simpler", language, task, SIMPLER_INSTRUCTION, SIMPLER_SCHEMA, _SimplerPayload
        )
        request = "Explain it more simply, please."
        return FollowUpReply(
            payload.explanation, task.with_turn(request, payload.explanation), call
        )

    async def check_answer(
        self, language: str, task: TaskContext, student_answer: str
    ) -> FollowUpReply:
        instruction = CHECK_ANSWER_INSTRUCTION.format(student_answer=student_answer)
        payload, call = await self._ask(
            "check", language, task, instruction, CHECK_SCHEMA, _CheckPayload
        )
        request = f"Check my answer: {student_answer}"
        reply = f"[{payload.verdict.value}] {payload.explanation}"
        return FollowUpReply(
            payload.explanation, task.with_turn(request, reply), call, payload.verdict
        )

    async def answer_question(
        self, language: str, task: TaskContext, question: str
    ) -> FollowUpReply | NewProblemDetected:
        instruction = QUESTION_INSTRUCTION.format(question=question)
        payload, call = await self._ask(
            "question", language, task, instruction, QUESTION_SCHEMA, _QuestionPayload
        )
        if payload.is_new_problem or not payload.reply:
            return NewProblemDetected(call)
        return FollowUpReply(payload.reply, task.with_turn(question, payload.reply), call)

    async def _ask[T: BaseModel](
        self,
        kind: str,
        language: str,
        task: TaskContext,
        instruction: str,
        schema: dict[str, Any],
        payload_type: type[T],
    ) -> tuple[T, LLMCall]:
        if task.followups_left == 0:
            raise FollowUpLimitError
        history = [(turn.request, turn.reply) for turn in task.history]
        context = render_task_context(task.problem, task.steps, task.answer, history)
        return await call_json(
            self._llm,
            kind=kind,
            system=followup_system_prompt(language),
            text=f"{context}\n\n{instruction}",
            schema=schema,
            payload_type=payload_type,
        )

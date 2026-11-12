import json
from collections.abc import Mapping
from typing import Any
from unittest.mock import AsyncMock

import pytest

from tutor_bot.llm.client import JsonCompleter, LLMResponse
from tutor_bot.services.tasks import MAX_FOLLOWUPS, TaskContext
from tutor_bot.services.tutor import (
    FollowUpLimitError,
    NewProblemDetected,
    Tutor,
    Verdict,
)

TASK = TaskContext(task_id="t1", problem="2x + 3 = 11", steps=["2x = 8", "x = 4"], answer="x = 4")


def sent(complete: AsyncMock) -> Mapping[str, Any]:
    assert complete.await_args is not None
    return complete.await_args.kwargs


def make_tutor(payload: dict[str, Any]) -> tuple[Tutor, AsyncMock]:
    llm = AsyncMock(spec=JsonCompleter)
    llm.complete_json.return_value = LLMResponse(
        text=json.dumps(payload), model="claude-opus-5-5", usages=[], request_id=None
    )
    return Tutor(llm), llm.complete_json


async def test_context_and_history_sent_to_llm() -> None:
    tutor, complete = make_tutor({"explanation": "проще"})
    task = TASK.with_turn("Почему 8?", "Потому что 11 − 3")

    await tutor.explain_simpler("ru", task)

    text = sent(complete)["text"]
    assert "2x + 3 = 11" in text
    assert "1. 2x = 8" in text
    assert "Student: Почему 8?" in text
    assert sent(complete)["image"] is None


async def test_explain_simpler_adds_turn() -> None:
    tutor, _ = make_tutor({"explanation": "проще"})

    reply = await tutor.explain_simpler("ru", TASK)

    assert reply.text == "проще"
    assert reply.task.followups_left == MAX_FOLLOWUPS - 1
    assert TASK.followups_left == MAX_FOLLOWUPS  # исходная задача не меняется


async def test_check_answer_returns_verdict() -> None:
    tutor, complete = make_tutor({"verdict": "partial", "explanation": "забыл единицы"})

    reply = await tutor.check_answer("ru", TASK, "4")

    assert reply.verdict is Verdict.PARTIAL
    assert "<student_answer>\n4\n</student_answer>" in sent(complete)["text"]


async def test_question_flagged_as_new_problem() -> None:
    tutor, _ = make_tutor({"is_new_problem": True, "reply": ""})

    result = await tutor.answer_question("ru", TASK, "Реши 5x = 10")

    assert isinstance(result, NewProblemDetected)


async def test_limit_reached_does_not_call_llm() -> None:
    tutor, complete = make_tutor({"explanation": "проще"})
    task = TASK
    for i in range(MAX_FOLLOWUPS):
        task = task.with_turn(f"q{i}", f"a{i}")

    with pytest.raises(FollowUpLimitError):
        await tutor.explain_simpler("ru", task)
    complete.assert_not_awaited()

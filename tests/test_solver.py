import json
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock

import pytest

from tutor_bot.llm.client import ImageInput, LLMClient, LLMResponse, LLMUnavailableError
from tutor_bot.llm.pricing import TokenUsage
from tutor_bot.llm.prompts import solve_system_prompt
from tutor_bot.services.solver import SolutionStatus, Solver


def make_solver(payload: dict[str, Any] | str, model: str = "claude-opus-5-5") -> Solver:
    text = payload if isinstance(payload, str) else json.dumps(payload)
    llm = AsyncMock(spec=LLMClient)
    llm.complete_json.return_value = LLMResponse(
        text=text,
        model=model,
        usages=[TokenUsage(model, input_tokens=2_000, output_tokens=1_500)],
        request_id="req_1",
    )
    return Solver(llm)


OK_PAYLOAD = {"status": "ok", "problem": "2 + 2", "steps": ["Складываем"], "answer": "4"}


async def test_solve_ok_with_cost() -> None:
    solution = await make_solver(OK_PAYLOAD).solve("ru", text="2 + 2")

    assert solution.status is SolutionStatus.OK
    assert solution.steps == ["Складываем"]
    assert solution.answer == "4"
    assert solution.call.cost_usd == Decimal("0.038")


@pytest.mark.parametrize("status", ["unreadable", "not_a_problem"])
async def test_solve_passes_non_ok_status(status: str) -> None:
    payload = {"status": status, "problem": "", "steps": [], "answer": ""}

    solution = await make_solver(payload).solve("en", text="hello")

    assert solution.status.value == status


async def test_photo_without_caption_uses_default_instruction() -> None:
    solver = make_solver(OK_PAYLOAD)

    await solver.solve("ru", image=ImageInput(data=b"img"))

    llm: Any = solver._llm
    kwargs = llm.complete_json.await_args.kwargs
    assert kwargs["text"] == "Solve the problem in the photo."
    assert kwargs["system"] == solve_system_prompt("ru")


async def test_invalid_json_is_unavailable() -> None:
    with pytest.raises(LLMUnavailableError):
        await make_solver("not json").solve("ru", text="2 + 2")


async def test_ok_without_answer_is_unavailable() -> None:
    payload = {"status": "ok", "problem": "2 + 2", "steps": [], "answer": ""}

    with pytest.raises(LLMUnavailableError):
        await make_solver(payload).solve("ru", text="2 + 2")


async def test_unknown_model_price_does_not_fail() -> None:
    solution = await make_solver(OK_PAYLOAD, model="claude-new").solve("ru", text="2 + 2")

    assert solution.call.cost_usd is None


async def test_empty_input_rejected() -> None:
    with pytest.raises(ValueError):
        await make_solver(OK_PAYLOAD).solve("ru")

import pytest

from tutor_bot.bot.formatting import pack_messages, render_solution
from tutor_bot.llm.client import (
    LLMError,
    LLMRefusalError,
    LLMTruncatedError,
    LLMUnavailableError,
)
from tutor_bot.llm.fake import FakeLLMClient
from tutor_bot.services.solver import SolutionStatus, Solver


@pytest.fixture
def solver() -> Solver:
    return Solver(FakeLLMClient(delay_seconds=0))


async def test_default_solution_in_user_language(solver: Solver) -> None:
    ru = await solver.solve("ru", text="2x + 3 = 11")
    en = await solver.solve("en", text="2x + 3 = 11")

    assert ru.status is SolutionStatus.OK
    assert ru.problem.startswith("Решить")
    assert en.problem.startswith("Solve")
    assert ru.cost_usd == 0


@pytest.mark.parametrize("status", ["unreadable", "not_a_problem"])
async def test_status_commands(solver: Solver, status: str) -> None:
    solution = await solver.solve("ru", text=f"fake:{status}")

    assert solution.status.value == status


@pytest.mark.parametrize(
    ("command", "error"),
    [
        ("fake:refusal", LLMRefusalError),
        ("fake:max_tokens", LLMTruncatedError),
        ("fake:error", LLMUnavailableError),
    ],
)
async def test_error_commands(solver: Solver, command: str, error: type[LLMError]) -> None:
    with pytest.raises(error):
        await solver.solve("ru", text=command)


async def test_long_solution_needs_several_messages(solver: Solver) -> None:
    solution = await solver.solve("ru", text="fake:long")

    assert len(pack_messages(render_solution(solution, "ru"))) > 1

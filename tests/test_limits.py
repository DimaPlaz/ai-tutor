from datetime import UTC, datetime
from decimal import Decimal

import pytest
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tutor_bot.db.models import LlmCall, User
from tutor_bot.llm.fake import FakeLLMClient
from tutor_bot.llm.pricing import TokenUsage
from tutor_bot.services.assistant import Assistant
from tutor_bot.services.limits import (
    AccessDeniedError,
    Denial,
    Limits,
    LimitsConfig,
    month_start,
)
from tutor_bot.services.llm_json import LLMCall
from tutor_bot.services.solver import Solver
from tutor_bot.services.throttle import Throttle
from tutor_bot.services.tutor import Tutor
from tutor_bot.services.users import register_user

CONFIG = LimitsConfig(
    free_solutions=2, free_budget_usd=Decimal("1.00"), paid_budget_usd=Decimal("5.00")
)


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def call(cost: str) -> LLMCall:
    return LLMCall(
        model="claude-opus-5-5",
        usages=[TokenUsage("claude-opus-5-5", input_tokens=10, output_tokens=5)],
        cost_usd=Decimal(cost),
    )


@pytest.fixture
async def user(session: AsyncSession) -> User:
    return await register_user(session, 7, "kid", "ru")


@pytest.fixture
def clock() -> Clock:
    return Clock(datetime(2026, 1, 31, 23, 59, tzinfo=UTC))


@pytest.fixture
def limits(session: AsyncSession, clock: Clock) -> Limits:
    return Limits(session, CONFIG, now=clock)


def test_month_start_in_utc() -> None:
    moscow_morning = datetime.fromisoformat("2026-03-01T02:00:00+03:00")  # 28 фев 23:00 UTC

    assert month_start(moscow_morning) == datetime(2026, 2, 1, tzinfo=UTC)


async def test_solutions_exhausted(limits: Limits, user: User) -> None:
    for _ in range(2):
        await limits.record(user, "solve", call("0.01"), task_id="t", charged=True)

    with pytest.raises(AccessDeniedError) as e:
        await limits.check(user, new_solution=True, subscribed=False)
    assert e.value.reason is Denial.FREE_EXHAUSTED
    # уточнения решений не тратят — пока бюджет есть, они доступны
    await limits.check(user, new_solution=False, subscribed=False)


async def test_not_charged_calls_do_not_spend_solutions(limits: Limits, user: User) -> None:
    for _ in range(5):
        await limits.record(user, "solve", call("0.01"), task_id=None, charged=False)

    assert await limits.remaining_free_solutions(user) == 2


async def test_budget_blocks_even_with_solutions_left(limits: Limits, user: User) -> None:
    await limits.record(user, "simpler", call("1.00"), task_id="t", charged=False)

    assert await limits.remaining_free_solutions(user) == 2
    with pytest.raises(AccessDeniedError):
        await limits.check(user, new_solution=True, subscribed=False)
    with pytest.raises(AccessDeniedError):
        await limits.check(user, new_solution=False, subscribed=False)


async def test_new_month_resets_limits(limits: Limits, user: User, clock: Clock) -> None:
    for _ in range(2):
        await limits.record(user, "solve", call("0.60"), task_id="t", charged=True)
    with pytest.raises(AccessDeniedError):
        await limits.check(user, new_solution=True, subscribed=False)

    clock.now = datetime(2026, 2, 1, 0, 0, tzinfo=UTC)

    await limits.check(user, new_solution=True, subscribed=False)
    assert await limits.remaining_free_solutions(user) == 2


async def test_subscriber_has_no_solution_limit_but_has_budget_cap(
    limits: Limits, user: User
) -> None:
    for _ in range(10):
        await limits.record(user, "solve", call("0.40"), task_id="t", charged=True)
    await limits.check(user, new_solution=True, subscribed=True)

    await limits.record(user, "solve", call("1.00"), task_id="t", charged=True)

    with pytest.raises(AccessDeniedError) as e:
        await limits.check(user, new_solution=True, subscribed=True)
    assert e.value.reason is Denial.PAID_CAP_REACHED


async def test_cost_stored_without_precision_loss(
    limits: Limits, user: User, session: AsyncSession
) -> None:
    await limits.record(user, "solve", call("0.038125"), task_id="t", charged=True)
    await limits.record(user, "simpler", call("0.000001"), task_id="t", charged=False)

    usage = await limits.usage(user)
    assert usage.cost_usd == Decimal("0.038126")
    row = await session.scalar(select(LlmCall).where(LlmCall.kind == "solve"))
    assert row is not None
    assert (row.input_tokens, row.output_tokens, row.model) == (10, 5, "claude-opus-5-5")


async def test_failed_paid_call_goes_to_budget_but_not_solutions(
    session: AsyncSession, user: User, redis: Redis
) -> None:
    llm = FakeLLMClient(delay_seconds=0)
    limits = Limits(session, CONFIG)
    assistant = Assistant(limits, Solver(llm), Tutor(llm), Throttle(redis, per_minute=100))

    with pytest.raises(Exception, match="max_tokens"):
        await assistant.solve(user, "fake:max_tokens", None)
    await assistant.solve(user, "fake:unreadable", None)

    usage = await limits.usage(user)
    assert usage.solutions == 0
    assert usage.cost_usd > 0
    kinds = (await session.scalars(select(LlmCall.kind))).all()
    assert kinds == ["solve", "solve"]


async def test_successful_solve_charged_with_task_id(
    session: AsyncSession, user: User, redis: Redis
) -> None:
    llm = FakeLLMClient(delay_seconds=0)
    assistant = Assistant(
        Limits(session, CONFIG), Solver(llm), Tutor(llm), Throttle(redis, per_minute=100)
    )

    result = await assistant.solve(user, "2x + 3 = 11", None)

    assert result.task is not None
    row = await session.scalar(select(LlmCall))
    assert row is not None
    assert row.charged and row.task_id == result.task.task_id
    assert row.cost_usd == Decimal("0.038")

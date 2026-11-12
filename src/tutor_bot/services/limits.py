from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy.ext.asyncio import AsyncSession

from tutor_bot.db.models import LlmCall, User
from tutor_bot.db.repositories.llm_calls import LlmCallRepository
from tutor_bot.services.llm_json import LLMCall


class Denial(StrEnum):
    FREE_EXHAUSTED = "free_exhausted"  # кончились бесплатные решения или бюджет
    PAID_CAP_REACHED = "paid_cap_reached"  # подписчик упёрся в месячный потолок расходов


class AccessDeniedError(Exception):
    def __init__(self, reason: Denial) -> None:
        super().__init__(reason.value)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class LimitsConfig:
    free_solutions: int
    free_budget_usd: Decimal
    paid_budget_usd: Decimal


@dataclass(frozen=True, slots=True)
class MonthUsage:
    solutions: int
    cost_usd: Decimal


def utc_now() -> datetime:
    return datetime.now(UTC)


def month_start(now: datetime) -> datetime:
    return now.astimezone(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)


class Limits:
    def __init__(
        self,
        session: AsyncSession,
        config: LimitsConfig,
        now: Callable[[], datetime] = utc_now,
    ) -> None:
        self._session = session
        self._repo = LlmCallRepository(session)
        self._config = config
        self._now = now

    async def usage(self, user: User) -> MonthUsage:
        solutions, cost = await self._repo.usage_since(user.id, month_start(self._now()))
        return MonthUsage(solutions, cost)

    async def remaining_free_solutions(self, user: User) -> int:
        usage = await self.usage(user)
        return max(self._config.free_solutions - usage.solutions, 0)

    def is_subscribed(self, user: User) -> bool:
        return user.subscription_until is not None and user.subscription_until > self._now()

    async def check(self, user: User, *, new_solution: bool) -> None:
        """Бросает AccessDeniedError, если запрос к LLM делать нельзя.

        Уточнения (new_solution=False) не тратят решения, но упираются в бюджет.
        """
        usage = await self.usage(user)
        if self.is_subscribed(user):
            if usage.cost_usd >= self._config.paid_budget_usd:
                raise AccessDeniedError(Denial.PAID_CAP_REACHED)
            return
        out_of_solutions = new_solution and usage.solutions >= self._config.free_solutions
        if out_of_solutions or usage.cost_usd >= self._config.free_budget_usd:
            raise AccessDeniedError(Denial.FREE_EXHAUSTED)

    async def record(
        self, user: User, kind: str, call: LLMCall, *, task_id: str | None, charged: bool
    ) -> None:
        """Записывает вызов и, если charged, засчитывает решение — в одной транзакции."""
        self._repo.add(
            LlmCall(
                user_id=user.id,
                task_id=task_id,
                kind=kind,
                model=call.model,
                input_tokens=sum(u.input_tokens for u in call.usages),
                output_tokens=sum(u.output_tokens for u in call.usages),
                cache_read_tokens=sum(u.cache_read_tokens for u in call.usages),
                cache_write_tokens=sum(u.cache_write_tokens for u in call.usages),
                cost_usd=call.cost_usd,
                charged=charged,
                created_at=self._now(),
            )
        )
        await self._session.commit()

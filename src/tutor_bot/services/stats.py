"""Сводка для админа: пользователи, решения, подписки, выручка и расходы на LLM."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import ColumnElement, Select, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tutor_bot.db.models import LlmCall, Payment, User
from tutor_bot.services.limits import month_start, utc_now
from tutor_bot.services.subscriptions import CURRENCY

ACTIVE_WINDOW = timedelta(days=7)
RECENT_PAYMENTS = 5


@dataclass(frozen=True, slots=True)
class PaymentRow:
    created_at: datetime
    user_id: int
    amount: int
    charge_id: str
    refunded: bool


@dataclass(frozen=True, slots=True)
class Stats:
    users_total: int
    users_active: int  # был хотя бы один вызов LLM за ACTIVE_WINDOW
    solutions_today: int
    solutions_month: int
    followups_month: int
    subscribers: int
    subscribers_auto_renew: int
    revenue_month: int  # Stars, без возвратов
    revenue_total: int
    cost_today: Decimal
    cost_month: Decimal
    cost_total: Decimal
    recent_payments: list[PaymentRow]

    @property
    def cost_per_solution_month(self) -> Decimal | None:
        """Все расходы месяца (с уточнениями и ошибками) на одно успешное решение."""
        if not self.solutions_month:
            return None
        return self.cost_month / self.solutions_month


class StatsService:
    def __init__(self, session: AsyncSession, now: Callable[[], datetime] = utc_now) -> None:
        self._session = session
        self._now = now

    async def collect(self) -> Stats:
        now = self._now()
        today = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        month = month_start(now)
        solution = (LlmCall.kind == "solve") & LlmCall.charged
        followup = LlmCall.kind != "solve"
        subscribed = User.subscription_until > now
        paid = (Payment.refunded_at.is_(None)) & (Payment.currency == CURRENCY)

        return Stats(
            users_total=await self._count(select(func.count()).select_from(User)),
            users_active=await self._count(
                select(func.count(distinct(LlmCall.user_id))).where(
                    LlmCall.created_at >= now - ACTIVE_WINDOW
                )
            ),
            solutions_today=await self._count_calls(solution, today),
            solutions_month=await self._count_calls(solution, month),
            followups_month=await self._count_calls(followup, month),
            subscribers=await self._count(select(func.count()).where(subscribed)),
            subscribers_auto_renew=await self._count(
                select(func.count()).where(subscribed, User.subscription_auto_renew)
            ),
            revenue_month=await self._count(
                select(func.coalesce(func.sum(Payment.amount), 0)).where(
                    paid, Payment.created_at >= month
                )
            ),
            revenue_total=await self._count(
                select(func.coalesce(func.sum(Payment.amount), 0)).where(paid)
            ),
            cost_today=await self._cost_since(today),
            cost_month=await self._cost_since(month),
            cost_total=await self._cost_since(None),
            recent_payments=await self._recent_payments(),
        )

    async def _count(self, query: Select[Any]) -> int:
        return int(await self._session.scalar(query) or 0)

    async def _count_calls(self, condition: ColumnElement[bool], since: datetime) -> int:
        return await self._count(select(func.count()).where(condition, LlmCall.created_at >= since))

    async def _cost_since(self, since: datetime | None) -> Decimal:
        query = select(func.coalesce(func.sum(LlmCall.cost_usd), 0))
        if since is not None:
            query = query.where(LlmCall.created_at >= since)
        return Decimal(await self._session.scalar(query) or 0)

    async def _recent_payments(self) -> list[PaymentRow]:
        rows = await self._session.scalars(
            select(Payment)
            .order_by(Payment.created_at.desc(), Payment.id.desc())
            .limit(RECENT_PAYMENTS)
        )
        return [
            PaymentRow(
                created_at=p.created_at,
                user_id=p.user_id,
                amount=p.amount,
                charge_id=p.telegram_payment_charge_id,
                refunded=p.refunded_at is not None,
            )
            for p in rows
        ]

from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tutor_bot.db.models import LlmCall


class LlmCallRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, call: LlmCall) -> None:
        self._session.add(call)

    async def usage_since(self, user_id: int, since: datetime) -> tuple[int, Decimal]:
        """Засчитанные решения и сумма расходов в $ с момента `since`."""
        query = select(
            func.count().filter(LlmCall.charged),
            func.coalesce(func.sum(LlmCall.cost_usd), 0),
        ).where(LlmCall.user_id == user_id, LlmCall.created_at >= since)
        solutions, cost = (await self._session.execute(query)).one()
        return solutions, Decimal(cost or 0)

"""Подписка за Telegram Stars: проверка оплаты, идемпотентное начисление, статус."""

import logging
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from tutor_bot.db.models import Payment, User
from tutor_bot.services.limits import utc_now

logger = logging.getLogger(__name__)

CURRENCY = "XTR"
# Telegram принимает для подписок только период 30 дней
SUBSCRIPTION_PERIOD = timedelta(days=30)
_PAYLOAD_PREFIX = "sub"


def make_payload(user_id: int) -> str:
    return f"{_PAYLOAD_PREFIX}:{user_id}:{secrets.token_hex(4)}"


def payload_user_id(payload: str) -> int | None:
    parts = payload.split(":")
    if len(parts) != 3 or parts[0] != _PAYLOAD_PREFIX or not parts[1].isdigit():
        return None
    return int(parts[1])


@dataclass(frozen=True, slots=True)
class PaymentEvent:
    """Нужные поля successful_payment — без привязки к aiogram."""

    telegram_payment_charge_id: str
    provider_payment_charge_id: str
    amount: int
    currency: str
    payload: str
    subscription_expiration_date: int | None
    is_recurring: bool
    is_first_recurring: bool


def short_charge_id(charge_id: str) -> str:
    # В логи — только начало идентификатора платежа
    return f"{charge_id[:8]}…"


class Subscriptions:
    def __init__(
        self,
        session: AsyncSession,
        price_stars: int,
        now: Callable[[], datetime] = utc_now,
    ) -> None:
        self._session = session
        self._price = price_stars
        self._now = now

    @property
    def price_stars(self) -> int:
        return self._price

    def is_valid_checkout(self, payer_id: int, currency: str, amount: int, payload: str) -> bool:
        """Проверка pre_checkout_query: оплачиваем ровно нашу подписку и за себя."""
        return (
            currency == CURRENCY and amount == self._price and payload_user_id(payload) == payer_id
        )

    async def apply_payment(self, user: User, event: PaymentEvent) -> bool:
        """Начисляет подписку за платёж. Повторное событие с тем же charge_id — без эффекта.

        Запись платежа и продление — в одной транзакции. Возвращает True, если начислили.
        """
        paid_until = self._paid_until(user, event)
        inserted = await self._session.scalar(
            insert(Payment)
            .values(
                user_id=user.id,
                telegram_payment_charge_id=event.telegram_payment_charge_id,
                provider_payment_charge_id=event.provider_payment_charge_id,
                amount=event.amount,
                currency=event.currency,
                is_recurring=event.is_recurring,
                is_first_recurring=event.is_first_recurring,
                paid_until=paid_until,
            )
            .on_conflict_do_nothing(index_elements=[Payment.telegram_payment_charge_id])
            .returning(Payment.id)
        )
        if inserted is None:
            await self._session.commit()  # вставки не было — просто закрываем транзакцию
            logger.warning(
                "Duplicate payment ignored user_id=%s charge=%s",
                user.id,
                short_charge_id(event.telegram_payment_charge_id),
            )
            return False

        user.subscription_until = paid_until
        user.subscription_auto_renew = event.is_recurring
        await self._session.commit()
        logger.info(
            "Subscription paid user_id=%s amount=%s until=%s charge=%s",
            user.id,
            event.amount,
            paid_until.isoformat(),
            short_charge_id(event.telegram_payment_charge_id),
        )
        return True

    async def last_charge_id(self, user: User) -> str | None:
        """charge_id последнего платежа — нужен для editUserStarSubscription."""
        return await self._session.scalar(
            select(Payment.telegram_payment_charge_id)
            .where(Payment.user_id == user.id, Payment.refunded_at.is_(None))
            .order_by(Payment.created_at.desc(), Payment.id.desc())
            .limit(1)
        )

    async def set_auto_renew(self, user: User, auto_renew: bool) -> None:
        user.subscription_auto_renew = auto_renew
        await self._session.commit()

    def _paid_until(self, user: User, event: PaymentEvent) -> datetime:
        if event.subscription_expiration_date is not None:
            paid_until = datetime.fromtimestamp(event.subscription_expiration_date, UTC)
        else:
            start = max(self._now(), user.subscription_until or self._now())
            paid_until = start + SUBSCRIPTION_PERIOD
        # Оплата не должна укорачивать уже выданную подписку (например, через /grant)
        if user.subscription_until is not None:
            paid_until = max(paid_until, user.subscription_until)
        return paid_until

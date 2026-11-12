from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tutor_bot.bot.keyboards import CANCEL_RENEWAL, RESUME_RENEWAL, SubscriptionAction
from tutor_bot.bot.routers.payments import (
    cmd_paysupport,
    cmd_subscription,
    on_pre_checkout,
    on_subscription_action,
    on_successful_payment,
)
from tutor_bot.bot.texts import t
from tutor_bot.db.models import Payment, User
from tutor_bot.services.limits import Limits, LimitsConfig
from tutor_bot.services.subscriptions import (
    PaymentEvent,
    Subscriptions,
    make_payload,
    payload_user_id,
)
from tutor_bot.services.users import register_user

PRICE = 250
NOW = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)
CONFIG = LimitsConfig(free_solutions=15, free_budget_usd=Decimal("1"), paid_budget_usd=Decimal("2"))


@pytest.fixture
async def user(session: AsyncSession) -> User:
    return await register_user(session, 42, "kid", "ru")


@pytest.fixture
def subs(session: AsyncSession) -> Subscriptions:
    return Subscriptions(session, PRICE, now=lambda: NOW)


@pytest.fixture
def limits(session: AsyncSession) -> Limits:
    return Limits(session, CONFIG, now=lambda: NOW)


def event(
    charge_id: str = "charge-1",
    expires: datetime | None = NOW + timedelta(days=30),
    recurring: bool = True,
    first: bool = True,
) -> PaymentEvent:
    return PaymentEvent(
        telegram_payment_charge_id=charge_id,
        provider_payment_charge_id="",
        amount=PRICE,
        currency="XTR",
        payload=make_payload(42),
        subscription_expiration_date=int(expires.timestamp()) if expires else None,
        is_recurring=recurring,
        is_first_recurring=first,
    )


async def payments_count(session: AsyncSession) -> int:
    return await session.scalar(select(func.count()).select_from(Payment)) or 0


def test_payload_roundtrip() -> None:
    assert payload_user_id(make_payload(42)) == 42
    assert payload_user_id("sub:abc:1") is None
    assert payload_user_id("other:42:1") is None
    assert payload_user_id("garbage") is None


@pytest.mark.parametrize(
    ("payer", "currency", "amount", "payload", "ok"),
    [
        (42, "XTR", PRICE, make_payload(42), True),
        (42, "XTR", 1, make_payload(42), False),  # не та сумма
        (42, "USD", PRICE, make_payload(42), False),  # не та валюта
        (7, "XTR", PRICE, make_payload(42), False),  # платит другой пользователь
        (42, "XTR", PRICE, "garbage", False),
    ],
)
def test_checkout_validation(
    subs: Subscriptions, payer: int, currency: str, amount: int, payload: str, ok: bool
) -> None:
    assert subs.is_valid_checkout(payer, currency, amount, payload) is ok


async def test_payment_activates_subscription(
    subs: Subscriptions, limits: Limits, user: User, session: AsyncSession
) -> None:
    assert await subs.apply_payment(user, event())

    assert user.subscription_until == NOW + timedelta(days=30)
    assert user.subscription_auto_renew
    assert limits.is_subscribed(user)
    assert await payments_count(session) == 1


async def test_duplicate_event_does_not_extend_twice(
    subs: Subscriptions, user: User, session: AsyncSession
) -> None:
    await subs.apply_payment(user, event())
    until = user.subscription_until

    # повторное событие, даже с другой датой, ничего не меняет
    again = event(expires=NOW + timedelta(days=60))
    assert not await subs.apply_payment(user, again)

    await session.refresh(user)
    assert user.subscription_until == until
    assert user.language == "ru"  # объект пользователя по-прежнему рабочий
    assert await payments_count(session) == 1


async def test_renewal_extends_subscription(
    subs: Subscriptions, user: User, session: AsyncSession
) -> None:
    await subs.apply_payment(user, event())

    renewal = event("charge-2", expires=NOW + timedelta(days=60), first=False)
    assert await subs.apply_payment(user, renewal)

    assert user.subscription_until == NOW + timedelta(days=60)
    assert await payments_count(session) == 2


async def test_payment_never_shortens_granted_subscription(subs: Subscriptions, user: User) -> None:
    user.subscription_until = NOW + timedelta(days=90)  # например, выдано через /grant

    await subs.apply_payment(user, event())

    assert user.subscription_until == NOW + timedelta(days=90)


async def test_payment_without_expiration_adds_period(subs: Subscriptions, user: User) -> None:
    await subs.apply_payment(user, event(expires=None))

    assert user.subscription_until == NOW + timedelta(days=30)


async def test_failed_transaction_leaves_nothing(
    subs: Subscriptions, user: User, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken_commit() -> None:
        raise RuntimeError("db down")

    monkeypatch.setattr(session, "commit", broken_commit)
    with pytest.raises(RuntimeError):
        await subs.apply_payment(user, event())
    await session.rollback()
    monkeypatch.undo()

    assert await payments_count(session) == 0
    await session.refresh(user)
    assert user.subscription_until is None


async def test_expired_subscription_is_not_active(
    subs: Subscriptions, user: User, session: AsyncSession
) -> None:
    await subs.apply_payment(user, event(expires=NOW - timedelta(seconds=1)))
    later = Limits(session, CONFIG, now=lambda: NOW)

    assert not later.is_subscribed(user)


# --- бот ---


def make_message() -> MagicMock:
    message = MagicMock(spec=Message)
    message.answer = AsyncMock()
    message.edit_text = AsyncMock()
    return message


async def test_pre_checkout_handler(subs: Subscriptions, user: User) -> None:
    good = MagicMock(currency="XTR", total_amount=PRICE, invoice_payload=make_payload(42))
    good.from_user.id = 42
    good.answer = AsyncMock()
    bad = MagicMock(currency="XTR", total_amount=1, invoice_payload=make_payload(42))
    bad.from_user.id = 42
    bad.answer = AsyncMock()

    await on_pre_checkout(good, user, subs)
    await on_pre_checkout(bad, user, subs)

    good.answer.assert_awaited_once_with(ok=True)
    bad.answer.assert_awaited_once_with(ok=False, error_message=t("checkout_invalid", "ru"))


async def test_successful_payment_handler_thanks_once(subs: Subscriptions, user: User) -> None:
    def payment_message() -> MagicMock:
        message = make_message()
        message.successful_payment = MagicMock(
            telegram_payment_charge_id="charge-1",
            provider_payment_charge_id="",
            total_amount=PRICE,
            currency="XTR",
            invoice_payload=make_payload(42),
            subscription_expiration_date=int((NOW + timedelta(days=30)).timestamp()),
            is_recurring=True,
            is_first_recurring=True,
        )
        return message

    first, duplicate = payment_message(), payment_message()
    await on_successful_payment(first, user, subs)
    await on_successful_payment(duplicate, user, subs)

    first.answer.assert_awaited_once_with(t("sub_thanks", "ru").format(date="09.04.2026"))
    duplicate.answer.assert_not_awaited()


async def test_subscription_status_and_cancel_renewal(
    subs: Subscriptions, limits: Limits, user: User
) -> None:
    await subs.apply_payment(user, event())
    bot = MagicMock()
    bot.edit_user_star_subscription = AsyncMock(return_value=True)

    status = make_message()
    await cmd_subscription(status, bot, user, limits, subs)
    assert status.answer.await_args.args[0] == t("sub_active_renews", "ru").format(
        date="09.04.2026"
    )

    callback = MagicMock(message=make_message())
    callback.answer = AsyncMock()
    data = SubscriptionAction(action=CANCEL_RENEWAL)
    await on_subscription_action(callback, data, bot, user, limits, subs)

    bot.edit_user_star_subscription.assert_awaited_once_with(42, "charge-1", is_canceled=True)
    assert not user.subscription_auto_renew
    assert limits.is_subscribed(user)  # активна до конца оплаченного периода
    callback.message.edit_text.assert_awaited_once()
    assert callback.message.edit_text.await_args.args[0] == t("sub_active_canceled", "ru").format(
        date="09.04.2026"
    )


async def test_cancel_renewal_telegram_error_keeps_state(
    subs: Subscriptions, limits: Limits, user: User
) -> None:
    await subs.apply_payment(user, event())
    bot = MagicMock()
    bot.edit_user_star_subscription = AsyncMock(
        side_effect=TelegramBadRequest(method=MagicMock(), message="bad")
    )
    callback = MagicMock(message=make_message())
    callback.answer = AsyncMock()

    data = SubscriptionAction(action=CANCEL_RENEWAL)
    await on_subscription_action(callback, data, bot, user, limits, subs)

    assert user.subscription_auto_renew
    callback.answer.assert_awaited_once_with(t("sub_change_failed", "ru"), show_alert=True)


async def test_resume_renewal_without_subscription_fails(
    subs: Subscriptions, limits: Limits, user: User
) -> None:
    bot = MagicMock()
    bot.edit_user_star_subscription = AsyncMock()
    callback = MagicMock(message=make_message())
    callback.answer = AsyncMock()

    data = SubscriptionAction(action=RESUME_RENEWAL)
    await on_subscription_action(callback, data, bot, user, limits, subs)

    bot.edit_user_star_subscription.assert_not_awaited()


async def test_subscription_status_without_subscription_offers_invoice(
    subs: Subscriptions, limits: Limits, user: User
) -> None:
    bot = MagicMock()
    bot.create_invoice_link = AsyncMock(return_value="https://t.me/$invoice")
    message = make_message()

    await cmd_subscription(message, bot, user, limits, subs)

    assert message.answer.await_args.args[0] == t("sub_none", "ru").format(price=PRICE)
    markup = message.answer.await_args.kwargs["reply_markup"]
    assert markup.inline_keyboard[0][0].url == "https://t.me/$invoice"


async def test_paysupport_shows_contact(user: User) -> None:
    message = make_message()

    await cmd_paysupport(message, user, "@dimopl")

    assert "@dimopl" in message.answer.await_args.args[0]

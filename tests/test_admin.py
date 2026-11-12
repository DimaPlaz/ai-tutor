from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import CommandObject
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tutor_bot.bot.filters import IsAdmin
from tutor_bot.bot.routers.admin import cmd_grant, cmd_refund, parse_grant_args, render_stats
from tutor_bot.bot.texts import t
from tutor_bot.db.models import LlmCall, Payment, User
from tutor_bot.services.stats import StatsService
from tutor_bot.services.subscriptions import (
    ChargeAlreadyRefundedError,
    RefundOutcome,
    Subscriptions,
)
from tutor_bot.services.users import register_user

NOW = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)
PAID_UNTIL = NOW + timedelta(days=30)


@pytest.fixture
async def admin(session: AsyncSession) -> User:
    return await register_user(session, 1, "boss", "ru")


@pytest.fixture
async def kid(session: AsyncSession) -> User:
    return await register_user(session, 42, "kid", "en")


@pytest.fixture
def subs(session: AsyncSession) -> Subscriptions:
    return Subscriptions(session, 250, now=lambda: NOW)


async def add_payment(
    session: AsyncSession,
    user_id: int,
    charge_id: str,
    *,
    amount: int = 250,
    created_at: datetime = NOW,
    refunded: bool = False,
) -> Payment:
    payment = Payment(
        user_id=user_id,
        telegram_payment_charge_id=charge_id,
        provider_payment_charge_id="",
        amount=amount,
        currency="XTR",
        is_recurring=True,
        is_first_recurring=True,
        paid_until=PAID_UNTIL,
        refunded_at=NOW if refunded else None,
        created_at=created_at,
    )
    session.add(payment)
    await session.commit()
    return payment


def add_call(
    session: AsyncSession, user_id: int, kind: str, cost: str, created_at: datetime, charged: bool
) -> None:
    session.add(
        LlmCall(
            user_id=user_id,
            kind=kind,
            model="claude-opus-5-5",
            input_tokens=1,
            output_tokens=1,
            cache_read_tokens=0,
            cache_write_tokens=0,
            cost_usd=Decimal(cost),
            charged=charged,
            created_at=created_at,
        )
    )


# --- /grant ---


async def test_grant_without_subscription_starts_now(subs: Subscriptions, kid: User) -> None:
    granted = await subs.grant(42, 10)

    assert granted is kid
    assert kid.subscription_until == NOW + timedelta(days=10)
    assert not kid.subscription_auto_renew


async def test_grant_extends_active_subscription(subs: Subscriptions, kid: User) -> None:
    kid.subscription_until = NOW + timedelta(days=5)

    await subs.grant(42, 10)

    assert kid.subscription_until == NOW + timedelta(days=15)


async def test_grant_after_expired_subscription_starts_now(subs: Subscriptions, kid: User) -> None:
    kid.subscription_until = NOW - timedelta(days=5)

    await subs.grant(42, 10)

    assert kid.subscription_until == NOW + timedelta(days=10)


async def test_grant_unknown_user(subs: Subscriptions) -> None:
    assert await subs.grant(777, 10) is None


@pytest.mark.parametrize("days", [0, -1, 3651])
async def test_grant_rejects_bad_days(subs: Subscriptions, kid: User, days: int) -> None:
    with pytest.raises(ValueError):
        await subs.grant(42, days)


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        ("42 30", (42, 30)),
        ("  42   30 ", (42, 30)),
        (None, None),
        ("42", None),
        ("42 30 1", None),
        ("abc 30", None),
        ("42 -3", None),
        ("42 0", None),
        ("42 3651", None),
    ],
)
def test_parse_grant_args(args: str | None, expected: tuple[int, int] | None) -> None:
    assert parse_grant_args(args) == expected


def make_message() -> MagicMock:
    message = MagicMock(spec=Message)
    message.answer = AsyncMock()
    return message


def command(args: str | None) -> CommandObject:
    return CommandObject(prefix="/", command="cmd", args=args)


async def test_grant_handler_notifies_user(subs: Subscriptions, admin: User, kid: User) -> None:
    bot = MagicMock()
    bot.send_message = AsyncMock()
    message = make_message()

    await cmd_grant(message, command("42 30"), bot, admin, subs)

    date = "09.04.2026"
    bot.send_message.assert_awaited_once_with(42, t("grant_notice", "en").format(date=date))
    message.answer.assert_awaited_once_with(
        t("admin_grant_done", "ru").format(user_id=42, date=date)
    )


async def test_grant_handler_user_blocked_bot(subs: Subscriptions, admin: User, kid: User) -> None:
    bot = MagicMock()
    bot.send_message = AsyncMock(
        side_effect=TelegramForbiddenError(method=MagicMock(), message="blocked")
    )
    message = make_message()

    await cmd_grant(message, command("42 30"), bot, admin, subs)

    assert kid.subscription_until == NOW + timedelta(days=30)  # выдано несмотря на ошибку
    assert t("admin_grant_not_notified", "ru") in message.answer.await_args.args[0]


async def test_grant_handler_bad_args(subs: Subscriptions, admin: User) -> None:
    message = make_message()

    await cmd_grant(message, command("42"), MagicMock(), admin, subs)

    message.answer.assert_awaited_once_with(t("admin_grant_usage", "ru").format(max=3650))


async def test_grant_handler_unknown_user(subs: Subscriptions, admin: User) -> None:
    message = make_message()

    await cmd_grant(message, command("777 30"), MagicMock(), admin, subs)

    message.answer.assert_awaited_once_with(t("admin_user_not_found", "ru").format(user_id=777))


# --- /refund ---


async def test_refund_marks_payment_and_keeps_paid_period(
    subs: Subscriptions, kid: User, session: AsyncSession
) -> None:
    kid.subscription_until = PAID_UNTIL
    kid.subscription_auto_renew = True
    payment = await add_payment(session, 42, "charge-1")
    send = AsyncMock()

    assert await subs.refund("charge-1", send) is RefundOutcome.REFUNDED

    send.assert_awaited_once_with(42, "charge-1")
    assert payment.refunded_at == NOW
    assert kid.subscription_until == PAID_UNTIL  # подписка — до оплаченной даты
    assert not kid.subscription_auto_renew


async def test_refund_twice_does_not_call_telegram(
    subs: Subscriptions, kid: User, session: AsyncSession
) -> None:
    await add_payment(session, 42, "charge-1", refunded=True)
    send = AsyncMock()

    assert await subs.refund("charge-1", send) is RefundOutcome.ALREADY_REFUNDED
    send.assert_not_awaited()


async def test_refund_unknown_charge(subs: Subscriptions) -> None:
    send = AsyncMock()

    assert await subs.refund("nope", send) is RefundOutcome.NOT_FOUND
    send.assert_not_awaited()


async def test_refund_already_refunded_in_telegram_is_recorded(
    subs: Subscriptions, kid: User, session: AsyncSession
) -> None:
    payment = await add_payment(session, 42, "charge-1")
    send = AsyncMock(side_effect=ChargeAlreadyRefundedError)

    assert await subs.refund("charge-1", send) is RefundOutcome.ALREADY_REFUNDED
    assert payment.refunded_at == NOW


async def test_refund_telegram_error_changes_nothing(
    subs: Subscriptions, kid: User, session: AsyncSession
) -> None:
    kid.subscription_auto_renew = True
    await add_payment(session, 42, "charge-1")
    send = AsyncMock(side_effect=TelegramBadRequest(method=MagicMock(), message="NOT_ENOUGH"))

    with pytest.raises(TelegramBadRequest):
        await subs.refund("charge-1", send)

    await session.rollback()
    payment = await session.scalar(select(Payment))
    assert payment is not None and payment.refunded_at is None
    await session.refresh(kid)
    assert kid.subscription_auto_renew


async def test_refund_handler_translates_already_refunded(
    subs: Subscriptions, admin: User, kid: User, session: AsyncSession
) -> None:
    await add_payment(session, 42, "charge-1")
    bot = MagicMock()
    bot.refund_star_payment = AsyncMock(
        side_effect=TelegramBadRequest(
            method=MagicMock(), message="Bad Request: CHARGE_ALREADY_REFUNDED"
        )
    )
    message = make_message()

    await cmd_refund(message, command("charge-1"), bot, admin, subs)

    message.answer.assert_awaited_once_with(t("admin_refund_already", "ru"))


async def test_refund_handler_reports_telegram_error(
    subs: Subscriptions, admin: User, kid: User, session: AsyncSession
) -> None:
    await add_payment(session, 42, "charge-1")
    bot = MagicMock()
    bot.refund_star_payment = AsyncMock(
        side_effect=TelegramBadRequest(method=MagicMock(), message="Bad Request: <oops>")
    )
    message = make_message()

    await cmd_refund(message, command("charge-1"), bot, admin, subs)

    message.answer.assert_awaited_once_with(
        t("admin_refund_failed", "ru").format(error="Bad Request: &lt;oops&gt;")
    )


@pytest.mark.parametrize("args", [None, "", "a b"])
async def test_refund_handler_bad_args(subs: Subscriptions, admin: User, args: str | None) -> None:
    message = make_message()

    await cmd_refund(message, command(args), MagicMock(), admin, subs)

    message.answer.assert_awaited_once_with(t("admin_refund_usage", "ru"))


# --- /stats ---


async def test_stats(session: AsyncSession, admin: User, kid: User) -> None:
    other = await register_user(session, 7, None, "ru")
    kid.subscription_until = NOW + timedelta(days=3)
    kid.subscription_auto_renew = True
    other.subscription_until = NOW + timedelta(days=3)
    admin.subscription_until = NOW - timedelta(days=1)  # истекла

    today = NOW - timedelta(hours=1)
    earlier_this_month = NOW - timedelta(days=5)
    last_month = NOW - timedelta(days=20)
    add_call(session, 42, "solve", "0.04", today, charged=True)
    add_call(session, 42, "check", "0.01", today, charged=False)
    add_call(session, 42, "solve", "0.02", today, charged=False)  # нечитаемое фото
    add_call(session, 7, "solve", "0.03", earlier_this_month, charged=True)
    add_call(session, 1, "solve", "0.05", last_month, charged=True)
    await session.commit()

    await add_payment(session, 42, "p-old", created_at=last_month)
    await add_payment(session, 42, "p-new", created_at=today)
    await add_payment(session, 7, "p-refunded", created_at=today, refunded=True)

    stats = await StatsService(session, now=lambda: NOW).collect()

    assert stats.users_total == 3
    assert stats.users_active == 2  # admin писал только 20 дней назад
    assert stats.solutions_today == 1
    assert stats.solutions_month == 2
    assert stats.followups_month == 1
    assert stats.subscribers == 2
    assert stats.subscribers_auto_renew == 1
    assert stats.revenue_month == 250
    assert stats.revenue_total == 500
    assert stats.cost_today == Decimal("0.07")
    assert stats.cost_month == Decimal("0.10")
    assert stats.cost_total == Decimal("0.15")
    assert stats.cost_per_solution_month == Decimal("0.05")
    assert [p.charge_id for p in stats.recent_payments] == ["p-refunded", "p-new", "p-old"]
    assert stats.recent_payments[0].refunded

    text = render_stats(stats, "ru")
    assert "<code>p-new</code>" in text
    assert "$0.050" in text
    assert t("admin_refunded_mark", "ru") in text


async def test_stats_empty(session: AsyncSession) -> None:
    stats = await StatsService(session, now=lambda: NOW).collect()

    assert stats.users_total == 0
    assert stats.cost_total == Decimal("0")
    assert stats.cost_per_solution_month is None
    assert t("admin_no_payments", "en") in render_stats(stats, "en")


# --- доступ ---


@pytest.mark.parametrize(("user_id", "allowed"), [(1, True), (42, False)])
async def test_is_admin_filter(user_id: int, allowed: bool) -> None:
    tg_user = MagicMock(id=user_id)

    assert await IsAdmin()(MagicMock(), event_from_user=tg_user, admin_ids=[1]) is allowed


async def test_is_admin_filter_without_user() -> None:
    assert not await IsAdmin()(MagicMock(), admin_ids=[1])

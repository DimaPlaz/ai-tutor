"""Админ-команды: доступны только ADMIN_IDS, остальным бот не отвечает."""

import html
import logging
from decimal import Decimal

from aiogram import Bot, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from tutor_bot.bot.filters import IsAdmin
from tutor_bot.bot.subscription_ui import fmt_date
from tutor_bot.bot.texts import t
from tutor_bot.db.models import User
from tutor_bot.services.stats import PaymentRow, Stats, StatsService
from tutor_bot.services.subscriptions import (
    MAX_GRANT_DAYS,
    ChargeAlreadyRefundedError,
    RefundOutcome,
    Subscriptions,
)

logger = logging.getLogger(__name__)

router = Router(name="admin")
router.message.filter(IsAdmin())


def parse_grant_args(args: str | None) -> tuple[int, int] | None:
    parts = (args or "").split()
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        return None
    user_id, days = int(parts[0]), int(parts[1])
    if not 1 <= days <= MAX_GRANT_DAYS:
        return None
    return user_id, days


def render_stats(stats: Stats, lang: str) -> str:
    per_solution = stats.cost_per_solution_month
    payments = "\n".join(_payment_line(p, lang) for p in stats.recent_payments)
    return t("admin_stats", lang).format(
        users_total=stats.users_total,
        users_active=stats.users_active,
        solutions_today=stats.solutions_today,
        solutions_month=stats.solutions_month,
        followups_month=stats.followups_month,
        subscribers=stats.subscribers,
        subscribers_auto_renew=stats.subscribers_auto_renew,
        revenue_month=stats.revenue_month,
        revenue_total=stats.revenue_total,
        cost_today=_usd(stats.cost_today),
        cost_month=_usd(stats.cost_month),
        cost_total=_usd(stats.cost_total),
        cost_per_solution=f"${per_solution:.3f}" if per_solution is not None else "—",
        payments=payments or t("admin_no_payments", lang),
    )


def _usd(value: Decimal) -> str:
    return f"{value:.2f}"


def _payment_line(payment: PaymentRow, lang: str) -> str:
    line = (
        f"{fmt_date(payment.created_at)} · {payment.user_id} · {payment.amount} ⭐ · "
        f"<code>{html.escape(payment.charge_id)}</code>"
    )
    if payment.refunded:
        line += f" · {t('admin_refunded_mark', lang)}"
    return line


@router.message(Command("stats"))
async def cmd_stats(message: Message, user: User, stats: StatsService) -> None:
    await message.answer(render_stats(await stats.collect(), user.language))


@router.message(Command("grant"))
async def cmd_grant(
    message: Message, command: CommandObject, bot: Bot, user: User, subscriptions: Subscriptions
) -> None:
    lang = user.language
    parsed = parse_grant_args(command.args)
    if parsed is None:
        await message.answer(t("admin_grant_usage", lang).format(max=MAX_GRANT_DAYS))
        return
    user_id, days = parsed
    target = await subscriptions.grant(user_id, days)
    if target is None or target.subscription_until is None:
        await message.answer(t("admin_user_not_found", lang).format(user_id=user_id))
        return
    date = fmt_date(target.subscription_until)
    reply = t("admin_grant_done", lang).format(user_id=user_id, date=date)
    try:
        await bot.send_message(user_id, t("grant_notice", target.language).format(date=date))
    except TelegramAPIError:
        logger.warning("Grant notice not delivered user_id=%s", user_id)
        reply += "\n" + t("admin_grant_not_notified", lang)
    await message.answer(reply)


@router.message(Command("refund"))
async def cmd_refund(
    message: Message, command: CommandObject, bot: Bot, user: User, subscriptions: Subscriptions
) -> None:
    lang = user.language
    charge_id = (command.args or "").strip()
    if not charge_id or " " in charge_id:
        await message.answer(t("admin_refund_usage", lang))
        return

    async def send_refund(user_id: int, charge: str) -> None:
        try:
            await bot.refund_star_payment(user_id, charge)
        except TelegramBadRequest as e:
            if "CHARGE_ALREADY_REFUNDED" in e.message:
                raise ChargeAlreadyRefundedError from e
            raise

    try:
        outcome = await subscriptions.refund(charge_id, send_refund)
    except TelegramAPIError as e:
        logger.warning("refundStarPayment failed: %s", e.message)
        await message.answer(t("admin_refund_failed", lang).format(error=html.escape(e.message)))
        return
    key = {
        RefundOutcome.REFUNDED: "admin_refund_done",
        RefundOutcome.ALREADY_REFUNDED: "admin_refund_already",
        RefundOutcome.NOT_FOUND: "admin_refund_not_found",
    }[outcome]
    await message.answer(t(key, lang))

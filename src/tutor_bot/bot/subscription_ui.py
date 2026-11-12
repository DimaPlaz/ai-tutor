"""Счёт на подписку и статус подписки для ученика."""

import logging
from datetime import UTC, datetime

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardMarkup, LabeledPrice

from tutor_bot.bot.keyboards import renewal_keyboard, subscribe_keyboard
from tutor_bot.bot.texts import t
from tutor_bot.db.models import User
from tutor_bot.services.subscriptions import CURRENCY, SUBSCRIPTION_PERIOD, make_payload

logger = logging.getLogger(__name__)


def fmt_date(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%d.%m.%Y")


async def paywall_keyboard(bot: Bot, user: User, price: int) -> InlineKeyboardMarkup | None:
    """Кнопка оплаты со ссылкой на счёт. None, если Telegram не выдал ссылку."""
    lang = user.language
    try:
        link = await bot.create_invoice_link(
            title=t("invoice_title", lang),
            description=t("invoice_description", lang),
            payload=make_payload(user.id),
            currency=CURRENCY,
            prices=[LabeledPrice(label=t("invoice_title", lang), amount=price)],
            subscription_period=int(SUBSCRIPTION_PERIOD.total_seconds()),
        )
    except TelegramAPIError:
        logger.exception("Failed to create invoice link user_id=%s", user.id)
        return None
    return subscribe_keyboard(link, lang, price)


async def subscription_status(
    bot: Bot, user: User, price: int, subscribed: bool
) -> tuple[str, InlineKeyboardMarkup | None]:
    lang = user.language
    if subscribed and user.subscription_until is not None:
        key = "sub_active_renews" if user.subscription_auto_renew else "sub_active_canceled"
        text = t(key, lang).format(date=fmt_date(user.subscription_until))
        return text, renewal_keyboard(lang, user.subscription_auto_renew)
    text = t("sub_none", lang).format(price=price)
    return text, await paywall_keyboard(bot, user, price)

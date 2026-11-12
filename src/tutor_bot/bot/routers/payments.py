import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message, PreCheckoutQuery

from tutor_bot.bot.keyboards import CANCEL_RENEWAL, SubscriptionAction
from tutor_bot.bot.subscription_ui import fmt_date, subscription_status
from tutor_bot.bot.texts import t
from tutor_bot.db.models import User
from tutor_bot.services.limits import Limits
from tutor_bot.services.subscriptions import PaymentEvent, Subscriptions

logger = logging.getLogger(__name__)

router = Router(name="payments")


@router.pre_checkout_query()
async def on_pre_checkout(
    query: PreCheckoutQuery, user: User, subscriptions: Subscriptions
) -> None:
    # Telegram ждёт ответа не больше 10 секунд — здесь только быстрые проверки
    if subscriptions.is_valid_checkout(
        query.from_user.id, query.currency, query.total_amount, query.invoice_payload
    ):
        await query.answer(ok=True)
        return
    logger.warning("Rejected pre_checkout user_id=%s", query.from_user.id)
    await query.answer(ok=False, error_message=t("checkout_invalid", user.language))


@router.message(F.successful_payment)
async def on_successful_payment(message: Message, user: User, subscriptions: Subscriptions) -> None:
    payment = message.successful_payment
    assert payment is not None  # гарантирует фильтр
    event = PaymentEvent(
        telegram_payment_charge_id=payment.telegram_payment_charge_id,
        provider_payment_charge_id=payment.provider_payment_charge_id,
        amount=payment.total_amount,
        currency=payment.currency,
        payload=payment.invoice_payload,
        subscription_expiration_date=payment.subscription_expiration_date,
        is_recurring=bool(payment.is_recurring),
        is_first_recurring=bool(payment.is_first_recurring),
    )
    if not await subscriptions.apply_payment(user, event):
        return  # повторное событие — уже начислено
    assert user.subscription_until is not None
    key = "sub_renewed" if event.is_recurring and not event.is_first_recurring else "sub_thanks"
    await message.answer(t(key, user.language).format(date=fmt_date(user.subscription_until)))


@router.message(Command("subscription"))
async def cmd_subscription(
    message: Message, bot: Bot, user: User, limits: Limits, subscriptions: Subscriptions
) -> None:
    text, keyboard = await subscription_status(
        bot, user, subscriptions.price_stars, limits.is_subscribed(user)
    )
    await message.answer(text, reply_markup=keyboard)


@router.callback_query(SubscriptionAction.filter())
async def on_subscription_action(
    callback: CallbackQuery,
    callback_data: SubscriptionAction,
    bot: Bot,
    user: User,
    limits: Limits,
    subscriptions: Subscriptions,
) -> None:
    lang = user.language
    cancel = callback_data.action == CANCEL_RENEWAL
    charge_id = await subscriptions.last_charge_id(user)
    if charge_id is None or not limits.is_subscribed(user):
        await callback.answer(t("sub_change_failed", lang), show_alert=True)
        return
    try:
        await bot.edit_user_star_subscription(user.id, charge_id, is_canceled=cancel)
    except TelegramAPIError:
        logger.exception("editUserStarSubscription failed user_id=%s", user.id)
        await callback.answer(t("sub_change_failed", lang), show_alert=True)
        return
    await subscriptions.set_auto_renew(user, not cancel)
    await callback.answer()
    if isinstance(callback.message, Message):
        text, keyboard = await subscription_status(bot, user, subscriptions.price_stars, True)
        await callback.message.edit_text(text, reply_markup=keyboard)


@router.message(Command("terms"))
async def cmd_terms(
    message: Message, user: User, subscriptions: Subscriptions, free_total: int
) -> None:
    text = t("terms", user.language).format(free=free_total, price=subscriptions.price_stars)
    await message.answer(text)


@router.message(Command("paysupport"))
async def cmd_paysupport(message: Message, user: User, support_contact: str) -> None:
    await message.answer(t("paysupport", user.language).format(contact=support_contact))

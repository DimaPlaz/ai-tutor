from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from tutor_bot.bot.subscription_ui import fmt_date
from tutor_bot.bot.texts import t
from tutor_bot.db.models import User
from tutor_bot.services.assistant import Assistant

router = Router(name="start")


@router.message(CommandStart())
async def cmd_start(message: Message, user: User, assistant: Assistant, free_total: int) -> None:
    lang = user.language
    left = await assistant.remaining_free_solutions(user)
    if left is None and user.subscription_until is not None:
        status = t("sub_active_short", lang).format(date=fmt_date(user.subscription_until))
    else:
        status = t("free_left", lang).format(left=left, total=free_total)
    await message.answer(f"{t('start', lang)}\n\n{status}")

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from tutor_bot.bot.texts import t
from tutor_bot.db.models import User

router = Router(name="start")


@router.message(CommandStart())
async def cmd_start(message: Message, user: User) -> None:
    await message.answer(t("start", user.language))

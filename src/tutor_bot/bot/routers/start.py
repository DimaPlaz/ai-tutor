from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from tutor_bot.bot.texts import t
from tutor_bot.services.users import register_user

router = Router(name="start")


@router.message(CommandStart())
async def cmd_start(message: Message, session: AsyncSession) -> None:
    if message.from_user is None:
        return
    tg_user = message.from_user
    user = await register_user(session, tg_user.id, tg_user.username, tg_user.language_code)
    await message.answer(t("start", user.language))

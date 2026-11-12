from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from tutor_bot.bot.keyboards import LangChoice, lang_keyboard
from tutor_bot.bot.texts import t
from tutor_bot.db.models import User
from tutor_bot.services.users import SUPPORTED_LANGUAGES, set_language

router = Router(name="lang")


@router.message(Command("lang"))
async def cmd_lang(message: Message, user: User) -> None:
    await message.answer(t("lang_choose", user.language), reply_markup=lang_keyboard())


@router.callback_query(LangChoice.filter(F.lang.in_(SUPPORTED_LANGUAGES)))
async def on_lang_choice(
    callback: CallbackQuery, callback_data: LangChoice, user: User, session: AsyncSession
) -> None:
    await set_language(session, user, callback_data.lang)
    await callback.answer()
    if isinstance(callback.message, Message):
        await callback.message.edit_text(t("lang_set", user.language))

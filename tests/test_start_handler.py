from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.ext.asyncio import AsyncSession

from tutor_bot.bot.routers.start import cmd_start
from tutor_bot.bot.texts import t


def _message(language_code: str | None) -> MagicMock:
    message = MagicMock()
    message.from_user.id = 42
    message.from_user.username = "kid"
    message.from_user.language_code = language_code
    message.answer = AsyncMock()
    return message


async def test_start_answers_in_user_language(session: AsyncSession) -> None:
    message = _message("ru")

    await cmd_start(message, session)

    message.answer.assert_awaited_once_with(t("start", "ru"))


async def test_start_falls_back_to_english(session: AsyncSession) -> None:
    message = _message("de")

    await cmd_start(message, session)

    message.answer.assert_awaited_once_with(t("start", "en"))

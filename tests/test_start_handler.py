from unittest.mock import AsyncMock, MagicMock

from tutor_bot.bot.routers.start import cmd_start
from tutor_bot.bot.texts import t
from tutor_bot.db.models import User


async def test_start_answers_in_user_language() -> None:
    message = MagicMock()
    message.answer = AsyncMock()

    await cmd_start(message, User(id=42, language="ru"))

    message.answer.assert_awaited_once_with(t("start", "ru"))

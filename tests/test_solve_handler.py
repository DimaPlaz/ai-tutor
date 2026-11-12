from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.ext.asyncio import AsyncSession

from tutor_bot.bot.routers.solve import solve_photo, solve_text
from tutor_bot.bot.texts import t
from tutor_bot.llm.fake import FakeLLMClient
from tutor_bot.services.solver import Solver

SOLVER = Solver(FakeLLMClient(delay_seconds=0))


def _message(text: str | None = None, caption: str | None = None) -> MagicMock:
    message = MagicMock()
    message.from_user.id = 42
    message.from_user.username = "kid"
    message.from_user.language_code = "ru"
    message.chat.id = 42
    message.text = text
    message.caption = caption
    message.answer = AsyncMock()
    return message


def _bot() -> MagicMock:
    bot = MagicMock()
    bot.download = AsyncMock()
    bot.send_chat_action = AsyncMock()
    return bot


def _answers(message: MagicMock) -> list[str]:
    return [call.args[0] for call in message.answer.await_args_list]


async def test_text_problem_gets_solution(session: AsyncSession) -> None:
    message = _message(text="2x + 3 = 11")

    await solve_text(message, _bot(), session, SOLVER)

    [reply] = _answers(message)
    assert "<b>📝 Условие</b>" in reply
    assert "<b>✅ Ответ:</b> x = 4" in reply


async def test_photo_is_downloaded_and_solved(session: AsyncSession) -> None:
    message = _message(caption=None)
    message.photo = [MagicMock(name="small"), MagicMock(name="large")]
    bot = _bot()

    await solve_photo(message, bot, session, SOLVER)

    assert bot.download.await_args.args[0] is message.photo[-1]
    assert "x = 4" in _answers(message)[0]


async def test_unreadable_photo_asks_to_retake(session: AsyncSession) -> None:
    message = _message(text="fake:unreadable")

    await solve_text(message, _bot(), session, SOLVER)

    assert _answers(message) == [t("unreadable", "ru")]


async def test_llm_error_gives_friendly_message(session: AsyncSession) -> None:
    message = _message(text="fake:error")

    await solve_text(message, _bot(), session, SOLVER)

    assert _answers(message) == [t("llm_unavailable", "ru")]


async def test_long_solution_sent_in_several_messages(session: AsyncSession) -> None:
    message = _message(text="fake:long")

    await solve_text(message, _bot(), session, SOLVER)

    replies = _answers(message)
    assert len(replies) > 1
    assert all(len(r) <= 4096 for r in replies)

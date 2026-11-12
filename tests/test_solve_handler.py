"""Сценарии бота целиком: Telegram замокан, LLM — тестовый режим, FSM — в памяти, БД настоящая."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from tutor_bot.bot.keyboards import CHECK, NEW, SIMPLER, LangChoice, TaskAction
from tutor_bot.bot.routers.lang import on_lang_choice
from tutor_bot.bot.routers.solve import handle_text, solve_photo
from tutor_bot.bot.routers.task import on_student_answer, on_task_action
from tutor_bot.bot.states import TaskStates
from tutor_bot.bot.task_store import load_task, save_task
from tutor_bot.bot.texts import t
from tutor_bot.db.models import User
from tutor_bot.llm.fake import FakeLLMClient
from tutor_bot.services.solver import Solver
from tutor_bot.services.tasks import MAX_FOLLOWUPS
from tutor_bot.services.tutor import Tutor
from tutor_bot.services.users import register_user

LLM = FakeLLMClient(delay_seconds=0)
SOLVER = Solver(LLM)
TUTOR = Tutor(LLM)


@pytest.fixture
async def user(session: AsyncSession) -> User:
    return await register_user(session, 42, "kid", "ru")


@pytest.fixture
def state() -> FSMContext:
    return FSMContext(MemoryStorage(), StorageKey(bot_id=1, chat_id=42, user_id=42))


@pytest.fixture
def bot() -> MagicMock:
    bot = MagicMock()
    bot.download = AsyncMock()
    bot.send_chat_action = AsyncMock()
    return bot


def make_message(text: str | None = None, caption: str | None = None) -> MagicMock:
    message = MagicMock(spec=Message)
    message.chat = MagicMock(id=42)
    message.text = text
    message.caption = caption
    message.answer = AsyncMock()
    message.edit_text = AsyncMock()
    return message


def make_callback(data: Any, message: MagicMock) -> MagicMock:
    callback = MagicMock()
    callback.message = message
    callback.answer = AsyncMock()
    return callback


def answers(message: MagicMock) -> list[str]:
    return [call.args[0] for call in message.answer.await_args_list]


def last_keyboard_actions(message: MagicMock) -> list[str]:
    markup = message.answer.await_args_list[-1].kwargs["reply_markup"]
    return [
        TaskAction.unpack(button.callback_data).action
        for row in markup.inline_keyboard
        for button in row
    ]


async def send_text(text: str, bot: MagicMock, user: User, state: FSMContext) -> MagicMock:
    message = make_message(text=text)
    if await state.get_state() == TaskStates.waiting_answer.state:
        await on_student_answer(message, bot, user, state, TUTOR)
    else:
        await handle_text(message, bot, user, state, SOLVER, TUTOR)
    return message


async def press(
    action: str, task_id: str, bot: MagicMock, user: User, state: FSMContext
) -> tuple[MagicMock, MagicMock]:
    message = make_message()
    data = TaskAction(action=action, task_id=task_id)
    callback = make_callback(data, message)
    await on_task_action(callback, data, bot, user, state, TUTOR)
    return callback, message


async def test_text_problem_gets_solution_with_buttons(
    bot: MagicMock, user: User, state: FSMContext
) -> None:
    message = await send_text("2x + 3 = 11", bot, user, state)

    [reply] = answers(message)
    assert "<b>📝 Условие</b>" in reply
    assert "<b>✅ Ответ:</b> x = 4" in reply
    assert last_keyboard_actions(message) == [SIMPLER, CHECK, NEW]
    assert await load_task(state) is not None


async def test_photo_is_downloaded_and_starts_new_task(
    bot: MagicMock, user: User, state: FSMContext
) -> None:
    await send_text("2x + 3 = 11", bot, user, state)
    old_task = await load_task(state)
    message = make_message()
    message.photo = [MagicMock(name="small"), MagicMock(name="large")]

    await solve_photo(message, bot, user, state, SOLVER)

    assert bot.download.await_args.args[0] is message.photo[-1]
    new_task = await load_task(state)
    assert old_task is not None and new_task is not None
    assert new_task.task_id != old_task.task_id


async def test_unreadable_photo_keeps_no_task(
    bot: MagicMock, user: User, state: FSMContext
) -> None:
    message = await send_text("fake:unreadable", bot, user, state)

    assert answers(message) == [t("unreadable", "ru")]
    assert await load_task(state) is None


async def test_llm_error_gives_friendly_message(
    bot: MagicMock, user: User, state: FSMContext
) -> None:
    message = await send_text("fake:error", bot, user, state)

    assert answers(message) == [t("llm_unavailable", "ru")]


async def test_long_solution_sent_in_several_messages_buttons_on_last(
    bot: MagicMock, user: User, state: FSMContext
) -> None:
    message = await send_text("fake:long", bot, user, state)

    calls = message.answer.await_args_list
    assert len(calls) > 1
    assert all(len(c.args[0]) <= 4096 for c in calls)
    assert all("reply_markup" not in c.kwargs for c in calls[:-1])
    assert "reply_markup" in calls[-1].kwargs


async def test_explain_simpler_counts_followup(
    bot: MagicMock, user: User, state: FSMContext
) -> None:
    await send_text("2x + 3 = 11", bot, user, state)
    task = await load_task(state)
    assert task is not None

    _, message = await press(SIMPLER, task.task_id, bot, user, state)

    assert "весы" in answers(message)[0]
    task = await load_task(state)
    assert task is not None and task.followups_left == MAX_FOLLOWUPS - 1


async def test_check_answer_flow(bot: MagicMock, user: User, state: FSMContext) -> None:
    await send_text("2x + 3 = 11", bot, user, state)
    task = await load_task(state)
    assert task is not None

    _, prompt = await press(CHECK, task.task_id, bot, user, state)
    assert answers(prompt) == [t("ask_answer", "ru")]
    assert await state.get_state() == TaskStates.waiting_answer.state

    wrong = await send_text("x = 7", bot, user, state)
    assert answers(wrong)[0].startswith("<b>❌ Пока неверно</b>\n\n")
    assert await state.get_state() is None

    await press(CHECK, task.task_id, bot, user, state)
    right = await send_text("x = 4", bot, user, state)
    assert answers(right)[0].startswith("<b>✅ Верно!</b>")


async def test_question_answered_in_task_context(
    bot: MagicMock, user: User, state: FSMContext
) -> None:
    await send_text("2x + 3 = 11", bot, user, state)

    message = await send_text("А почему делим на 2?", bot, user, state)

    assert "делим на 2" in answers(message)[0]
    task = await load_task(state)
    assert task is not None and len(task.history) == 1


async def test_new_problem_instead_of_question_starts_new_task(
    bot: MagicMock, user: User, state: FSMContext
) -> None:
    await send_text("2x + 3 = 11", bot, user, state)
    old_task = await load_task(state)

    message = await send_text("fake:new 5x = 10", bot, user, state)

    assert "<b>📝 Условие</b>" in answers(message)[0]
    new_task = await load_task(state)
    assert old_task is not None and new_task is not None
    assert new_task.task_id != old_task.task_id


async def test_followup_limit(bot: MagicMock, user: User, state: FSMContext) -> None:
    await send_text("2x + 3 = 11", bot, user, state)
    task = await load_task(state)
    assert task is not None
    for _ in range(MAX_FOLLOWUPS - 1):
        await press(SIMPLER, task.task_id, bot, user, state)
    _, message = await press(SIMPLER, task.task_id, bot, user, state)

    # после последнего уточнения осталась только кнопка «Новая задача»
    assert last_keyboard_actions(message) == [NEW]
    _, message = await press(SIMPLER, task.task_id, bot, user, state)
    assert answers(message) == [t("followups_over", "ru")]


async def test_stale_button_does_nothing(bot: MagicMock, user: User, state: FSMContext) -> None:
    await send_text("2x + 3 = 11", bot, user, state)
    task = await load_task(state)
    assert task is not None
    await save_task(state, task.model_copy(update={"task_id": "newer"}))

    callback, message = await press(SIMPLER, task.task_id, bot, user, state)

    callback.answer.assert_awaited_once_with(t("task_closed", "ru"), show_alert=True)
    message.answer.assert_not_awaited()


async def test_new_task_button_clears_task(bot: MagicMock, user: User, state: FSMContext) -> None:
    await send_text("2x + 3 = 11", bot, user, state)
    task = await load_task(state)
    assert task is not None

    _, message = await press(NEW, task.task_id, bot, user, state)

    assert answers(message) == [t("new_task_prompt", "ru")]
    assert await load_task(state) is None


async def test_lang_switch_changes_next_answers(
    bot: MagicMock, user: User, state: FSMContext, session: AsyncSession
) -> None:
    message = make_message()
    data = LangChoice(lang="en")

    await on_lang_choice(make_callback(data, message), data, user, session)

    message.edit_text.assert_awaited_once_with(t("lang_set", "en"))
    reloaded = await session.get(User, 42)
    assert reloaded is not None and reloaded.language == "en"
    reply = await send_text("2x + 3 = 11", bot, user, state)
    assert "<b>📝 Problem</b>" in answers(reply)[0]

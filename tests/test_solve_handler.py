"""Сценарии бота целиком: Telegram замокан, LLM — тестовый режим, FSM — в памяти, БД настоящая."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from tutor_bot.bot.keyboards import CHECK, NEW, SIMPLER, LangChoice, TaskAction
from tutor_bot.bot.routers.lang import on_lang_choice
from tutor_bot.bot.routers.solve import handle_text, solve_photo
from tutor_bot.bot.routers.start import cmd_start
from tutor_bot.bot.routers.task import on_student_answer, on_task_action
from tutor_bot.bot.states import TaskStates
from tutor_bot.bot.task_store import load_task, save_task
from tutor_bot.bot.texts import t
from tutor_bot.db.models import User
from tutor_bot.llm.fake import FakeLLMClient
from tutor_bot.services.assistant import Assistant
from tutor_bot.services.limits import Limits, LimitsConfig
from tutor_bot.services.solver import Solver
from tutor_bot.services.subscriptions import Subscriptions
from tutor_bot.services.tasks import MAX_FOLLOWUPS
from tutor_bot.services.throttle import Throttle
from tutor_bot.services.tutor import Tutor
from tutor_bot.services.users import register_user

LLM = FakeLLMClient(delay_seconds=0)
CONFIG = LimitsConfig(
    free_solutions=15, free_budget_usd=Decimal("100"), paid_budget_usd=Decimal("100")
)


@pytest.fixture
async def user(session: AsyncSession) -> User:
    return await register_user(session, 42, "kid", "ru")


@pytest.fixture
def assistant(session: AsyncSession, redis: Redis) -> Assistant:
    return make_assistant(session, redis, CONFIG)


def make_assistant(session: AsyncSession, redis: Redis, config: LimitsConfig) -> Assistant:
    return Assistant(
        Limits(session, config), Solver(LLM), Tutor(LLM), Throttle(redis, per_minute=1000)
    )


@pytest.fixture
def state() -> FSMContext:
    return FSMContext(MemoryStorage(), StorageKey(bot_id=1, chat_id=42, user_id=42))


@pytest.fixture
def bot() -> MagicMock:
    bot = MagicMock()
    bot.download = AsyncMock()
    bot.send_chat_action = AsyncMock()
    bot.create_invoice_link = AsyncMock(return_value="https://t.me/$invoice")
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


class Chat:
    """Ученик в чате с ботом: всё, что нужно хендлерам, в одном месте."""

    def __init__(
        self,
        bot: MagicMock,
        user: User,
        state: FSMContext,
        assistant: Assistant,
        subscriptions: Subscriptions,
    ):
        self.bot = bot
        self.user = user
        self.state = state
        self.assistant = assistant
        self.subscriptions = subscriptions

    async def send(self, text: str) -> MagicMock:
        message = make_message(text=text)
        if await self.state.get_state() == TaskStates.waiting_answer.state:
            await on_student_answer(
                message, self.bot, self.user, self.state, self.assistant, self.subscriptions
            )
        else:
            await handle_text(
                message, self.bot, self.user, self.state, self.assistant, self.subscriptions
            )
        return message

    async def press(self, action: str, task_id: str) -> tuple[MagicMock, MagicMock]:
        message = make_message()
        data = TaskAction(action=action, task_id=task_id)
        callback = make_callback(data, message)
        await on_task_action(
            callback, data, self.bot, self.user, self.state, self.assistant, self.subscriptions
        )
        return callback, message

    async def task_id(self) -> str:
        task = await load_task(self.state)
        assert task is not None
        return task.task_id


@pytest.fixture
def subscriptions(session: AsyncSession) -> Subscriptions:
    return Subscriptions(session, price_stars=250)


@pytest.fixture
def chat(
    bot: MagicMock,
    user: User,
    state: FSMContext,
    assistant: Assistant,
    subscriptions: Subscriptions,
) -> Chat:
    return Chat(bot, user, state, assistant, subscriptions)


async def test_text_problem_gets_solution_with_buttons(chat: Chat) -> None:
    message = await chat.send("2x + 3 = 11")

    [reply] = answers(message)
    assert "<b>📝 Условие</b>" in reply
    assert "<b>✅ Ответ:</b> x = 4" in reply
    assert last_keyboard_actions(message) == [SIMPLER, CHECK, NEW]
    assert await load_task(chat.state) is not None


async def test_photo_is_downloaded_and_starts_new_task(chat: Chat) -> None:
    await chat.send("2x + 3 = 11")
    old_task_id = await chat.task_id()
    message = make_message()
    message.photo = [MagicMock(name="small"), MagicMock(name="large")]

    await solve_photo(message, chat.bot, chat.user, chat.state, chat.assistant, chat.subscriptions)

    assert chat.bot.download.await_args.args[0] is message.photo[-1]
    assert await chat.task_id() != old_task_id


async def test_unreadable_photo_keeps_no_task(chat: Chat) -> None:
    message = await chat.send("fake:unreadable")

    assert answers(message) == [t("unreadable", "ru")]
    assert await load_task(chat.state) is None


async def test_llm_error_gives_friendly_message(chat: Chat) -> None:
    message = await chat.send("fake:error")

    assert answers(message) == [t("llm_unavailable", "ru")]


async def test_long_solution_sent_in_several_messages_buttons_on_last(chat: Chat) -> None:
    message = await chat.send("fake:long")

    calls = message.answer.await_args_list
    assert len(calls) > 1
    assert all(len(c.args[0]) <= 4096 for c in calls)
    assert all("reply_markup" not in c.kwargs for c in calls[:-1])
    assert "reply_markup" in calls[-1].kwargs


async def test_explain_simpler_counts_followup(chat: Chat) -> None:
    await chat.send("2x + 3 = 11")

    _, message = await chat.press(SIMPLER, await chat.task_id())

    assert "весы" in answers(message)[0]
    task = await load_task(chat.state)
    assert task is not None and task.followups_left == MAX_FOLLOWUPS - 1


async def test_check_answer_flow(chat: Chat) -> None:
    await chat.send("2x + 3 = 11")
    task_id = await chat.task_id()

    _, prompt = await chat.press(CHECK, task_id)
    assert answers(prompt) == [t("ask_answer", "ru")]
    assert await chat.state.get_state() == TaskStates.waiting_answer.state

    wrong = await chat.send("x = 7")
    assert answers(wrong)[0].startswith("<b>❌ Пока неверно</b>\n\n")
    assert await chat.state.get_state() is None

    await chat.press(CHECK, task_id)
    right = await chat.send("x = 4")
    assert answers(right)[0].startswith("<b>✅ Верно!</b>")


async def test_question_answered_in_task_context(chat: Chat) -> None:
    await chat.send("2x + 3 = 11")

    message = await chat.send("А почему делим на 2?")

    assert "делим на 2" in answers(message)[0]
    task = await load_task(chat.state)
    assert task is not None and len(task.history) == 1


async def test_new_problem_instead_of_question_starts_new_task(chat: Chat) -> None:
    await chat.send("2x + 3 = 11")
    old_task_id = await chat.task_id()

    message = await chat.send("fake:new 5x = 10")

    assert "<b>📝 Условие</b>" in answers(message)[0]
    assert await chat.task_id() != old_task_id


async def test_followup_limit(chat: Chat) -> None:
    await chat.send("2x + 3 = 11")
    task_id = await chat.task_id()
    for _ in range(MAX_FOLLOWUPS - 1):
        await chat.press(SIMPLER, task_id)
    _, message = await chat.press(SIMPLER, task_id)

    # после последнего уточнения осталась только кнопка «Новая задача»
    assert last_keyboard_actions(message) == [NEW]
    _, message = await chat.press(SIMPLER, task_id)
    assert answers(message) == [t("followups_over", "ru")]


async def test_stale_button_does_nothing(chat: Chat) -> None:
    await chat.send("2x + 3 = 11")
    task = await load_task(chat.state)
    assert task is not None
    await save_task(chat.state, task.model_copy(update={"task_id": "newer"}))

    callback, message = await chat.press(SIMPLER, task.task_id)

    callback.answer.assert_awaited_once_with(t("task_closed", "ru"), show_alert=True)
    message.answer.assert_not_awaited()


async def test_new_task_button_clears_task(chat: Chat) -> None:
    await chat.send("2x + 3 = 11")

    _, message = await chat.press(NEW, await chat.task_id())

    assert answers(message) == [t("new_task_prompt", "ru")]
    assert await load_task(chat.state) is None


async def test_lang_switch_changes_next_answers(chat: Chat, session: AsyncSession) -> None:
    message = make_message()
    data = LangChoice(lang="en")

    await on_lang_choice(make_callback(data, message), data, chat.user, session)

    message.edit_text.assert_awaited_once_with(t("lang_set", "en"))
    reloaded = await session.get(User, 42)
    assert reloaded is not None and reloaded.language == "en"
    reply = await chat.send("2x + 3 = 11")
    assert "<b>📝 Problem</b>" in answers(reply)[0]


async def test_paywall_after_free_solutions(
    bot: MagicMock,
    user: User,
    state: FSMContext,
    session: AsyncSession,
    redis: Redis,
    subscriptions: Subscriptions,
) -> None:
    config = LimitsConfig(
        free_solutions=2, free_budget_usd=Decimal("100"), paid_budget_usd=Decimal("100")
    )
    chat = Chat(bot, user, state, make_assistant(session, redis, config), subscriptions)

    first = await chat.send("2x + 3 = 11")
    await chat.press(NEW, await chat.task_id())
    second = await chat.send("2x + 3 = 11")
    await chat.press(NEW, await chat.task_id())
    third = await chat.send("2x + 3 = 11")

    assert "Осталось бесплатных решений в этом месяце: 1" in answers(first)[0]
    assert "Осталось бесплатных решений в этом месяце: 0" in answers(second)[0]
    assert answers(third) == [t("paywall_free", "ru")]
    keyboard = third.answer.await_args.kwargs["reply_markup"]
    [[button]] = keyboard.inline_keyboard
    assert button.url == "https://t.me/$invoice"
    invoice = bot.create_invoice_link.await_args.kwargs
    assert invoice["currency"] == "XTR"
    assert invoice["prices"][0].amount == 250
    assert invoice["subscription_period"] == 30 * 24 * 3600


async def test_followups_still_work_after_last_free_solution(
    bot: MagicMock,
    user: User,
    state: FSMContext,
    session: AsyncSession,
    redis: Redis,
    subscriptions: Subscriptions,
) -> None:
    config = LimitsConfig(
        free_solutions=1, free_budget_usd=Decimal("100"), paid_budget_usd=Decimal("100")
    )
    chat = Chat(bot, user, state, make_assistant(session, redis, config), subscriptions)
    await chat.send("2x + 3 = 11")

    _, message = await chat.press(SIMPLER, await chat.task_id())

    assert "весы" in answers(message)[0]


async def test_budget_exhausted_blocks_followups(
    bot: MagicMock,
    user: User,
    state: FSMContext,
    session: AsyncSession,
    redis: Redis,
    subscriptions: Subscriptions,
) -> None:
    # Одно решение в тестовом режиме стоит $0.038 — после него бюджет $0.03 исчерпан
    config = LimitsConfig(
        free_solutions=15, free_budget_usd=Decimal("0.03"), paid_budget_usd=Decimal("100")
    )
    chat = Chat(bot, user, state, make_assistant(session, redis, config), subscriptions)
    await chat.send("2x + 3 = 11")

    _, message = await chat.press(SIMPLER, await chat.task_id())

    assert answers(message) == [t("paywall_free", "ru")]


async def test_busy_user_gets_wait_message(chat: Chat, redis: Redis) -> None:
    await redis.set(f"throttle:busy:{chat.user.id}", "other-request")

    message = await chat.send("2x + 3 = 11")

    assert answers(message) == [t("busy", "ru")]


async def test_start_shows_free_solutions_left(chat: Chat) -> None:
    await chat.send("2x + 3 = 11")
    message = make_message()

    await cmd_start(message, chat.user, chat.assistant, free_total=15)

    assert answers(message)[0].endswith("осталось бесплатных решений: 14 из 15.")


async def test_subscriber_not_limited_by_solution_count(
    bot: MagicMock,
    user: User,
    state: FSMContext,
    session: AsyncSession,
    redis: Redis,
    subscriptions: Subscriptions,
) -> None:
    config = LimitsConfig(
        free_solutions=1, free_budget_usd=Decimal("100"), paid_budget_usd=Decimal("100")
    )
    user.subscription_until = datetime.now(UTC) + timedelta(days=10)
    chat = Chat(bot, user, state, make_assistant(session, redis, config), subscriptions)

    await chat.send("2x + 3 = 11")
    await chat.press(NEW, await chat.task_id())
    second = await chat.send("2x + 3 = 11")

    assert "<b>✅ Ответ:</b> x = 4" in answers(second)[0]
    assert "Осталось бесплатных" not in answers(second)[0]

from collections.abc import Awaitable, Callable

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.chat_action import ChatActionSender

from tutor_bot.bot.keyboards import CHECK, NEW, SIMPLER, TaskAction
from tutor_bot.bot.replies import llm_error_key, send_followup
from tutor_bot.bot.states import TaskStates
from tutor_bot.bot.task_store import clear_task, load_task, save_task
from tutor_bot.bot.texts import t
from tutor_bot.db.models import User
from tutor_bot.llm.client import LLMError
from tutor_bot.services.tutor import FollowUpLimitError, FollowUpReply, Tutor

router = Router(name="task")


@router.callback_query(TaskAction.filter())
async def on_task_action(
    callback: CallbackQuery,
    callback_data: TaskAction,
    bot: Bot,
    user: User,
    state: FSMContext,
    tutor: Tutor,
) -> None:
    lang = user.language
    message = callback.message
    task = await load_task(state)
    if task is None or task.task_id != callback_data.task_id or not isinstance(message, Message):
        await callback.answer(t("task_closed", lang), show_alert=True)
        return
    await callback.answer()

    if callback_data.action == NEW:
        await clear_task(state)
        await message.answer(t("new_task_prompt", lang))
    elif task.followups_left == 0:
        await message.answer(t("followups_over", lang))
    elif callback_data.action == CHECK:
        await state.set_state(TaskStates.waiting_answer)
        await message.answer(t("ask_answer", lang))
    elif callback_data.action == SIMPLER:
        await _run_followup(message, bot, lang, state, lambda: tutor.explain_simpler(lang, task))


@router.message(StateFilter(TaskStates.waiting_answer), F.text & ~F.text.startswith("/"))
async def on_student_answer(
    message: Message, bot: Bot, user: User, state: FSMContext, tutor: Tutor
) -> None:
    assert message.text is not None
    answer = message.text
    lang = user.language
    task = await load_task(state)
    await state.set_state(None)
    if task is None:
        await message.answer(t("task_closed", lang))
        return
    await _run_followup(message, bot, lang, state, lambda: tutor.check_answer(lang, task, answer))


async def _run_followup(
    message: Message,
    bot: Bot,
    lang: str,
    state: FSMContext,
    ask: Callable[[], Awaitable[FollowUpReply]],
) -> None:
    try:
        async with ChatActionSender.typing(bot=bot, chat_id=message.chat.id):
            reply = await ask()
    except FollowUpLimitError:
        await message.answer(t("followups_over", lang))
        return
    except LLMError as e:
        await message.answer(t(llm_error_key(e), lang))
        return
    await save_task(state, reply.task)
    await send_followup(message, reply, lang)

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from tutor_bot.bot.keyboards import CHECK, NEW, SIMPLER, TaskAction
from tutor_bot.bot.replies import run_guarded, send_followup
from tutor_bot.bot.states import TaskStates
from tutor_bot.bot.task_store import clear_task, load_task, save_task
from tutor_bot.bot.texts import t
from tutor_bot.db.models import User
from tutor_bot.services.assistant import Assistant
from tutor_bot.services.subscriptions import Subscriptions

router = Router(name="task")


@router.callback_query(TaskAction.filter())
async def on_task_action(
    callback: CallbackQuery,
    callback_data: TaskAction,
    bot: Bot,
    user: User,
    state: FSMContext,
    assistant: Assistant,
    subscriptions: Subscriptions,
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
        reply = await run_guarded(
            message, bot, user, subscriptions, lambda: assistant.explain_simpler(user, task)
        )
        if reply is not None:
            await save_task(state, reply.task)
            await send_followup(message, reply, lang)


@router.message(StateFilter(TaskStates.waiting_answer), F.text & ~F.text.startswith("/"))
async def on_student_answer(
    message: Message,
    bot: Bot,
    user: User,
    state: FSMContext,
    assistant: Assistant,
    subscriptions: Subscriptions,
) -> None:
    assert message.text is not None
    answer = message.text
    lang = user.language
    task = await load_task(state)
    await state.set_state(None)
    if task is None:
        await message.answer(t("task_closed", lang))
        return
    reply = await run_guarded(
        message, bot, user, subscriptions, lambda: assistant.check_answer(user, task, answer)
    )
    if reply is not None:
        await save_task(state, reply.task)
        await send_followup(message, reply, lang)

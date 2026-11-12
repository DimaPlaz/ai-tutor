from io import BytesIO

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from tutor_bot.bot.replies import run_guarded, send_followup, send_solution
from tutor_bot.bot.task_store import load_task, save_task, start_task
from tutor_bot.bot.texts import t
from tutor_bot.db.models import User
from tutor_bot.llm.client import ImageInput
from tutor_bot.services.assistant import Assistant
from tutor_bot.services.solver import SolutionStatus
from tutor_bot.services.tasks import TaskContext
from tutor_bot.services.tutor import NewProblemDetected

router = Router(name="solve")


@router.message(F.photo)
async def solve_photo(
    message: Message, bot: Bot, user: User, state: FSMContext, assistant: Assistant
) -> None:
    assert message.photo is not None  # гарантирует фильтр F.photo
    # Фото — всегда новая задача. Последний размер в списке — самый крупный
    buffer = BytesIO()
    await bot.download(message.photo[-1], destination=buffer)
    image = ImageInput(data=buffer.getvalue())
    await solve_new_task(message, bot, user, state, assistant, message.caption, image)


@router.message(F.text & ~F.text.startswith("/"))
async def handle_text(
    message: Message, bot: Bot, user: User, state: FSMContext, assistant: Assistant
) -> None:
    assert message.text is not None
    task = await load_task(state)
    if task is None or task.followups_left == 0:
        await solve_new_task(message, bot, user, state, assistant, message.text, None)
        return
    await answer_question(message, bot, user, state, assistant, task, message.text)


async def answer_question(
    message: Message,
    bot: Bot,
    user: User,
    state: FSMContext,
    assistant: Assistant,
    task: TaskContext,
    question: str,
) -> None:
    """Текст при открытой задаче — уточнение. Если это другая задача, решаем её как новую."""
    result = await run_guarded(
        message, bot, user.language, lambda: assistant.answer_question(user, task, question)
    )
    if result is None:
        return
    if isinstance(result, NewProblemDetected):
        await solve_new_task(message, bot, user, state, assistant, question, None)
        return
    await save_task(state, result.task)
    await send_followup(message, result, user.language)


async def solve_new_task(
    message: Message,
    bot: Bot,
    user: User,
    state: FSMContext,
    assistant: Assistant,
    text: str | None,
    image: ImageInput | None,
) -> None:
    lang = user.language
    result = await run_guarded(message, bot, lang, lambda: assistant.solve(user, text, image))
    if result is None:
        return
    if result.solution.status is SolutionStatus.UNREADABLE:
        await message.answer(t("unreadable", lang))
        return
    if result.solution.status is SolutionStatus.NOT_A_PROBLEM or result.task is None:
        await message.answer(t("not_a_problem", lang))
        return

    await start_task(state, result.task)
    free_left = await assistant.remaining_free_solutions(user)
    await send_solution(message, result.solution, result.task, lang, free_left)

from io import BytesIO

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from aiogram.utils.chat_action import ChatActionSender

from tutor_bot.bot.replies import llm_error_key, send_followup, send_solution
from tutor_bot.bot.task_store import load_task, save_task, start_task
from tutor_bot.bot.texts import t
from tutor_bot.db.models import User
from tutor_bot.llm.client import ImageInput, LLMError
from tutor_bot.services.solver import SolutionStatus, Solver
from tutor_bot.services.tasks import TaskContext
from tutor_bot.services.tutor import FollowUpLimitError, NewProblemDetected, Tutor

router = Router(name="solve")


@router.message(F.photo)
async def solve_photo(
    message: Message, bot: Bot, user: User, state: FSMContext, solver: Solver
) -> None:
    assert message.photo is not None  # гарантирует фильтр F.photo
    # Фото — всегда новая задача. Последний размер в списке — самый крупный
    buffer = BytesIO()
    await bot.download(message.photo[-1], destination=buffer)
    image = ImageInput(data=buffer.getvalue())
    await solve_new_task(message, bot, user, state, solver, text=message.caption, image=image)


@router.message(F.text & ~F.text.startswith("/"))
async def handle_text(
    message: Message, bot: Bot, user: User, state: FSMContext, solver: Solver, tutor: Tutor
) -> None:
    assert message.text is not None
    task = await load_task(state)
    if task is None:
        await solve_new_task(message, bot, user, state, solver, text=message.text, image=None)
        return
    await answer_question(message, bot, user, state, solver, tutor, task, message.text)


async def answer_question(
    message: Message,
    bot: Bot,
    user: User,
    state: FSMContext,
    solver: Solver,
    tutor: Tutor,
    task: TaskContext,
    question: str,
) -> None:
    """Текст при открытой задаче — уточнение. Если это другая задача, решаем её как новую."""
    lang = user.language
    if task.followups_left == 0:
        await solve_new_task(message, bot, user, state, solver, text=question, image=None)
        return
    try:
        async with ChatActionSender.typing(bot=bot, chat_id=message.chat.id):
            result = await tutor.answer_question(lang, task, question)
    except FollowUpLimitError:
        await message.answer(t("followups_over", lang))
        return
    except LLMError as e:
        await message.answer(t(llm_error_key(e), lang))
        return

    if isinstance(result, NewProblemDetected):
        await solve_new_task(message, bot, user, state, solver, text=question, image=None)
        return
    await save_task(state, result.task)
    await send_followup(message, result, lang)


async def solve_new_task(
    message: Message,
    bot: Bot,
    user: User,
    state: FSMContext,
    solver: Solver,
    text: str | None,
    image: ImageInput | None,
) -> None:
    lang = user.language
    try:
        async with ChatActionSender.typing(bot=bot, chat_id=message.chat.id):
            solution = await solver.solve(lang, text=text, image=image)
    except LLMError as e:
        await message.answer(t(llm_error_key(e), lang))
        return

    if solution.status is SolutionStatus.UNREADABLE:
        await message.answer(t("unreadable", lang))
        return
    if solution.status is SolutionStatus.NOT_A_PROBLEM:
        await message.answer(t("not_a_problem", lang))
        return

    task = TaskContext.from_solution(solution)
    await start_task(state, task)
    await send_solution(message, solution, task, lang)

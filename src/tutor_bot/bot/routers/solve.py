from io import BytesIO

from aiogram import Bot, F, Router
from aiogram.types import Message
from aiogram.utils.chat_action import ChatActionSender
from sqlalchemy.ext.asyncio import AsyncSession

from tutor_bot.bot.formatting import pack_messages, render_solution
from tutor_bot.bot.texts import t
from tutor_bot.llm.client import (
    ImageInput,
    LLMError,
    LLMRefusalError,
    LLMTruncatedError,
)
from tutor_bot.services.solver import SolutionStatus, Solver
from tutor_bot.services.users import register_user

router = Router(name="solve")


@router.message(F.photo)
async def solve_photo(message: Message, bot: Bot, session: AsyncSession, solver: Solver) -> None:
    assert message.photo is not None  # гарантирует фильтр F.photo
    # Последний размер в списке — самый крупный
    buffer = BytesIO()
    await bot.download(message.photo[-1], destination=buffer)
    image = ImageInput(data=buffer.getvalue())
    await _solve_and_reply(message, bot, session, solver, text=message.caption, image=image)


@router.message(F.text & ~F.text.startswith("/"))
async def solve_text(message: Message, bot: Bot, session: AsyncSession, solver: Solver) -> None:
    await _solve_and_reply(message, bot, session, solver, text=message.text, image=None)


async def _solve_and_reply(
    message: Message,
    bot: Bot,
    session: AsyncSession,
    solver: Solver,
    text: str | None,
    image: ImageInput | None,
) -> None:
    if message.from_user is None:
        return
    tg_user = message.from_user
    user = await register_user(session, tg_user.id, tg_user.username, tg_user.language_code)
    lang = user.language

    try:
        async with ChatActionSender.typing(bot=bot, chat_id=message.chat.id):
            solution = await solver.solve(lang, text=text, image=image)
    except LLMRefusalError:
        await message.answer(t("llm_refused", lang))
        return
    except LLMTruncatedError:
        await message.answer(t("llm_truncated", lang))
        return
    except LLMError:
        await message.answer(t("llm_unavailable", lang))
        return

    if solution.status is SolutionStatus.UNREADABLE:
        await message.answer(t("unreadable", lang))
        return
    if solution.status is SolutionStatus.NOT_A_PROBLEM:
        await message.answer(t("not_a_problem", lang))
        return

    for chunk in pack_messages(render_solution(solution, lang)):
        await message.answer(chunk)

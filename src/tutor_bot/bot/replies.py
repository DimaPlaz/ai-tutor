"""Отправка ответов ученику: решение, уточнение, ошибки LLM."""

from aiogram.types import InlineKeyboardMarkup, Message

from tutor_bot.bot.formatting import pack_messages, render_followup, render_solution
from tutor_bot.bot.keyboards import task_keyboard
from tutor_bot.llm.client import LLMError, LLMRefusalError, LLMTruncatedError
from tutor_bot.services.solver import Solution
from tutor_bot.services.tasks import TaskContext
from tutor_bot.services.tutor import FollowUpReply


def llm_error_key(error: LLMError) -> str:
    if isinstance(error, LLMRefusalError):
        return "llm_refused"
    if isinstance(error, LLMTruncatedError):
        return "llm_truncated"
    return "llm_unavailable"


async def send_solution(message: Message, solution: Solution, task: TaskContext, lang: str) -> None:
    keyboard = task_keyboard(task.task_id, lang, task.followups_left)
    await _send_chunks(message, pack_messages(render_solution(solution, lang)), keyboard)


async def send_followup(message: Message, reply: FollowUpReply, lang: str) -> None:
    keyboard = task_keyboard(reply.task.task_id, lang, reply.task.followups_left)
    chunks = pack_messages(render_followup(reply.text, lang, reply.verdict))
    await _send_chunks(message, chunks, keyboard)


async def _send_chunks(message: Message, chunks: list[str], keyboard: InlineKeyboardMarkup) -> None:
    # Кнопки — только под последним сообщением, чтобы они были рядом с концом ответа
    for chunk in chunks[:-1]:
        await message.answer(chunk)
    await message.answer(chunks[-1], reply_markup=keyboard)

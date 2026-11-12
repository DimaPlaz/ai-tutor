"""Отправка ответов ученику: решение, уточнение, понятные сообщения об ошибках."""

from collections.abc import Awaitable, Callable

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, Message
from aiogram.utils.chat_action import ChatActionSender

from tutor_bot.bot.formatting import pack_messages, render_followup, render_solution
from tutor_bot.bot.keyboards import task_keyboard
from tutor_bot.bot.subscription_ui import paywall_keyboard
from tutor_bot.bot.texts import t
from tutor_bot.db.models import User
from tutor_bot.llm.client import LLMError, LLMRefusalError, LLMTruncatedError
from tutor_bot.services.limits import AccessDeniedError, Denial
from tutor_bot.services.solver import Solution
from tutor_bot.services.subscriptions import Subscriptions
from tutor_bot.services.tasks import TaskContext
from tutor_bot.services.throttle import BusyError, RateLimitedError
from tutor_bot.services.tutor import FollowUpLimitError, FollowUpReply

# Показываем, только когда бесплатных решений осталось совсем мало
FREE_LEFT_HINT_THRESHOLD = 3


def error_key(error: Exception) -> str:
    match error:
        case AccessDeniedError(reason=Denial.PAID_CAP_REACHED):
            return "paywall_paid_cap"
        case AccessDeniedError():
            return "paywall_free"
        case BusyError():
            return "busy"
        case RateLimitedError():
            return "rate_limited"
        case FollowUpLimitError():
            return "followups_over"
        case LLMRefusalError():
            return "llm_refused"
        case LLMTruncatedError():
            return "llm_truncated"
        case _:
            return "llm_unavailable"


async def run_guarded[T](
    message: Message,
    bot: Bot,
    user: User,
    subscriptions: Subscriptions,
    run: Callable[[], Awaitable[T]],
) -> T | None:
    """Запрос к ассистенту с «печатает…». Ожидаемые ошибки — сообщением ученику, результат None."""
    lang = user.language
    try:
        async with ChatActionSender.typing(bot=bot, chat_id=message.chat.id):
            return await run()
    except AccessDeniedError as e:
        keyboard = None
        if e.reason is Denial.FREE_EXHAUSTED:
            keyboard = await paywall_keyboard(bot, user, subscriptions.price_stars)
        await message.answer(t(error_key(e), lang), reply_markup=keyboard)
        return None
    except (LLMError, BusyError, RateLimitedError, FollowUpLimitError) as e:
        await message.answer(t(error_key(e), lang))
        return None


async def send_solution(
    message: Message, solution: Solution, task: TaskContext, lang: str, free_left: int | None
) -> None:
    blocks = render_solution(solution, lang)
    if free_left is not None and free_left <= FREE_LEFT_HINT_THRESHOLD:
        blocks.append(f"<i>{t('free_left_short', lang).format(left=free_left)}</i>")
    keyboard = task_keyboard(task.task_id, lang, task.followups_left)
    await _send_chunks(message, pack_messages(blocks), keyboard)


async def send_followup(message: Message, reply: FollowUpReply, lang: str) -> None:
    keyboard = task_keyboard(reply.task.task_id, lang, reply.task.followups_left)
    chunks = pack_messages(render_followup(reply.text, lang, reply.verdict))
    await _send_chunks(message, chunks, keyboard)


async def _send_chunks(message: Message, chunks: list[str], keyboard: InlineKeyboardMarkup) -> None:
    # Кнопки — только под последним сообщением, чтобы они были рядом с концом ответа
    for chunk in chunks[:-1]:
        await message.answer(chunk)
    await message.answer(chunks[-1], reply_markup=keyboard)

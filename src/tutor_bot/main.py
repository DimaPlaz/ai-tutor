import asyncio
import logging

import anthropic
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import BotCommand
from redis.asyncio import Redis

from tutor_bot.bot.middlewares import AssistantMiddleware, DbSessionMiddleware, UserMiddleware
from tutor_bot.bot.routers import lang, solve, start, task
from tutor_bot.bot.task_store import TASK_TTL
from tutor_bot.bot.texts import t
from tutor_bot.config import get_settings
from tutor_bot.db.session import create_engine, create_session_factory
from tutor_bot.llm.client import JsonCompleter, LLMClient
from tutor_bot.llm.fake import FakeLLMClient
from tutor_bot.logging import setup_logging
from tutor_bot.services.limits import LimitsConfig
from tutor_bot.services.solver import Solver
from tutor_bot.services.throttle import Throttle
from tutor_bot.services.tutor import Tutor

logger = logging.getLogger(__name__)


async def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)

    engine = create_engine(settings.database_url)
    redis = Redis.from_url(settings.redis_url)
    storage = RedisStorage(redis, state_ttl=TASK_TTL, data_ttl=TASK_TTL)
    bot = Bot(
        token=settings.tg_bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    anthropic_client: anthropic.AsyncAnthropic | None = None
    llm: JsonCompleter
    if settings.llm_fake:
        logger.warning("LLM_FAKE=true: answers are canned, Claude API is not called")
        llm = FakeLLMClient()
    else:
        assert settings.anthropic_api_key is not None  # проверено в Settings
        anthropic_client = anthropic.AsyncAnthropic(
            api_key=settings.anthropic_api_key.get_secret_value()
        )
        llm = LLMClient(
            anthropic_client,
            model=settings.llm_model,
            effort=settings.llm_effort,
            max_tokens=settings.llm_max_tokens,
        )

    limits_config = LimitsConfig(
        free_solutions=settings.free_solutions_per_month,
        free_budget_usd=settings.free_budget_usd,
        paid_budget_usd=settings.paid_budget_usd,
    )
    throttle = Throttle(redis, per_minute=settings.rate_limit_per_minute)

    dp = Dispatcher(storage=storage, free_total=settings.free_solutions_per_month)
    dp.update.middleware(DbSessionMiddleware(create_session_factory(engine)))
    dp.update.middleware(UserMiddleware())
    dp.update.middleware(AssistantMiddleware(Solver(llm), Tutor(llm), throttle, limits_config))
    # Порядок важен: команды и ожидание ответа раньше общего обработчика текста
    dp.include_routers(start.router, lang.router, task.router, solve.router)

    await set_commands(bot)

    logger.info("Bot started")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        if anthropic_client is not None:
            await anthropic_client.close()
        await storage.close()  # закрывает и общий клиент Redis
        await engine.dispose()


async def set_commands(bot: Bot) -> None:
    for language in ("ru", "en"):
        commands = [
            BotCommand(command="start", description=t("cmd_start", language)),
            BotCommand(command="lang", description=t("cmd_lang", language)),
        ]
        # Английский — меню по умолчанию для всех остальных языков
        code = None if language == "en" else language
        await bot.set_my_commands(commands, language_code=code)


if __name__ == "__main__":
    asyncio.run(main())

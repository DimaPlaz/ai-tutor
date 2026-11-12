import asyncio
import logging

import anthropic
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage

from tutor_bot.bot.middlewares import DbSessionMiddleware
from tutor_bot.bot.routers import solve, start
from tutor_bot.config import get_settings
from tutor_bot.db.session import create_engine, create_session_factory
from tutor_bot.llm.client import JsonCompleter, LLMClient
from tutor_bot.llm.fake import FakeLLMClient
from tutor_bot.logging import setup_logging
from tutor_bot.services.solver import Solver

logger = logging.getLogger(__name__)


async def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)

    engine = create_engine(settings.database_url)
    storage = RedisStorage.from_url(settings.redis_url)
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

    dp = Dispatcher(storage=storage, solver=Solver(llm))
    dp.update.middleware(DbSessionMiddleware(create_session_factory(engine)))
    dp.include_router(start.router)
    dp.include_router(solve.router)

    logger.info("Bot started")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        if anthropic_client is not None:
            await anthropic_client.close()
        await storage.close()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

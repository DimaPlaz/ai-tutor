import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage

from tutor_bot.bot.middlewares import DbSessionMiddleware
from tutor_bot.bot.routers import start
from tutor_bot.config import get_settings
from tutor_bot.db.session import create_engine, create_session_factory
from tutor_bot.logging import setup_logging

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

    dp = Dispatcher(storage=storage)
    dp.update.middleware(DbSessionMiddleware(create_session_factory(engine)))
    dp.include_router(start.router)

    logger.info("Bot started")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        await storage.close()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

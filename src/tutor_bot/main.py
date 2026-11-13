import asyncio
import logging

import anthropic
import openai
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import PRODUCTION, TEST
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import BotCommand, BotCommandScopeChat
from redis.asyncio import Redis

from tutor_bot.bot.middlewares import DbSessionMiddleware, ServicesMiddleware, UserMiddleware
from tutor_bot.bot.routers import admin, lang, payments, solve, start, task
from tutor_bot.bot.task_store import TASK_TTL
from tutor_bot.bot.texts import t
from tutor_bot.config import get_settings
from tutor_bot.db.session import create_engine, create_session_factory
from tutor_bot.llm.client import JsonCompleter, LLMClient
from tutor_bot.llm.fake import FakeLLMClient
from tutor_bot.llm.openai_compat import OpenAICompatClient
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
    if settings.tg_test_env:
        logger.warning("TG_TEST_ENV=true: using Telegram test environment")
    bot = Bot(
        token=settings.bot_token,
        session=AiohttpSession(api=TEST if settings.tg_test_env else PRODUCTION),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    sdk_client: anthropic.AsyncAnthropic | openai.AsyncOpenAI | None = None
    llm: JsonCompleter
    if settings.llm_fake:
        logger.warning("LLM_FAKE=true: answers are canned, Claude API is not called")
        llm = FakeLLMClient()
    elif settings.llm_provider == "openai":
        assert settings.anthropic_api_key is not None  # проверено в Settings
        logger.warning("LLM_PROVIDER=openai: Claude via OpenAI-compatible proxy")
        sdk_client = openai.AsyncOpenAI(
            api_key=settings.anthropic_api_key.get_secret_value(),
            base_url=settings.llm_base_url,
        )
        llm = OpenAICompatClient(
            sdk_client,
            model=settings.llm_model,
            effort=settings.llm_effort,
            max_tokens=settings.llm_max_tokens,
        )
    else:
        assert settings.anthropic_api_key is not None  # проверено в Settings
        anthropic_client = anthropic.AsyncAnthropic(
            api_key=settings.anthropic_api_key.get_secret_value()
        )
        sdk_client = anthropic_client
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

    dp = Dispatcher(
        storage=storage,
        free_total=settings.free_solutions_per_month,
        support_contact=settings.support_contact,
        admin_ids=settings.admin_ids,
    )
    dp.update.middleware(DbSessionMiddleware(create_session_factory(engine)))
    dp.update.middleware(UserMiddleware())
    dp.update.middleware(
        ServicesMiddleware(
            Solver(llm),
            Tutor(llm),
            throttle,
            limits_config,
            price_stars=settings.subscription_price_stars,
        )
    )
    # Порядок важен: команды и ожидание ответа раньше общего обработчика текста
    dp.include_routers(
        admin.router, start.router, lang.router, payments.router, task.router, solve.router
    )

    await set_commands(bot, settings.admin_ids)

    logger.info("Bot started")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        if sdk_client is not None:
            await sdk_client.close()
        await storage.close()  # закрывает и общий клиент Redis
        await engine.dispose()


def user_commands(language: str) -> list[BotCommand]:
    return [
        BotCommand(command="start", description=t("cmd_start", language)),
        BotCommand(command="lang", description=t("cmd_lang", language)),
        BotCommand(command="subscription", description=t("cmd_subscription", language)),
        BotCommand(command="terms", description=t("cmd_terms", language)),
        BotCommand(command="paysupport", description=t("cmd_paysupport", language)),
    ]


def admin_commands(language: str) -> list[BotCommand]:
    return [
        *user_commands(language),
        BotCommand(command="stats", description=t("cmd_stats", language)),
        BotCommand(command="grant", description=t("cmd_grant", language)),
        BotCommand(command="refund", description=t("cmd_refund", language)),
    ]


async def set_commands(bot: Bot, admin_ids: list[int]) -> None:
    for language in ("ru", "en"):
        # Английский — меню по умолчанию для всех остальных языков
        code = None if language == "en" else language
        await bot.set_my_commands(user_commands(language), language_code=code)
        # Админ-команды видны только в чатах админов
        for admin_id in admin_ids:
            try:
                await bot.set_my_commands(
                    admin_commands(language),
                    scope=BotCommandScopeChat(chat_id=admin_id),
                    language_code=code,
                )
            except TelegramAPIError:
                # Например, админ ещё не открывал чат с ботом
                logger.warning("Failed to set admin commands for %s", admin_id)


if __name__ == "__main__":
    asyncio.run(main())

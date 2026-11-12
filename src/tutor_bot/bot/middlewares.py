from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from aiogram.types import User as TgUser
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tutor_bot.services.assistant import Assistant
from tutor_bot.services.limits import Limits, LimitsConfig
from tutor_bot.services.solver import Solver
from tutor_bot.services.subscriptions import Subscriptions
from tutor_bot.services.throttle import Throttle
from tutor_bot.services.tutor import Tutor
from tutor_bot.services.users import register_user


class DbSessionMiddleware(BaseMiddleware):
    """Открывает сессию БД на каждый апдейт и передаёт её в хендлер как `session`."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        async with self._session_factory() as session:
            data["session"] = session
            return await handler(event, data)


class UserMiddleware(BaseMiddleware):
    """Регистрирует пользователя и передаёт его в хендлер как `user`.

    Ставится после DbSessionMiddleware: нужна `session`.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user: TgUser | None = data.get("event_from_user")
        if tg_user is None or tg_user.is_bot:
            return await handler(event, data)
        data["user"] = await register_user(
            data["session"], tg_user.id, tg_user.username, tg_user.language_code
        )
        return await handler(event, data)


class ServicesMiddleware(BaseMiddleware):
    """Собирает сервисы на сессии БД текущего апдейта: `assistant`, `limits`, `subscriptions`."""

    def __init__(
        self,
        solver: Solver,
        tutor: Tutor,
        throttle: Throttle,
        limits_config: LimitsConfig,
        price_stars: int,
    ) -> None:
        self._solver = solver
        self._tutor = tutor
        self._throttle = throttle
        self._limits_config = limits_config
        self._price_stars = price_stars

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        session = data["session"]
        limits = Limits(session, self._limits_config)
        data["limits"] = limits
        data["assistant"] = Assistant(limits, self._solver, self._tutor, self._throttle)
        data["subscriptions"] = Subscriptions(session, self._price_stars)
        return await handler(event, data)

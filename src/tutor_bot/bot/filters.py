from typing import Any

from aiogram.filters import BaseFilter
from aiogram.types import TelegramObject
from aiogram.types import User as TgUser


class IsAdmin(BaseFilter):
    """Пропускает только пользователей из ADMIN_IDS (`admin_ids` в данных диспетчера)."""

    async def __call__(self, event: TelegramObject, **data: Any) -> bool:
        tg_user: TgUser | None = data.get("event_from_user")
        admin_ids: list[int] = data.get("admin_ids", [])
        return tg_user is not None and tg_user.id in admin_ids

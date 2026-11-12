import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tutor_bot.db.models import User
from tutor_bot.services.users import detect_language, register_user


@pytest.mark.parametrize(
    ("code", "expected"),
    [("ru", "ru"), ("ru-RU", "ru"), ("en", "en"), ("EN-us", "en"), ("de", "en"), (None, "en")],
)
def test_detect_language(code: str | None, expected: str) -> None:
    assert detect_language(code) == expected


async def test_register_creates_user(session: AsyncSession) -> None:
    user = await register_user(session, 100, "kid", "ru")

    assert (user.id, user.username, user.language) == (100, "kid", "ru")


async def test_register_twice_does_not_duplicate(session: AsyncSession) -> None:
    await register_user(session, 100, "kid", "ru")
    await register_user(session, 100, "kid", "ru")

    count = await session.scalar(select(func.count()).select_from(User))
    assert count == 1


async def test_register_keeps_language_but_updates_username(session: AsyncSession) -> None:
    await register_user(session, 100, "kid", "ru")

    user = await register_user(session, 100, "new_nick", "en")

    assert user.language == "ru"
    assert user.username == "new_nick"

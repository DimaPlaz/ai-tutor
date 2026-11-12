from sqlalchemy.ext.asyncio import AsyncSession

from tutor_bot.db.models import User
from tutor_bot.db.repositories.users import UserRepository

SUPPORTED_LANGUAGES = ("ru", "en")
DEFAULT_LANGUAGE = "en"


def detect_language(language_code: str | None) -> str:
    if not language_code:
        return DEFAULT_LANGUAGE
    lang = language_code.split("-")[0].lower()
    return lang if lang in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE


async def register_user(
    session: AsyncSession, user_id: int, username: str | None, language_code: str | None
) -> User:
    """Создаёт пользователя при первом /start.

    Язык существующего пользователя не трогаем: его меняют через /lang.
    """
    repo = UserRepository(session)
    user = await repo.get(user_id)
    if user is None:
        user = await repo.add(
            User(id=user_id, username=username, language=detect_language(language_code))
        )
    elif user.username != username:
        user.username = username
    await session.commit()
    return user

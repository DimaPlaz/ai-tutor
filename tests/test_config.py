from pathlib import Path

import pytest

from tutor_bot.config import Settings


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # Не читаем настоящий .env разработчика
    monkeypatch.chdir(tmp_path)
    for name in ("TG_BOT_TOKEN", "ADMIN_IDS", "DATABASE_URL", "REDIS_URL", "LOG_LEVEL"):
        monkeypatch.delenv(name, raising=False)


def test_admin_ids_parsed_from_comma_separated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TG_BOT_TOKEN", "x")
    monkeypatch.setenv("ADMIN_IDS", "1, 22,333")

    assert Settings().admin_ids == [1, 22, 333]  # pyright: ignore[reportCallIssue]


def test_admin_ids_empty_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TG_BOT_TOKEN", "x")
    monkeypatch.setenv("ADMIN_IDS", "")

    assert Settings().admin_ids == []  # pyright: ignore[reportCallIssue]


def test_token_hidden_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TG_BOT_TOKEN", "secret-token")

    assert "secret-token" not in repr(Settings())  # pyright: ignore[reportCallIssue]

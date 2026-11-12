from pathlib import Path

import pytest
from pydantic import ValidationError

from tutor_bot.config import Settings

OPTIONAL_ENV = (
    "ADMIN_IDS",
    "DATABASE_URL",
    "REDIS_URL",
    "LOG_LEVEL",
    "LLM_MODEL",
    "LLM_EFFORT",
    "LLM_FAKE",
)


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # Не читаем настоящий .env разработчика
    monkeypatch.chdir(tmp_path)
    for name in OPTIONAL_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("TG_BOT_TOKEN", "x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "y")


def test_admin_ids_parsed_from_comma_separated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_IDS", "1, 22,333")

    assert Settings().admin_ids == [1, 22, 333]  # pyright: ignore[reportCallIssue]


def test_admin_ids_empty_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_IDS", "")

    assert Settings().admin_ids == []  # pyright: ignore[reportCallIssue]


def test_secrets_hidden_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TG_BOT_TOKEN", "secret-token")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secret")

    text = repr(Settings())  # pyright: ignore[reportCallIssue]

    assert "secret-token" not in text
    assert "sk-ant-secret" not in text


def test_llm_defaults() -> None:
    settings = Settings()  # pyright: ignore[reportCallIssue]

    assert settings.llm_model == "claude-opus-5-5"
    assert settings.llm_effort == "medium"


def test_api_key_required_without_fake_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY")

    with pytest.raises(ValidationError, match="ANTHROPIC_API_KEY"):
        Settings()  # pyright: ignore[reportCallIssue]


def test_fake_mode_works_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    monkeypatch.setenv("LLM_FAKE", "true")

    settings = Settings()  # pyright: ignore[reportCallIssue]

    assert settings.llm_fake
    assert settings.anthropic_api_key is None

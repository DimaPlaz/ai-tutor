from decimal import Decimal
from typing import Annotated, Literal

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    tg_bot_token: SecretStr
    # Тестовая среда Telegram (бесплатные Stars): отдельный бот от тестового @BotFather
    tg_test_env: bool = False
    tg_test_bot_token: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None
    # Тестовый режим: заготовленные ответы вместо Claude API, ключ не нужен
    llm_fake: bool = False
    # openai — Claude через OpenAI-совместимый прокси (LLM_BASE_URL), ключ тот же ANTHROPIC_API_KEY
    llm_provider: Literal["anthropic", "openai"] = "anthropic"
    llm_base_url: str | None = None
    llm_model: str = "claude-opus-5-5"
    llm_effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    llm_max_tokens: int = 16000
    free_solutions_per_month: int = 15
    # Скрытые потолки расходов на LLM за календарный месяц (UTC), в $
    free_budget_usd: Decimal = Decimal("0.90")
    paid_budget_usd: Decimal = Decimal("2")
    subscription_price_stars: int = 250
    # Контакт для /paysupport, например @username
    support_contact: str
    rate_limit_per_minute: int = 6
    database_url: str = "postgresql+asyncpg://tutor:tutor@localhost:5432/tutor"
    redis_url: str = "redis://localhost:6379/0"
    # NoDecode: принимаем "1,2,3" из .env, а не только JSON-список
    admin_ids: Annotated[list[int], NoDecode] = []
    log_level: str = "INFO"

    @field_validator("admin_ids", mode="before")
    @classmethod
    def _parse_admin_ids(cls, value: object) -> object:
        if isinstance(value, str):
            return [int(part) for part in value.split(",") if part.strip()]
        return value

    @model_validator(mode="after")
    def _require_api_key(self) -> Settings:
        if not self.llm_fake and self.anthropic_api_key is None:
            raise ValueError("ANTHROPIC_API_KEY is required unless LLM_FAKE=true")
        if self.llm_provider == "openai" and self.llm_base_url is None:
            raise ValueError("LLM_BASE_URL is required when LLM_PROVIDER=openai")
        if self.tg_test_env and self.tg_test_bot_token is None:
            raise ValueError("TG_TEST_BOT_TOKEN is required when TG_TEST_ENV=true")
        return self

    @property
    def bot_token(self) -> str:
        token = self.tg_test_bot_token if self.tg_test_env else self.tg_bot_token
        assert token is not None  # проверено в _require_api_key
        return token.get_secret_value()


def get_settings() -> Settings:
    return Settings()  # pyright: ignore[reportCallIssue]

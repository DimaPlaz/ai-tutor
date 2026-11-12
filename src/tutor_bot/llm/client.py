import base64
import logging
from dataclasses import dataclass
from typing import Any, Protocol

import anthropic
from anthropic.types.beta import (
    BetaFallbackMessageIterationUsage,
    BetaMessage,
    BetaMessageIterationUsage,
)

from tutor_bot.llm.pricing import TokenUsage

logger = logging.getLogger(__name__)

# Если классификатор безопасности отклонит запрос, API сам повторит его на запасной модели
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLMError(Exception):
    """Базовая ошибка вызова LLM: пользователю — понятное сообщение, лимит не списываем."""


class LLMRefusalError(LLMError):
    pass


class LLMTruncatedError(LLMError):
    pass


class LLMUnavailableError(LLMError):
    pass


@dataclass(frozen=True, slots=True)
class LLMResponse:
    text: str
    model: str
    usages: list[TokenUsage]
    request_id: str | None


@dataclass(frozen=True, slots=True)
class ImageInput:
    data: bytes
    media_type: str = "image/jpeg"


class JsonCompleter(Protocol):
    async def complete_json(
        self, system: str, text: str, schema: dict[str, Any], image: ImageInput | None = None
    ) -> LLMResponse: ...


class LLMClient:
    def __init__(
        self,
        client: anthropic.AsyncAnthropic,
        model: str,
        effort: str,
        max_tokens: int,
    ) -> None:
        self._client = client
        self._model = model
        self._effort = effort
        self._max_tokens = max_tokens

    async def complete_json(
        self, system: str, text: str, schema: dict[str, Any], image: ImageInput | None = None
    ) -> LLMResponse:
        content: list[dict[str, Any]] = []
        if image is not None:
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": image.media_type,
                        "data": base64.standard_b64encode(image.data).decode("ascii"),
                    },
                }
            )
        content.append({"type": "text", "text": text})

        try:
            message = await self._client.beta.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=system,
                messages=[{"role": "user", "content": content}],  # pyright: ignore[reportArgumentType]
                output_config={
                    "effort": self._effort,  # pyright: ignore[reportArgumentType]
                    "format": {"type": "json_schema", "schema": schema},
                },
                fallbacks="default",
                betas=[FALLBACK_BETA],
            )
        except anthropic.APIStatusError as e:
            logger.error("LLM API error status=%s request_id=%s", e.status_code, e.request_id)
            raise LLMUnavailableError from e
        except anthropic.APIConnectionError as e:
            # Сюда же попадает APITimeoutError
            logger.error("LLM connection error: %s", type(e).__name__)
            raise LLMUnavailableError from e

        return self._parse(message)

    def _parse(self, message: BetaMessage) -> LLMResponse:
        usages = _collect_usages(message)
        request_id: str | None = getattr(message, "_request_id", None)
        if message.stop_reason == "refusal":
            category = message.stop_details.category if message.stop_details else None
            logger.warning("LLM refusal category=%s request_id=%s", category, request_id)
            raise LLMRefusalError(usages)
        if message.stop_reason == "max_tokens":
            logger.warning("LLM hit max_tokens request_id=%s", request_id)
            raise LLMTruncatedError(usages)

        # При fallback перед ответом идёт блок "fallback"; JSON — в последнем текстовом блоке
        texts = [block.text for block in message.content if block.type == "text"]
        if not texts:
            raise LLMUnavailableError("no text block in response")
        return LLMResponse(
            text=texts[-1], model=message.model, usages=usages, request_id=request_id
        )


def _collect_usages(message: BetaMessage) -> list[TokenUsage]:
    """Токены по каждой попытке: при fallback платим и за отклонённую, и за запасную модель."""
    usage = message.usage
    if usage.iterations:
        return [
            TokenUsage(
                model=item.model or message.model,
                input_tokens=item.input_tokens,
                output_tokens=item.output_tokens,
                cache_read_tokens=item.cache_read_input_tokens or 0,
                cache_write_tokens=item.cache_creation_input_tokens or 0,
            )
            for item in usage.iterations
            if isinstance(item, BetaMessageIterationUsage | BetaFallbackMessageIterationUsage)
        ]
    return [
        TokenUsage(
            model=message.model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_tokens=usage.cache_read_input_tokens or 0,
            cache_write_tokens=usage.cache_creation_input_tokens or 0,
        )
    ]

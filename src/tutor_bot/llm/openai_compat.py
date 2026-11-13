import base64
import logging
from typing import Any

import openai
from openai.types.chat import ChatCompletion

from tutor_bot.llm.client import (
    ImageInput,
    LLMRefusalError,
    LLMResponse,
    LLMTruncatedError,
    LLMUnavailableError,
)
from tutor_bot.llm.pricing import TokenUsage

logger = logging.getLogger(__name__)


class OpenAICompatClient:
    """Claude через OpenAI-совместимый прокси (временный режим, пока нет ключа Anthropic).

    В отличие от LLMClient, здесь нет серверного fallback на запасную модель.
    """

    def __init__(
        self,
        client: openai.AsyncOpenAI,
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
            data = base64.standard_b64encode(image.data).decode("ascii")
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{image.media_type};base64,{data}"},
                }
            )
        content.append({"type": "text", "text": text})

        try:
            completion = await self._client.chat.completions.create(
                model=self._model,
                max_completion_tokens=self._max_tokens,
                reasoning_effort=self._effort,  # pyright: ignore[reportArgumentType]
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": content},  # pyright: ignore[reportArgumentType]
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": "answer", "schema": schema},
                },
            )
        except openai.APIStatusError as e:
            logger.error("LLM API error status=%s request_id=%s", e.status_code, e.request_id)
            raise LLMUnavailableError from e
        except openai.APIConnectionError as e:
            # Сюда же попадает APITimeoutError
            logger.error("LLM connection error: %s", type(e).__name__)
            raise LLMUnavailableError from e

        return self._parse(completion)

    def _parse(self, completion: ChatCompletion) -> LLMResponse:
        usages = _collect_usages(completion)
        request_id = completion.id
        if not completion.choices:
            raise LLMUnavailableError("no choices in response", usages)
        choice = completion.choices[0]
        if choice.finish_reason == "content_filter":
            logger.warning("LLM refusal request_id=%s", request_id)
            raise LLMRefusalError("refusal", usages)
        if choice.finish_reason == "length":
            logger.warning("LLM hit max_tokens request_id=%s", request_id)
            raise LLMTruncatedError("max_tokens", usages)

        text = choice.message.content
        if not text:
            raise LLMUnavailableError("no text in response", usages)
        return LLMResponse(text=text, model=completion.model, usages=usages, request_id=request_id)


def _collect_usages(completion: ChatCompletion) -> list[TokenUsage]:
    usage = completion.usage
    if usage is None:
        return []
    details = usage.prompt_tokens_details
    cache_read = (details.cached_tokens if details else None) or 0
    cache_write = (details.cache_write_tokens if details else None) or 0
    # prompt_tokens в OpenAI-формате уже включает кэшированные токены
    return [
        TokenUsage(
            model=completion.model,
            input_tokens=max(usage.prompt_tokens - cache_read - cache_write, 0),
            output_tokens=usage.completion_tokens,
            cache_read_tokens=cache_read,
            cache_write_tokens=cache_write,
        )
    ]

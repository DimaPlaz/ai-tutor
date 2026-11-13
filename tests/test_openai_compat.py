from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx2
import openai
import pytest
from openai.types.chat import ChatCompletion

from tutor_bot.llm.client import (
    ImageInput,
    LLMRefusalError,
    LLMTruncatedError,
    LLMUnavailableError,
)
from tutor_bot.llm.openai_compat import OpenAICompatClient
from tutor_bot.llm.pricing import TokenUsage

MODEL = "anthropic/claude-opus-5-5"
SCHEMA: dict[str, Any] = {"type": "object"}


def make_completion(
    finish_reason: str = "stop",
    content: str | None = "{}",
    usage: dict[str, Any] | None = None,
) -> ChatCompletion:
    return ChatCompletion.model_validate(
        {
            "id": "chatcmpl-1",
            "object": "chat.completion",
            "created": 0,
            "model": MODEL,
            "choices": [
                {
                    "index": 0,
                    "finish_reason": finish_reason,
                    "message": {"role": "assistant", "content": content},
                }
            ],
            "usage": usage or {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        }
    )


def make_client(result: ChatCompletion | Exception) -> tuple[OpenAICompatClient, AsyncMock]:
    create = AsyncMock(side_effect=[result])
    sdk = MagicMock()
    sdk.chat.completions.create = create
    return OpenAICompatClient(sdk, model=MODEL, effort="medium", max_tokens=16000), create


async def test_sends_image_schema_and_effort() -> None:
    llm, create = make_client(make_completion())

    await llm.complete_json("sys", "solve", SCHEMA, image=ImageInput(data=b"\xff\xd8"))

    assert create.await_args is not None
    kwargs = create.await_args.kwargs
    system, user = kwargs["messages"]
    assert system == {"role": "system", "content": "sys"}
    image, text = user["content"]
    assert image["type"] == "image_url"
    assert image["image_url"]["url"] == "data:image/jpeg;base64,/9g="
    assert text == {"type": "text", "text": "solve"}
    assert kwargs["model"] == MODEL
    assert kwargs["reasoning_effort"] == "medium"
    assert kwargs["max_completion_tokens"] == 16000
    assert kwargs["response_format"]["json_schema"]["schema"] == SCHEMA


async def test_returns_text_and_usage() -> None:
    llm, _ = make_client(make_completion(content='{"ok": true}'))

    response = await llm.complete_json("sys", "solve", SCHEMA)

    assert response.text == '{"ok": true}'
    assert response.model == MODEL
    assert response.usages == [TokenUsage(MODEL, 100, 50)]


async def test_cached_tokens_split_from_prompt_tokens() -> None:
    usage = {
        "prompt_tokens": 1000,
        "completion_tokens": 50,
        "total_tokens": 1050,
        "prompt_tokens_details": {"cached_tokens": 600, "cache_write_tokens": 300},
    }
    llm, _ = make_client(make_completion(usage=usage))

    response = await llm.complete_json("sys", "solve", SCHEMA)

    assert response.usages == [TokenUsage(MODEL, 100, 50, 600, 300)]


async def test_content_filter_raises_refusal_with_usage() -> None:
    llm, _ = make_client(make_completion(finish_reason="content_filter", content=None))

    with pytest.raises(LLMRefusalError) as exc:
        await llm.complete_json("sys", "solve", SCHEMA)

    assert exc.value.usages == [TokenUsage(MODEL, 100, 50)]


async def test_length_raises_truncated() -> None:
    llm, _ = make_client(make_completion(finish_reason="length"))

    with pytest.raises(LLMTruncatedError):
        await llm.complete_json("sys", "solve", SCHEMA)


async def test_empty_content_raises_unavailable() -> None:
    llm, _ = make_client(make_completion(content=None))

    with pytest.raises(LLMUnavailableError):
        await llm.complete_json("sys", "solve", SCHEMA)


async def test_connection_error_raises_unavailable() -> None:
    error = openai.APIConnectionError(request=httpx2.Request("POST", "https://api.test"))
    llm, _ = make_client(error)

    with pytest.raises(LLMUnavailableError):
        await llm.complete_json("sys", "solve", SCHEMA)


async def test_api_status_error_raises_unavailable() -> None:
    request = httpx2.Request("POST", "https://api.test")
    error = openai.PermissionDeniedError(
        "denied", response=httpx2.Response(403, request=request), body=None
    )
    llm, _ = make_client(error)

    with pytest.raises(LLMUnavailableError):
        await llm.complete_json("sys", "solve", SCHEMA)

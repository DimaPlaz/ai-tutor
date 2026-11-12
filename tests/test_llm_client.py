import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import anthropic
import httpx2
import pytest
from anthropic.types.beta import BetaMessage

from tutor_bot.llm.client import (
    FALLBACK_BETA,
    ImageInput,
    LLMClient,
    LLMRefusalError,
    LLMTruncatedError,
    LLMUnavailableError,
)
from tutor_bot.llm.pricing import TokenUsage

SCHEMA: dict[str, Any] = {"type": "object"}
NO_CACHE = {"cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}


def make_message(
    stop_reason: str = "end_turn",
    content: list[dict[str, Any]] | None = None,
    usage: dict[str, Any] | None = None,
    stop_details: dict[str, Any] | None = None,
) -> BetaMessage:
    return BetaMessage.model_validate(
        {
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": "claude-opus-5-5",
            "content": content if content is not None else [{"type": "text", "text": "{}"}],
            "stop_reason": stop_reason,
            "stop_sequence": None,
            "stop_details": stop_details,
            "usage": usage or {"input_tokens": 100, "output_tokens": 50},
        }
    )


def make_client(result: BetaMessage | Exception) -> tuple[LLMClient, AsyncMock]:
    create = AsyncMock(side_effect=[result])
    sdk = MagicMock()
    sdk.beta.messages.create = create
    return LLMClient(sdk, model="claude-opus-5-5", effort="medium", max_tokens=16000), create


async def test_sends_image_schema_and_fallbacks() -> None:
    llm, create = make_client(make_message())

    await llm.complete_json("sys", "solve", SCHEMA, image=ImageInput(data=b"\xff\xd8"))

    assert create.await_args is not None
    kwargs = create.await_args.kwargs
    content = kwargs["messages"][0]["content"]
    assert content[0]["type"] == "image"
    assert content[0]["source"]["media_type"] == "image/jpeg"
    assert content[1] == {"type": "text", "text": "solve"}
    assert kwargs["model"] == "claude-opus-5-5"
    assert kwargs["output_config"]["format"] == {"type": "json_schema", "schema": SCHEMA}
    assert kwargs["output_config"]["effort"] == "medium"
    assert kwargs["fallbacks"] == "default"
    assert kwargs["betas"] == [FALLBACK_BETA]


async def test_returns_text_and_usage() -> None:
    payload = json.dumps({"ok": True})
    llm, _ = make_client(make_message(content=[{"type": "text", "text": payload}]))

    response = await llm.complete_json("sys", "solve", SCHEMA)

    assert response.text == payload
    assert response.usages == [TokenUsage("claude-opus-5-5", 100, 50)]


async def test_fallback_usage_taken_per_attempt() -> None:
    usage = {
        "input_tokens": 100,
        "output_tokens": 50,
        "iterations": [
            {"type": "message", "model": "claude-opus-5-5", "input_tokens": 100,
             "output_tokens": 0, **NO_CACHE},
            {"type": "fallback_message", "model": "claude-opus-4-8", "input_tokens": 100,
             "output_tokens": 50, **NO_CACHE},
        ],
    }  # fmt: skip
    content = [
        {"type": "fallback", "from": {"model": "claude-opus-5-5"},
         "to": {"model": "claude-opus-4-8"},
         "trigger": {"type": "refusal", "category": None}},
        {"type": "text", "text": "{}"},
    ]  # fmt: skip
    llm, _ = make_client(make_message(content=content, usage=usage))

    response = await llm.complete_json("sys", "solve", SCHEMA)

    assert [u.model for u in response.usages] == ["claude-opus-5-5", "claude-opus-4-8"]
    assert response.text == "{}"


async def test_refusal_raises() -> None:
    message = make_message(
        stop_reason="refusal",
        content=[],
        stop_details={"type": "refusal", "category": None, "explanation": None},
    )
    llm, _ = make_client(message)

    with pytest.raises(LLMRefusalError):
        await llm.complete_json("sys", "solve", SCHEMA)


async def test_max_tokens_raises() -> None:
    llm, _ = make_client(make_message(stop_reason="max_tokens"))

    with pytest.raises(LLMTruncatedError):
        await llm.complete_json("sys", "solve", SCHEMA)


async def test_connection_error_raises_unavailable() -> None:
    error = anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.test"))
    llm, _ = make_client(error)

    with pytest.raises(LLMUnavailableError):
        await llm.complete_json("sys", "solve", SCHEMA)


async def test_api_status_error_raises_unavailable() -> None:
    request = httpx2.Request("POST", "https://api.test")
    error = anthropic.InternalServerError(
        "boom", response=httpx2.Response(500, request=request), body=None
    )
    llm, _ = make_client(error)

    with pytest.raises(LLMUnavailableError):
        await llm.complete_json("sys", "solve", SCHEMA)

"""Тестовый режим (LLM_FAKE=true): заготовленные ответы без обращения к Claude API.

Кодовые слова в тексте или подписи к фото переключают сценарий, чтобы проверить
все ветки бота в Telegram: fake:unreadable, fake:not_a_problem, fake:refusal,
fake:max_tokens, fake:error, fake:long.
"""

import asyncio
import json
from typing import Any

from tutor_bot.llm.client import (
    ImageInput,
    LLMRefusalError,
    LLMResponse,
    LLMTruncatedError,
    LLMUnavailableError,
)
from tutor_bot.llm.prompts import solve_system_prompt

FAKE_MODEL = "fake"

_SOLUTIONS = {
    "ru": {
        "problem": "Решить уравнение: 2x + 3 = 11",
        "steps": [
            "Перенесём 3 в правую часть с противоположным знаком: 2x = 11 − 3.",
            "Посчитаем правую часть: 11 − 3 = 8, значит 2x = 8.",
            "Разделим обе части на 2: x = 8 ÷ 2 = 4.",
            "Проверка: 2 · 4 + 3 = 11 ✓",
        ],
        "answer": "x = 4",
    },
    "en": {
        "problem": "Solve the equation: 2x + 3 = 11",
        "steps": [
            "Move 3 to the right side with the opposite sign: 2x = 11 − 3.",
            "Calculate the right side: 11 − 3 = 8, so 2x = 8.",
            "Divide both sides by 2: x = 8 ÷ 2 = 4.",
            "Check: 2 · 4 + 3 = 11 ✓",
        ],
        "answer": "x = 4",
    },
}


class FakeLLMClient:
    def __init__(self, delay_seconds: float = 1.5) -> None:
        self._delay = delay_seconds

    async def complete_json(
        self, system: str, text: str, schema: dict[str, Any], image: ImageInput | None = None
    ) -> LLMResponse:
        await asyncio.sleep(self._delay)  # чтобы было видно «печатает…»
        command = text.lower()
        if "fake:refusal" in command:
            raise LLMRefusalError([])
        if "fake:max_tokens" in command:
            raise LLMTruncatedError([])
        if "fake:error" in command:
            raise LLMUnavailableError("fake error")

        if "fake:unreadable" in command:
            payload = _empty("unreadable")
        elif "fake:not_a_problem" in command:
            payload = _empty("not_a_problem")
        else:
            lang = "ru" if system == solve_system_prompt("ru") else "en"
            payload = {"status": "ok", **_SOLUTIONS[lang]}
            if "fake:long" in command:
                payload["steps"] = [f"{step} " * 40 for step in payload["steps"]] * 5

        return LLMResponse(
            text=json.dumps(payload, ensure_ascii=False),
            model=FAKE_MODEL,
            usages=[],
            request_id=None,
        )


def _empty(status: str) -> dict[str, Any]:
    return {"status": status, "problem": "", "steps": [], "answer": ""}

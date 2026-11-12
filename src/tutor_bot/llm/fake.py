"""Тестовый режим (LLM_FAKE=true): заготовленные ответы без обращения к Claude API.

Кодовые слова в тексте или подписи к фото переключают сценарий, чтобы проверить
все ветки бота в Telegram: fake:unreadable, fake:not_a_problem, fake:refusal,
fake:max_tokens, fake:error, fake:long.
Уточнения: ответ с «4» при проверке считается верным; вопрос с fake:new — это новая задача.
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
from tutor_bot.llm.pricing import TokenUsage
from tutor_bot.llm.prompts import followup_system_prompt, solve_system_prompt

FAKE_MODEL = "fake"

# Правдоподобный расход как у Opus 5.5 (~$0.04 решение, ~$0.014 уточнение),
# чтобы лимиты по бюджету можно было проверить без ключа
_SOLVE_USAGE = TokenUsage("claude-opus-5-5", input_tokens=2_000, output_tokens=1_500)
_FOLLOWUP_USAGE = TokenUsage("claude-opus-5-5", input_tokens=1_500, output_tokens=400)

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

_FOLLOWUPS = {
    "ru": {
        "simpler": (
            "Представь весы: слева 2 одинаковые коробки и 3 яблока, справа 11 яблок.\n\n"
            "Уберём 3 яблока с обеих сторон — весы останутся в равновесии: "
            "2 коробки = 8 яблок.\n\n"
            "Значит, в одной коробке 8 ÷ 2 = 4 яблока. Это и есть x = 4."
        ),
        "correct": "Ты нашёл x = 4 — всё правильно. Отличная работа!",
        "incorrect": (
            "Проверь шаг, где переносишь 3 вправо: знак меняется на минус, "
            "получается 11 − 3 = 8. Попробуй ещё раз."
        ),
        "question": (
            "Мы делим на 2, потому что x умножен на 2. "
            "Деление — обратное действие к умножению, оно «отменяет» двойку."
        ),
    },
    "en": {
        "simpler": (
            "Picture a balance: 2 identical boxes and 3 apples on the left, "
            "11 apples on the right.\n\n"
            "Take 3 apples off both sides — it still balances: 2 boxes = 8 apples.\n\n"
            "So one box holds 8 ÷ 2 = 4 apples. That's x = 4."
        ),
        "correct": "You found x = 4 — that's right. Great job!",
        "incorrect": (
            "Check the step where you move 3 to the right: the sign flips to minus, "
            "so it's 11 − 3 = 8. Try again."
        ),
        "question": (
            "We divide by 2 because x is multiplied by 2. "
            "Division is the opposite of multiplication, so it 'undoes' the 2."
        ),
    },
}


class FakeLLMClient:
    def __init__(self, delay_seconds: float = 1.5) -> None:
        self._delay = delay_seconds

    async def complete_json(
        self, system: str, text: str, schema: dict[str, Any], image: ImageInput | None = None
    ) -> LLMResponse:
        await asyncio.sleep(self._delay)  # чтобы было видно «печатает…»
        fields = set(schema["properties"])
        lang = "ru" if system in (solve_system_prompt("ru"), followup_system_prompt("ru")) else "en"
        # Кодовые слова ищем только в последнем вводе ученика, а не во всём контексте
        if "status" in fields:
            student_input = text
        elif "verdict" in fields:
            student_input = _between(text, "student_answer")
        elif "is_new_problem" in fields:
            student_input = _between(text, "student_message")
        else:
            student_input = ""
        command = student_input.lower()

        if "fake:refusal" in command:
            raise LLMRefusalError("fake refusal")
        if "fake:max_tokens" in command:
            raise LLMTruncatedError("fake max_tokens", [_FOLLOWUP_USAGE])
        if "fake:error" in command:
            raise LLMUnavailableError("fake error")

        if "status" in fields:
            payload = _solve_payload(command, lang)
        elif "verdict" in fields:
            correct = "4" in command
            payload = {
                "verdict": "correct" if correct else "incorrect",
                "explanation": _FOLLOWUPS[lang]["correct" if correct else "incorrect"],
            }
        elif "is_new_problem" in fields:
            is_new = "fake:new" in command
            payload = {
                "is_new_problem": is_new,
                "reply": "" if is_new else _FOLLOWUPS[lang]["question"],
            }
        else:
            payload = {"explanation": _FOLLOWUPS[lang]["simpler"]}

        return LLMResponse(
            text=json.dumps(payload, ensure_ascii=False),
            model=FAKE_MODEL,
            usages=[_SOLVE_USAGE if "status" in fields else _FOLLOWUP_USAGE],
            request_id=None,
        )


def _solve_payload(command: str, lang: str) -> dict[str, Any]:
    if "fake:unreadable" in command:
        return _empty("unreadable")
    if "fake:not_a_problem" in command:
        return _empty("not_a_problem")
    payload: dict[str, Any] = {"status": "ok", **_SOLUTIONS[lang]}
    if "fake:long" in command:
        payload["steps"] = [f"{step} " * 40 for step in payload["steps"]] * 5
    return payload


def _empty(status: str) -> dict[str, Any]:
    return {"status": status, "problem": "", "steps": [], "answer": ""}


def _between(text: str, tag: str) -> str:
    start = text.find(f"<{tag}>")
    end = text.find(f"</{tag}>")
    return text[start + len(tag) + 2 : end].strip() if start != -1 and end != -1 else ""

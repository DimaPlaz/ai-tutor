from html import escape

from tutor_bot.bot.texts import t
from tutor_bot.services.solver import Solution
from tutor_bot.services.tutor import Verdict

TELEGRAM_MESSAGE_LIMIT = 4096


def render_solution(solution: Solution, lang: str) -> list[str]:
    """HTML-блоки решения. Текст модели экранируем: разметку добавляем только сами."""
    blocks = [f"<b>{t('solution_problem', lang)}</b>\n{escape(solution.problem, quote=False)}"]
    blocks.append(f"<b>{t('solution_steps', lang)}</b>")
    blocks.extend(
        f"<b>{i}.</b> {escape(step, quote=False)}" for i, step in enumerate(solution.steps, 1)
    )
    blocks.append(f"<b>{t('solution_answer', lang)}</b> {escape(solution.answer, quote=False)}")
    return blocks


def pack_messages(blocks: list[str], limit: int = TELEGRAM_MESSAGE_LIMIT) -> list[str]:
    """Собирает блоки в сообщения не длиннее limit, разделяя их пустой строкой."""
    messages: list[str] = []
    current = ""
    for block in blocks:
        for piece in _split_block(block, limit):
            candidate = f"{current}\n\n{piece}" if current else piece
            if len(candidate) <= limit:
                current = candidate
            else:
                messages.append(current)
                current = piece
    if current:
        messages.append(current)
    return messages


def _split_block(block: str, limit: int) -> list[str]:
    # Режем только по переносам строк и пробелам: наши теги стоят в начале блока
    # и не содержат пробелов внутри, поэтому разрез их не порвёт
    pieces: list[str] = []
    rest = block
    while len(rest) > limit:
        cut = rest.rfind("\n", 0, limit + 1)
        if cut <= 0:
            cut = rest.rfind(" ", 0, limit + 1)
        if cut <= 0:
            cut = _safe_hard_cut(rest, limit)
            pieces.append(rest[:cut])
            rest = rest[cut:]
            continue
        pieces.append(rest[:cut])
        rest = rest[cut + 1 :]
    if rest:
        pieces.append(rest)
    return pieces


def _safe_hard_cut(text: str, limit: int) -> int:
    """Позиция разреза длинного слова без пробелов, не внутри HTML-сущности вроде &amp;."""
    amp = text.rfind("&", 0, limit)
    if amp > 0 and text.find(";", amp, limit) == -1:
        return amp
    return limit


VERDICT_KEYS = {
    Verdict.CORRECT: "verdict_correct",
    Verdict.PARTIAL: "verdict_partial",
    Verdict.INCORRECT: "verdict_incorrect",
}


def render_followup(text: str, lang: str, verdict: Verdict | None = None) -> list[str]:
    blocks = [f"<b>{t(VERDICT_KEYS[verdict], lang)}</b>"] if verdict else []
    # Абзацы — отдельные блоки, чтобы длинный ответ резался по ним
    blocks += [escape(part, quote=False) for part in text.split("\n\n") if part.strip()]
    return blocks

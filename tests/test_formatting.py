from decimal import Decimal

from tutor_bot.bot.formatting import TELEGRAM_MESSAGE_LIMIT, pack_messages, render_solution
from tutor_bot.services.solver import Solution, SolutionStatus


def _solution(steps: list[str], problem: str = "2 + 2 = ?", answer: str = "4") -> Solution:
    return Solution(
        status=SolutionStatus.OK,
        problem=problem,
        steps=steps,
        answer=answer,
        model="claude-opus-5-5",
        usages=[],
        cost_usd=Decimal(0),
    )


def test_render_escapes_model_text() -> None:
    blocks = render_solution(_solution(["a < b & c > d"], problem="<b>x</b>"), "ru")
    html = "\n".join(blocks)

    assert "a &lt; b &amp; c &gt; d" in html
    assert "&lt;b&gt;x&lt;/b&gt;" in html


def test_render_numbers_steps_and_answer_last() -> None:
    blocks = render_solution(_solution(["first", "second"]), "en")

    assert blocks[2] == "<b>1.</b> first"
    assert blocks[3] == "<b>2.</b> second"
    assert blocks[-1] == "<b>✅ Answer:</b> 4"


def test_short_solution_fits_one_message() -> None:
    messages = pack_messages(render_solution(_solution(["one", "two"]), "ru"))

    assert len(messages) == 1


def test_long_solution_split_by_blocks() -> None:
    steps = ["x" * 1000 + f" step {i}" for i in range(12)]
    blocks = render_solution(_solution(steps), "ru")

    messages = pack_messages(blocks)

    assert len(messages) > 1
    assert all(len(m) <= TELEGRAM_MESSAGE_LIMIT for m in messages)
    # каждый блок целиком попал в какое-то сообщение — теги не порваны
    for block in blocks:
        assert any(block in m for m in messages)


def test_huge_block_split_by_words_without_losing_text() -> None:
    words = [f"w{i}" for i in range(3000)]
    block = " ".join(words)

    messages = pack_messages([block], limit=500)

    assert all(len(m) <= 500 for m in messages)
    assert " ".join(messages).split() == words


def test_word_longer_than_limit_does_not_cut_entity() -> None:
    block = "a" * 98 + "&amp;" + "b" * 50

    messages = pack_messages([block], limit=100)

    assert all(len(m) <= 100 for m in messages)
    assert "".join(messages) == block
    assert "&amp;" in messages[1]

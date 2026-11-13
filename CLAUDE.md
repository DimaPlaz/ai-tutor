# AI Tutor Bot

Telegram-бот: решает школьные задачи по фото/тексту с объяснением, бесплатный лимит в месяц, дальше подписка за Telegram Stars.
Полное ТЗ, этапы и чек-лист — в `SPEC.md`. Это источник правды по функциональности.

## Как работаем
- Идём строго по этапам из `SPEC.md`, по одному этапу за раз.
- Перед этапом — короткий план (файлы, модели БД, что тестируем), жди подтверждения.
- Этап закончен, когда выполнен его критерий готовности, тесты и линтеры зелёные. Тогда отметь его в чек-листе `SPEC.md` и предложи коммит.
- Не делай то, что в ТЗ помечено «вне MVP», без явной просьбы.
- Если в ТЗ чего-то не хватает или есть противоречие — спроси, не додумывай.

## Стек
Python 3.14, pip + venv (зависимости в `pyproject.toml`), aiogram 3, PostgreSQL + SQLAlchemy 2 (async) + Alembic, Redis, Anthropic SDK, pydantic-settings, pytest, ruff, pyright, Docker Compose.

## Структура
```
src/tutor_bot/
  main.py            # точка входа: бот, роутеры, polling
  config.py          # Settings (pydantic-settings), всё из .env
  bot/               # aiogram: роутеры, клавиатуры, middleware, тексты RU/EN
  services/          # бизнес-логика: solver, limits, subscriptions, stats
  llm/               # клиент Anthropic, промпты, расчёт стоимости
  db/                # модели, репозитории, сессия
migrations/          # Alembic
tests/
```
Хендлеры aiogram тонкие: только разбор входа и ответ. Вся логика — в `services/`, чтобы её можно было тестировать без Telegram.

## Команды
```bash
python3.14 -m venv venv && source venv/bin/activate
pip install -e ".[dev]"
docker compose up -d db redis
alembic upgrade head
python -m tutor_bot.main
pytest
ruff check . && ruff format . && pyright
```

## Стиль кода
- Аннотации типов везде. `X | None` вместо `Optional`, `list`/`dict`/`str` вместо `typing.List`/`Dict`/`Text`.
- async везде, где есть I/O.
- Небольшие функции, понятные имена, комментарии только там, где неочевидно «почему».
- Не добавлять зависимости без необходимости.

## LLM
- Только официальный Anthropic SDK (`anthropic`). Исключение — временный режим `LLM_PROVIDER=openai` (`llm/openai_compat.py`): Claude через OpenAI-совместимый прокси, пока нет ключа Anthropic; там нет серверного fallback. Перед написанием кода работы с API используй скилл `claude-api`, не пиши вызовы по памяти.
- Модель — из `LLM_MODEL` в `.env`, не хардкодить.
- Всегда проверяй `stop_reason` (`refusal`, `max_tokens`) до чтения ответа. Ошибка или отказ — понятное сообщение пользователю, лимит не списывается.
- Промпты — в `llm/prompts.py`, отдельно от кода. Пиши их для школьника: по шагам, простыми словами, ответ отдельной строкой, формулы Unicode-текстом без LaTeX, разметка Telegram HTML.
- На каждый вызов сохраняй токены (`usage`) и стоимость в $.

## Платежи (Telegram Stars)
- Начисление подписки — только по `successful_payment`, идемпотентно по `telegram_payment_charge_id` (уникальный индекс в БД).
- Начисление и запись платежа — в одной транзакции.
- Никогда не доверять данным из callback-кнопок для начисления.

## Безопасность
- Секреты только в `.env`, в репозитории только `.env.example`.
- Админ-команды проверяют `ADMIN_IDS`.
- Не логировать токены, ключи и полный текст платёжных событий.

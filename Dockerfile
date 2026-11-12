FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Сначала только метаданные — слой с зависимостями кешируется, пока не менялся pyproject.toml
COPY pyproject.toml README.md ./
RUN mkdir -p src/tutor_bot && touch src/tutor_bot/__init__.py && pip install . \
    && pip uninstall -y tutor-bot

COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./
RUN pip install --no-deps .

RUN useradd --create-home --uid 1000 app
USER app

CMD ["python", "-m", "tutor_bot.main"]

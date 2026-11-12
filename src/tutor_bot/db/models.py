from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    false,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from tutor_bot.db.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    username: Mapped[str | None] = mapped_column(String(64))
    language: Mapped[str] = mapped_column(String(2))
    # Подписка за Stars: до какого момента оплачена и продлевается ли автоматически
    subscription_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    subscription_auto_renew: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false()
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class LlmCall(Base):
    """Один вызов LLM: для лимитов (решения и бюджет за месяц) и для статистики расходов."""

    __tablename__ = "llm_calls"
    __table_args__ = (Index("ix_llm_calls_user_id_created_at", "user_id", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))
    task_id: Mapped[str | None] = mapped_column(String(16))
    kind: Mapped[str] = mapped_column(String(16))
    model: Mapped[str] = mapped_column(String(64))
    input_tokens: Mapped[int] = mapped_column(Integer)
    output_tokens: Mapped[int] = mapped_column(Integer)
    cache_read_tokens: Mapped[int] = mapped_column(Integer)
    cache_write_tokens: Mapped[int] = mapped_column(Integer)
    # NULL, если для модели нет цены в llm/pricing.py
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    # True — вызов засчитан как решение из месячного лимита
    charged: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Payment(Base):
    """Платёж Stars. Уникальный charge_id делает начисление идемпотентным."""

    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))
    telegram_payment_charge_id: Mapped[str] = mapped_column(String(255), unique=True)
    provider_payment_charge_id: Mapped[str] = mapped_column(String(255))
    amount: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(8))
    is_recurring: Mapped[bool] = mapped_column(Boolean)
    is_first_recurring: Mapped[bool] = mapped_column(Boolean)
    # До какого момента продлил подписку этот платёж
    paid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    refunded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

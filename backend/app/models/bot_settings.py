import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class BotSettings(Base):
    __tablename__ = "bot_settings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    platform_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trading_platforms.id")
    )
    is_running: Mapped[bool] = mapped_column(Boolean, default=True)
    interval_seconds: Mapped[int] = mapped_column(Integer, default=300)
    max_trades_per_day: Mapped[int] = mapped_column(Integer, default=10)
    risk_percent: Mapped[float] = mapped_column(Numeric(5, 2), default=1.0)
    sl_points: Mapped[float] = mapped_column(Numeric(10, 2), default=300)
    tp_points: Mapped[float] = mapped_column(Numeric(10, 2), default=600)
    pause_max_retries: Mapped[int] = mapped_column(Integer, default=5)
    pause_retry_sec: Mapped[int] = mapped_column(Integer, default=10)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

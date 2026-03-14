import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AiAnalysisLog(Base):
    __tablename__ = "ai_analysis_log"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    ai_provider_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai_providers.id"), index=True
    )
    platform_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trading_platforms.id")
    )
    symbol: Mapped[str] = mapped_column(String(30), nullable=False)
    bid: Mapped[float | None] = mapped_column(Numeric(16, 8))
    ask: Mapped[float | None] = mapped_column(Numeric(16, 8))
    ai_recommendation: Mapped[str | None] = mapped_column(String, nullable=True)
    sentiment: Mapped[str | None] = mapped_column(String(20))
    trade_action: Mapped[str] = mapped_column(String(10), default="WAIT")
    lot_size: Mapped[float | None] = mapped_column(Numeric(12, 6))
    sl_price: Mapped[float | None] = mapped_column(Numeric(16, 8))
    tp_price: Mapped[float | None] = mapped_column(Numeric(16, 8))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    correlation_id: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )

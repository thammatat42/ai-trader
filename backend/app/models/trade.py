import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    platform_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trading_platforms.id"), index=True
    )
    order_id: Mapped[str | None] = mapped_column(String(100))
    symbol: Mapped[str] = mapped_column(String(30), nullable=False)
    action: Mapped[str] = mapped_column(String(10), nullable=False)
    lot: Mapped[float] = mapped_column(Numeric(12, 6), nullable=False)
    open_price: Mapped[float | None] = mapped_column(Numeric(16, 8))
    close_price: Mapped[float | None] = mapped_column(Numeric(16, 8))
    sl_price: Mapped[float | None] = mapped_column(Numeric(16, 8))
    tp_price: Mapped[float | None] = mapped_column(Numeric(16, 8))
    profit: Mapped[float | None] = mapped_column(Numeric(16, 4))
    commission: Mapped[float | None] = mapped_column(Numeric(12, 4))
    swap: Mapped[float | None] = mapped_column(Numeric(12, 4))
    status: Mapped[str] = mapped_column(String(20), default="OPEN", index=True)
    ai_provider_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai_providers.id")
    )
    ai_analysis_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        # Composite unique: same order on same platform
        # Using Index instead of UniqueConstraint to allow NULLs
    )

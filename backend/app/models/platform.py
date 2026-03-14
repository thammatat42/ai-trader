import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, LargeBinary, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class TradingPlatform(Base):
    __tablename__ = "trading_platforms"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    platform_type: Mapped[str] = mapped_column(String(50), nullable=False)
    endpoint_url: Mapped[str | None] = mapped_column(String(500))
    api_key_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    api_secret_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    config_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    market_hours: Mapped[str] = mapped_column(String(50), default="24h")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class AIUsageLog(Base):
    """Logs AI usage (OpenRouter/Local LLM) for cost tracking and analytics."""

    __tablename__ = 'ai_usage_logs'

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey('users.id', ondelete='SET NULL'), index=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey('organizations.id', ondelete='CASCADE'),
        index=True,
    )

    model_name: Mapped[str] = mapped_column(String(255))
    provider: Mapped[str | None] = mapped_column(String(100))

    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)

    estimated_cost_usd: Mapped[float | None] = mapped_column(Float)
    cost_is_estimated: Mapped[bool] = mapped_column(
        default=False, server_default='false'
    )

    action_type: Mapped[str | None] = mapped_column(String(100))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True
    )

    user: Mapped['User'] = relationship(backref='ai_usage_history')  # type: ignore[name-defined]
    organization: Mapped['Organization'] = relationship(backref='ai_usage_history')  # type: ignore[name-defined]

"""SQLAlchemy model for the AI Connections pool.

Each row is a named, reusable LLM/provider configuration owned by one
organization. Modules bind their declared *purposes* (e.g. ``vision.extract``,
``recipes.text_parse``) to one of these rows via
``organization.settings.ai.defaults[<purpose>]`` — one slot per purpose key,
whatever the owner module. The module-scoped
``settings.modules.<module>.ai_default_connection_id`` is the legacy home of
choices made before per-purpose slots: it still reads as a fallback, and the
first re-bind carries it across.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AiConnection(Base):
    """A pooled set of provider credentials and model parameters.

    Notable column choices:

    - ``provider`` is stored as a plain varchar (``String(50)``) rather than
      a Postgres ENUM type. New providers can be added by extending
      :class:`app.core.llm.enums.LlmProvider` without an Alembic migration.
    - ``api_key_enc`` is always non-null; the empty string means "no key"
      (e.g. a local LM Studio install without authentication). This matches
      :func:`app.services.crypto_service.encrypt_value` semantics.
    - ``temperature``/``max_tokens``/``top_p`` are nullable so that
      ``NULL`` means "use provider SDK default" — never encode a sentinel
      like ``-1`` or ``0``.
    - ``capabilities`` is ``list[str]`` JSONB; runtime resolution checks
      ``purpose.capability in connection.capabilities`` so adding new
      tags (embedding, TTS) is a no-op at the schema layer.
    """

    __tablename__ = 'ai_connections'

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey('organizations.id', ondelete='CASCADE'),
        index=True,
        nullable=False,
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)

    api_key_enc: Mapped[str] = mapped_column(String, nullable=False, default='')
    api_base_url: Mapped[str] = mapped_column(String(512), nullable=False, default='')
    model_name: Mapped[str] = mapped_column(String(255), nullable=False, default='')

    temperature: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    top_p: Mapped[float | None] = mapped_column(Float, nullable=True)

    capabilities: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)

    #: What the connection test found out, per capability:
    #: ``{"vision": {"ok": false, "at": "2026-08-27T…", "purpose": "vision.extract"}}``.
    #:
    #: ``capabilities`` is a claim — somebody ticked a box, or the form ticked
    #: it for them off the provider's name. This is the answer to whether the
    #: model actually did the job when asked, which is a different question and
    #: was being thrown away: the probe ran, judged the answer, and told nobody
    #: but the toast. A capability absent here has never been tested; present
    #: with ``ok: false`` failed the last time it was.
    capability_checks: Mapped[dict[str, dict]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default='{}'
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            'organization_id',
            'name',
            name='uq_ai_connections_org_name',
        ),
    )

    def __repr__(self) -> str:
        return (
            f'<AiConnection id={self.id} org={self.organization_id} '
            f'provider={self.provider!r} name={self.name!r}>'
        )

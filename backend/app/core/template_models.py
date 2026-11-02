"""Core DocumentTemplate model — shared across equipment, documents, purchase_orders modules."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class DocumentTemplate(Base):
    """User-configurable document templates stored in the database.

    Each template belongs to a module (``equipment``, ``documents``, ``purchase_orders``)
    and has a ``document_type`` discriminator that is module-specific (plain string, no enum).
    The ``is_default`` field is constrained to one default per ``(organization_id, module, document_type)``.
    """

    __tablename__ = 'document_templates'
    __table_args__ = (
        Index('ix_doc_templates_org_module', 'organization_id', 'module'),
        {
            'keep_existing': True,
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE'),
        index=True,
    )
    module: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    document_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default='DEFAULT',
    )
    body_html: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    version: Mapped[int] = mapped_column(
        default=1,
        nullable=False,
    )
    # Where a copied built-in came from, and what it looked like at the
    # time. A copy belongs to the organization and is never touched by an
    # upgrade — but an organization that copied a layout in 2026 and has been
    # printing it ever since had no way to find out that the built-in it came
    # from has moved on. ``None`` on a template written from scratch.
    source_builtin: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    source_checksum: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    is_default: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        # Stamped in Python, not by ``now()``: Postgres' now() is the
        # transaction's start, so templates created in one transaction (the
        # built-in seeding, which is one by design now) would all carry the
        # same instant and the newest-first list would have no order to sort
        # by. Microseconds from datetime.now separate them.
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        onupdate=lambda: datetime.now(UTC),
    )

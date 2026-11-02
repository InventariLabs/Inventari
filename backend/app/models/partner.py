import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    false,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Partner(Base):
    """
    Core entity representing a business partner (supplier, customer, etc.).
    Partners are owned by an organisation but are not module-specific —
    they can be referenced by Items, Equipment, Orders, etc.
    """

    __tablename__ = 'partners'
    __table_args__ = (
        UniqueConstraint(
            'organization_id', 'name', 'type', name='uq_partner_org_name_type'
        ),
        # Partial unique index: (organization_id, code) WHERE code IS NOT NULL
        Index(
            'uq_partner_org_code',
            'organization_id',
            'code',
            unique=True,
            postgresql_where=text('code IS NOT NULL'),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE'),
        index=True,
        nullable=False,
    )

    # --- Identification ---
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    type: Mapped[str] = mapped_column(
        String(30), nullable=False
    )  # SUPPLIER | CUSTOMER | BOTH | SERVICE_PROVIDER | MANUFACTURER | EMPLOYEE
    tax_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # A private person: someone with no tax id to give, whom a country's
    # tax-id requirement on documents does not reach.
    is_consumer: Mapped[bool] = mapped_column(
        Boolean, server_default=false(), nullable=False
    )

    # --- Contact ---
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    website: Mapped[str | None] = mapped_column(String(500), nullable=True)
    contact_person: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # --- Address (flexible JSONB — avoids rigid schema changes) ---
    address: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # --- Internal notes ---
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Status ---
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, index=True, nullable=False
    )

    # --- Audit ---
    created_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('users.id', ondelete='SET NULL'), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    # --- Relationships ---
    items: Mapped[list['Item']] = relationship(  # type: ignore[name-defined]
        'Item',
        back_populates='partner',
        lazy='dynamic',
        foreign_keys='Item.partner_id',
    )

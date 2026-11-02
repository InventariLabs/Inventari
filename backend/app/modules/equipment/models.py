import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db_facade import Base


class EquipmentAttachment(Base):
    """File attachments for equipment assets (invoices, warranties, photos, manuals)."""

    __tablename__ = 'equipment_attachments'
    __table_args__ = (
        Index('ix_eq_attachments_org_item', 'organization_id', 'item_id'),
        {'keep_existing': True},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE'),
        index=True,
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('items.id', ondelete='CASCADE'),
        index=True,
    )

    file_path: Mapped[str] = mapped_column(String(500))
    original_name: Mapped[str] = mapped_column(String(255))
    file_type: Mapped[str] = mapped_column(
        String(30)
    )  # INVOICE | WARRANTY | PHOTO | MANUAL | OTHER
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(default=0)

    uploaded_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('users.id', ondelete='SET NULL')
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class EquipmentAssignment(Base):
    """Check-out / check-in tracking for equipment assets."""

    __tablename__ = 'equipment_assignments'
    __table_args__ = (
        Index('ix_eq_assignments_org_item', 'organization_id', 'item_id'),
        Index(
            'uq_eq_assignments_active_per_item',
            'item_id',
            unique=True,
            postgresql_where=text('checked_in_at IS NULL'),
        ),
        {'keep_existing': True},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE'),
        index=True,
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('items.id', ondelete='CASCADE'),
        index=True,
    )

    # Assignee — optional link to a Partner (type=EMPLOYEE or other)
    assignee_partner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('partners.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )

    # Checkout to location (alternative to person assignment)
    checkout_location_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('storage_locations.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )

    # Assignee info (free-text fallback — supports external names without partner records)
    assigned_to_name: Mapped[str] = mapped_column(String(255))
    assigned_to_email: Mapped[str | None] = mapped_column(String(255))

    # Timeline
    checked_out_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    expected_return_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    checked_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Operators
    checked_out_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('users.id', ondelete='SET NULL')
    )
    checked_in_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('users.id', ondelete='SET NULL')
    )

    # Notes
    checkout_notes: Mapped[str | None] = mapped_column(Text)
    checkin_notes: Mapped[str | None] = mapped_column(Text)
    checkin_condition: Mapped[str | None] = mapped_column(
        String(30)
    )  # GOOD | DAMAGED | NEEDS_REPAIR

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    # Relationships
    item: Mapped['Item'] = relationship(lazy='selectin')  # type: ignore[name-defined]
    assignee_partner: Mapped['Partner | None'] = relationship(lazy='selectin')  # type: ignore[name-defined]
    checkout_location: Mapped['StorageLocation | None'] = relationship(lazy='selectin')  # type: ignore[name-defined]


class EquipmentMaintenanceLog(Base):
    """Service history entries for equipment assets."""

    __tablename__ = 'equipment_maintenance_logs'
    __table_args__ = (
        Index('ix_eq_maintenance_org_item', 'organization_id', 'item_id'),
        {'keep_existing': True},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE'),
        index=True,
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('items.id', ondelete='CASCADE'),
        index=True,
    )

    # Type and description
    maintenance_type: Mapped[str] = mapped_column(
        String(30)
    )  # REPAIR | CLEANING | UPGRADE | INSPECTION | OTHER
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)

    # Cost
    cost: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    currency: Mapped[str | None] = mapped_column(String(3))

    # Who and when
    performed_at: Mapped[date] = mapped_column(Date)
    performed_by: Mapped[str | None] = mapped_column(String(255))
    service_partner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('partners.id', ondelete='SET NULL'),
        nullable=True,
    )
    next_maintenance_at: Mapped[date | None] = mapped_column(Date)

    # Audit
    created_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('users.id', ondelete='SET NULL')
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    # Relationships
    item: Mapped['Item'] = relationship(lazy='selectin')  # type: ignore[name-defined]


class AuditCampaign(Base):
    """Periodic asset verification campaign."""

    __tablename__ = 'audit_campaigns'
    __table_args__ = (
        Index('ix_audit_campaigns_org', 'organization_id'),
        {'keep_existing': True},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE'),
        index=True,
    )

    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)

    # Scope: ALL | STORAGE | CATEGORY
    scope_type: Mapped[str] = mapped_column(String(20), default='ALL')
    scope_filter_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)

    # Timeline
    launched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # `deadline` is a DAY, not a moment. Nobody ever shows the clock
    # half — the scheduler counts whole days, the e-mail prints the date, and
    # a client that sent midnight would expire every token the moment the day
    # began. `create_campaign` pins the contract on write: the stored value is
    # the end of the deadline's own day, in the deadline's own timezone
    # (23:59:59.999999). Read it as "last day to answer", never as a time.
    deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reminder_days_before: Mapped[int] = mapped_column(default=3)
    last_reminder_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    # Status: DRAFT | ACTIVE | COMPLETED | CANCELLED
    status: Mapped[str] = mapped_column(String(20), default='DRAFT')

    # Custom email content
    email_subject: Mapped[str | None] = mapped_column(String(255))
    email_body: Mapped[str | None] = mapped_column(Text)

    created_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('users.id', ondelete='SET NULL')
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    responses: Mapped[list['AuditResponse']] = relationship(
        back_populates='campaign', cascade='all, delete-orphan', lazy='selectin'
    )


class AuditResponse(Base):
    """Individual assignee response within an audit campaign."""

    __tablename__ = 'audit_responses'
    __table_args__ = (
        Index('ix_audit_responses_campaign_status', 'campaign_id', 'status'),
        {'keep_existing': True},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('audit_campaigns.id', ondelete='CASCADE'),
        index=True,
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE'),
        index=True,
    )
    assignment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('equipment_assignments.id', ondelete='CASCADE'),
        nullable=True,  # grouped responses bind items instead
        index=True,
    )

    assignee_email: Mapped[str] = mapped_column(String(255))
    assignee_name: Mapped[str] = mapped_column(String(255))

    # Secure zero-login token
    token: Mapped[str] = mapped_column(String(86), unique=True, index=True)
    token_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    # Response: PENDING | CONFIRMED | DISPUTED | EXPIRED
    status: Mapped[str] = mapped_column(String(20), default='PENDING')
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dispute_reason: Mapped[str | None] = mapped_column(Text)
    # MISSING | DAMAGED | WRONG_ITEM | OTHER
    dispute_type: Mapped[str | None] = mapped_column(String(30))

    # Audit trail
    response_ip: Mapped[str | None] = mapped_column(String(45))
    response_user_agent: Mapped[str | None] = mapped_column(String(500))

    # Notification tracking
    email_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reminder_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    campaign: Mapped['AuditCampaign'] = relationship(
        back_populates='responses', lazy='selectin'
    )
    assignment: Mapped['EquipmentAssignment'] = relationship(lazy='selectin')
    items: Mapped[list['AuditResponseItem']] = relationship(
        back_populates='response', cascade='all, delete-orphan', lazy='selectin'
    )

    @property
    def item_name(self) -> str:
        # Expose the asset name on the response so Pydantic's
        # ``from_attributes=True`` picks it up via the schema field of the
        # same name. Walks assignment.item (both lazy='selectin' so no
        # extra round-trip in the common case); grouped envelopes
        # fall back to the first item row.
        assignment = self.assignment
        if assignment is None:
            return self.items[0].item_name if self.items else ''
        item = getattr(assignment, 'item', None)
        if item is None:
            return ''
        return getattr(item, 'name', '') or ''

    @property
    def assets_returned(self) -> bool:
        """Every asset this response asks about is back from its holder.

        Nothing is left to attest, whichever door the return came through
        (a check-in, a bulk return): the question is closed by the assets, not
        by the person, so it is read here rather than written by each of them.
        """
        assignments = [item.assignment for item in self.items] or [self.assignment]
        return all(a is not None and a.checked_in_at is not None for a in assignments)

    @property
    def serial_number(self) -> str | None:
        from ._serial import serial_of

        assignment = self.assignment
        if assignment is None:
            return self.items[0].serial_number if self.items else None
        item = getattr(assignment, 'item', None)
        return serial_of(item) if item is not None else None


class AuditResponseItem(Base):
    """One asset within a per-person attestation response.

    A campaign used to create one ``AuditResponse`` per assignment; now one
    response is created per person (grouped by email) and each asset is an
    item row here, so the public page confirms everything at once and can
    dispute a specific asset.
    """

    __tablename__ = 'audit_response_items'
    __table_args__ = ({'keep_existing': True},)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    response_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('audit_responses.id', ondelete='CASCADE'),
        index=True,
    )
    assignment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('equipment_assignments.id', ondelete='CASCADE'),
        index=True,
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('items.id', ondelete='CASCADE'),
        index=True,
    )

    # Denormalized snapshot — the public page must render the list without
    # walking live item rows that may be edited later.
    item_name: Mapped[str] = mapped_column(String(255))
    serial_number: Mapped[str | None] = mapped_column(String(100))

    # Per-item response: PENDING | CONFIRMED | DISPUTED
    status: Mapped[str] = mapped_column(String(20), default='PENDING')
    dispute_type: Mapped[str | None] = mapped_column(String(30))
    dispute_reason: Mapped[str | None] = mapped_column(Text)
    # When this asset was answered. The envelope's ``responded_at`` is set
    # only once every asset has an answer, so it cannot date a single report.
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    response: Mapped['AuditResponse'] = relationship(
        back_populates='items', lazy='selectin'
    )
    assignment: Mapped['EquipmentAssignment'] = relationship(lazy='selectin')

    @property
    def returned(self) -> bool:
        """The asset came back after the request went out: nothing to attest."""
        return self.assignment is not None and self.assignment.checked_in_at is not None

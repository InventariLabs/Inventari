"""DocumentProfile, DocumentTypeConfig, TaxRate, TaxRateAssignment models."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
    false,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.module_sdk import CoreModelBase


class TaxHandling(StrEnum):
    NONE = 'NONE'
    SIMPLE_RATE = 'SIMPLE_RATE'
    PER_LINE_RATE = 'PER_LINE_RATE'


#: How a document number is shaped when nobody has said otherwise.
#:
#: One constant, because there used to be three: this column's default, the
#: "Simple" preset, and a literal in the numbering code — and which of them
#: applied depended on call order. The first document of an organization was
#: numbered before its profile existed, so it got the numbering code's width
#: and every document after it got the preset's: IN/2026/0001, then
#: IN/2026/002. Two defaults for one question is a bug waiting for its next
#: field; this is the one place the answer lives.
DEFAULT_NUMBERING_FORMAT = '{TYPE}/{YEAR}/{SEQ:03d}'
DEFAULT_NUMBER_PADDING = 3


class DocumentProfile(CoreModelBase):
    """Per-organization configuration for document behavior and appearance."""

    __tablename__ = 'document_profiles'
    __table_args__ = (
        UniqueConstraint('organization_id', name='uq_document_profile_org'),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE'),
        index=True,
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    value_tracking_enabled: Mapped[bool] = mapped_column(default=False)
    tax_handling: Mapped[str] = mapped_column(
        String(20), nullable=False, default=TaxHandling.NONE.value
    )
    default_tax_rate: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 2), nullable=True
    )
    # Tri-state: ``None`` is "the profile states no opinion" and the
    # organization's country answers (``country_tax_rules``); True or False
    # is an explicit entry and wins over the country. Presets write None —
    # whether a partner needs a tax id is law, not a way of working.
    require_partner_tax_id: Mapped[bool | None] = mapped_column(nullable=True)
    require_unit_price: Mapped[bool] = mapped_column(default=False)
    # When on, a picking or receiving session expects the shelf's label to be
    # scanned before the product of a line standing on that shelf.
    confirm_shelf_by_scan: Mapped[bool] = mapped_column(
        default=False, server_default=false()
    )
    numbering_format: Mapped[str] = mapped_column(
        String(100), nullable=False, default=DEFAULT_NUMBERING_FORMAT
    )
    number_padding: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=DEFAULT_NUMBER_PADDING
    )
    type_labels: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    default_unit: Mapped[str] = mapped_column(String(20), nullable=False, default='pcs')
    # ``None`` here is the column's unset state, not a third answer: every
    # path that CREATES a profile writes the preset's list explicitly —
    # ``create_default_profile`` spreads the Simple preset,
    # ``apply_preset`` assigns each key before commit — so no created row
    # holds NULL. One entrance can still put it there:
    # ``PUT /warehouse/profile`` rewrites every field present in the
    # payload, so an explicit JSON ``null`` lands in the column, and a
    # reader must treat it the same as ``[]``. Deliberately no
    # ORM ``default=list``: with every creation path naming the list, a column
    # default would be one more dormant default-of-defaults, and dropping
    # the nullability would buy a migration for a state no creation path
    # produces.
    visible_line_fields: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    print_template: Mapped[str] = mapped_column(
        String(50), nullable=False, default='auto'
    )
    default_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    default_template_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('document_templates.id', ondelete='SET NULL'),
        nullable=True,
    )
    # Where a receipt line coded DAMAGE or QUALITY_HOLD is put when it has no
    # batch to hold back (a batch is quarantined where it stands).
    quarantine_location_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('storage_locations.id', ondelete='SET NULL'),
        nullable=True,
    )
    approval_threshold: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 2), nullable=True
    )
    approval_required_for_types: Mapped[list[str] | None] = mapped_column(
        JSON, nullable=True
    )
    # The pick-order strategy the warehouse is walked by — a name the
    # registry holds (``pick_order_strategies``). ``None`` is "nothing
    # chosen", which walks the default; so does a name whose module is
    # switched off, so a choice survives its module's holidays.
    pick_order_strategy: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # Carrier name → tracking link template with ``{tracking_number}``, read
    # before the built-in ones (``shipment_service.tracking_url``). ``None``
    # and ``{}`` both mean "the built-in templates only".
    tracking_url_templates: Mapped[dict[str, str] | None] = mapped_column(
        JSON, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class DocumentTypeConfig(CoreModelBase):
    """Per-document-type defaults for an organization."""

    __tablename__ = 'document_type_configs'
    __table_args__ = (
        UniqueConstraint(
            'organization_id',
            'document_type',
            name='uq_doctype_config_org_type',
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE'),
        index=True,
    )
    document_type: Mapped[str] = mapped_column(String(15))
    default_source_location_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('storage_locations.id'),
        nullable=True,
    )
    default_target_location_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('storage_locations.id'),
        nullable=True,
    )
    sequence_format: Mapped[str] = mapped_column(
        String(50), default='{TYPE}/{YEAR}/{SEQ:05d}'
    )
    require_partner: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class TaxRate(CoreModelBase):
    """Configurable tax rate per organization for document lines."""

    __tablename__ = 'tax_rates'

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE'),
        index=True,
    )
    name: Mapped[str] = mapped_column(String(100))
    rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    country: Mapped[str | None] = mapped_column(String(2), nullable=True)
    is_default: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class TaxRateAssignment(CoreModelBase):
    """One product or one category naming the rate its document lines take.

    A row names exactly one of the two. The product's own row wins over its
    category's; neither is the organization's default, which stays on the
    profile and the country. Deleting the rate deletes the rows that named
    it, and the goods fall back to that default.
    """

    __tablename__ = 'tax_rate_assignments'
    __table_args__ = (
        CheckConstraint(
            'num_nonnulls(product_template_id, category_id) = 1',
            name='ck_tax_rate_assignments_one_target',
        ),
        # A NULL is distinct from every other NULL, so each pair is unique
        # only among the rows that name that kind of target.
        UniqueConstraint(
            'organization_id',
            'product_template_id',
            name='uq_tax_rate_assignments_org_product',
        ),
        UniqueConstraint(
            'organization_id',
            'category_id',
            name='uq_tax_rate_assignments_org_category',
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE'),
        index=True,
    )
    tax_rate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('tax_rates.id', ondelete='CASCADE'),
        index=True,
    )
    product_template_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('product_templates.id', ondelete='CASCADE'),
        nullable=True,
    )
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('categories.id', ondelete='CASCADE'),
        nullable=True,
    )

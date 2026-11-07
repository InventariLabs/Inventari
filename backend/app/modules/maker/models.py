"""Maker module — Recipes, Bill of Materials, Production Orders and Order Lines."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship, synonym

from app.core.db_facade import Base
from app.core.module_sdk import utc_now

if TYPE_CHECKING:
    from app.models.product_template import ProductTemplate


class MakerRecipe(Base):
    """A production recipe describing how to manufacture a product.

    A template may have multiple recipes (variants), but at most one
    ``is_default`` (enforced by a partial unique index).  The default recipe
    is used by ``explode`` and ``POST /production/orders`` when no explicit
    recipe is specified.
    """

    __tablename__ = 'maker_recipes'
    __table_args__ = (
        UniqueConstraint(
            'organization_id',
            'output_template_id',
            'name',
            name='uq_recipe_org_template_name',
        ),
        Index('ix_recipe_org_template', 'organization_id', 'output_template_id'),
        # Partial unique index: at most one default recipe per (org, template).
        Index(
            'uq_recipe_default_per_template',
            'organization_id',
            'output_template_id',
            unique=True,
            postgresql_where=text('is_default'),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE'),
        nullable=False,
    )
    output_template_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('product_templates.id', ondelete='CASCADE'),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    batch_yield_qty: Mapped[Decimal] = mapped_column(
        Numeric(12, 4),
        nullable=False,
        default=Decimal('1'),
    )
    batch_yield_uom_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('uoms.id'),
        nullable=True,
    )
    process_steps: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    reference_price: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2),
        nullable=True,
    )
    is_default: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    # Plain UUID — NOT a FK. The culinary recipe may be disabled or absent
    # (module boundary).  This is a soft, audit-only reference.
    source_recipe_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    source_snapshot_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    # Relationships
    lines: Mapped[list[BoMLine]] = relationship(
        back_populates='recipe',
        cascade='all, delete-orphan',
        lazy='selectin',
    )
    cost_lines: Mapped[list[MakerRecipeCostLine]] = relationship(
        back_populates='recipe',
        cascade='all, delete-orphan',
        lazy='selectin',
    )
    output_template: Mapped[ProductTemplate] = relationship(lazy='selectin')


class MakerRecipeCostLine(Base):
    """Fixed cost per batch — labor, packaging, overhead, other."""

    __tablename__ = 'maker_recipe_cost_lines'
    __table_args__ = (
        Index('ix_recipe_cost_recipe', 'recipe_id'),
        Index('ix_recipe_cost_org', 'organization_id'),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    recipe_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('maker_recipes.id', ondelete='CASCADE'),
        nullable=False,
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE'),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    sort_order: Mapped[int] = mapped_column(default=0)

    recipe: Mapped[MakerRecipe] = relationship(back_populates='cost_lines')


class BoMLine(Base):
    """One ingredient in a recipe's Bill of Materials.

    ``recipe_id`` links the line to its :class:`MakerRecipe`.
    ``parent_template_id`` is a denormalised copy of
    ``recipe.output_template_id``. The
    invariant ``parent_template_id == recipe.output_template_id`` is
    enforced at the application level (``bom_service._validate_line_parent``
    in every line write path — ``add_line`` and ``bom_tree.move_line``;
    covered by the 0a integration tests).
    """

    __tablename__ = 'maker_bom_lines'
    __table_args__ = (
        UniqueConstraint(
            'recipe_id',
            'child_template_id',
            name='uq_bom_recipe_child',
        ),
        CheckConstraint('qty_per_batch > 0', name='ck_bom_qty'),
        CheckConstraint(
            'parent_template_id <> child_template_id',
            name='ck_bom_no_self',
        ),
        CheckConstraint(
            'yield_loss_pct >= 0 AND yield_loss_pct <= 100',
            name='ck_bom_yield_range',
        ),
        Index('ix_bom_recipe', 'recipe_id'),
        Index('ix_bom_parent', 'parent_template_id'),
        Index('ix_bom_org', 'organization_id'),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE'),
        nullable=False,
    )
    recipe_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('maker_recipes.id', ondelete='CASCADE'),
        nullable=False,
    )
    parent_template_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('product_templates.id', ondelete='CASCADE'),
        nullable=False,
    )
    child_template_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('product_templates.id', ondelete='CASCADE'),
        nullable=False,
    )
    qty_per_batch: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    uom_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('uoms.id'),
        nullable=True,
    )
    unit: Mapped[str] = mapped_column(String(8), nullable=False)
    yield_loss_pct: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),
        nullable=False,
        default=Decimal('0'),
    )
    notes: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    recipe: Mapped[MakerRecipe] = relationship(back_populates='lines')


class ProductionOrder(Base):
    """A production run: consume inputs across locations → produce output."""

    __tablename__ = 'maker_production_orders'
    __table_args__ = (
        Index(
            'ix_prod_org_status',
            'organization_id',
            'status',
        ),
        Index('ix_prod_org_output', 'organization_id', 'output_template_id'),
        Index(
            'uq_prod_org_number',
            'organization_id',
            'number',
            unique=True,
            postgresql_where=text('number IS NOT NULL'),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE'),
        nullable=False,
    )
    # Human-facing run number ("PR/2026/0001"), unique per organization.
    # A run identified by eight UUID characters told two runs on the same
    # product apart the way a machine reads, not a person. Assigned at
    # creation; legacy rows keep NULL (the interface falls back to the old
    # short-UUID display for them).
    number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    output_template_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('product_templates.id'),
        nullable=False,
    )
    recipe_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('maker_recipes.id'),
        nullable=True,
    )
    planned_qty: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    actual_qty: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    overproduced: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default='false',
    )
    scrap_qty: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    output_storage_location_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('storage_locations.id'),
        nullable=False,
    )
    #: The name the API and the contract DTOs give this column: a client
    #: meets a location, the table keeps its storage_location spelling.
    output_location_id: Mapped[uuid.UUID] = synonym('output_storage_location_id')
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default='DRAFT',
    )
    total_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    # financial result snapshot at completion — self-contained per
    # order (survives recipe edits/deletes). Legacy orders (recipe_id=None)
    # keep NULL values; the FE renders "—".
    unit_cost_snapshot: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    reference_price_snapshot: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    # reference_price − unit_cost (per unit of output) — NULL when the recipe
    # had no reference price at completion.
    result_per_unit: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    # result_per_unit × recipe.batch_yield_qty (per produced batch).
    result_per_batch: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    production_date: Mapped[date | None] = mapped_column(Date())
    notes: Mapped[str | None] = mapped_column(String(500))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('users.id'),
        nullable=True,
    )
    completed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('users.id'),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(String(500))
    produced_item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('items.id', ondelete='SET NULL'),
        nullable=True,
    )
    # Whether the planned consumption already exceeded stock at creation —
    # recomputed when a draft's planned_qty changes. The refusal dialog used
    # to invent history ("ran out since the draft was created") for an order
    # that was never satisfiable; with the fact recorded at birth the
    # sentence tells that case from a real shortage.
    short_at_create: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default='false',
    )

    # ORM relationship (no schema column — FK is output_template_id).
    # lazy='selectin' batches the load so list/detail avoid N+1.
    output_template: Mapped[ProductTemplate] = relationship(lazy='selectin')


class ProductionOrderLine(Base):
    """Audit snapshot of consumption per child template at completion.

    ``source_storage_location_id`` records the dominant source location
    (where most of the quantity was consumed) — full cross-location
    breakdown lives on ``stock_moves`` (reference_type='maker_production').
    """

    __tablename__ = 'maker_production_order_lines'
    __table_args__ = (Index('ix_prod_line_order', 'production_order_id'),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    production_order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('maker_production_orders.id', ondelete='CASCADE'),
        nullable=False,
    )
    child_template_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('product_templates.id'),
        nullable=False,
    )
    consumed_qty: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    unit: Mapped[str] = mapped_column(String(8), nullable=False)
    source_storage_location_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('storage_locations.id'),
        nullable=True,
    )
    #: The name the API and the contract DTOs give this column: a client
    #: meets a location, the table keeps its storage_location spelling.
    source_location_id: Mapped[uuid.UUID | None] = synonym('source_storage_location_id')
    unit_cost_snapshot: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    cost_source: Mapped[str | None] = mapped_column(String(16))
    # The part of ``consumed_qty`` the records did not hold, in the same unit,
    # on a run recorded after the fact: the goods were used, so the records
    # were wrong, and the ingredient is due a count. NULL on a run that drew
    # everything it consumed.
    shortfall_qty: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))


class MakerModuleSettings(Base):
    """Per-org behavioral settings for the maker module.

    Establishes the ``<name>_module_settings`` pattern: org_id PK, typed
    columns for known knobs.
    """

    __tablename__ = 'maker_module_settings'

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE'),
        primary_key=True,
    )
    # A new organization reads production's result as a margin (sale price
    # minus the cost to make); savings against a shop price is opted into.
    reference_direction: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default='MARGIN',
        server_default='MARGIN',
    )
    allow_overproduction: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default='true',
    )
    availability_check_scope: Mapped[str] = mapped_column(
        String(15),
        nullable=False,
        default='GLOBAL',
        server_default='GLOBAL',
    )
    create_on_shortage_strategy: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default='WARN',
        server_default='WARN',
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

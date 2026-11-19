"""Maker module — Recipes, Bill of Materials, Production Orders and Order Lines."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
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
    #: One object per step (``{text, minutes}``). A bare sentence saved
    #: before steps carried durations was normalised to ``minutes: null``.
    process_steps: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONB, nullable=True
    )
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
    #: An ingredient that has a recipe of its own is taken from its own stock
    #: first and made only for what the stock does not cover. A line marked
    #: fresh is always made through its recipe and never taken from stock —
    #: the dough that must be mixed on the day. Meaningless on a line whose
    #: ingredient has no recipe.
    make_fresh: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default='false',
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
    #: What the formula predicted this run would cost, read when it closed —
    #: the figure the actual cost is measured against. NULL on runs that
    #: closed before the estimate was kept.
    estimated_total_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
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
    # The batch the run's output goes into, as the person named it. NULL
    # puts the output on the shelf without a batch, as runs always did. A
    # named batch is what lets a recall of an ingredient follow the run to
    # the goods it made and on to their customers.
    output_lot_name: Mapped[str | None] = mapped_column(String(100))
    #: The batch the output went into, set when the run completes: the one
    #: named above, or the one the run named for itself when nobody did.
    output_lot_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('stock_lots.id', ondelete='SET NULL'),
        nullable=True,
    )
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
    #: The cost layer the run's output opened, when it was completed in one
    #: step: what the goods put on the shelf are worth. Undoing the run takes
    #: them off at that layer, not at whichever layer of the product is
    #: oldest — those differ as soon as the product was made more than once
    #: at different costs. NULL on a run filled in portions (each portion
    #: keeps its own layer) and on runs that closed before it was kept.
    output_layer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('stock_valuation_layers.id', ondelete='SET NULL'),
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

    #: The day the run was started, when it was started before it was
    #: finished: its ingredients left the records that day. NULL on a run
    #: that was completed in one step.
    started_on: Mapped[date | None] = mapped_column(Date())
    #: The day a draft was planned for, kept when the run closes on another
    #: day (``production_date`` then holds the day it was made). NULL when the
    #: run was made on its planned day, or never had one.
    planned_for: Mapped[date | None] = mapped_column(Date())
    #: The moment the run was started, for the as-of valuation: the work in
    #: progress is held from this instant until the run closes.
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: What the ingredients taken at the start cost, in the organisation's
    #: money — the work in progress the run holds until it finishes. Set
    #: when the run starts and kept after, so the finish divides it by what
    #: came out. NULL on a run completed in one step.
    material_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    #: The part of a closed run's cost that could not go on the shelf: the
    #: run's output was sold or used before the run closed, and its cost left
    #: with it. NULL on a run that was not filled in portions.
    unshelved_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    #: The formula's process steps as the run began, one object per step
    #: (``{text, minutes, done_on}``). The steps are ticked on the run with
    #: the day each was done; a copy, so a later edit of the formula does
    #: not move a run that is under way.
    steps: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)

    # ORM relationship (no schema column — FK is output_template_id).
    # lazy='selectin' batches the load so list/detail avoid N+1.
    output_template: Mapped[ProductTemplate] = relationship(lazy='selectin')


class ProductionPortion(Base):
    """One portion of a run's output, put on the shelf before the run closes.

    A vat bottled over three days is three portions of one run. Each has its
    own day and batch; the run's actual quantity is their sum once it closes.
    """

    __tablename__ = 'maker_production_portions'
    __table_args__ = (Index('ix_prod_portion_order', 'production_order_id'),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE'),
        nullable=False,
    )
    production_order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('maker_production_orders.id', ondelete='CASCADE'),
        nullable=False,
    )
    qty: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    #: The day the portion came out.
    made_on: Mapped[date] = mapped_column(Date(), nullable=False)
    lot_name: Mapped[str | None] = mapped_column(String(100))
    #: The record the portion opened on the shelf.
    item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('items.id', ondelete='SET NULL'),
        nullable=True,
    )
    #: What the portion was booked at per unit, so the closing portion can
    #: carry the rest of the run's cost.
    unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    #: The cost layer the portion opened: where the rest of the run's cost is
    #: placed when the run closes with its whole output already on the shelf.
    layer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('stock_valuation_layers.id', ondelete='SET NULL'),
        nullable=True,
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('users.id'),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )


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
    #: The formula's standard quantity for this ingredient on the output
    #: that came out, and the estimated rate it was priced at when the run
    #: closed. The guess the actual beside it is measured against.
    estimated_qty: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    estimated_unit_cost_snapshot: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    # The part of ``consumed_qty`` the records did not hold, in the same unit,
    # on a run recorded after the fact: the goods were used, so the records
    # were wrong, and the ingredient is due a count. NULL on a run that drew
    # everything it consumed.
    shortfall_qty: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))


class MakerIngredientPrice(Base):
    """A price typed once for an ingredient the records do not price.

    A product made an hour ago has no cost layer and no supplier quote, so
    every estimate that asks what the formula costs answers zero — a number
    nobody can plan from. The price typed on the product is that
    organisation's own fallback, one per product and never per formula: two
    formulas that share an ingredient share what it costs.

    It is the last answer the estimate policy asks, after the layers (what
    the stock actually cost) and a supplier's quote (a live offer). A
    product can be a global catalogue row shared by every organisation, so
    the price lives here rather than on ``product_templates``.
    """

    __tablename__ = 'maker_ingredient_prices'
    __table_args__ = (
        UniqueConstraint(
            'organization_id',
            'product_template_id',
            name='uq_maker_price_org_template',
        ),
        Index('ix_maker_price_org', 'organization_id'),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE'),
        nullable=False,
    )
    product_template_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('product_templates.id', ondelete='CASCADE'),
        nullable=False,
    )
    #: Per stock unit, in the organization's money — the same unit the
    #: layers and the supplier prices are held in.
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
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


class MakerShelfLife(Base):
    """How many days a product keeps once made, in one organization.

    A run dates its output batch from it: best before is the run's day plus
    these days, which the person closing the run may change. One row per
    product and organization, for the reason the typed prices are kept here:
    a product can be a catalogue row shared by every organization.
    """

    __tablename__ = 'maker_shelf_lives'
    __table_args__ = (
        UniqueConstraint(
            'organization_id',
            'product_template_id',
            name='uq_maker_shelf_life_org_template',
        ),
        CheckConstraint('shelf_life_days > 0', name='ck_maker_shelf_life_positive'),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE'),
        nullable=False,
    )
    product_template_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('product_templates.id', ondelete='CASCADE'),
        nullable=False,
    )
    shelf_life_days: Mapped[int] = mapped_column(Integer, nullable=False)
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


class MakerLabelFacts(Base):
    """What a product's label says of it, in one organization.

    The name it goes under in an ingredient list (a legal food name, an INCI
    name), the allergens it contains and the ones it may contain. A made
    product's list and allergens are computed from its recipe out of these
    facts on each ingredient (``labelling.py``). One row per product and
    organization, for the reason the shelf lives are kept here: a product can
    be a catalogue row shared by every organization.
    """

    __tablename__ = 'maker_label_facts'
    __table_args__ = (
        UniqueConstraint(
            'organization_id',
            'product_template_id',
            name='uq_maker_label_facts_org_template',
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE'),
        nullable=False,
    )
    product_template_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('product_templates.id', ondelete='CASCADE'),
        nullable=False,
    )
    #: The name the product goes under in an ingredient list; None reads the
    #: product's own name.
    label_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    #: The allergen keys a person confirmed. None: nobody has checked yet,
    #: which is not the same answer as an empty list (checked, none).
    allergens: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    #: Allergens the product may carry by cross-contact ("may contain").
    may_contain: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
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


class ProductionAttachment(Base):
    """A photo or a file filed under a production run."""

    __tablename__ = 'maker_production_attachments'
    __table_args__ = (
        Index(
            'ix_maker_attachment_order',
            'organization_id',
            'production_order_id',
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE'),
        nullable=False,
    )
    production_order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('maker_production_orders.id', ondelete='CASCADE'),
        nullable=False,
    )
    #: Relative to the organization's ``maker`` folder: ``<order>/<uuid>.<ext>``.
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )


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
    #: What an hour of the organization's own work costs. A craft producer
    #: prices a batch from the time the steps take, not from a lump sum
    #: typed per batch, so a formula's labour is its steps' minutes at this
    #: rate. Zero means nobody has named a rate, and labour costs nothing.
    labor_hourly_rate: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
        default=Decimal('0'),
        server_default='0',
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

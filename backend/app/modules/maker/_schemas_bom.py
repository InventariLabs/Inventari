"""Pydantic schemas for Bill of Materials (BOM) endpoints."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class BoMLineRead(BaseModel):
    """Output schema for a BOM line."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    #: The recipe the line belongs to — the one its edit is addressed to.
    recipe_id: UUID
    parent_template_id: UUID
    child_template_id: UUID
    qty_per_batch: Decimal
    uom_id: UUID | None = None
    unit: str
    yield_loss_pct: Decimal
    #: Always made through its own recipe, never taken from its stock.
    make_fresh: bool = False
    notes: str | None
    created_at: datetime
    updated_at: datetime
    # Denormalised display name (None when the template was deleted).
    child_template_name: str | None = None
    # The ingredient's picture is its product's picture — same source of
    # truth the catalog rows use.
    child_template_image_url: str | None = None
    # The price typed once on the product, for an ingredient the stock
    # records and the suppliers do not price. It is the fallback the shared
    # estimate asks last; the line carries it so the formula's own screen can
    # show it and offer to set it.
    typed_unit_price: Decimal | None = None
    #: Whether the estimate actually used that price. The cost layers and a
    #: supplier quote answer first, so a typed price can sit on a product
    #: while the line is costed by something else — and a card that showed it
    #: plainly beside a different figure read as if it were in use.
    typed_unit_price_in_use: bool = False
    #: For an ingredient that has a recipe of its own: what its stock holds
    #: now, in the line's unit — the part of a run a shelf covers before
    #: the recipe is used. Null for an ingredient with no recipe, or when the
    #: line's unit has no bridge to the stock's.
    stock_on_hand: Decimal | None = None


class BoMTemplateIdsResponse(BaseModel):
    """Ids of the product templates that have a formula, for list filtering."""

    template_ids: list[UUID]


class BoMSummaryItem(BaseModel):
    """One row of the batched BOM-existence query."""

    template_id: UUID
    line_count: int
    # Default recipe for this template (link target for badges/slots).
    default_recipe_id: UUID | None = None


class BoMSummaryResponse(BaseModel):
    """Batched BOM summary for a list of templates (product-list badges)."""

    items: list[BoMSummaryItem]


class BoMParentItem(BaseModel):
    """One recipe in the parents list — a template that has a BOM."""

    template_id: UUID
    name: str
    line_count: int


class WhereUsedItem(BaseModel):
    """One recipe whose BOM consumes a given child template."""

    recipe_id: UUID
    recipe_name: str
    output_template_id: UUID
    output_template_name: str | None = None
    # Consumption per batch of the using recipe (for the where-used view).
    qty_per_batch: Decimal
    unit: str


class BomMoveRequest(BaseModel):
    """Input for POST /bom/{line_id}/move — reparent an existing line."""

    new_parent_template_id: UUID


class BomTreeNode(BaseModel):
    """Recursive BOM tree node — a line + nested children."""

    line: BoMLineRead | None
    children: list[BomTreeNode]


class BomTreeResponse(BaseModel):
    """Output for GET /bom/tree/{template_id} — full hierarchy under parent."""

    parent_template_id: UUID
    root: BomTreeNode

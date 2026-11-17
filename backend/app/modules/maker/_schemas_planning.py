"""Schemas for the combined needs of planned runs and ordering what is missing."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ExpectedDeliveryRead(BaseModel):
    """An open purchase order line that will bring some of an ingredient."""

    model_config = ConfigDict(from_attributes=True)

    purchase_order_id: UUID
    number: str
    expected_date: date | None
    quantity: Decimal


class NeedRowRead(BaseModel):
    """One ingredient of the combined list, in its own stock unit."""

    model_config = ConfigDict(from_attributes=True)

    template_id: UUID
    name: str | None
    uom_symbol: str | None
    needed: Decimal
    in_stock: Decimal
    #: Null while purchasing is off — the column does not exist then, which is
    #: not the same as nothing being on order.
    on_order: Decimal | None
    expected: list[ExpectedDeliveryRead]
    missing: Decimal
    #: What draft runs of the ingredient itself already bring.
    planned: Decimal
    #: ``make`` for an ingredient with a recipe of its own: its missing part is
    #: proposed as a planned run of it, not as a purchase.
    action: Literal['buy', 'make']
    needed_by: date | None = None
    output_location_id: UUID | None = None


class NeedsRead(BaseModel):
    """Output for GET /production/needs."""

    rows: list[NeedRowRead]
    purchasing: bool
    run_count: int
    #: Ingredients whose measure cannot be compared with their stock unit.
    unmeasured: list[str]


class NeedsScope(BaseModel):
    """Which runs a needs request is about: one run, or the runs of a period."""

    order_id: UUID | None = None
    date_from: date | None = None
    date_to: date | None = None


class OrderedLineRead(BaseModel):
    template_id: UUID
    name: str | None
    quantity: Decimal
    uom_symbol: str | None


class OrderedPurchaseRead(BaseModel):
    purchase_order_id: UUID
    number: str
    partner_id: UUID
    lines: list[OrderedLineRead]


class OrderMissingRead(BaseModel):
    """Output for POST /production/needs/order — what ordering the missing did."""

    purchase_orders: list[OrderedPurchaseRead]
    #: Ingredients no supplier offers, put on the shopping list.
    shopping_list_added: int = 0
    shopping_list_name: str | None = None
    #: No supplier and no shopping list to put them on.
    unplaced: list[NeedRowRead]
    #: Missing ingredients with a recipe of their own: to be planned as runs.
    to_make: list[NeedRowRead]


class PlannedIntermediateRead(BaseModel):
    order_id: UUID
    number: str | None
    template_id: UUID
    name: str | None
    planned_qty: Decimal
    production_date: date | None


class PlanIntermediatesRead(BaseModel):
    """Output for POST /production/needs/plan-intermediates."""

    runs: list[PlannedIntermediateRead]

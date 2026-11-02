"""Inventory invariant assertion helpers.

These query the DB directly to assert cross-cutting consistency invariants
that must hold after ANY inventory operation:

* No ``Item.quantity`` / ``StockValuationLayer.remaining_qty`` may go
  negative.
* Every ``StockValuationLayer`` row must satisfy
  ``0 <= remaining_qty <= quantity``.

Intended usage: call ``assert_invariants(db, org_id)`` at the end of any
test that mutates inventory.  Operation-specific cost-preservation tests
should additionally compare ``get_stock_value(db, org_id)`` before/after an
operation and assert it is unchanged (guards AVCO corruption like the
picking-undo zero-cost bug).

Operates on a sync ``Session`` (the dominant test fixture). Co-located with
``_core_api_helpers.py`` to follow the repo's helper-module convention.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.item import Item
from app.models.stock_valuation_layer import StockValuationLayer


def assert_no_negative_quantities(db: Session, org_id: UUID) -> None:
    """No Item.quantity or SVL remaining_qty < 0."""
    neg_items = db.scalar(
        select(func.count())
        .select_from(Item)
        .where(Item.organization_id == org_id, Item.quantity < 0)
    )
    assert not neg_items, (
        f'{neg_items} Item rows with negative quantity in org {org_id}'
    )
    neg_svl = db.scalar(
        select(func.count())
        .select_from(StockValuationLayer)
        .where(
            StockValuationLayer.organization_id == org_id,
            StockValuationLayer.remaining_qty < 0,
        )
    )
    assert not neg_svl, (
        f'{neg_svl} SVL rows with negative remaining_qty in org {org_id}'
    )


def assert_valuation_layers_valid(db: Session, org_id: UUID) -> None:
    """Every SVL row must satisfy 0 <= remaining_qty <= quantity."""
    bad = db.execute(
        select(
            StockValuationLayer.id,
            StockValuationLayer.remaining_qty,
            StockValuationLayer.quantity,
        ).where(
            StockValuationLayer.organization_id == org_id,
            (StockValuationLayer.remaining_qty < 0)
            | (StockValuationLayer.remaining_qty > StockValuationLayer.quantity),
        )
    ).all()
    assert not bad, (
        f'Invalid SVL rows (remaining_qty outside [0, quantity]) in org {org_id}: {bad}'
    )


def get_stock_value(db: Session, org_id: UUID) -> Decimal:
    """Total on-hand stock value = SUM(remaining_qty * unit_cost) over IN layers.

    Use for cost-preservation assertions: snapshot before an operation, run
    the operation, assert the value is unchanged (or changed by an exact,
    expected delta). Guards AVCO corruption where a consume+undo pair or a
    manual create silently destroys or fabricates cost.
    """
    val = db.scalar(
        select(
            func.coalesce(
                func.sum(
                    StockValuationLayer.remaining_qty * StockValuationLayer.unit_cost
                ),
                0,
            )
        ).where(
            StockValuationLayer.organization_id == org_id,
            StockValuationLayer.direction == 'IN',
        )
    )
    return Decimal(val or 0)


def assert_invariants(db: Session, org_id: UUID) -> None:
    """Run all DB-level inventory invariants for an organization."""
    assert_no_negative_quantities(db, org_id)
    assert_valuation_layers_valid(db, org_id)

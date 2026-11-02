"""The warehouse-scale seed writes stock the reconciliation finds consistent.

``seed_scale_data.py`` writes an organization of up to a million products
straight into the tables, statement by statement, without the posting paths
that keep the shelves, the journal and the cost layers in step. What it
writes is only worth measuring if it is the shape those paths would have
produced, and a column added to one of its thirteen tables can break it
without anyone running it for months. So it is run here at a size of a few
hundred products, against the same checks a real organization answers to:
the stock reconciliation finds no drift, every group of stock has its
anchor, and every movement belongs to a completed document.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

import seed_scale_data as seed
from app.models.organization import Organization
from app.models.user import User
from app.services.analytics.reconciliation import get_reconciliation_async

pytestmark = pytest.mark.integration

PRODUCTS = 200


def _reconcile(engine: Engine, org_id):
    """The reconciliation's answer, read on the async driver it is written for."""

    async def read():
        async_engine = create_async_engine(
            engine.url.set(drivername='postgresql+asyncpg'), poolclass=NullPool
        )
        try:
            async with AsyncSession(async_engine) as adb:
                return await get_reconciliation_async(adb, org_id)
        finally:
            await async_engine.dispose()

    return asyncio.run(read())


def _count(db: Session, sql: str, org) -> int:
    return db.execute(text(sql), {'org': org}).scalar_one()


def test_the_seeded_organization_reconciles_and_keeps_the_posting_shape(
    engine: Engine, db_session: Session, test_household: Organization, test_user: User
) -> None:
    ctx = seed.context(db_session, test_household, test_user)
    db_session.commit()
    # The seed writes and commits on a connection of its own, as the script does.
    with engine.connect() as conn:
        seed.seed_organization(conn, ctx, seed._sizes(PRODUCTS), 1)

    reconciliation = _reconcile(engine, test_household.id)

    db = db_session
    org = test_household
    assert reconciliation.items_scanned > PRODUCTS
    assert reconciliation.quant_move_drift_count == 0
    assert reconciliation.layer_quant_drift_count == 0
    assert (
        _count(
            db,
            'SELECT count(*) FROM product_templates WHERE organization_id = :org',
            org.id,
        )
        == PRODUCTS
    )
    unanchored = _count(
        db,
        """
        SELECT count(*) FROM items i
        WHERE i.organization_id = :org AND i.quantity > 0
          AND NOT EXISTS (
            SELECT 1 FROM stock_anchors a
            WHERE a.product_template_id = i.template_id
              AND a.storage_location_id = i.storage_location_id)
        """,
        org.id,
    )
    assert unanchored == 0
    orphan_moves = _count(
        db,
        """
        SELECT count(*) FROM stock_moves m
        WHERE m.organization_id = :org
          AND NOT EXISTS (
            SELECT 1 FROM documents d
            WHERE d.id = m.reference_id AND d.status = 'COMPLETED')
        """,
        org.id,
    )
    assert orphan_moves == 0

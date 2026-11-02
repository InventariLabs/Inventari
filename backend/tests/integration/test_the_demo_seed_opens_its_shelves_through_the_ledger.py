"""The demo organization's stock reconciles, from the first page.

The demo seed wrote its stock the one way the application never does: a quant
per shelf, put in place directly, with no movement saying where it came from
and no cost layer behind it. The records and the quants agreed, so the first
pair of the reconciliation report stayed silent; the second (the shelf against
the movement ledger) and the third (cost layers against the shelf) did not —
measured on ``make db-seed-demo``, 364 groups and 111 products, 2,901.7 units
each — and ``make demo-reset`` shows that report on the public demo's
Statistics page, a drift no path of the application had made.

The seed now opens every record's stock the way the application opens stock
it did not receive: through the core movement call, a movement marked
``opening_balance`` pointing at the record, and a cost layer at the record's
purchase price. The report has nothing to say.

The first and fourth pairs compared the records and their view with the quant
table, and ended with it; the two pairs held here are the ones left.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.contracts import ItemAction
from app.models.item import Item
from app.models.item_history import ItemHistory
from app.models.stock_move import StockMove, StockMoveReferenceType
from app.modules.maker.models import ProductionOrder
from app.services.token_service import create_access_token
from tests.integration._demo_world import ids, seeded_organization

pytestmark = pytest.mark.integration


@pytest.fixture
def seeded(demo_world) -> tuple[uuid.UUID, uuid.UUID]:
    """A demo organization seeded with every module."""
    payload = demo_world('org-60', seeded_organization(items=60))
    return ids(payload)


def test_the_seeded_organization_reconciles_in_both_pairs(
    client, db_session: Session, seeded
) -> None:
    org_id, user_id = seeded
    headers = {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user_id)})}'
    }

    response = client.get('/api/v1/stats/reconciliation', headers=headers)

    assert response.status_code == 200, response.text
    report = response.json()
    # Not a silence over nothing: the seed put stock on the shelves.
    assert report['items_scanned'] > 0, report
    pairs = {
        'the shelf against movements': (
            'quant_move_drift_count',
            'quant_move_drift_total',
        ),
        'cost layers against the shelf': (
            'layer_quant_drift_count',
            'layer_quant_drift_total',
        ),
    }
    assert {
        pair: (report[groups], Decimal(str(report[total])))
        for pair, (groups, total) in pairs.items()
    } == dict.fromkeys(pairs, (0, Decimal('0'))), report


def test_every_seeded_record_opens_with_a_movement_of_its_own(
    db_session: Session, seeded
) -> None:
    """Two kinds of records are opened by something other than an opening
    balance, and for both the door that made them is their movement: the
    jars a production run made (the run points at itself when it made
    them), and the stock a seeded document's delivery opened (its receipt
    points at the document).

    The check runs one way: every record standing with stock carries its
    opening. The converse is not a promise the seed makes — it opens the
    shelves before its documents execute, so a seeded dispatch may draw an
    opened record down to nothing, and the record then leaves the shelves
    while its opening stays (a full-suite run once landed on exactly that
    dataset and the equality that used to stand here went red on it). An
    opening for a record that holds nothing is goods consumed, not a
    record the register never opened."""
    org_id, _user_id = seeded
    made = select(ProductionOrder.produced_item_id).where(
        ProductionOrder.organization_id == org_id,
        ProductionOrder.produced_item_id.is_not(None),
    )
    delivered = select(ItemHistory.item_id).where(
        ItemHistory.organization_id == org_id,
        ItemHistory.action == ItemAction.CREATED.value,
        ItemHistory.source_document_id.in_(
            select(StockMove.reference_id).where(
                StockMove.organization_id == org_id,
                StockMove.reference_type == StockMoveReferenceType.DOCUMENT,
                StockMove.reference_id.is_not(None),
            )
        ),
    )
    stocked_ids = set(
        db_session.scalars(
            select(Item.id).where(
                Item.organization_id == org_id,
                Item.template_id.is_not(None),
                Item.storage_location_id.is_not(None),
                Item.quantity > 0,
                Item.id.not_in(made),
                Item.id.not_in(delivered),
            )
        ).all()
    )
    opened_refs = set(
        db_session.scalars(
            select(StockMove.reference_id).where(
                StockMove.organization_id == org_id,
                StockMove.reference_type == StockMoveReferenceType.OPENING_BALANCE,
            )
        ).all()
    )
    produced = db_session.scalar(
        select(func.count())
        .select_from(StockMove)
        .where(
            StockMove.organization_id == org_id,
            StockMove.reference_type == 'maker_production',
            StockMove.to_location_id.is_not(None),
        )
    )
    delivered_count = db_session.scalar(
        select(func.count()).select_from(delivered.subquery())
    )
    assert stocked_ids
    assert delivered_count > 0, 'no document opened a record — nothing was checked'
    unopened = stocked_ids - opened_refs
    assert not unopened, (
        'stocked records with no opening of their own: '
        f'{sorted(str(item_id) for item_id in unopened)}'
    )
    assert produced == len(db_session.scalars(made).all())


def test_the_seeded_transfer_draft_can_be_confirmed(
    client, db_session: Session, seeded
) -> None:
    """The demo's transfer names the stock it takes, so Confirm works."""
    _org_id, user_id = seeded
    headers = {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user_id)})}'
    }
    listing = client.get(
        '/api/v1/warehouse/documents',
        params={'type': 'INT', 'status': 'DRAFT'},
        headers=headers,
    )
    assert listing.status_code == 200, listing.text
    drafts = listing.json()['items']
    assert drafts, listing.json()

    confirm = client.patch(
        f'/api/v1/warehouse/documents/{drafts[0]["id"]}/confirm', headers=headers
    )

    assert confirm.status_code == 200, confirm.text

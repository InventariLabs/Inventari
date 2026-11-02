"""Zero and "no idea" are different answers, and the report has to pick one.

The consumption and waste figures come from the ledger's outgoing half.
Where that half has nothing to say — outflows recorded before it existed, or
priced from a cost nobody ever stated — an empty sum reads as 0.00, and a
confident nothing over a month of real waste is worse than no figure at all.
``window_is_valued_async`` is what tells the two apart, and it had no test
that could fail: every case in the suite happened to be a priced window, so a
version answering ``True`` unconditionally would have passed.

Three windows, three answers: everything priced, an outflow with no layer,
and an outflow whose layer says the cost is unknown. The third is the one a
reader would expect to be safe and is not — the layer exists, so the move is
in the books, but its value is short by an amount nobody can name.

The question is asked per record rather than per outflow, and the test says
so where it matters: one outflow can consume several layers, so counting
layers against history rows would call every FIFO withdrawal unknown.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi import status
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models.item import Item
from app.models.item_history import ItemHistory
from app.models.product_template import ProductTemplate
from app.models.stock_valuation_layer import CostBasis, StockValuationLayer
from app.models.storage_location import StorageLocation
from app.models.user import User
from tests.integration._shelf import anchor_pending_records


def _item(
    db_session: Session, user: User, location: StorageLocation, name: str = 'Perishable'
) -> Item:
    template = ProductTemplate(name=name, organization_id=user.organization_id)
    db_session.add(template)
    db_session.flush()
    item = Item(
        organization_id=user.organization_id,
        storage_location_id=location.id,
        template_id=template.id,
        name=name,
        quantity=Decimal('5'),
        currency='USD',
    )
    db_session.add(item)
    anchor_pending_records(db_session)
    db_session.commit()
    db_session.refresh(item)
    return item


def _thrown_away(
    db_session: Session,
    item: Item,
    *,
    quantity: Decimal,
    value: Decimal | None,
    cost_basis: str = CostBasis.STATED,
) -> None:
    """A disposal, with or without a priced layer beside it."""
    db_session.add(
        ItemHistory(
            organization_id=item.organization_id,
            item_id=item.id,
            action='DISPOSED',
            changes={'qty': float(quantity), 'reason': 'EXPIRED'},
        )
    )
    if value is not None:
        db_session.add(
            StockValuationLayer(
                organization_id=item.organization_id,
                product_template_id=item.template_id,
                item_id=item.id,
                quantity=quantity,
                remaining_qty=Decimal('0'),
                unit_cost=value / quantity,
                total_value=value,
                direction='OUT',
                reason='DISPOSED',
                cost_basis=cost_basis,
                created_at=datetime.now(UTC),
            )
        )
    db_session.commit()


@pytest.mark.integration
class TestAReportSaysItDoesNotKnow:
    def test_a_priced_window_gives_a_number(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        item = _item(db_session, test_user, test_storage_location)
        _thrown_away(db_session, item, quantity=Decimal('2'), value=Decimal('4'))

        data = client.get('/api/v1/stats/consumption', headers=auth_headers).json()
        assert data['total_wasted_value'] == 4.0

    def test_an_outflow_with_no_layer_makes_the_total_unknown(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        priced = _item(db_session, test_user, test_storage_location, 'Priced')
        _thrown_away(db_session, priced, quantity=Decimal('2'), value=Decimal('4'))
        # A second record thrown away before the ledger's outgoing half
        # existed. The question is asked per record, not per outflow: one
        # outflow of a record that has any priced outflow in the window reads
        # as priced, because a single outflow can consume several layers and
        # counting them would call every FIFO withdrawal unknown.
        unpriced = _item(db_session, test_user, test_storage_location, 'Unpriced')
        _thrown_away(db_session, unpriced, quantity=Decimal('1'), value=None)

        response = client.get('/api/v1/stats/consumption', headers=auth_headers)
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        # Not 4.0, which would be a confident total short by an unknown
        # amount, and not 0.0 either.
        assert data['total_wasted_value'] is None
        assert data['total_consumed_value'] is None

    def test_a_layer_priced_from_nothing_makes_it_unknown_too(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        # The layer exists, so the move is in the books — but its cost was
        # never stated and there was no rate to fall back on. Counting it as
        # priced would put a confident number over a figure that is short.
        item = _item(db_session, test_user, test_storage_location)
        _thrown_away(
            db_session,
            item,
            quantity=Decimal('2'),
            value=Decimal('0'),
            cost_basis=CostBasis.UNKNOWN,
        )

        data = client.get('/api/v1/stats/consumption', headers=auth_headers).json()
        assert data['total_wasted_value'] is None

    def test_a_quiet_window_is_not_an_unknown_one(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        # The control. Nothing left the shelves, which is a fact, not a gap:
        # a report that answered "I do not know" here would be unreadable for
        # every organization that simply had a quiet month.
        _item(db_session, test_user, test_storage_location)

        data = client.get('/api/v1/stats/consumption', headers=auth_headers).json()
        assert data['total_wasted_value'] == 0.0

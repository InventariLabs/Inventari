"""FIFO consumes in business-date order — the date the receipt is about.

Layers used to be consumed in ``created_at`` order: the order the rows
happened to be written. A booking typed late pushed the goods it
describes to the back of the queue, so the cost of a dispatch could
come from a receipt the business would call the newer one. The layer
now carries the receipt's business date (a document's scheduled date),
and consumption follows it; layers with no document behind them fall
back to their write time, and ``id`` breaks the ties a same-day batch
of receipts would otherwise leave to chance.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from fastapi import status
from sqlalchemy.orm import Session

from app.core.testing import seed_org_storage_types
from app.models.item import Item
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.user import User
from app.services.token_service import create_access_token, get_password_hash
from tests.integration._shelf import post_on_shelf
from tests.integration.test_outflow_leaves_a_price_behind import _layers


@pytest.fixture
def fifo_org(db_session: Session) -> Organization:
    org = Organization(
        name='FIFO Order Org',
        enabled_modules=['core', 'items', 'locations', 'categories', 'stock_takes'],
        currency='PLN',
    )
    db_session.add(org)
    db_session.flush()
    seed_org_storage_types(db_session, org.id)
    db_session.commit()
    db_session.refresh(org)
    return org


@pytest.fixture
def fifo_user(db_session: Session, fifo_org: Organization) -> User:
    user = User(
        email='fifo-order@test.com',
        hashed_password=get_password_hash('pass'),
        full_name='FIFO Order User',
        organization_id=fifo_org.id,
        role='admin',
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def fifo_headers(fifo_user: User) -> dict:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(fifo_user.id)})}'
    }


@pytest.fixture
def fifo_shelf(
    client,
    db_session: Session,
    fifo_org: Organization,
    fifo_user: User,
    fifo_headers: dict,
) -> Item:
    """Two receipts, five pieces each.

    The *newer* receipt was written to the ledger first and holds the
    dearer stock; the *older* receipt's booking was typed later. Its
    business date (August 1st against August 20th) is what makes it the
    one FIFO consumes first.
    """
    st = StorageType(name='FIFO Shelf', type_code='SHELF_FIFO', behavior_mode='NONE')
    db_session.add(st)
    db_session.flush()
    location = StorageLocation(
        name='FIFO Location',
        organization_id=fifo_org.id,
        storage_type_id=st.id,
        created_by=fifo_user.id,
    )
    db_session.add(location)
    db_session.flush()

    template = ProductTemplate(
        name='Flour', organization_id=fifo_org.id, barcode='FIFO0001'
    )
    db_session.add(template)
    db_session.flush()

    db_session.commit()
    first = post_on_shelf(
        client, fifo_headers, template, location.id, 5, purchase_price='20.00'
    )
    post_on_shelf(
        client, fifo_headers, template, location.id, 5, purchase_price='10.00'
    )
    db_session.expire_all()
    receipts = {layer.unit_cost: layer for layer in _layers(db_session, fifo_org, 'IN')}
    # Written an hour earlier, but dated the 20th.
    receipts[Decimal('20.00')].created_at = datetime.now(UTC) - timedelta(hours=1)
    receipts[Decimal('20.00')].document_date = date(2026, 8, 20)
    # Written second, but its document speaks of August 1st: the
    # business-older stock.
    receipts[Decimal('10.00')].created_at = datetime.now(UTC)
    receipts[Decimal('10.00')].document_date = date(2026, 8, 1)
    db_session.commit()
    item = db_session.get(Item, UUID(first['id']))
    assert item is not None
    return item


@pytest.mark.integration
class TestFifoConsumesInBusinessDateOrder:
    def test_a_late_booking_does_not_push_its_goods_to_the_back(
        self, client, db_session, fifo_headers, fifo_org, fifo_shelf
    ) -> None:
        """The August 1st receipt leaves first, though it was booked last."""
        resp = client.patch(
            f'/api/v1/items/{fifo_shelf.id}/discard',
            headers=fifo_headers,
            json={'quantity': 5, 'reason': 'EXPIRED'},
        )
        assert resp.status_code in (
            status.HTTP_200_OK,
            status.HTTP_201_CREATED,
        ), resp.text

        db_session.expire_all()
        outgoing = _layers(db_session, fifo_org, 'OUT')
        assert len(outgoing) == 1
        # The outflow is priced at the rate then in force (the layer
        # average — the value itself leaves layer by layer). The order is
        # visible in what remains: the August 1st layer is emptied, the
        # dearer August 20th one is untouched.
        remaining = {
            layer.unit_cost: layer.remaining_qty
            for layer in _layers(db_session, fifo_org, 'IN')
        }
        assert remaining[Decimal('10.00')] == Decimal('0')
        assert remaining[Decimal('20.00')] == Decimal('5')

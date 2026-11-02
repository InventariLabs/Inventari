"""Stock that leaves says what it was worth, and says it once.

``StockValuationLayer.direction`` has been on the table since it was created
and only ever held ``'IN'``. An outflow drained the receipt layers, recomputed
the average, and left no record of its own value — so the reports that exist
to say what was used and what was thrown away had no source, and read the
figure out of ``ItemHistory.changes`` under four keys nothing writes.

Every ERP posts the value of an outgoing move when it happens, at the cost in
force then, and never recomputes it: a report about March has to say the same
thing in December. These tests hold that shape — the layer exists, it carries
the reason, it cannot reach the average, and it is priced from the
organization's own cost basis rather than a column a shared template row
happens to hold.
"""

from decimal import Decimal
from uuid import UUID

import pytest
from fastapi import status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.testing import seed_org_storage_types
from app.models.item import Item
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.stock_valuation_layer import CostBasis, StockValuationLayer
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.user import User
from app.services.token_service import create_access_token, get_password_hash
from tests.integration._shelf import post_on_shelf


@pytest.fixture
def of_org(db_session: Session) -> Organization:
    org = Organization(
        name='Outflow Value Org',
        # stock_takes consumes StockQuant, which is what switches the
        # valuation bridge on — it is in all three product profiles.
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
def of_user(db_session: Session, of_org: Organization) -> User:
    user = User(
        email='outflow@test.com',
        hashed_password=get_password_hash('pass'),
        full_name='Outflow User',
        organization_id=of_org.id,
        role='admin',
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def of_headers(of_user: User) -> dict:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(of_user.id)})}'
    }


@pytest.fixture
def of_location(
    db_session: Session, of_org: Organization, of_user: User
) -> StorageLocation:
    st = StorageType(name='Outflow Shelf', type_code='SHELF_OF', behavior_mode='NONE')
    db_session.add(st)
    db_session.flush()
    loc = StorageLocation(
        name='Shelf',
        organization_id=of_org.id,
        storage_type_id=st.id,
        created_by=of_user.id,
    )
    db_session.add(loc)
    db_session.commit()
    db_session.refresh(loc)
    return loc


@pytest.fixture
def of_stock(
    client,
    db_session: Session,
    of_org: Organization,
    of_location: StorageLocation,
    of_headers: dict,
) -> Item:
    """Ten units bought at four złoty each, on the shelf and in the ledger."""
    template = ProductTemplate(
        name='Yoghurt', organization_id=of_org.id, barcode='OUTFLOW001'
    )
    db_session.add(template)
    db_session.commit()
    record = post_on_shelf(
        client, of_headers, template, of_location.id, 10, purchase_price='4.00'
    )
    db_session.expire_all()
    item = db_session.get(Item, UUID(record['id']))
    assert item is not None
    return item


def _layers(db: Session, org: Organization, direction: str) -> list:
    return list(
        db.scalars(
            select(StockValuationLayer).where(
                StockValuationLayer.organization_id == org.id,
                StockValuationLayer.direction == direction,
            )
        ).all()
    )


@pytest.mark.integration
class TestAnOutflowIsPriced:
    def test_disposing_stock_posts_what_it_was_worth(
        self, client, db_session, of_headers, of_org, of_stock
    ) -> None:
        resp = client.patch(
            f'/api/v1/items/{of_stock.id}/discard',
            headers=of_headers,
            json={'quantity': 3, 'reason': 'EXPIRED'},
        )
        assert resp.status_code in (
            status.HTTP_200_OK,
            status.HTTP_201_CREATED,
        ), resp.text

        db_session.expire_all()
        outgoing = _layers(db_session, of_org, 'OUT')
        assert len(outgoing) == 1
        assert outgoing[0].quantity == Decimal('3')
        assert outgoing[0].unit_cost == Decimal('4.00')
        assert outgoing[0].total_value == Decimal('12.00')
        assert outgoing[0].item_id == of_stock.id

    def test_the_layer_says_it_was_a_disposal(
        self, client, db_session, of_headers, of_org, of_stock
    ) -> None:
        # Which is the whole content of the waste report: a use is not a
        # disposal, and `direction` alone cannot say which this was.
        client.patch(
            f'/api/v1/items/{of_stock.id}/discard',
            headers=of_headers,
            json={'quantity': 2, 'reason': 'EXPIRED'},
        )
        db_session.expire_all()
        outgoing = _layers(db_session, of_org, 'OUT')
        assert len(outgoing) == 1
        assert outgoing[0].reason == 'DISPOSED'

    def test_using_stock_is_recorded_as_a_use(
        self, client, db_session, of_headers, of_org, of_stock
    ) -> None:
        client.patch(
            f'/api/v1/items/{of_stock.id}/consume',
            headers=of_headers,
            json={'quantity': 2},
        )
        db_session.expire_all()
        outgoing = _layers(db_session, of_org, 'OUT')
        assert len(outgoing) == 1
        assert outgoing[0].reason == 'USED'

    def test_the_outgoing_layer_cannot_reach_the_average(
        self, client, db_session, of_headers, of_org, of_stock
    ) -> None:
        # Every AVCO query filters direction == 'IN', and the outgoing layer
        # holds nothing anybody can draw on. Ten at four, three gone: the
        # remaining seven are still worth four each.
        client.patch(
            f'/api/v1/items/{of_stock.id}/discard',
            headers=of_headers,
            json={'quantity': 3, 'reason': 'EXPIRED'},
        )
        db_session.expire_all()

        outgoing = _layers(db_session, of_org, 'OUT')
        assert outgoing[0].remaining_qty == Decimal('0')

        # The remaining IN layer still prices this organization's stock at
        # 4.00 — an outgoing layer cannot be drawn on, which is the point.
        remaining = _layers(db_session, of_org, 'IN')
        assert [layer.unit_cost for layer in remaining] == [Decimal('4.00')]

    def test_two_disposals_post_two_layers(
        self, client, db_session, of_headers, of_org, of_stock
    ) -> None:
        # The ledger records events, not a running balance: each outflow is
        # its own line, at the rate that was true when it happened.
        for _ in range(2):
            client.patch(
                f'/api/v1/items/{of_stock.id}/discard',
                headers=of_headers,
                json={'quantity': 2, 'reason': 'EXPIRED'},
            )
        db_session.expire_all()
        outgoing = _layers(db_session, of_org, 'OUT')
        assert len(outgoing) == 2
        assert sum(layer.total_value for layer in outgoing) == Decimal('16.00')

    def test_stock_bought_in_one_foreign_currency_is_not_priced_as_the_house(
        self, client, db_session, of_headers, of_org, of_location
    ) -> None:
        """A unanimous foreign currency is refused, not read as złoty.

        The org keeps its books in złoty and all of the stock was bought in
        euros. The layers agreed with themselves, so the average came back
        bare and the outflow was posted at it under the house's sign — 4.00
        eurocents read as 12.00 złoty. Refused like a mixed batch now: the
        move stays in the books, marked unknown, and the report is not
        handed a confident figure over money nobody can add up.
        """
        template = ProductTemplate(
            name='Imported Goods', organization_id=of_org.id, barcode='OUTFLOW002'
        )
        db_session.add(template)
        db_session.commit()
        record = post_on_shelf(client, of_headers, template, of_location.id, 10)
        db_session.expire_all()
        item = db_session.get(Item, UUID(record['id']))
        assert item is not None
        # A record cannot be priced in another currency than the house's;
        # euros reach the ledger with a receipt from abroad. Its layer is what
        # this test is about, so the one the record opened says so.
        (layer,) = _layers(db_session, of_org, 'IN')
        layer.unit_cost = Decimal('4.00')
        layer.total_value = Decimal('40.00')
        layer.currency = 'EUR'
        layer.cost_basis = CostBasis.STATED
        db_session.commit()

        resp = client.patch(
            f'/api/v1/items/{item.id}/discard',
            headers=of_headers,
            json={'quantity': 3, 'reason': 'EXPIRED'},
        )
        assert resp.status_code in (
            status.HTTP_200_OK,
            status.HTTP_201_CREATED,
        ), resp.text

        db_session.expire_all()
        outgoing = _layers(db_session, of_org, 'OUT')
        assert len(outgoing) == 1
        assert outgoing[0].item_id == item.id
        # Not 12.00 posted as the house's money: the layers cannot back a
        # rate in it, so the value is unknown — the same explicit answer a
        # mixed batch gets — and the cost report treats the window as such.
        assert outgoing[0].cost_basis == 'unknown'
        assert outgoing[0].unit_cost == Decimal('0')
        assert outgoing[0].total_value == Decimal('0')

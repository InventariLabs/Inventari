"""A counted difference carries a reason from a closed list.

The column was there from the first migration, with three example values in
its comment, and no screen ever wrote to it. So a count that found eight
where the records said ten produced a correction of minus two and no answer
to the question a warehouse asks after every count: how much of this is
breakage, how much is theft, and how much is somebody putting the goods on
the wrong shelf. Free text could not answer it either — twenty spellings of
"broken" do not add up.

The code is countable; the note says what the code cannot, and stops being
optional when the code is OTHER, because otherwise the escape hatch is the
answer nobody can read. Same bargain the correction and return documents
already struck.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest
from fastapi import status
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.testing import ModuleTestHelper
from app.models.item import Item
from app.models.item_history import ItemHistory
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.stock_takes.models import StockTake, StockTakeItem, StockTakeStatus
from tests.integration._shelf import post_on_shelf


@pytest.fixture
def why_org(db_session: Session) -> Organization:
    return ModuleTestHelper(db_session).create_org(
        'Reason Org', ['core', 'items', 'locations', 'categories', 'stock_takes']
    )


@pytest.fixture
def why_user(db_session: Session, why_org: Organization) -> User:
    return ModuleTestHelper(db_session).create_user(why_org, email='why@example.com')


@pytest.fixture
def why_headers(db_session: Session, why_user: User) -> dict[str, str]:
    return ModuleTestHelper(db_session).get_auth_headers(why_user)


@pytest.fixture
def why_location(
    db_session: Session, why_org: Organization, why_user: User
) -> StorageLocation:
    h = ModuleTestHelper(db_session)
    storage_type = h.create_storage_type(
        'Warehouse', 'WAREHOUSE', organization_id=why_org.id
    )
    return h.create_storage_location(why_org, storage_type, why_user, name='Cold store')


@pytest.fixture
def why_item(
    client: TestClient,
    why_headers: dict[str, str],
    db_session: Session,
    why_org: Organization,
    why_location: StorageLocation,
) -> Item:
    template: ProductTemplate = ModuleTestHelper(db_session).create_template(
        why_org, name='Perishable Goods'
    )
    db_session.commit()
    record = post_on_shelf(client, why_headers, template, why_location.id, 10)
    db_session.expire_all()
    item = db_session.get(Item, UUID(record['id']))
    assert item is not None
    return item


@pytest.fixture
def why_count(
    db_session: Session,
    why_org: Organization,
    why_user: User,
    why_location: StorageLocation,
    why_item: Item,
) -> StockTake:
    stock_take = StockTake(
        user_id=why_user.id,
        organization_id=why_org.id,
        storage_location_id=why_location.id,
        name='Cold store count',
        status=StockTakeStatus.IN_PROGRESS,
    )
    db_session.add(stock_take)
    db_session.flush()
    db_session.add(
        StockTakeItem(
            stock_take_id=stock_take.id,
            item_id=why_item.id,
            item_name=why_item.name,
            system_quantity=Decimal('10'),
        )
    )
    db_session.commit()
    db_session.refresh(stock_take)
    return stock_take


def _line(db_session: Session, stock_take_id: UUID) -> StockTakeItem:
    return db_session.execute(
        select(StockTakeItem).where(StockTakeItem.stock_take_id == stock_take_id)
    ).scalar_one()


@pytest.mark.integration
class TestADifferenceSaysWhy:
    def test_the_code_is_stored_with_the_count(
        self,
        client: TestClient,
        why_headers: dict[str, str],
        db_session: Session,
        why_count: StockTake,
    ) -> None:
        line_id = _line(db_session, why_count.id).id
        resp = client.patch(
            f'/api/v1/stock-takes/{why_count.id}/items/{line_id}/count',
            headers=why_headers,
            json={'counted_quantity': 8, 'discrepancy_reason_code': 'DAMAGE'},
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        assert resp.json()['discrepancy_reason_code'] == 'DAMAGE'

        db_session.expire_all()
        assert _line(db_session, why_count.id).discrepancy_reason_code == 'DAMAGE'

    def test_other_without_a_note_is_refused(
        self,
        client: TestClient,
        why_headers: dict[str, str],
        db_session: Session,
        why_count: StockTake,
    ) -> None:
        line_id = _line(db_session, why_count.id).id
        resp = client.patch(
            f'/api/v1/stock-takes/{why_count.id}/items/{line_id}/count',
            headers=why_headers,
            json={'counted_quantity': 8, 'discrepancy_reason_code': 'OTHER'},
        )
        assert resp.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT, resp.text

        db_session.expire_all()
        # The count did not land either: a row half-saved is worse than one
        # the reader has to fill in again.
        assert _line(db_session, why_count.id).counted_quantity is None

    def test_other_with_a_note_is_the_reason(
        self,
        client: TestClient,
        why_headers: dict[str, str],
        db_session: Session,
        why_count: StockTake,
    ) -> None:
        line_id = _line(db_session, why_count.id).id
        resp = client.patch(
            f'/api/v1/stock-takes/{why_count.id}/items/{line_id}/count',
            headers=why_headers,
            json={
                'counted_quantity': 8,
                'discrepancy_reason_code': 'OTHER',
                'discrepancy_reason': 'Two crates went to the fair and came back short',
            },
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text

        db_session.expire_all()
        line = _line(db_session, why_count.id)
        assert line.discrepancy_reason_code == 'OTHER'
        assert line.discrepancy_reason is not None

    def test_an_unknown_code_is_refused(
        self,
        client: TestClient,
        why_headers: dict[str, str],
        db_session: Session,
        why_count: StockTake,
    ) -> None:
        line_id = _line(db_session, why_count.id).id
        resp = client.patch(
            f'/api/v1/stock-takes/{why_count.id}/items/{line_id}/count',
            headers=why_headers,
            json={'counted_quantity': 8, 'discrepancy_reason_code': 'BROKEN-ISH'},
        )
        assert resp.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT, resp.text

    def test_the_reason_reaches_the_product_history(
        self,
        client: TestClient,
        why_headers: dict[str, str],
        db_session: Session,
        why_count: StockTake,
        why_item: Item,
    ) -> None:
        line_id = _line(db_session, why_count.id).id
        assert (
            client.patch(
                f'/api/v1/stock-takes/{why_count.id}/items/{line_id}/count',
                headers=why_headers,
                json={'counted_quantity': 8, 'discrepancy_reason_code': 'LOSS'},
            ).status_code
            == status.HTTP_200_OK
        )
        resp = client.post(
            f'/api/v1/stock-takes/{why_count.id}/complete',
            headers=why_headers,
            json={'apply_adjustments': True},
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text

        # The product's own history is where a person looks first when a
        # quantity has moved without a document.
        rows = (
            db_session.execute(
                select(ItemHistory).where(ItemHistory.item_id == why_item.id)
            )
            .scalars()
            .all()
        )
        reasons = [(row.changes or {}).get('discrepancy_reason_code') for row in rows]
        assert 'LOSS' in reasons

"""A count that says nothing about the note keeps the note.

The counting schema types `location_in_storage`, `notes`,
`discrepancy_reason` and `discrepancy_reason_code` all optional with a
default of None — the shape a partial PATCH has — and the writer read that
None as "write NULL". The screen sends only the quantity it just counted, so
the location badge the snapshot put on the row vanished on the first save and
the sorting that reads the column went with it (AGENTS.md §2b: an absent key
is not a decision).

Both halves are pinned: a payload that did not carry the keys leaves them
alone, and a payload that carried them as null clears them — a writer fixed
in the first direction alone would keep the badge for ever.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from fastapi import status
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.testing import ModuleTestHelper
from app.models.item import Item
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.stock_takes.models import StockTake, StockTakeItem, StockTakeStatus
from tests.integration._shelf import post_on_shelf


@pytest.fixture
def badge_org(db_session: Session) -> Organization:
    return ModuleTestHelper(db_session).create_org(
        'Badge Org', ['core', 'items', 'locations', 'categories', 'stock_takes']
    )


@pytest.fixture
def badge_user(db_session: Session, badge_org: Organization) -> User:
    return ModuleTestHelper(db_session).create_user(
        badge_org, email='badge@example.com'
    )


@pytest.fixture
def badge_headers(db_session: Session, badge_user: User) -> dict[str, str]:
    return ModuleTestHelper(db_session).get_auth_headers(badge_user)


@pytest.fixture
def badge_location(
    db_session: Session, badge_org: Organization, badge_user: User
) -> StorageLocation:
    h = ModuleTestHelper(db_session)
    storage_type = h.create_storage_type(
        'Warehouse', 'WAREHOUSE', organization_id=badge_org.id
    )
    return h.create_storage_location(
        badge_org, storage_type, badge_user, name='Aisle A'
    )


@pytest.fixture
def badge_item(
    client: TestClient,
    badge_headers: dict[str, str],
    db_session: Session,
    badge_org: Organization,
    badge_location: StorageLocation,
) -> Item:
    template: ProductTemplate = ModuleTestHelper(db_session).create_template(
        badge_org, name='Shelved Goods'
    )
    db_session.commit()
    record = post_on_shelf(client, badge_headers, template, badge_location.id, 10)
    db_session.expire_all()
    item = db_session.get(Item, UUID(record['id']))
    assert item is not None
    return item


@pytest.fixture
def badge_take(
    db_session: Session,
    badge_org: Organization,
    badge_user: User,
    badge_location: StorageLocation,
    badge_item: Item,
) -> StockTake:
    stock_take = StockTake(
        user_id=badge_user.id,
        organization_id=badge_org.id,
        storage_location_id=badge_location.id,
        name='Aisle count',
        status=StockTakeStatus.IN_PROGRESS,
    )
    db_session.add(stock_take)
    db_session.flush()
    db_session.add(
        StockTakeItem(
            stock_take_id=stock_take.id,
            item_id=badge_item.id,
            item_name=badge_item.name,
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


def _count(
    client: TestClient,
    headers: dict[str, str],
    take_id: UUID,
    line_id: UUID,
    payload: dict[str, object],
) -> Any:
    return client.patch(
        f'/api/v1/stock-takes/{take_id}/items/{line_id}/count',
        headers=headers,
        json=payload,
    )


@pytest.mark.integration
class TestACountThatSaysNothingKeepsWhatItDidNotMention:
    def test_a_count_that_carries_only_the_quantity_keeps_the_badge_and_the_note(
        self,
        client: TestClient,
        badge_headers: dict[str, str],
        db_session: Session,
        badge_take: StockTake,
    ) -> None:
        line_id = _line(db_session, badge_take.id).id
        first = _count(
            client,
            badge_headers,
            badge_take.id,
            line_id,
            {
                'counted_quantity': 10,
                'shelf_location': 'RV-A-01',
                'notes': 'first pass',
            },
        )
        assert first.status_code == status.HTTP_200_OK, first.text

        second = _count(
            client,
            badge_headers,
            badge_take.id,
            line_id,
            {'counted_quantity': 9},
        )
        assert second.status_code == status.HTTP_200_OK, second.text

        db_session.expire_all()
        row = _line(db_session, badge_take.id)
        assert row.counted_quantity == Decimal('9')
        assert row.location_in_storage == 'RV-A-01', (
            'the location badge vanished because the save did not mention it'
        )
        assert row.notes == 'first pass'

    def test_a_named_null_clears_the_badge_and_the_note(
        self,
        client: TestClient,
        badge_headers: dict[str, str],
        db_session: Session,
        badge_take: StockTake,
    ) -> None:
        """The other half: carrying the key as null is the instruction to
        clear it, and a writer fixed only in the first direction would keep
        the badge for ever."""
        line_id = _line(db_session, badge_take.id).id
        first = _count(
            client,
            badge_headers,
            badge_take.id,
            line_id,
            {
                'counted_quantity': 10,
                'shelf_location': 'RV-A-01',
                'notes': 'first pass',
            },
        )
        assert first.status_code == status.HTTP_200_OK, first.text

        cleared = _count(
            client,
            badge_headers,
            badge_take.id,
            line_id,
            {
                'counted_quantity': 9,
                'shelf_location': None,
                'notes': None,
            },
        )
        assert cleared.status_code == status.HTTP_200_OK, cleared.text

        db_session.expire_all()
        row = _line(db_session, badge_take.id)
        assert row.location_in_storage is None
        assert row.notes is None
        assert row.counted_quantity == Decimal('9')

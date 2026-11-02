"""A count that finished part of the shelf says so on its own report.

A partial count is an ordinary thing — a cycle count is one by definition,
and ``require_full_count`` exists so a warehouse can close one. But the
report built at finalization filled its own summary in by hand:
``counted_items`` was the number of rows the count had, whether or not
anybody had counted them, and ``progress_percent`` was the literal 100.0.

So the same page said twelve of twelve counted, at a hundred per cent, and
three not counted. The figures the rest of the app computes — the ones on the
list, on the detail screen and in the report endpoint — said something else,
which is worse than either answer alone.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi import status
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.testing import ModuleTestHelper
from app.models.item import Item
from app.models.organization import Organization
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.user import User
from app.modules.stock_takes.models import StockTake, StockTakeItem, StockTakeStatus


@pytest.fixture
def part_org(db_session: Session) -> Organization:
    return ModuleTestHelper(db_session).create_org(
        'Partial Count Org', ['core', 'items', 'locations', 'categories', 'stock_takes']
    )


@pytest.fixture
def part_user(db_session: Session, part_org: Organization) -> User:
    return ModuleTestHelper(db_session).create_user(
        part_org, email='part@example.com', role='manager'
    )


@pytest.fixture
def part_headers(db_session: Session, part_user: User) -> dict[str, str]:
    return ModuleTestHelper(db_session).get_auth_headers(part_user)


@pytest.fixture
def part_location(
    db_session: Session, part_org: Organization, part_user: User
) -> StorageLocation:
    h = ModuleTestHelper(db_session)
    storage_type: StorageType = h.create_storage_type(
        'Warehouse', 'WAREHOUSE', organization_id=part_org.id
    )
    return h.create_storage_location(
        part_org, storage_type, part_user, name='Half-counted shelf'
    )


def _three_rows_one_uncounted(
    db_session: Session,
    org: Organization,
    user: User,
    location: StorageLocation,
) -> StockTake:
    stock_take = StockTake(
        user_id=user.id,
        organization_id=org.id,
        storage_location_id=location.id,
        name='Partial count',
        status=StockTakeStatus.IN_PROGRESS,
        require_full_count=False,
    )
    db_session.add(stock_take)
    db_session.flush()
    for index, counted in enumerate((Decimal('5'), Decimal('5'), None), start=1):
        item = Item(
            name=f'Row {index}',
            organization_id=org.id,
            storage_location_id=location.id,
            quantity=Decimal('5'),
        )
        db_session.add(item)
        db_session.flush()
        db_session.add(
            StockTakeItem(
                stock_take_id=stock_take.id,
                item_id=item.id,
                item_name=item.name,
                system_quantity=Decimal('5'),
                counted_quantity=counted,
            )
        )
    db_session.commit()
    db_session.refresh(stock_take)
    return stock_take


@pytest.mark.integration
class TestAPartialCountReportsItselfPartial:
    def test_the_report_counts_the_rows_somebody_counted(
        self,
        client: TestClient,
        part_headers: dict[str, str],
        db_session: Session,
        part_org: Organization,
        part_user: User,
        part_location: StorageLocation,
    ) -> None:
        take = _three_rows_one_uncounted(db_session, part_org, part_user, part_location)
        resp = client.post(
            f'/api/v1/stock-takes/{take.id}/complete',
            headers=part_headers,
            json={'apply_adjustments': False},
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        report = resp.json()
        assert report['total_items'] == 3
        assert report['not_counted'] == 1
        assert report['counted_items'] == 2
        assert report['progress_percent'] < 100

    def test_a_full_count_still_reads_as_finished(
        self,
        client: TestClient,
        part_headers: dict[str, str],
        db_session: Session,
        part_org: Organization,
        part_user: User,
        part_location: StorageLocation,
    ) -> None:
        """The control: nothing changes for the count that did the whole shelf."""
        take = _three_rows_one_uncounted(db_session, part_org, part_user, part_location)
        last = (
            db_session.query(StockTakeItem)
            .filter(
                StockTakeItem.stock_take_id == take.id,
                StockTakeItem.counted_quantity.is_(None),
            )
            .one()
        )
        last.counted_quantity = Decimal('5')
        db_session.commit()

        resp = client.post(
            f'/api/v1/stock-takes/{take.id}/complete',
            headers=part_headers,
            json={'apply_adjustments': False},
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        report = resp.json()
        assert report['not_counted'] == 0
        assert report['counted_items'] == 3
        assert report['progress_percent'] == 100

"""What happens when a counted number is far above the system quantity.

The growth cap used to rewrite the counted number in silence: count 20 where
the system says 2 and the item ended up at 10, while the report kept claiming
20. Industry practice for a physical inventory is the opposite — a count
outside tolerance is *flagged*, never edited, and posting it takes an explicit
decision that leaves a trace of who made it.
"""

from decimal import Decimal

import pytest
from fastapi import status
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models.audit_log import AuditLog
from app.models.item import Item
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.stock_takes.models import StockTake, StockTakeItem, StockTakeStatus


def _stock_take_with_count(
    db_session: Session,
    storage: StorageLocation,
    user: User,
    counts: list[tuple[Item, Decimal]],
    *,
    name: str = 'Fridge',
) -> StockTake:
    """An in-progress stock take holding one row per (item, counted) pair."""
    stock_take = StockTake(
        user_id=user.id,
        organization_id=storage.organization_id,
        storage_location_id=storage.id,
        name=name,
        status=StockTakeStatus.IN_PROGRESS,
    )
    db_session.add(stock_take)
    db_session.flush()
    for item, counted in counts:
        db_session.add(
            StockTakeItem(
                stock_take_id=stock_take.id,
                item_id=item.id,
                item_name=item.name,
                system_quantity=item.quantity,
                counted_quantity=counted,
            )
        )
    db_session.commit()
    db_session.refresh(stock_take)
    return stock_take


@pytest.mark.integration
class TestACountFarAboveTheSystemIsFlaggedNotRewritten:
    """The cap holds the posting back instead of editing the count."""

    def test_completing_over_the_cap_is_refused_and_changes_nothing(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_storage_location: StorageLocation,
        test_item: Item,
        test_user: User,
    ) -> None:
        stock_take = _stock_take_with_count(
            db_session,
            test_storage_location,
            test_user,
            [(test_item, Decimal('20'))],  # system says 2 — ten times over
        )

        response = client.post(
            f'/api/v1/stock-takes/{stock_take.id}/complete',
            headers=auth_headers,
            json={'apply_adjustments': True},
        )

        assert response.status_code == status.HTTP_409_CONFLICT
        db_session.refresh(test_item)
        assert test_item.quantity == Decimal('2')
        db_session.refresh(stock_take)
        assert stock_take.status == StockTakeStatus.IN_PROGRESS

    def test_the_refusal_names_every_row_it_stopped_on(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_storage_location: StorageLocation,
        test_item: Item,
        test_user: User,
    ) -> None:
        stock_take = _stock_take_with_count(
            db_session,
            test_storage_location,
            test_user,
            [(test_item, Decimal('20'))],
        )

        response = client.post(
            f'/api/v1/stock-takes/{stock_take.id}/complete',
            headers=auth_headers,
            json={'apply_adjustments': True},
        )

        detail = response.json()['detail']
        assert detail['code'] == 'STOCK_TAKE_OVER_CAP'
        rows = detail['over_cap_items']
        assert len(rows) == 1
        assert rows[0]['item_name'] == test_item.name
        assert Decimal(str(rows[0]['system_quantity'])) == Decimal('2')
        assert Decimal(str(rows[0]['counted_quantity'])) == Decimal('20')
        assert Decimal(str(rows[0]['cap'])) == Decimal('10')

    def test_an_explicit_acceptance_writes_the_number_that_was_counted(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_storage_location: StorageLocation,
        test_item: Item,
        test_user: User,
    ) -> None:
        stock_take = _stock_take_with_count(
            db_session,
            test_storage_location,
            test_user,
            [(test_item, Decimal('20'))],
        )

        response = client.post(
            f'/api/v1/stock-takes/{stock_take.id}/complete',
            headers=auth_headers,
            json={'apply_adjustments': True, 'force_over_cap': True},
        )

        assert response.status_code == status.HTTP_200_OK
        db_session.refresh(test_item)
        assert test_item.quantity == Decimal('20')  # 20, not the old cap of 10

    def test_accepting_the_overrun_leaves_a_trace_of_who_did_it(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_storage_location: StorageLocation,
        test_item: Item,
        test_user: User,
    ) -> None:
        stock_take = _stock_take_with_count(
            db_session,
            test_storage_location,
            test_user,
            [(test_item, Decimal('20'))],
        )

        client.post(
            f'/api/v1/stock-takes/{stock_take.id}/complete',
            headers=auth_headers,
            json={'apply_adjustments': True, 'force_over_cap': True},
        )

        entries = (
            db_session.execute(
                select(AuditLog).where(
                    AuditLog.organization_id == test_storage_location.organization_id,
                    AuditLog.target_type == 'stock_take',
                )
            )
            .scalars()
            .all()
        )
        assert len(entries) == 1
        entry = entries[0]
        assert entry.user_id is not None
        assert entry.snapshot is not None
        assert entry.snapshot['over_cap_accepted'] == 1


@pytest.mark.integration
class TestTheLogSaysWhatTheStockTakeActuallyDid:
    """No entry for a row that did not move, and the rest carry why."""

    def test_counts_matching_the_system_leave_no_quantity_entries(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_storage_location: StorageLocation,
        test_items_batch: list[Item],
        test_user: User,
    ) -> None:
        stock_take = _stock_take_with_count(
            db_session,
            test_storage_location,
            test_user,
            [(item, item.quantity) for item in test_items_batch],
        )

        response = client.post(
            f'/api/v1/stock-takes/{stock_take.id}/complete',
            headers=auth_headers,
            json={'apply_adjustments': True},
        )

        assert response.status_code == status.HTTP_200_OK
        quantity_entries = (
            db_session.execute(
                select(AuditLog).where(
                    AuditLog.organization_id == test_storage_location.organization_id,
                    AuditLog.action == 'QUANTITY_CHANGE',
                )
            )
            .scalars()
            .all()
        )
        assert quantity_entries == []

    def test_a_real_correction_says_it_came_from_a_stock_take(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_storage_location: StorageLocation,
        test_item: Item,
        test_user: User,
    ) -> None:
        stock_take = _stock_take_with_count(
            db_session,
            test_storage_location,
            test_user,
            [(test_item, Decimal('3'))],  # within the cap, a genuine correction
        )

        client.post(
            f'/api/v1/stock-takes/{stock_take.id}/complete',
            headers=auth_headers,
            json={'apply_adjustments': True},
        )

        entry = (
            db_session.execute(
                select(AuditLog).where(
                    AuditLog.organization_id == test_storage_location.organization_id,
                    AuditLog.action == 'QUANTITY_CHANGE',
                )
            )
            .scalars()
            .one()
        )
        assert entry.reason == 'stock_take_adjustment'
        assert entry.meta_data is not None
        assert entry.meta_data['stock_take_id'] == str(stock_take.id)

    def test_finishing_a_stock_take_is_itself_an_entry_in_the_log(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_storage_location: StorageLocation,
        test_items_batch: list[Item],
        test_user: User,
    ) -> None:
        stock_take = _stock_take_with_count(
            db_session,
            test_storage_location,
            test_user,
            [(item, item.quantity) for item in test_items_batch],
            name='Fridge, Monday',
        )

        client.post(
            f'/api/v1/stock-takes/{stock_take.id}/complete',
            headers=auth_headers,
            json={'apply_adjustments': True},
        )

        entry = (
            db_session.execute(
                select(AuditLog).where(
                    AuditLog.organization_id == test_storage_location.organization_id,
                    AuditLog.target_type == 'stock_take',
                )
            )
            .scalars()
            .one()
        )
        assert entry.target_id == stock_take.id
        assert entry.snapshot is not None
        assert entry.snapshot['name'] == 'Fridge, Monday'
        assert entry.snapshot['counted_items'] == len(test_items_batch)
        assert entry.snapshot['adjusted_items'] == 0

"""
Integration tests for stock take finalize traceability.

Verifies that stock take adjustments are recorded in ItemHistory
with stock_take_id in the changes dict.
"""

import pytest
from fastapi import status
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models.item import Item
from app.models.item_history import ItemHistory
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.stock_takes.models import StockTake, StockTakeItem, StockTakeStatus


@pytest.mark.integration
class TestFinalizeTraceability:
    """Tests for item history recording during stock take finalization."""

    def test_finalize_with_adjustments_records_stock_take_in_history(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_storage_location: StorageLocation,
        test_items_batch: list[Item],
        test_user: User,
    ) -> None:
        """Finalize with adjustments must record stock_take_id in ItemHistory.changes."""
        org_id = test_items_batch[0].storage_location.organization_id

        stock_take = StockTake(
            user_id=test_user.id,
            organization_id=org_id,
            storage_location_id=test_storage_location.id,
            name='Traceability Test',
            status=StockTakeStatus.IN_PROGRESS,
        )
        db_session.add(stock_take)
        db_session.flush()

        # Add items with different counted quantities to trigger adjustments
        for item in test_items_batch:
            stock_take_item = StockTakeItem(
                stock_take_id=stock_take.id,
                item_id=item.id,
                item_name=item.name,
                system_quantity=item.quantity,
                # A deliberate mismatch, but inside the growth tolerance:
                # past it the posting is refused rather than applied.
                counted_quantity=item.quantity + 1,
            )
            db_session.add(stock_take_item)

        db_session.commit()

        response = client.post(
            f'/api/v1/stock-takes/{stock_take.id}/complete',
            headers=auth_headers,
            json={'apply_adjustments': True},
        )

        assert response.status_code == status.HTTP_200_OK

        # Verify ItemHistory entries have stock_take_id
        result = db_session.execute(
            select(ItemHistory).where(
                ItemHistory.organization_id == org_id,
            )
        )
        history_entries = result.scalars().all()

        adjustment_entries = [
            h
            for h in history_entries
            if h.changes and h.changes.get('reason') == 'stock_take_adjustment'
        ]

        assert len(adjustment_entries) == len(test_items_batch)
        for entry in adjustment_entries:
            assert entry.changes is not None
            assert entry.changes['stock_take_id'] == str(stock_take.id)

    def test_finalize_without_adjustments_creates_no_history(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_storage_location: StorageLocation,
        test_items_batch: list[Item],
        test_user: User,
    ) -> None:
        """Finalize without applying adjustments must not create adjustment history."""
        org_id = test_items_batch[0].storage_location.organization_id

        stock_take = StockTake(
            user_id=test_user.id,
            organization_id=org_id,
            storage_location_id=test_storage_location.id,
            name='No Adjustments Test',
            status=StockTakeStatus.IN_PROGRESS,
        )
        db_session.add(stock_take)
        db_session.flush()

        for item in test_items_batch:
            stock_take_item = StockTakeItem(
                stock_take_id=stock_take.id,
                item_id=item.id,
                item_name=item.name,
                system_quantity=item.quantity,
                counted_quantity=item.quantity,
            )
            db_session.add(stock_take_item)

        db_session.commit()

        response = client.post(
            f'/api/v1/stock-takes/{stock_take.id}/complete',
            headers=auth_headers,
            json={'apply_adjustments': False},
        )

        assert response.status_code == status.HTTP_200_OK

        # Count history entries after
        after_count = (
            db_session.execute(
                select(ItemHistory).where(ItemHistory.organization_id == org_id)
            )
            .scalars()
            .all()
        )

        # No new adjustment entries should be created
        adjustment_after = [
            h
            for h in after_count
            if h.changes and h.changes.get('reason') == 'stock_take_adjustment'
        ]
        assert len(adjustment_after) == 0

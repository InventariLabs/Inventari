"""
The report must answer "was this count clean?" without lying.

``is_discrepancy`` means "beyond the tolerance — somebody must explain it".
The report used to read it as "differs", so a row the tolerance excused was
published as a perfect match while the correction it produced sat in the
ledger, and the list card said "0 discrepancies" about a completion that
overwrote a product's stock.
"""

from decimal import Decimal
from uuid import uuid4

from fastapi import status
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models.item import Item
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.stock_takes.models import (
    StockTake,
    StockTakeItem,
    StockTakeStatus,
)
from app.modules.stock_takes.stock_take_service import (
    calculate_discrepancy_stats,
)


def _row(
    counted: str | None,
    system: str,
    is_discrepancy: int,
) -> StockTakeItem:
    return StockTakeItem(
        stock_take_id=uuid4(),
        item_name='whatever',
        system_quantity=Decimal(system),
        counted_quantity=Decimal(counted) if counted else None,
        is_discrepancy=is_discrepancy,
    )


class TestCalculateDiscrepancyStats:
    def test_a_row_the_tolerance_excused_is_not_a_perfect_match(self) -> None:
        # The shape: eight counted rows — six exact, one inside the
        # tolerance (2.1 against 2.3, −8.7% of a 10% tolerance), one beyond it.
        items = (
            [_row('5.000', '5.000', 0) for _ in range(6)]
            + [_row('2.100', '2.300', 0)]
            + [_row('4.000', '5.000', 1)]
        )

        stats = calculate_discrepancy_stats(items)

        assert stats['perfect_matches'] == 6
        assert stats['tolerated_differences'] == 1
        assert stats['understock'] == 1
        assert stats['overstock'] == 0
        assert stats['not_counted'] == 0

    def test_uncounted_and_equal_rows_stay_where_they_were(self) -> None:
        items = [
            _row(None, '3.000', 0),
            _row('3.000', '3.000', 0),
            _row('4.000', '3.000', 1),
        ]

        stats = calculate_discrepancy_stats(items)

        assert stats['perfect_matches'] == 1
        assert stats['tolerated_differences'] == 0
        assert stats['not_counted'] == 1
        assert stats['overstock'] == 1


class TestTheCountAgreesWithTheDialog:
    def test_report_counts_what_the_completion_overwrote(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_storage_location: StorageLocation,
        test_items_batch: list[Item],
        test_user: User,
    ) -> None:
        """The report's N is the dialog's N: rows whose stock gets overwritten."""
        org_id = test_items_batch[0].storage_location.organization_id

        stock_take = StockTake(
            user_id=test_user.id,
            organization_id=org_id,
            storage_location_id=test_storage_location.id,
            name='Honest report',
            status=StockTakeStatus.IN_PROGRESS,
            tolerance_percent=10,
        )
        db_session.add(stock_take)
        db_session.flush()

        exact_item, weighed_item = test_items_batch[0], test_items_batch[1]
        # The snapshot has to match the shelf: a count against a quantity the
        # stock no longer has is refused at the door (STOCK_TAKE_STOCK_MOVED).
        exact_system = Decimal(str(exact_item.quantity))
        weighed_system = Decimal(str(weighed_item.quantity))
        # +5% — inside the 10% tolerance, so the row is accepted without an
        # explanation and still overwrites the stock.
        weighed_counted = weighed_system * Decimal('1.05')
        rows = [
            StockTakeItem(
                stock_take_id=stock_take.id,
                item_id=exact_item.id,
                item_name=exact_item.name,
                system_quantity=exact_system,
            ),
            StockTakeItem(
                stock_take_id=stock_take.id,
                item_id=weighed_item.id,
                item_name=weighed_item.name,
                system_quantity=weighed_system,
            ),
        ]
        db_session.add_all(rows)
        db_session.commit()

        # Count one row exactly and one just inside the tolerance.
        for row, counted in zip(rows, [exact_system, weighed_counted], strict=True):
            response = client.patch(
                f'/api/v1/stock-takes/{stock_take.id}/items/{row.id}/count',
                headers=auth_headers,
                json={'counted_quantity': float(counted)},
            )
            assert response.status_code == status.HTTP_200_OK

        completion = client.post(
            f'/api/v1/stock-takes/{stock_take.id}/complete',
            headers=auth_headers,
            json={'apply_adjustments': True},
        )
        assert completion.status_code == status.HTTP_200_OK, completion.text
        report = completion.json()

        # One exact row: a perfect match. One excused row: a difference the
        # tolerance accepted — visible, named, not folded into "perfect".
        assert report['perfect_matches'] == 1
        assert report['tolerated_differences'] == 1
        assert report['overstock'] == 0
        assert report['understock'] == 0
        # And the number the confirmation dialog named before the button:
        # one product's stock was overwritten.
        assert report['discrepancies'] == 1
        assert [item['item_name'] for item in report['tolerated_items']] == [
            weighed_item.name
        ]

    def test_list_card_counts_differences_not_explanations(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_storage_location: StorageLocation,
        test_items_batch: list[Item],
        test_user: User,
    ) -> None:
        """A tolerated difference still reaches the list card's number."""
        org_id = test_items_batch[0].storage_location.organization_id

        stock_take = StockTake(
            user_id=test_user.id,
            organization_id=org_id,
            storage_location_id=test_storage_location.id,
            name='Card count',
            status=StockTakeStatus.IN_PROGRESS,
            tolerance_percent=10,
        )
        db_session.add(stock_take)
        db_session.flush()

        weighed = test_items_batch[0]
        row = StockTakeItem(
            stock_take_id=stock_take.id,
            item_id=weighed.id,
            item_name=weighed.name,
            system_quantity=Decimal('2.300'),
        )
        db_session.add(row)
        db_session.commit()

        counted = client.patch(
            f'/api/v1/stock-takes/{stock_take.id}/items/{row.id}/count',
            headers=auth_headers,
            json={'counted_quantity': 2.1},
        )
        assert counted.status_code == status.HTTP_200_OK

        fetched = client.get(
            f'/api/v1/stock-takes/{stock_take.id}',
            headers=auth_headers,
        )
        assert fetched.status_code == status.HTTP_200_OK
        # The tolerance flags nothing here, yet one product's stock would be
        # overwritten — the card has to say so.
        assert fetched.json()['discrepancies_count'] == 1

    def test_report_names_who_began_the_count(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_storage_location: StorageLocation,
        test_items_batch: list[Item],
        test_user: User,
    ) -> None:
        """The report lands in a binder as counting evidence, so it has to
        be attributable — it carries the name of who began the count."""
        org_id = test_items_batch[0].storage_location.organization_id

        stock_take = StockTake(
            user_id=test_user.id,
            organization_id=org_id,
            storage_location_id=test_storage_location.id,
            name='Signed count',
            status=StockTakeStatus.IN_PROGRESS,
        )
        db_session.add(stock_take)
        db_session.commit()

        fetched = client.get(
            f'/api/v1/stock-takes/{stock_take.id}/report',
            headers=auth_headers,
        )
        assert fetched.status_code == status.HTTP_200_OK
        assert fetched.json()['started_by_name'] == (
            test_user.full_name or test_user.email
        )

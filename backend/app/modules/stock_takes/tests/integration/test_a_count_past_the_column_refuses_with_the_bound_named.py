"""A count past what the stock-take column stores is refused with the bound named.

``stock_take_items.counted_quantity`` (and the counting passes beside it) are
``numeric(10, 3)`` — narrower than the items column the QUANTITY_MAX ceiling is
derived from. A count past 9,999,999.999 never reaches the items writer, so
its sentence is unreachable here: the doors wrote the column directly and the
driver answered with an overflow. The ceiling stands on the stock-take's own
writer (``count_item_and_commit`` and its bulk and surplus siblings), and the
counting schemas mirror it so the HTTP doors answer 422 before the service is
entered at all.
"""

from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.modules.stock_takes.models import StockTakeItem
from app.modules.stock_takes.schemas import (
    COUNTED_QUANTITY_MAX,
    StockTakeItemCountUpdate,
    StockTakeItemCreate,
    StockTakeItemUpdate,
)


def _kg_uom_id(db_session: Session) -> Any:
    return db_session.execute(
        text('SELECT id FROM uoms WHERE symbol = :s'), {'s': 'kg'}
    ).scalar()


def _rows(
    client: TestClient, auth_headers: dict[str, str], stock_take: Any
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = client.get(
        f'/api/v1/stock-takes/{stock_take.id}/items', headers=auth_headers
    ).json()['items']
    return rows


@pytest.mark.integration
class TestTheCountColumnCeiling:
    """The count column is numeric(10, 3): a count past its largest storable
    value is refused with the bound named, on every door that writes it —
    not with the driver's overflow."""

    def test_the_count_door_refuses_a_count_past_the_column(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_stock_take: Any,
    ) -> None:
        rows = _rows(client, auth_headers, test_stock_take)

        response = client.patch(
            f'/api/v1/stock-takes/{test_stock_take.id}/items/{rows[0]["id"]}/count',
            headers=auth_headers,
            json={'counted_quantity': 10000000},
        )

        assert response.status_code == 422, response.text
        assert response.json()['detail'][0]['type'] == 'less_than_equal'
        stored = client.get(
            f'/api/v1/stock-takes/{test_stock_take.id}/items', headers=auth_headers
        ).json()['items']
        row = next(r for r in stored if r['id'] == rows[0]['id'])
        assert row['counted_quantity'] is None

    def test_the_count_door_accepts_the_largest_storable_value(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_stock_take: Any,
        db_session: Session,
    ) -> None:
        # Boundary control: the largest storable value goes through — on a
        # decimal-capable unit, since the whole-number gate on pieces would
        # refuse the fraction before the ceiling had a say. Passes before
        # and after the guard; it is here so the refusal cannot be the
        # unit gate wearing the ceiling's name.
        rows = _rows(client, auth_headers, test_stock_take)
        row = db_session.get(StockTakeItem, rows[0]['id'])
        assert row is not None
        row.uom_id = _kg_uom_id(db_session)
        db_session.commit()

        response = client.patch(
            f'/api/v1/stock-takes/{test_stock_take.id}/items/{rows[0]["id"]}/count',
            headers=auth_headers,
            json={'counted_quantity': '9999999.999'},
        )

        assert response.status_code == 200, response.text
        assert Decimal(response.json()['counted_quantity']) == Decimal('9999999.999')

    def test_the_bulk_count_door_refuses_a_count_past_the_column(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_stock_take: Any,
    ) -> None:
        rows = _rows(client, auth_headers, test_stock_take)

        response = client.patch(
            f'/api/v1/stock-takes/{test_stock_take.id}/items/bulk-count',
            headers=auth_headers,
            json=[
                {'item_id': rows[0]['id'], 'counted_quantity': 1},
                {'item_id': rows[1]['id'], 'counted_quantity': 10000000},
            ],
        )

        assert response.status_code == 422, response.text
        assert response.json()['detail'][0]['type'] == 'less_than_equal'

    def test_the_surplus_door_refuses_a_count_past_the_column(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_stock_take: Any,
        test_item: Any,
    ) -> None:
        response = client.post(
            f'/api/v1/stock-takes/{test_stock_take.id}/items',
            headers=auth_headers,
            json={'item_id': str(test_item.id), 'counted_quantity': 10000000},
        )

        assert response.status_code == 422, response.text
        assert response.json()['detail'][0]['type'] == 'less_than_equal'

    def test_the_counting_schemas_mirror_the_column(self) -> None:
        # The bound travels on the input schemas, the column's own shape —
        # never on the response side: a read must not refuse.
        with pytest.raises(ValueError):
            StockTakeItemCountUpdate(counted_quantity=10000000)
        with pytest.raises(ValueError):
            StockTakeItemUpdate(counted_quantity=10000000)
        with pytest.raises(ValueError):
            StockTakeItemCreate(item_name='Past the column', counted_quantity=10000000)
        assert StockTakeItemCountUpdate(
            counted_quantity=COUNTED_QUANTITY_MAX
        ).counted_quantity == Decimal('9999999.999')

    @pytest.mark.asyncio
    async def test_the_writer_refuses_a_count_past_the_column(
        self,
        real_async_db_session: Any,
        async_test_user: Any,
        async_test_storage_location: Any,
    ) -> None:
        # The writer every door past the schema edge passes: a caller that
        # builds a count in code — model_construct stands in for the parse
        # the mirrors already do — meets the keyed refusal, not the column.
        from app.core.exceptions import ServiceRejectionError
        from app.modules.stock_takes._stock_take_crud import count_item_and_commit
        from app.modules.stock_takes.models import (
            StockTake,
            StockTakeItem,
            StockTakeStatus,
        )

        stock_take = StockTake(
            user_id=async_test_user.id,
            organization_id=async_test_user.organization_id,
            storage_location_id=async_test_storage_location.id,
            name='Counted past the column',
            status=StockTakeStatus.IN_PROGRESS,
        )
        real_async_db_session.add(stock_take)
        await real_async_db_session.flush()
        row = StockTakeItem(
            stock_take_id=stock_take.id,
            item_name='Past the column',
            system_quantity=Decimal('2'),
        )
        real_async_db_session.add(row)
        await real_async_db_session.flush()

        assert async_test_user.organization_id is not None
        with pytest.raises(ServiceRejectionError) as refused:
            await count_item_and_commit(
                real_async_db_session,
                row,
                StockTakeItemCountUpdate.model_construct(
                    counted_quantity=Decimal('10000000')
                ),
                user_id=async_test_user.id,
                organization_id=async_test_user.organization_id,
            )

        assert refused.value.key == 'counted_quantity_above_ceiling'

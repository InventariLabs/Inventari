"""An order is numbered under the year it is dated to, not the year it was typed.

The year in the number came from the clock: an order entered in January
and dated to the December it belongs to was filed under January. Receipts
had already been fixed to number by their own date; the orders they are
made from had not.
"""

from __future__ import annotations

from typing import Any, cast

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.modules.warehouse.models.profile import DEFAULT_NUMBER_PADDING


def _order_dated(
    client: TestClient,
    headers: dict[str, str],
    *,
    partner_id: Any,
    scheduled_date: str | None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        'partner_id': str(partner_id),
        'lines': [{'name': 'Olive oil', 'quantity_ordered': '1', 'unit_price': '1.00'}],
    }
    if scheduled_date is not None:
        body['scheduled_date'] = scheduled_date
    resp = client.post('/api/v1/purchase-orders', headers=headers, json=body)
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    return cast(dict[str, Any], resp.json())


@pytest.mark.integration
class TestAnOrderIsNumberedByItsOwnDate:
    def test_a_backdated_order_is_filed_under_its_own_year(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        po_partner: Any,
    ) -> None:
        order = _order_dated(
            client,
            po_auth_headers,
            partner_id=po_partner.id,
            scheduled_date='2025-12-15',
        )
        assert order['number'] == f'PO/2025/{1:0{DEFAULT_NUMBER_PADDING}d}'

    def test_a_draft_moved_to_another_year_is_renumbered_there(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        po_partner: Any,
    ) -> None:
        order = _order_dated(
            client,
            po_auth_headers,
            partner_id=po_partner.id,
            scheduled_date='2025-12-15',
        )
        moved = client.patch(
            f'/api/v1/purchase-orders/{order["id"]}',
            headers=po_auth_headers,
            json={'scheduled_date': '2026-01-10'},
        )
        assert moved.status_code == status.HTTP_200_OK, moved.text
        assert moved.json()['number'] == f'PO/2026/{1:0{DEFAULT_NUMBER_PADDING}d}'

    def test_a_draft_moved_within_its_year_keeps_its_number(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        po_partner: Any,
    ) -> None:
        order = _order_dated(
            client,
            po_auth_headers,
            partner_id=po_partner.id,
            scheduled_date='2026-01-10',
        )
        moved = client.patch(
            f'/api/v1/purchase-orders/{order["id"]}',
            headers=po_auth_headers,
            json={'scheduled_date': '2026-03-01'},
        )
        assert moved.status_code == status.HTTP_200_OK, moved.text
        assert moved.json()['number'] == order['number']

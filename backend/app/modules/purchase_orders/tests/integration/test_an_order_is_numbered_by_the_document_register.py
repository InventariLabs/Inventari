"""Orders are numbered by the register the organization already keeps.

Purchase orders used to carry a numbering engine of their own — its own
advisory lock, its own regex over `PO/{year}/{seq}`, the shape hardcoded —
beside the one every document goes through. An organization that changed
how its documents are numbered saw the change everywhere except on its
orders, and two counters were kept in step by hand.

The risk in moving them across is the counter's starting point: the engine
seeds a new counter from the highest number already in use, and it looks in
`documents`, where no order has ever been. An organization a year into its
register must not be offered number one again.
"""

from __future__ import annotations

from typing import Any, cast

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.modules.warehouse.models.profile import DEFAULT_NUMBER_PADDING


def _raise_order(
    client: TestClient, headers: dict[str, str], partner_id: Any
) -> dict[str, Any]:
    resp = client.post(
        '/api/v1/purchase-orders',
        headers=headers,
        json={
            'partner_id': str(partner_id),
            'scheduled_date': '2026-05-04',
            'lines': [
                {'name': 'Olive oil', 'quantity_ordered': '1', 'unit_price': '1.00'}
            ],
        },
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    return cast(dict[str, Any], resp.json())


@pytest.mark.integration
class TestAnOrderIsNumberedByTheDocumentRegister:
    def test_numbers_run_on_from_the_orders_already_on_file(
        self,
        client: TestClient,
        db_session: Session,
        po_org: Organization,
        po_user: Any,
        po_auth_headers: dict[str, str],
        po_partner: Any,
    ) -> None:
        """An order raised before the counter existed still counts.

        This is the upgrade case: the rows are there, the counter row is
        not, and the unique index on (organization, number) turns a wrong
        starting point into a refused order rather than a duplicate.
        """
        from app.modules.purchase_orders.models import PurchaseOrder

        db_session.add(
            PurchaseOrder(
                organization_id=po_org.id,
                partner_id=po_partner.id,
                number=f'PO/2026/{7:0{DEFAULT_NUMBER_PADDING}d}',
                status='DRAFT',
                currency='PLN',
                created_by=po_user.id,
            )
        )
        db_session.commit()

        order = _raise_order(client, po_auth_headers, po_partner.id)
        assert order['number'] == f'PO/2026/{8:0{DEFAULT_NUMBER_PADDING}d}'

    def test_two_orders_in_a_row_take_two_numbers(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        po_partner: Any,
    ) -> None:
        first = _raise_order(client, po_auth_headers, po_partner.id)
        second = _raise_order(client, po_auth_headers, po_partner.id)

        # The width is the shared default, not a literal: an organization
        # with no profile is numbered by the same rule as one with the
        # preset it is about to get.
        assert first['number'] == f'PO/2026/{1:0{DEFAULT_NUMBER_PADDING}d}'
        assert second['number'] == f'PO/2026/{2:0{DEFAULT_NUMBER_PADDING}d}'

    def test_the_organizations_document_format_reaches_its_orders(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        po_partner: Any,
    ) -> None:
        """The point of the move: one format, one place to change it."""
        profile = client.put(
            '/api/v1/warehouse/profile',
            headers=po_auth_headers,
            json={'numbering_format': '{TYPE}-{YEAR}-{SEQ:05d}', 'number_padding': 5},
        )
        assert profile.status_code == status.HTTP_200_OK, profile.text

        order = _raise_order(client, po_auth_headers, po_partner.id)
        assert order['number'] == 'PO-2026-00001'

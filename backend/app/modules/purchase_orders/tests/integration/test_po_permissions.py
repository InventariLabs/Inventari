"""Permission enforcement and payload guards on purchase orders.

``purchase_orders:read`` / ``purchase_orders:write`` were declared in the
manifest and checked nowhere: confirming an order, turning it into a receipt
or e-mailing a supplier was open to every member of the organization. The
guard is mounted on the module router, so these tests pin the boundary.
"""

from typing import Any

import pytest
from fastapi import status
from starlette.testclient import TestClient

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization

BASE = '/api/v1/purchase-orders'


def _payload(partner: Any, template: Any) -> dict[str, Any]:
    return {
        'partner_id': str(partner.id),
        'lines': [
            {
                'product_template_id': str(template.id),
                'quantity_ordered': 2,
                'unit_price': '10.00',
            }
        ],
    }


@pytest.mark.integration
class TestPurchaseOrderPermissions:
    def test_operator_without_role_row_keeps_write_access(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        po_org: Organization,
        po_partner: Any,
        po_template: Any,
    ) -> None:
        user = h.create_user(po_org, email='po-operator@example.com', role='user')
        resp = client.post(
            BASE,
            headers=h.get_auth_headers(user),
            json=_payload(po_partner, po_template),
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text

    def test_viewer_reads_but_cannot_order(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        po_org: Organization,
        po_partner: Any,
        po_template: Any,
    ) -> None:
        headers = h.get_auth_headers(
            h.create_user(po_org, email='po-viewer@example.com', role='viewer')
        )
        assert client.get(BASE, headers=headers).status_code == status.HTTP_200_OK

        resp = client.post(
            BASE, headers=headers, json=_payload(po_partner, po_template)
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN, resp.text

    def test_read_grant_alone_cannot_confirm(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        po_org: Organization,
        po_auth_headers: dict[str, str],
        po_partner: Any,
        po_template: Any,
    ) -> None:
        created = client.post(
            BASE, headers=po_auth_headers, json=_payload(po_partner, po_template)
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        po_id = created.json()['id']

        reader = h.create_user(po_org, email='po-reader@example.com', role='user')
        h.grant_permissions(reader, ['purchase_orders:read'])
        resp = client.post(
            f'{BASE}/{po_id}/confirm', headers=h.get_auth_headers(reader)
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN, resp.text


@pytest.mark.integration
class TestPurchaseOrderUpdateGuards:
    def test_update_cannot_empty_the_order(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        po_partner: Any,
        po_template: Any,
    ) -> None:
        """An order with no lines could be confirmed and sent to a supplier."""
        created = client.post(
            BASE, headers=po_auth_headers, json=_payload(po_partner, po_template)
        )
        po_id = created.json()['id']

        resp = client.patch(
            f'{BASE}/{po_id}', headers=po_auth_headers, json={'lines': []}
        )
        assert resp.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT, resp.text

    def test_update_without_lines_key_leaves_them_untouched(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        po_partner: Any,
        po_template: Any,
    ) -> None:
        created = client.post(
            BASE, headers=po_auth_headers, json=_payload(po_partner, po_template)
        )
        po_id = created.json()['id']

        resp = client.patch(
            f'{BASE}/{po_id}', headers=po_auth_headers, json={'notes': 'call first'}
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        assert len(resp.json()['lines']) == 1


@pytest.mark.integration
class TestPurchaseOrderPartnerFilter:
    def test_list_filters_by_partner(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        po_org: Organization,
        po_auth_headers: dict[str, Any],
        po_partner: Any,
        po_template: Any,
        po_user: Any,
    ) -> None:
        """the partner card links to the orders raised with them."""
        other = h.create_partner(po_org, po_user, name='Other Supplier')
        mine = client.post(
            BASE, headers=po_auth_headers, json=_payload(po_partner, po_template)
        )
        assert mine.status_code == status.HTTP_201_CREATED, mine.text
        theirs = client.post(
            BASE, headers=po_auth_headers, json=_payload(other, po_template)
        )
        assert theirs.status_code == status.HTTP_201_CREATED, theirs.text

        resp = client.get(
            BASE, headers=po_auth_headers, params={'partner_id': str(po_partner.id)}
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        ids = {row['id'] for row in resp.json()['items']}
        assert mine.json()['id'] in ids
        assert theirs.json()['id'] not in ids

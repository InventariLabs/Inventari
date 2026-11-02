"""PO numbering respects the organization's ``number_padding``.

The width used to be hardcoded ``:04d``, then read through an accessor of
its own beside the document numbering engine. Orders now go through that
engine, so the width is simply the one the profile states — and
``DEFAULT_NUMBER_PADDING`` when there is no profile to state one. That
default used to be a second opinion (four here, three in the preset every
organization actually gets), which is how the first document of an
organization came out shaped differently from every one after it.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.modules.warehouse.models.profile import DEFAULT_NUMBER_PADDING


@pytest.mark.integration
class TestPurchaseOrderPadding:
    """Purchase orders honour the org-wide number_padding."""

    def test_po_uses_the_shared_default_padding_when_no_profile(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        po_partner: Any,
    ) -> None:
        """First PO after migration: no profile → the shared default."""
        response = client.post(
            '/api/v1/purchase-orders',
            headers=po_auth_headers,
            json={
                'partner_id': str(po_partner.id),
                'currency': 'PLN',
                'lines': [
                    {
                        'name': 'Item',
                        'quantity_ordered': '1',
                        'unit_price': '1.00',
                        'tax_rate': '0',
                    },
                ],
            },
        )
        assert response.status_code == status.HTTP_201_CREATED
        number = response.json()['number']
        seq_part = number.rsplit('/', 1)[-1]
        assert len(seq_part) == DEFAULT_NUMBER_PADDING, (
            f'expected {DEFAULT_NUMBER_PADDING} digits by default, '
            f'got {seq_part!r} from {number!r}'
        )

    def test_po_respects_profile_padding_3(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        po_partner: Any,
    ) -> None:
        """Setting profile.number_padding=3 produces 3-digit PO sequences."""
        profile_resp = client.put(
            '/api/v1/warehouse/profile',
            headers=po_auth_headers,
            json={'number_padding': 3},
        )
        assert profile_resp.status_code == status.HTTP_200_OK

        response = client.post(
            '/api/v1/purchase-orders',
            headers=po_auth_headers,
            json={
                'partner_id': str(po_partner.id),
                'currency': 'PLN',
                'lines': [
                    {
                        'name': 'Item',
                        'quantity_ordered': '1',
                        'unit_price': '1.00',
                        'tax_rate': '0',
                    },
                ],
            },
        )
        assert response.status_code == status.HTTP_201_CREATED
        number = response.json()['number']
        seq_part = number.rsplit('/', 1)[-1]
        assert len(seq_part) == 3, (
            f'expected 3-digit sequence, got {seq_part!r} from {number!r}'
        )

    def test_po_respects_profile_padding_6(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        po_partner: Any,
    ) -> None:
        """Setting profile.number_padding=6 produces 6-digit PO sequences."""
        profile_resp = client.put(
            '/api/v1/warehouse/profile',
            headers=po_auth_headers,
            json={'number_padding': 6},
        )
        assert profile_resp.status_code == status.HTTP_200_OK

        response = client.post(
            '/api/v1/purchase-orders',
            headers=po_auth_headers,
            json={
                'partner_id': str(po_partner.id),
                'currency': 'PLN',
                'lines': [
                    {
                        'name': 'Item',
                        'quantity_ordered': '1',
                        'unit_price': '1.00',
                        'tax_rate': '0',
                    },
                ],
            },
        )
        assert response.status_code == status.HTTP_201_CREATED
        number = response.json()['number']
        seq_part = number.rsplit('/', 1)[-1]
        assert len(seq_part) == 6, (
            f'expected 6-digit sequence, got {seq_part!r} from {number!r}'
        )

    def test_po_padding_independent_per_org(
        self,
        client: TestClient,
        h: Any,
        po_auth_headers: dict[str, str],
        po_partner: Any,
    ) -> None:
        """Each org keeps its own padding; one org changing padding must not
        leak into another org's POs."""
        other_org = h.create_org(
            'Padding Other Org',
            [
                'core',
                'items',
                'locations',
                'categories',
                'warehouse',
                'purchase_orders',
            ],
        )
        other_user = h.create_user(other_org, email='po-other-padding@example.com')
        other_headers = h.get_auth_headers(other_user)
        other_partner = h.create_partner(
            other_org, other_user, name='Other Supplier', email='other@example.com'
        )

        # First org defaults to 4.
        resp_first = client.post(
            '/api/v1/purchase-orders',
            headers=po_auth_headers,
            json={
                'partner_id': str(po_partner.id),
                'currency': 'PLN',
                'lines': [
                    {
                        'name': 'X',
                        'quantity_ordered': '1',
                        'unit_price': '1.00',
                        'tax_rate': '0',
                    },
                ],
            },
        )
        assert resp_first.status_code == status.HTTP_201_CREATED
        first_seq = resp_first.json()['number'].rsplit('/', 1)[-1]
        assert len(first_seq) == DEFAULT_NUMBER_PADDING

        # Other org uses padding 6 — must not affect first org.
        client.put(
            '/api/v1/warehouse/profile',
            headers=other_headers,
            json={'number_padding': 6},
        )
        resp_other = client.post(
            '/api/v1/purchase-orders',
            headers=other_headers,
            json={
                'partner_id': str(other_partner.id),
                'currency': 'EUR',
                'lines': [
                    {
                        'name': 'Y',
                        'quantity_ordered': '1',
                        'unit_price': '1.00',
                        'tax_rate': '0',
                    },
                ],
            },
        )
        assert resp_other.status_code == status.HTTP_201_CREATED
        other_seq = resp_other.json()['number'].rsplit('/', 1)[-1]
        assert len(other_seq) == 6

        # First org still uses its own padding (4).
        resp_first_again = client.post(
            '/api/v1/purchase-orders',
            headers=po_auth_headers,
            json={
                'partner_id': str(po_partner.id),
                'currency': 'PLN',
                'lines': [
                    {
                        'name': 'Z',
                        'quantity_ordered': '1',
                        'unit_price': '1.00',
                        'tax_rate': '0',
                    },
                ],
            },
        )
        assert resp_first_again.status_code == status.HTTP_201_CREATED
        first_again_seq = resp_first_again.json()['number'].rsplit('/', 1)[-1]
        assert len(first_again_seq) == DEFAULT_NUMBER_PADDING

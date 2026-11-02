"""A cleared optional field reaches the column as NULL.

The update services read optional fields with ``if not None`` — which
makes an explicit null in the payload indistinguishable from a field the
client left out. An optional value, once set, could never be removed:
the screens already send null on an emptied field (an open-ended
valid_to, a detached preferred supplier) and the patch answered 200 with
the old value still in the column.

The distinction is decided at the router, where Pydantic still knows
which keys the payload named (``model_fields_set``): an absent key stays
UNSET, a present null clears. The same contract the PO settings endpoint
already speaks.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import status
from starlette.testclient import TestClient

PRICELIST_URL = '/api/v1/purchase-orders/pricelist'
RULES_URL = '/api/v1/purchase-orders/reorder-rules'


@pytest.mark.integration
class TestAClearedFieldReachesTheColumn:
    def test_clearing_valid_to_notes_and_min_quantity_on_a_pricelist_entry(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        po_partner: Any,
        po_template: Any,
    ) -> None:
        created = client.post(
            PRICELIST_URL,
            headers=po_auth_headers,
            json={
                'partner_id': str(po_partner.id),
                'product_template_id': str(po_template.id),
                'unit_price': '10.0000',
                'valid_from': '2026-01-01',
                'min_quantity': '5.000',
                'valid_to': '2026-12-31',
                'notes': 'contract 2026',
            },
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        entry_id = created.json()['id']

        patched = client.patch(
            f'{PRICELIST_URL}/{entry_id}',
            headers=po_auth_headers,
            json={'valid_to': None, 'notes': None, 'min_quantity': None},
        )
        assert patched.status_code == 200, patched.text

        fetched = client.get(f'{PRICELIST_URL}/{entry_id}', headers=po_auth_headers)
        assert fetched.status_code == 200
        assert fetched.json()['valid_to'] is None
        assert fetched.json()['notes'] is None
        assert fetched.json()['min_quantity'] is None

    def test_a_key_left_out_of_the_payload_leaves_the_column_alone(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        po_partner: Any,
        po_template: Any,
    ) -> None:
        created = client.post(
            PRICELIST_URL,
            headers=po_auth_headers,
            json={
                'partner_id': str(po_partner.id),
                'product_template_id': str(po_template.id),
                'unit_price': '10.0000',
                'valid_from': '2026-01-01',
                'valid_to': '2026-12-31',
                'notes': 'contract 2026',
            },
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        entry_id = created.json()['id']

        patched = client.patch(
            f'{PRICELIST_URL}/{entry_id}',
            headers=po_auth_headers,
            json={'unit_price': '12.0000'},
        )
        assert patched.status_code == 200, patched.text

        fetched = client.get(f'{PRICELIST_URL}/{entry_id}', headers=po_auth_headers)
        assert fetched.status_code == 200
        assert fetched.json()['unit_price'] == '12.0000'
        assert fetched.json()['valid_to'] == '2026-12-31'
        assert fetched.json()['notes'] == 'contract 2026'

    def test_detaching_the_preferred_supplier_on_a_reorder_rule(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        po_partner: Any,
        po_template: Any,
        po_location: Any,
    ) -> None:
        created = client.post(
            RULES_URL,
            headers=po_auth_headers,
            json={
                'product_template_id': str(po_template.id),
                'location_id': str(po_location.id),
                'min_quantity': '5',
                'max_quantity': '20',
                'safety_stock': '2',
                'preferred_partner_id': str(po_partner.id),
                'notes': 'reorder from main supplier',
            },
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        rule_id = created.json()['id']
        assert created.json()['preferred_partner_id'] == str(po_partner.id)

        patched = client.patch(
            f'{RULES_URL}/{rule_id}',
            headers=po_auth_headers,
            json={'preferred_partner_id': None, 'notes': None},
        )
        assert patched.status_code == 200, patched.text

        fetched = client.get(f'{RULES_URL}/{rule_id}', headers=po_auth_headers)
        assert fetched.status_code == 200
        assert fetched.json()['preferred_partner_id'] is None
        assert fetched.json()['notes'] is None


@pytest.mark.integration
class TestPurchaseOrderNotesAnswerANamedNull:
    def test_a_named_null_clears_the_note_and_an_absent_key_leaves_it(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        po_partner: Any,
        po_template: Any,
    ) -> None:
        line = {
            'product_template_id': str(po_template.id),
            'quantity_ordered': 2,
            'unit_price': '100.00',
        }
        created = client.post(
            '/api/v1/purchase-orders',
            headers=po_auth_headers,
            json={
                'partner_id': str(po_partner.id),
                'lines': [line],
                'notes': 'ferry on Tuesday',
            },
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        po_id = created.json()['id']
        assert created.json()['notes'] == 'ferry on Tuesday'

        # A named null is a clearing instruction — the column is nullable
        # and the screen sends null on an emptied field.
        cleared = client.patch(
            f'/api/v1/purchase-orders/{po_id}',
            headers=po_auth_headers,
            json={'notes': None},
        )
        assert cleared.status_code == 200, cleared.text
        assert cleared.json()['notes'] is None

        # Re-set, then leave the key out entirely: the note stays.
        client.patch(
            f'/api/v1/purchase-orders/{po_id}',
            headers=po_auth_headers,
            json={'notes': 'reinstalled'},
        )
        untouched = client.patch(
            f'/api/v1/purchase-orders/{po_id}',
            headers=po_auth_headers,
            json={'scheduled_date': '2030-01-15'},
        )
        assert untouched.status_code == 200, untouched.text
        assert untouched.json()['notes'] == 'reinstalled'

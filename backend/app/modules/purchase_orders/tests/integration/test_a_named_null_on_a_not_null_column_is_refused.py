"""A named null on a column that cannot be cleared is refused by name.

§2b's contract has three answers and they must stay disjoint: an unnamed
key leaves the column alone, a named null on a nullable column clears
it, and a named null on a column that cannot take NULL is refused with
400 naming the field — never a 200 the operator reads as success while
the row stands untouched. The refused sets here: the settings flag, the
reorder thresholds, the price list's price, currency and start date, and
the order's scheduled date — the last one is nullable by column but
refused by exception, because the order number carries the date's period
(§2b records the reason). The order's clearable columns answer the
second way instead; they are pinned in the classes below.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import status
from starlette.testclient import TestClient

PRICELIST_URL = '/api/v1/purchase-orders/pricelist'
RULES_URL = '/api/v1/purchase-orders/reorder-rules'


@pytest.mark.integration
class TestANamedNullOnANotNullColumnIsRefused:
    def test_pricelist_refuses_nulling_unit_price_currency_and_valid_from(
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
                'currency': 'PLN',
                'valid_from': '2026-01-01',
            },
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        entry_id = created.json()['id']

        patched = client.patch(
            f'{PRICELIST_URL}/{entry_id}',
            headers=po_auth_headers,
            json={
                'unit_price': None,
                'currency': None,
                'valid_from': None,
                'notes': 'still here',
            },
        )
        assert patched.status_code == status.HTTP_400_BAD_REQUEST, patched.text
        assert 'unit_price' in patched.text
        assert 'currency' in patched.text
        assert 'valid_from' in patched.text

        fetched = client.get(f'{PRICELIST_URL}/{entry_id}', headers=po_auth_headers)
        assert fetched.json()['unit_price'] == '10.0000'
        assert fetched.json()['currency'] == 'PLN'
        assert fetched.json()['valid_from'] == '2026-01-01'
        assert fetched.json()['notes'] is None

    def test_reorder_rule_refuses_nulling_its_thresholds(
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
            },
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        rule_id = created.json()['id']

        patched = client.patch(
            f'{RULES_URL}/{rule_id}',
            headers=po_auth_headers,
            json={'min_quantity': None, 'max_quantity': None},
        )
        assert patched.status_code == status.HTTP_400_BAD_REQUEST, patched.text
        assert 'min_quantity' in patched.text
        assert 'max_quantity' in patched.text

        fetched = client.get(f'{RULES_URL}/{rule_id}', headers=po_auth_headers)
        assert fetched.json()['min_quantity'] == '5.000'
        assert fetched.json()['max_quantity'] == '20.000'

    def test_a_named_null_clears_the_order_currency_and_an_absent_key_leaves_it(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        po_partner: Any,
        po_template: Any,
    ) -> None:
        """The currency column is nullable — §2b's second answer, not the
        third: a named null is a clearing instruction, an omitted key
        leaves the column alone."""
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
                'currency': 'USD',
            },
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        po_id = created.json()['id']
        assert created.json()['currency'] == 'USD'

        cleared = client.patch(
            f'/api/v1/purchase-orders/{po_id}',
            headers=po_auth_headers,
            json={'currency': None},
        )
        assert cleared.status_code == 200, cleared.text
        assert cleared.json()['currency'] is None

        # Re-set, then leave the key out entirely: the currency stays.
        client.patch(
            f'/api/v1/purchase-orders/{po_id}',
            headers=po_auth_headers,
            json={'currency': 'PLN'},
        )
        untouched = client.patch(
            f'/api/v1/purchase-orders/{po_id}',
            headers=po_auth_headers,
            json={'notes': 'a note, not a currency'},
        )
        assert untouched.status_code == 200, untouched.text
        assert untouched.json()['currency'] == 'PLN'

        fetched = client.get(
            f'/api/v1/purchase-orders/{po_id}', headers=po_auth_headers
        )
        assert fetched.json()['currency'] == 'PLN'

    def test_a_named_null_detaches_the_partner(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        po_partner: Any,
        po_template: Any,
    ) -> None:
        """partner_id is nullable — a named null detaches the supplier
        instead of being read as "leave alone"."""
        line = {
            'product_template_id': str(po_template.id),
            'quantity_ordered': 2,
            'unit_price': '100.00',
        }
        created = client.post(
            '/api/v1/purchase-orders',
            headers=po_auth_headers,
            json={'partner_id': str(po_partner.id), 'lines': [line]},
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        po_id = created.json()['id']
        assert created.json()['partner_id'] == str(po_partner.id)

        cleared = client.patch(
            f'/api/v1/purchase-orders/{po_id}',
            headers=po_auth_headers,
            json={'partner_id': None},
        )
        assert cleared.status_code == 200, cleared.text
        assert cleared.json()['partner_id'] is None

        # The clearing reaches the column, not just the response body.
        fetched = client.get(
            f'/api/v1/purchase-orders/{po_id}', headers=po_auth_headers
        )
        assert fetched.json()['partner_id'] is None

    def test_a_key_left_out_leaves_the_partner_attached(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        po_partner: Any,
        po_template: Any,
    ) -> None:
        """The omitted-key half of partner_id's contract: a PATCH that
        does not name the key leaves the supplier attached — read back
        from the row, not from the response body, so a service that
        clears on absence fails here and not only in review."""
        line = {
            'product_template_id': str(po_template.id),
            'quantity_ordered': 2,
            'unit_price': '100.00',
        }
        created = client.post(
            '/api/v1/purchase-orders',
            headers=po_auth_headers,
            json={'partner_id': str(po_partner.id), 'lines': [line]},
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        po_id = created.json()['id']

        # A value change that never names the partner.
        redated = client.patch(
            f'/api/v1/purchase-orders/{po_id}',
            headers=po_auth_headers,
            json={'scheduled_date': '2031-02-20'},
        )
        assert redated.status_code == 200, redated.text

        fetched = client.get(
            f'/api/v1/purchase-orders/{po_id}', headers=po_auth_headers
        )
        assert fetched.json()['partner_id'] == str(po_partner.id)
        assert fetched.json()['scheduled_date'] == '2031-02-20'

    def test_purchase_order_refuses_nulling_its_scheduled_date(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        po_partner: Any,
        po_template: Any,
    ) -> None:
        """scheduled_date is nullable by column, yet refused by §2b
        exception: the order number carries the date's period — dated by
        it on create, renumbered when a value change moves it — and the
        engine's answer for an absent date is "today". Clearing it would
        strand the number in the old period or, on the next renumber,
        re-file the order in the current one."""
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
                'scheduled_date': '2030-01-15',
            },
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        po_id = created.json()['id']

        patched = client.patch(
            f'/api/v1/purchase-orders/{po_id}',
            headers=po_auth_headers,
            json={'scheduled_date': None},
        )
        assert patched.status_code == status.HTTP_400_BAD_REQUEST, patched.text
        assert 'scheduled_date' in patched.text

        fetched = client.get(
            f'/api/v1/purchase-orders/{po_id}', headers=po_auth_headers
        )
        assert fetched.json()['scheduled_date'] == '2030-01-15'

    def test_po_settings_refuse_nulling_approval_required(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
    ) -> None:
        """The threshold stays tri-state (absent = leave, null = clear,
        value = set); approval_required is a NOT NULL flag, so naming it
        with null is refused instead of silently read as "leave alone"."""
        put = client.put(
            '/api/v1/purchase-orders/settings',
            headers=po_auth_headers,
            json={'approval_required': None},
        )
        assert put.status_code == status.HTTP_400_BAD_REQUEST, put.text
        assert 'approval_required' in put.text

        fetched = client.get(
            '/api/v1/purchase-orders/settings', headers=po_auth_headers
        )
        assert fetched.status_code == 200
        assert fetched.json()['approval_required'] is False

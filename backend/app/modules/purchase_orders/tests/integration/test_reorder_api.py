"""API tests for ReorderRule CRUD.

Covers: create/get/list/update/delete, 409 duplicate, 400 validation,
404 not found, multi-tenancy isolation, list filters.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from fastapi import status
from starlette.testclient import TestClient

from app.core.testing import ModuleTestHelper

URL = '/api/v1/purchase-orders/reorder-rules'


def _rule_payload(template: Any, location: Any, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        'product_template_id': str(template.id),
        'location_id': str(location.id),
        'min_quantity': '5',
        'max_quantity': '20',
        'safety_stock': '2',
        'notes': 'reorder from main supplier',
    }
    payload.update(overrides)
    return payload


@pytest.mark.integration
class TestReorderRuleAPI:
    def test_create_get_list_update_delete(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        po_location: Any,
        po_template: Any,
    ) -> None:
        # Create.
        response = client.post(
            URL,
            headers=po_auth_headers,
            json=_rule_payload(po_template, po_location),
        )
        assert response.status_code == status.HTTP_201_CREATED
        body = response.json()
        rule_id = body['id']
        assert body['product_template_id'] == str(po_template.id)
        assert body['location_id'] == str(po_location.id)
        assert Decimal(body['min_quantity']) == 5
        assert Decimal(body['max_quantity']) == 20
        assert Decimal(body['safety_stock']) == 2
        assert body['notes'] == 'reorder from main supplier'

        # Get by id.
        fetched = client.get(f'{URL}/{rule_id}', headers=po_auth_headers)
        assert fetched.status_code == 200
        assert fetched.json()['id'] == rule_id

        # List.
        listing = client.get(URL, headers=po_auth_headers)
        assert listing.status_code == 200
        assert any(entry['id'] == rule_id for entry in listing.json()['items'])

        # Update.
        updated = client.patch(
            f'{URL}/{rule_id}',
            headers=po_auth_headers,
            json={'min_quantity': '8', 'notes': 'updated note'},
        )
        assert updated.status_code == 200
        assert Decimal(updated.json()['min_quantity']) == 8
        assert updated.json()['notes'] == 'updated note'

        # Delete.
        deleted = client.delete(f'{URL}/{rule_id}', headers=po_auth_headers)
        assert deleted.status_code == status.HTTP_204_NO_CONTENT

        gone = client.get(f'{URL}/{rule_id}', headers=po_auth_headers)
        assert gone.status_code == 404

    def test_create_duplicate_returns_409(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        po_location: Any,
        po_template: Any,
    ) -> None:
        first = client.post(
            URL,
            headers=po_auth_headers,
            json=_rule_payload(po_template, po_location),
        )
        assert first.status_code == status.HTTP_201_CREATED

        duplicate = client.post(
            URL,
            headers=po_auth_headers,
            json=_rule_payload(po_template, po_location),
        )
        assert duplicate.status_code == status.HTTP_409_CONFLICT

    def test_create_max_below_min_returns_400(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        po_location: Any,
        po_template: Any,
    ) -> None:
        response = client.post(
            URL,
            headers=po_auth_headers,
            json=_rule_payload(po_template, po_location, max_quantity='2'),
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_create_negative_safety_stock_rejected(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        po_location: Any,
        po_template: Any,
    ) -> None:
        # The schema itself forbids negative safety stock (ge=0) — the
        # request is rejected with 422 before the service runs.
        response = client.post(
            URL,
            headers=po_auth_headers,
            json=_rule_payload(po_template, po_location, safety_stock='-1'),
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_get_unknown_returns_404(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
    ) -> None:
        response = client.get(f'{URL}/{uuid4()}', headers=po_auth_headers)
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_patch_unknown_returns_404(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
    ) -> None:
        response = client.patch(
            f'{URL}/{uuid4()}',
            headers=po_auth_headers,
            json={'notes': 'nope'},
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_delete_unknown_returns_404(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
    ) -> None:
        response = client.delete(f'{URL}/{uuid4()}', headers=po_auth_headers)
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_other_org_cannot_access_rule(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        po_location: Any,
        po_template: Any,
        h: ModuleTestHelper,
    ) -> None:
        created = client.post(
            URL,
            headers=po_auth_headers,
            json=_rule_payload(po_template, po_location),
        )
        assert created.status_code == status.HTTP_201_CREATED
        rule_id = created.json()['id']

        other_org = h.create_org(
            'Reorder Other Org',
            [
                'core',
                'items',
                'locations',
                'categories',
                'warehouse',
                'purchase_orders',
            ],
        )
        other_user = h.create_user(other_org, email='reorder-other@example.com')
        other_headers = h.get_auth_headers(other_user)

        fetched = client.get(f'{URL}/{rule_id}', headers=other_headers)
        assert fetched.status_code == status.HTTP_404_NOT_FOUND

        listing = client.get(URL, headers=other_headers)
        assert listing.status_code == 200
        assert listing.json()['items'] == []

    def test_list_filters_by_product_and_location(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        po_location: Any,
        po_template: Any,
        po_org: Any,
        h: ModuleTestHelper,
    ) -> None:
        second_template = h.create_template(
            po_org, name='Second Product', sku='PO-REORDER-002'
        )
        first = client.post(
            URL,
            headers=po_auth_headers,
            json=_rule_payload(po_template, po_location),
        )
        second = client.post(
            URL,
            headers=po_auth_headers,
            json=_rule_payload(second_template, po_location),
        )
        assert first.status_code == status.HTTP_201_CREATED
        assert second.status_code == status.HTTP_201_CREATED

        by_product = client.get(
            URL,
            headers=po_auth_headers,
            params={'product_template_id': str(po_template.id)},
        )
        assert by_product.status_code == 200
        ids = [entry['id'] for entry in by_product.json()['items']]
        assert first.json()['id'] in ids
        assert second.json()['id'] not in ids

        by_location = client.get(
            URL,
            headers=po_auth_headers,
            params={'location_id': str(po_location.id)},
        )
        assert by_location.status_code == 200
        assert len(by_location.json()['items']) == 2

    def test_update_max_below_min_returns_400(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        po_location: Any,
        po_template: Any,
    ) -> None:
        created = client.post(
            URL,
            headers=po_auth_headers,
            json=_rule_payload(po_template, po_location),
        )
        assert created.status_code == status.HTTP_201_CREATED
        rule_id = created.json()['id']

        response = client.patch(
            f'{URL}/{rule_id}',
            headers=po_auth_headers,
            json={'max_quantity': '1'},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_rules_list_names_the_preferred_supplier(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        po_location: Any,
        po_template: Any,
        po_partner: Any,
    ) -> None:
        """The list carries the supplier's name, so a page never reads each
        partner by id to print it."""
        created = client.post(
            URL,
            headers=po_auth_headers,
            json=_rule_payload(
                po_template, po_location, preferred_partner_id=str(po_partner.id)
            ),
        )
        assert created.status_code == status.HTTP_201_CREATED
        assert created.json()['preferred_partner_name'] == po_partner.name

        listed = client.get(URL, headers=po_auth_headers).json()['items']
        assert [r['preferred_partner_name'] for r in listed] == [po_partner.name]

    def test_rule_without_supplier_has_no_supplier_name(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        po_location: Any,
        po_template: Any,
    ) -> None:
        response = client.post(
            URL,
            headers=po_auth_headers,
            json=_rule_payload(po_template, po_location),
        )
        assert response.json()['preferred_partner_name'] is None

    def test_rule_response_exposes_product_unit(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        po_location: Any,
        po_template_with_uom: Any,
    ) -> None:
        """The edit form needs the unit; the API returns it from the template."""
        response = client.post(
            URL,
            headers=po_auth_headers,
            json=_rule_payload(po_template_with_uom, po_location),
        )
        assert response.status_code == status.HTTP_201_CREATED
        body = response.json()
        assert body['uom_id'] == str(po_template_with_uom.uom_id)
        assert body['uom_symbol'] == 'kg'

        fetched = client.get(f'{URL}/{body["id"]}', headers=po_auth_headers).json()
        assert fetched['uom_symbol'] == 'kg'

    def test_rule_response_unit_none_without_product_unit(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        po_location: Any,
        po_template: Any,
    ) -> None:
        """A product without a unit yields ``None`` instead of a bogus symbol."""
        response = client.post(
            URL,
            headers=po_auth_headers,
            json=_rule_payload(po_template, po_location),
        )
        assert response.status_code == status.HTTP_201_CREATED
        body = response.json()
        assert body['uom_id'] is None
        assert body['uom_symbol'] is None


@pytest.mark.integration
class TestTheThresholdThatMakesARuleFire:
    """MIN is what triggers an order; MAX is only the level to reach.

    The form starred MAX and left MIN optional, and the schema agreed:
    ``min_quantity`` defaulted to 0. A rule saved with the required fields
    alone got 0 and the engine skipped it outright
    (``if rule.min_quantity <= 0: continue``) — so the row sat on the list
    looking like every other one and could never produce an alert. Measured
    on one record: min=0 returned no alerts, min=5 returned a shortage of 5.
    One number.
    """

    def test_a_rule_with_no_minimum_is_refused(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        po_location: Any,
        po_template: Any,
    ) -> None:
        payload = _rule_payload(po_template, po_location)
        del payload['min_quantity']

        response = client.post(URL, json=payload, headers=po_auth_headers)

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_a_minimum_of_zero_is_refused(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        po_location: Any,
        po_template: Any,
    ) -> None:
        response = client.post(
            URL,
            json=_rule_payload(po_template, po_location, min_quantity='0'),
            headers=po_auth_headers,
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_a_rule_cannot_be_edited_down_to_zero_either(
        self,
        client: TestClient,
        po_auth_headers: dict[str, str],
        po_location: Any,
        po_template: Any,
    ) -> None:
        created = client.post(
            URL,
            json=_rule_payload(po_template, po_location),
            headers=po_auth_headers,
        )
        assert created.status_code == status.HTTP_201_CREATED

        response = client.patch(
            f'{URL}/{created.json()["id"]}',
            json={'min_quantity': '0'},
            headers=po_auth_headers,
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

"""A hundred at ten, plus two hundred of freight, is twelve apiece.

Freight, duty and insurance belong in the value of the goods they arrived
with. Without them the shelf is worth what the supplier invoiced and nothing
else — the most common reason a warehouse's stock value disagrees with its
accounts.

And they are taken only before the receipt is posted. Afterwards the goods
may already have left, and spreading the invoice over what remains needs a
general ledger to absorb the rest. This product deliberately has none, so it
refuses and says what to do instead.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.stock_valuation_layer import StockValuationLayer
from app.models.storage_location import StorageLocation


def _receipt(
    client: TestClient,
    headers: dict[str, str],
    location: StorageLocation,
    partner: Partner,
    template: ProductTemplate,
    quantity: int = 100,
    price: str = '10.00',
) -> str:
    response = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'IN',
            'partner_id': str(partner.id),
            'target_location_id': str(location.id),
            'lines': [
                {
                    'product_template_id': str(template.id),
                    'expected_quantity': quantity,
                    'unit_price': price,
                }
            ],
        },
    )
    assert response.status_code == 201, response.text
    return str(response.json()['id'])


class TestTheFreightReachesTheShelf:
    def test_the_layer_is_posted_at_the_landed_cost(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        doc_id = _receipt(
            client, doc_auth_headers, doc_target_location, doc_partner, doc_template
        )
        added = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/extra-costs',
            headers=doc_auth_headers,
            json={'kind': 'freight', 'amount': '200.00'},
        )
        assert added.status_code == 201, added.text

        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )

        layer = db_session.scalars(
            select(StockValuationLayer).where(
                StockValuationLayer.product_template_id == doc_template.id,
                StockValuationLayer.direction == 'IN',
            )
        ).first()
        assert layer is not None
        assert Decimal(layer.unit_cost) == Decimal('12.00')

    def test_the_screen_says_twelve_before_anybody_posts(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        doc_id = _receipt(
            client, doc_auth_headers, doc_target_location, doc_partner, doc_template
        )
        response = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/extra-costs',
            headers=doc_auth_headers,
            json={'kind': 'freight', 'amount': '200.00'},
        )

        # The whole point of the section: seeing 12.00 instead of 10.00
        # before clicking, not after.
        preview = response.json()['lines'][0]
        assert Decimal(preview['unit_price']) == Decimal('10.00')
        assert Decimal(preview['unit_cost_after']) == Decimal('12.00')
        assert response.json()['editable'] is True


class TestTheCostCanBeTakenBackOff:
    def test_removing_it_puts_the_unit_cost_back(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        doc_id = _receipt(
            client, doc_auth_headers, doc_target_location, doc_partner, doc_template
        )
        added = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/extra-costs',
            headers=doc_auth_headers,
            json={'kind': 'freight', 'amount': '200.00'},
        )
        cost_id = added.json()['costs'][0]['id']

        response = client.delete(
            f'/api/v1/warehouse/documents/{doc_id}/extra-costs/{cost_id}',
            headers=doc_auth_headers,
        )

        assert response.json()['costs'] == []
        assert Decimal(response.json()['lines'][0]['unit_cost_after']) == Decimal(
            '10.00'
        )


class TestItRefusesAfterPosting:
    def test_a_posted_receipt_will_not_take_another_cost(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        doc_id = _receipt(
            client, doc_auth_headers, doc_target_location, doc_partner, doc_template
        )
        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )

        response = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/extra-costs',
            headers=doc_auth_headers,
            json={'kind': 'freight', 'amount': '200.00'},
        )

        # A refusal with a sentence, not a 500 and not a silent no-op: the
        # goods may have left, and a cost that quietly vanishes is worse
        # than being told no.
        assert response.status_code == 400
        detail = response.json()['detail']
        message = detail['message'] if isinstance(detail, dict) else detail
        assert 'correction' in message.lower()

    def test_the_costs_are_still_readable_afterwards(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        doc_id = _receipt(
            client, doc_auth_headers, doc_target_location, doc_partner, doc_template
        )
        client.post(
            f'/api/v1/warehouse/documents/{doc_id}/extra-costs',
            headers=doc_auth_headers,
            json={'kind': 'freight', 'amount': '200.00'},
        )
        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )

        response = client.get(
            f'/api/v1/warehouse/documents/{doc_id}/extra-costs',
            headers=doc_auth_headers,
        )

        # What the goods cost has to stay readable long after the receipt is
        # closed — that is the record an auditor asks for.
        assert response.status_code == 200
        assert len(response.json()['costs']) == 1
        assert response.json()['editable'] is False


class TestItRefusesAForeignCurrency:
    def test_a_cost_in_another_currency_is_refused(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        doc_id = _receipt(
            client, doc_auth_headers, doc_target_location, doc_partner, doc_template
        )
        response = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/extra-costs',
            headers=doc_auth_headers,
            json={'kind': 'freight', 'amount': '200.00', 'currency': 'JPY'},
        )

        # Converting at a rate nobody recorded puts a number in the stock
        # value with no history behind it.
        assert response.status_code == 400
        detail = response.json()['detail']
        message = detail['message'] if isinstance(detail, dict) else detail
        assert 'currency' in message.lower()

        listed = client.get(
            f'/api/v1/warehouse/documents/{doc_id}/extra-costs',
            headers=doc_auth_headers,
        )
        assert listed.json()['costs'] == []


class TestOnlyAManagerPricesTheDelivery:
    """Adding freight changes what the stock is worth, so it is a manager's act.

    Reading is not: anyone who can open the receipt may see what it cost to
    get the goods there. The module gate lets every member of an organization
    with the module through, so the refusal has to come from the endpoint.
    """

    def _member_of(self, h: Any, org: Any, email: str, permissions: list[str]) -> Any:
        from app.models.role import Role, UserRole

        user = h.create_user(org, email=email, role='user')
        role = Role(
            organization_id=org.id,
            name=f'Custom {email}',
            permissions=permissions,
            is_system=False,
        )
        h.db.add(role)
        h.db.flush()
        h.db.add(UserRole(user_id=user.id, role_id=role.id))
        h.db.commit()
        return user

    def test_a_member_without_manage_cannot_add_a_cost(
        self,
        client: TestClient,
        h: Any,
        doc_org: Any,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        doc_id = _receipt(
            client, doc_auth_headers, doc_target_location, doc_partner, doc_template
        )
        user = self._member_of(
            h,
            doc_org,
            'freight-noperm@example.com',
            ['warehouse:read', 'warehouse:write'],
        )

        response = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/extra-costs',
            headers=h.get_auth_headers(user),
            json={'kind': 'freight', 'amount': '200.00'},
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_a_member_without_manage_cannot_take_one_off(
        self,
        client: TestClient,
        h: Any,
        doc_org: Any,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        doc_id = _receipt(
            client, doc_auth_headers, doc_target_location, doc_partner, doc_template
        )
        created = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/extra-costs',
            headers=doc_auth_headers,
            json={'kind': 'freight', 'amount': '200.00'},
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        cost_id = created.json()['costs'][0]['id']
        user = self._member_of(
            h,
            doc_org,
            'freight-nodelete@example.com',
            ['warehouse:read', 'warehouse:write'],
        )

        response = client.delete(
            f'/api/v1/warehouse/documents/{doc_id}/extra-costs/{cost_id}',
            headers=h.get_auth_headers(user),
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_a_member_without_manage_may_still_read_them(
        self,
        client: TestClient,
        h: Any,
        doc_org: Any,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        doc_id = _receipt(
            client, doc_auth_headers, doc_target_location, doc_partner, doc_template
        )
        user = self._member_of(
            h, doc_org, 'freight-reader@example.com', ['warehouse:read']
        )

        response = client.get(
            f'/api/v1/warehouse/documents/{doc_id}/extra-costs',
            headers=h.get_auth_headers(user),
        )

        assert response.status_code == status.HTTP_200_OK

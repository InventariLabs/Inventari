"""Goods name their tax rate; a new document line takes it.

Food sits at a reduced rate in every country the product is sold in, so one
receipt carries two or three rates. The organization keeps its rates in a
table (seeded from its country's law); a product, or the category its
records are filed under, names one of them. A line that states no rate of
its own takes the product's, then its category's, and only then the
profile's or the country's default. A rate typed on the line stays.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper
from app.models.audit_log import AuditLog
from app.models.category import Category
from app.models.item import Item
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.user import User
from tests.integration._shelf import anchor_pending_records

pytestmark = pytest.mark.integration

RATES = '/api/v1/warehouse/tax-rates'


def _german_org_on_full_value(
    client: TestClient,
    headers: dict[str, str],
    db_session: Session,
    org: Organization,
) -> dict[str, str]:
    """A German organization with its country's rates; returns rate -> id."""
    org.country = 'DE'
    db_session.commit()
    response = client.post(
        '/api/v1/warehouse/profile/apply-preset/Full Value', headers=headers
    )
    assert response.status_code == status.HTTP_200_OK, response.text
    offer = client.get(f'{RATES}/country', headers=headers).json()['rates']
    rates = {}
    for row in offer:
        created = client.post(
            RATES, json={'name': row['name'], 'rate': row['rate']}, headers=headers
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        rates[row['rate']] = created.json()['id']
    return rates


def _receipt(
    client: TestClient,
    headers: dict[str, str],
    partner: Partner,
    location: StorageLocation,
    lines: list[dict[str, Any]],
) -> dict[str, Any]:
    response = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'IN',
            'partner_id': str(partner.id),
            'target_location_id': str(location.id),
            'lines': lines,
        },
    )
    assert response.status_code == status.HTTP_201_CREATED, response.text
    payload: dict[str, Any] = response.json()
    return payload


def _line(template: ProductTemplate, **extra: Any) -> dict[str, Any]:
    return {
        'product_template_id': str(template.id),
        'expected_quantity': 10,
        'unit_price': '10.00',
        **extra,
    }


def _file_under(
    db_session: Session,
    org: Organization,
    location: StorageLocation,
    template: ProductTemplate,
    category: Category,
) -> None:
    db_session.add(
        Item(
            name=template.name,
            organization_id=org.id,
            storage_location_id=location.id,
            template_id=template.id,
            category_id=category.id,
            quantity=Decimal('1'),
        )
    )
    anchor_pending_records(db_session)
    db_session.commit()


@pytest.fixture
def bread(h: ModuleTestHelper, doc_org: Organization) -> ProductTemplate:
    return h.create_template(doc_org, name='Rye bread', barcode='4001234567892')


@pytest.fixture
def food(db_session: Session, doc_org: Organization) -> Category:
    category = Category(organization_id=doc_org.id, name='Food')
    db_session.add(category)
    db_session.commit()
    db_session.refresh(category)
    return category


class TestTheCountryOffersItsRates:
    def test_a_german_org_is_offered_the_standard_and_the_reduced_rate(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        db_session: Session,
    ) -> None:
        """Fails without the fix with 404/422: no country offer existed."""
        doc_org.country = 'DE'
        db_session.commit()

        offer = client.get(f'{RATES}/country', headers=doc_auth_headers)
        assert offer.status_code == status.HTTP_200_OK, offer.text
        assert offer.json()['country'] == 'DE'
        assert [
            (r['name'], r['rate'], r['is_standard']) for r in offer.json()['rates']
        ] == [('USt. 19%', '19.00', True), ('USt. 7%', '7.00', False)]

    def test_an_org_without_a_country_rule_is_offered_nothing(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        db_session: Session,
    ) -> None:
        doc_org.country = 'BR'
        db_session.commit()
        offer = client.get(f'{RATES}/country', headers=doc_auth_headers)
        assert offer.json() == {'country': 'BR', 'rates': []}

    def test_a_zero_rate_is_a_rate(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        """Zero-rated food is on the return in its own box; refusing 0 made the
        British food rate impossible to keep. Fails without the fix with 422."""
        response = client.post(
            RATES, json={'name': 'Zero', 'rate': '0'}, headers=doc_auth_headers
        )
        assert response.status_code == status.HTTP_201_CREATED, response.text


class TestANewLineTakesTheGoodsRate:
    def test_a_german_receipt_carries_seven_and_nineteen_without_typing_a_rate(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        bread: ProductTemplate,
        db_session: Session,
    ) -> None:
        """Fails without the fix: both lines took the country's 19 %."""
        rates = _german_org_on_full_value(client, doc_auth_headers, db_session, doc_org)
        named = client.put(
            f'{RATES}/products/{bread.id}',
            json={'tax_rate_id': rates['7.00']},
            headers=doc_auth_headers,
        )
        assert named.status_code == status.HTTP_200_OK, named.text
        assert named.json()['tax_rate_id'] == rates['7.00']

        doc = _receipt(
            client,
            doc_auth_headers,
            doc_partner,
            doc_target_location,
            [_line(doc_template), _line(bread)],
        )
        assert [line['tax_rate'] for line in doc['lines']] == ['19.00', '7.00']
        assert doc['total_tax'] == '26.00'

    def test_the_category_names_the_rate_and_the_product_overrides_it(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        bread: ProductTemplate,
        food: Category,
        db_session: Session,
    ) -> None:
        rates = _german_org_on_full_value(client, doc_auth_headers, db_session, doc_org)
        _file_under(db_session, doc_org, doc_target_location, bread, food)
        _file_under(db_session, doc_org, doc_target_location, doc_template, food)
        response = client.put(
            f'{RATES}/categories/{food.id}',
            json={'tax_rate_id': rates['7.00']},
            headers=doc_auth_headers,
        )
        assert response.status_code == status.HTTP_200_OK, response.text
        client.put(
            f'{RATES}/products/{doc_template.id}',
            json={'tax_rate_id': rates['19.00']},
            headers=doc_auth_headers,
        )

        doc = _receipt(
            client,
            doc_auth_headers,
            doc_partner,
            doc_target_location,
            [_line(doc_template), _line(bread)],
        )
        assert [line['tax_rate'] for line in doc['lines']] == ['19.00', '7.00']

        product = client.get(f'{RATES}/products/{bread.id}', headers=doc_auth_headers)
        assert product.json() == {
            'product_template_id': str(bread.id),
            'tax_rate_id': None,
            'category_tax_rate_id': rates['7.00'],
        }
        listed = client.get(f'{RATES}/categories', headers=doc_auth_headers)
        assert listed.json()['items'] == [
            {'category_id': str(food.id), 'tax_rate_id': rates['7.00']}
        ]

    def test_a_rate_typed_on_the_line_stays(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        bread: ProductTemplate,
        db_session: Session,
    ) -> None:
        rates = _german_org_on_full_value(client, doc_auth_headers, db_session, doc_org)
        client.put(
            f'{RATES}/products/{bread.id}',
            json={'tax_rate_id': rates['7.00']},
            headers=doc_auth_headers,
        )
        doc = _receipt(
            client,
            doc_auth_headers,
            doc_partner,
            doc_target_location,
            [_line(bread, tax_rate='19.00')],
        )
        assert doc['lines'][0]['tax_rate'] == '19.00'

    def test_clearing_the_products_rate_returns_it_to_the_default(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        bread: ProductTemplate,
        db_session: Session,
    ) -> None:
        rates = _german_org_on_full_value(client, doc_auth_headers, db_session, doc_org)
        client.put(
            f'{RATES}/products/{bread.id}',
            json={'tax_rate_id': rates['7.00']},
            headers=doc_auth_headers,
        )
        cleared = client.put(
            f'{RATES}/products/{bread.id}',
            json={'tax_rate_id': None},
            headers=doc_auth_headers,
        )
        assert cleared.json()['tax_rate_id'] is None
        doc = _receipt(
            client, doc_auth_headers, doc_partner, doc_target_location, [_line(bread)]
        )
        assert doc['lines'][0]['tax_rate'] == '19.00'

    def test_the_price_hint_suggests_the_products_rate(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        bread: ProductTemplate,
        db_session: Session,
    ) -> None:
        """The form fills a new line from the hint; it answered 19 % for bread."""
        rates = _german_org_on_full_value(client, doc_auth_headers, db_session, doc_org)
        client.put(
            f'{RATES}/products/{bread.id}',
            json={'tax_rate_id': rates['7.00']},
            headers=doc_auth_headers,
        )
        hint = client.get(
            '/api/v1/warehouse/price-hint',
            params={'template_id': str(bread.id)},
            headers=doc_auth_headers,
        )
        assert hint.json()['tax_rate'] == '7.00'

    def test_an_untaxed_profile_stays_untaxed(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        bread: ProductTemplate,
        db_session: Session,
    ) -> None:
        """A profile that charges no tax charges none on bread either."""
        rates = _german_org_on_full_value(client, doc_auth_headers, db_session, doc_org)
        client.put(
            f'{RATES}/products/{bread.id}',
            json={'tax_rate_id': rates['7.00']},
            headers=doc_auth_headers,
        )
        client.put(
            '/api/v1/warehouse/profile',
            json={'tax_handling': 'NONE'},
            headers=doc_auth_headers,
        )
        doc = _receipt(
            client, doc_auth_headers, doc_partner, doc_target_location, [_line(bread)]
        )
        assert doc['lines'][0]['tax_rate'] is None


class TestTheRatesAreTheOrganizations:
    def test_another_orgs_rate_cannot_be_named(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        doc_auth_headers: dict[str, str],
        bread: ProductTemplate,
    ) -> None:
        other = h.create_org('Other', ['core', 'items', 'warehouse'])
        other_user: User = h.create_user(other, email='other@example.com')
        foreign = client.post(
            RATES,
            json={'name': 'Theirs', 'rate': '7.00'},
            headers=h.get_auth_headers(other_user),
        ).json()
        response = client.put(
            f'{RATES}/products/{bread.id}',
            json={'tax_rate_id': foreign['id']},
            headers=doc_auth_headers,
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_naming_a_rate_takes_the_managers_permission(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        doc_org: Organization,
        bread: ProductTemplate,
    ) -> None:
        clerk = h.create_user(doc_org, email='clerk@example.com', role='user')
        h.grant_permissions(clerk, ['warehouse:read', 'warehouse:write'])
        response = client.put(
            f'{RATES}/products/{bread.id}',
            json={'tax_rate_id': None},
            headers=h.get_auth_headers(clerk),
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_naming_a_products_rate_is_journalled(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        bread: ProductTemplate,
        db_session: Session,
    ) -> None:
        rates = _german_org_on_full_value(client, doc_auth_headers, db_session, doc_org)
        client.put(
            f'{RATES}/products/{bread.id}',
            json={'tax_rate_id': rates['7.00']},
            headers=doc_auth_headers,
        )
        entry = db_session.scalar(
            select(AuditLog).where(
                AuditLog.organization_id == doc_org.id,
                AuditLog.target_id == bread.id,
            )
        )
        assert entry is not None
        assert entry.target_type == 'product_template'
        assert entry.snapshot == {'tax_rate': '7.00'}

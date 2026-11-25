"""A receipt in one step asks about the home shelf too.

A warehouse that receives straight onto its shelves has no put-away task, so
the question 'is this now the product's home?' is asked from the posted
receipt: one offer for each product whose line was put on a shelf other than
the one the rules suggested. It is asked only while the warehouse keeps fixed
places, never for a product the question was silenced for, and never in a
warehouse that receives in two steps — there the put-away asks.
"""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.user import User

API = '/api/v1/warehouse'


@pytest.fixture
def warehouse(
    h: ModuleTestHelper,
    doc_org: Organization,
    doc_storage_type: StorageType,
    doc_user: User,
) -> StorageLocation:
    return h.create_storage_location(
        doc_org, doc_storage_type, doc_user, name='Main Warehouse'
    )


def _shelf(
    db: Session,
    h: ModuleTestHelper,
    org: Organization,
    storage_type: StorageType,
    user: User,
    warehouse: StorageLocation,
    name: str,
) -> StorageLocation:
    location = h.create_storage_location(org, storage_type, user, name=name)
    location.parent_id = warehouse.id
    db.commit()
    return location


@pytest.fixture
def shelf_a(
    db_session: Session,
    h: ModuleTestHelper,
    doc_org: Organization,
    doc_storage_type: StorageType,
    doc_user: User,
    warehouse: StorageLocation,
) -> StorageLocation:
    return _shelf(
        db_session, h, doc_org, doc_storage_type, doc_user, warehouse, 'Shelf A'
    )


@pytest.fixture
def shelf_b(
    db_session: Session,
    h: ModuleTestHelper,
    doc_org: Organization,
    doc_storage_type: StorageType,
    doc_user: User,
    warehouse: StorageLocation,
) -> StorageLocation:
    return _shelf(
        db_session, h, doc_org, doc_storage_type, doc_user, warehouse, 'Shelf B'
    )


@pytest.fixture
def rice(h: ModuleTestHelper, doc_org: Organization) -> ProductTemplate:
    return h.create_template(doc_org, name='Jasmine Rice')


@pytest.fixture
def lentils(h: ModuleTestHelper, doc_org: Organization) -> ProductTemplate:
    return h.create_template(doc_org, name='Red Lentils')


def _rule(
    client: TestClient,
    headers: dict[str, str],
    template: ProductTemplate,
    target: StorageLocation,
) -> None:
    resp = client.post(
        f'{API}/putaway-rules',
        headers=headers,
        json={
            'product_template_id': str(template.id),
            'target_location_id': str(target.id),
        },
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text


def _receive(
    client: TestClient,
    headers: dict[str, str],
    partner: Partner,
    warehouse: StorageLocation,
    lines: list[tuple[ProductTemplate, StorageLocation | None]],
) -> UUID:
    resp = client.post(
        f'{API}/documents/post',
        headers=headers,
        json={
            'type': 'IN',
            'partner_id': str(partner.id),
            'target_location_id': str(warehouse.id),
            'lines': [
                {
                    'product_template_id': str(template.id),
                    'expected_quantity': 10,
                    **({'target_location_id': str(shelf.id)} if shelf else {}),
                }
                for template, shelf in lines
            ],
        },
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    return UUID(resp.json()['id'])


def _offers(
    client: TestClient, headers: dict[str, str], document_id: UUID
) -> list[dict[str, Any]]:
    resp = client.get(
        f'{API}/documents/{document_id}/home-shelf-offers', headers=headers
    )
    assert resp.status_code == status.HTTP_200_OK, resp.text
    return cast(list[dict[str, Any]], resp.json()['items'])


@pytest.mark.integration
class TestOneStepReceiptOffersHomeShelf:
    def test_a_line_put_elsewhere_than_the_rule_says_offers_its_shelf(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        warehouse: StorageLocation,
        shelf_a: StorageLocation,
        shelf_b: StorageLocation,
        rice: ProductTemplate,
    ) -> None:
        _rule(client, doc_auth_headers, rice, shelf_a)
        doc = _receive(
            client, doc_auth_headers, doc_partner, warehouse, [(rice, shelf_b)]
        )

        (offer,) = _offers(client, doc_auth_headers, doc)
        assert offer['kind'] == 'change'
        assert offer['product_template_id'] == str(rice.id)
        assert offer['location_id'] == str(shelf_b.id)
        assert offer['location_name'] == 'Shelf B'

    def test_a_product_without_a_home_is_offered_the_shelf_it_was_put_on(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        warehouse: StorageLocation,
        shelf_b: StorageLocation,
        rice: ProductTemplate,
    ) -> None:
        doc = _receive(
            client, doc_auth_headers, doc_partner, warehouse, [(rice, shelf_b)]
        )

        (offer,) = _offers(client, doc_auth_headers, doc)
        assert offer['kind'] == 'set'

    def test_several_lines_are_asked_in_one_answer_each_product_once(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        warehouse: StorageLocation,
        shelf_a: StorageLocation,
        shelf_b: StorageLocation,
        rice: ProductTemplate,
        lentils: ProductTemplate,
    ) -> None:
        doc = _receive(
            client,
            doc_auth_headers,
            doc_partner,
            warehouse,
            [(rice, shelf_b), (lentils, shelf_a), (rice, shelf_a)],
        )

        offers = _offers(client, doc_auth_headers, doc)
        assert sorted(offer['product_name'] for offer in offers) == [
            'Jasmine Rice',
            'Red Lentils',
        ]

    def test_a_line_that_followed_the_rule_or_named_no_shelf_asks_nothing(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        warehouse: StorageLocation,
        shelf_a: StorageLocation,
        rice: ProductTemplate,
        lentils: ProductTemplate,
    ) -> None:
        _rule(client, doc_auth_headers, rice, shelf_a)
        doc = _receive(
            client,
            doc_auth_headers,
            doc_partner,
            warehouse,
            [(rice, shelf_a), (lentils, None)],
        )

        assert _offers(client, doc_auth_headers, doc) == []

    def test_a_warehouse_without_fixed_places_is_not_asked(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        warehouse: StorageLocation,
        shelf_b: StorageLocation,
        rice: ProductTemplate,
    ) -> None:
        resp = client.put(
            f'{API}/putaway/receiving-modes/{warehouse.id}',
            headers=doc_auth_headers,
            json={'free_placement': True},
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        doc = _receive(
            client, doc_auth_headers, doc_partner, warehouse, [(rice, shelf_b)]
        )

        assert _offers(client, doc_auth_headers, doc) == []

    def test_a_silenced_product_is_not_asked(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        warehouse: StorageLocation,
        shelf_b: StorageLocation,
        rice: ProductTemplate,
    ) -> None:
        silenced = client.put(
            f'{API}/putaway/home-shelf/silenced/{rice.id}', headers=doc_auth_headers
        )
        assert silenced.status_code == status.HTTP_204_NO_CONTENT, silenced.text
        doc = _receive(
            client, doc_auth_headers, doc_partner, warehouse, [(rice, shelf_b)]
        )

        assert _offers(client, doc_auth_headers, doc) == []

    def test_a_warehouse_that_receives_in_two_steps_leaves_the_question_to_the_putaway(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        warehouse: StorageLocation,
        shelf_b: StorageLocation,
        rice: ProductTemplate,
    ) -> None:
        resp = client.put(
            f'{API}/putaway/receiving-modes/{warehouse.id}',
            headers=doc_auth_headers,
            json={'two_step': True},
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        doc = _receive(
            client, doc_auth_headers, doc_partner, warehouse, [(rice, shelf_b)]
        )

        assert _offers(client, doc_auth_headers, doc) == []

    def test_a_shelf_that_cannot_be_a_home_is_refused_with_its_reason(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        warehouse: StorageLocation,
        shelf_b: StorageLocation,
        rice: ProductTemplate,
    ) -> None:
        shelf_b.usage = 'virtual'
        db_session.commit()
        doc = _receive(
            client, doc_auth_headers, doc_partner, warehouse, [(rice, shelf_b)]
        )

        (offer,) = _offers(client, doc_auth_headers, doc)
        assert offer['kind'] == 'refused'
        assert offer['reason'] == 'not_stock'

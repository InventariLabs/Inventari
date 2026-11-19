"""A putaway rule cannot send a delivery to a place goods are not kept in.

The home-shelf prompt already refuses a receiving area, the quarantine
location and a location that takes no stock. The rule editor is the other
door a target comes in by, and it asks the same question: a rule naming one
of them would tell every delivery of its goods to be put away there.

A rule stored before its target became such a place is not left to do it
either: the rules list shows its shelf as one that takes no goods, and the
planner steps past it.
"""

from __future__ import annotations

from typing import Any
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
def shelf(
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
def held(
    db_session: Session,
    h: ModuleTestHelper,
    doc_org: Organization,
    doc_storage_type: StorageType,
    doc_user: User,
    warehouse: StorageLocation,
) -> StorageLocation:
    """A shelf the warehouse keeps for held stock (not yet named as such)."""
    return _shelf(
        db_session, h, doc_org, doc_storage_type, doc_user, warehouse, 'Quarantine'
    )


@pytest.fixture
def cable(h: ModuleTestHelper, doc_org: Organization) -> ProductTemplate:
    return h.create_template(doc_org, name='USB-C cable')


def _name_quarantine(
    client: TestClient, headers: dict[str, str], location: StorageLocation
) -> None:
    resp = client.put(
        f'{API}/profile',
        headers=headers,
        json={'quarantine_location_id': str(location.id)},
    )
    assert resp.status_code == status.HTTP_200_OK, resp.text


def _two_step_area(
    client: TestClient, headers: dict[str, str], warehouse: StorageLocation
) -> UUID:
    resp = client.put(
        f'{API}/putaway/receiving-modes/{warehouse.id}',
        headers=headers,
        json={'two_step': True},
    )
    assert resp.status_code == status.HTTP_200_OK, resp.text
    return UUID(resp.json()['receiving_location_id'])


def _create(
    client: TestClient,
    headers: dict[str, str],
    template: ProductTemplate,
    target: UUID,
) -> Any:
    return client.post(
        f'{API}/putaway-rules',
        headers=headers,
        json={
            'product_template_id': str(template.id),
            'target_location_id': str(target),
        },
    )


@pytest.mark.integration
class TestPutawayRuleTargetIsAPlaceGoodsAreKept:
    def test_the_quarantine_location_is_refused_as_a_target(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        cable: ProductTemplate,
        held: StorageLocation,
    ) -> None:
        _name_quarantine(client, doc_auth_headers, held)

        refused = _create(client, doc_auth_headers, cable, held.id)

        assert refused.status_code == status.HTTP_400_BAD_REQUEST, refused.text
        assert 'quarantine' in refused.text.lower()

    def test_a_receiving_area_is_refused_as_a_target(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        cable: ProductTemplate,
        warehouse: StorageLocation,
    ) -> None:
        area = _two_step_area(client, doc_auth_headers, warehouse)

        refused = _create(client, doc_auth_headers, cable, area)

        assert refused.status_code == status.HTTP_400_BAD_REQUEST, refused.text
        assert 'receiving' in refused.text.lower()

    def test_a_location_that_takes_no_stock_is_refused_as_a_target(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        db_session: Session,
        cable: ProductTemplate,
        shelf: StorageLocation,
    ) -> None:
        shelf.usage = 'customer'
        db_session.commit()

        refused = _create(client, doc_auth_headers, cable, shelf.id)

        assert refused.status_code == status.HTTP_400_BAD_REQUEST, refused.text

    def test_an_edit_cannot_move_a_rule_onto_the_quarantine_location(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        cable: ProductTemplate,
        shelf: StorageLocation,
        held: StorageLocation,
    ) -> None:
        _name_quarantine(client, doc_auth_headers, held)
        rule = _create(client, doc_auth_headers, cable, shelf.id)
        assert rule.status_code == status.HTTP_201_CREATED, rule.text

        refused = client.put(
            f'{API}/putaway-rules/{rule.json()["id"]}',
            headers=doc_auth_headers,
            json={'location_ids': [str(shelf.id), str(held.id)]},
        )

        assert refused.status_code == status.HTTP_400_BAD_REQUEST, refused.text
        assert 'quarantine' in refused.text.lower()

    def test_a_stored_rule_naming_quarantine_is_flagged_and_skipped(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        cable: ProductTemplate,
        warehouse: StorageLocation,
        held: StorageLocation,
    ) -> None:
        """A rule written while the shelf was ordinary does not send goods on.

        What it fails on: leave the planner's held-back test out and the
        delivery is planned onto the quarantine location with source
        ``rule``; leave it out of the list and the rule's shelf reads as
        active.
        """
        created = _create(client, doc_auth_headers, cable, held.id)
        assert created.status_code == status.HTTP_201_CREATED, created.text
        _name_quarantine(client, doc_auth_headers, held)

        listed = client.get(f'{API}/putaway-rules', headers=doc_auth_headers)
        assert listed.status_code == status.HTTP_200_OK, listed.text
        rule = listed.json()['items'][0]
        assert rule['target_location_active'] is False
        assert rule['locations'][0]['active'] is False

        preview = client.post(
            f'{API}/putaway/preview',
            headers=doc_auth_headers,
            json={
                'target_location_id': str(warehouse.id),
                'lines': [
                    {'product_template_id': str(cable.id), 'quantity': 6},
                ],
            },
        )
        assert preview.status_code == status.HTTP_200_OK, preview.text
        planned = preview.json()[0]
        assert planned['planned_location_id'] != str(held.id)
        assert planned['planned_source'] != 'rule'

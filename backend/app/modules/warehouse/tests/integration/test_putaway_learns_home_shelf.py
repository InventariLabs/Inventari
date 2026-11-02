"""Putting goods away teaches the app where a product lives.

A small business writes no putaway rules, so the knowledge of where things go
stays in the worker's head. When a worker carries goods to a shelf other than
the one suggested, the put-away answers with an offer: make this the
product's home shelf. A home shelf is an ordinary product-scoped putaway rule,
so the existing ranking, capacity walk and journal take it without a second
code path.

The offer is made only where it means something: never in a warehouse marked
free (chaotic) storage, never when the worker was forced off a full shelf,
never for a product the worker asked not to be asked about, and never for a
shelf that cannot be a home (receiving area, quarantine, one off the lists).
"""

from __future__ import annotations

from datetime import date
from typing import Any, cast
from uuid import UUID

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper
from app.models.audit_log import AuditLog
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
def area_id(
    client: TestClient, doc_auth_headers: dict[str, str], warehouse: StorageLocation
) -> UUID:
    """A warehouse that receives in two steps; the id of its receiving area."""
    resp = client.put(
        f'{API}/putaway/receiving-modes/{warehouse.id}',
        headers=doc_auth_headers,
        json={'two_step': True},
    )
    assert resp.status_code == status.HTTP_200_OK, resp.text
    return UUID(resp.json()['receiving_location_id'])


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
    template: ProductTemplate,
    quantity: int = 40,
) -> None:
    resp = client.post(
        f'{API}/documents/post',
        headers=headers,
        json={
            'type': 'IN',
            'partner_id': str(partner.id),
            'target_location_id': str(warehouse.id),
            'lines': [
                {'product_template_id': str(template.id), 'expected_quantity': quantity}
            ],
        },
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text


def _task(client: TestClient, headers: dict[str, str]) -> dict[str, Any]:
    resp = client.get(
        f'{API}/todo', headers=headers, params={'date_to': date.today().isoformat()}
    )
    assert resp.status_code == status.HTTP_200_OK, resp.text
    (task,) = [
        item for item in resp.json()['work_items']['items'] if item['kind'] == 'putaway'
    ]
    return cast(dict[str, Any], task)


def _put_away(
    client: TestClient,
    headers: dict[str, str],
    task: dict[str, Any],
    shelf: StorageLocation | UUID,
) -> dict[str, Any]:
    location_id = shelf.id if isinstance(shelf, StorageLocation) else shelf
    resp = client.post(
        f'{API}/work-items/putaway/{task["source_id"]}',
        headers=headers,
        json={'location_id': str(location_id)},
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    return cast(dict[str, Any], resp.json())


def _make_home(
    client: TestClient,
    headers: dict[str, str],
    template: ProductTemplate,
    shelf: StorageLocation | UUID,
) -> Any:
    location_id = shelf.id if isinstance(shelf, StorageLocation) else shelf
    return client.put(
        f'{API}/putaway/home-shelf',
        headers=headers,
        json={
            'product_template_id': str(template.id),
            'location_id': str(location_id),
        },
    )


def _free_placement(
    client: TestClient, headers: dict[str, str], warehouse: StorageLocation
) -> None:
    resp = client.put(
        f'{API}/putaway/receiving-modes/{warehouse.id}',
        headers=headers,
        json={'free_placement': True},
    )
    assert resp.status_code == status.HTTP_200_OK, resp.text
    assert resp.json()['free_placement'] is True
    assert resp.json()['two_step'] is True


@pytest.mark.integration
class TestPutawayLearnsHomeShelf:
    def test_a_shelf_other_than_the_suggestion_offers_to_become_the_home(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        warehouse: StorageLocation,
        shelf_a: StorageLocation,
        shelf_b: StorageLocation,
        rice: ProductTemplate,
        area_id: UUID,
    ) -> None:
        _rule(client, doc_auth_headers, rice, shelf_a)
        _receive(client, doc_auth_headers, doc_partner, warehouse, rice)
        task = _task(client, doc_auth_headers)
        assert task['place_id'] == str(shelf_a.id)

        moved = _put_away(client, doc_auth_headers, task, shelf_b)

        offer = moved['home_shelf']
        assert offer['kind'] == 'change'
        assert offer['product_template_id'] == str(rice.id)
        assert offer['product_name'] == 'Jasmine Rice'
        assert offer['location_id'] == str(shelf_b.id)
        assert offer['location_name'] == 'Shelf B'

        # No answer yet: the next delivery is still sent to the old shelf.
        _receive(client, doc_auth_headers, doc_partner, warehouse, rice)
        assert _task(client, doc_auth_headers)['place_id'] == str(shelf_a.id)

    def test_saying_yes_changes_the_next_suggestion_for_that_product(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        warehouse: StorageLocation,
        shelf_a: StorageLocation,
        shelf_b: StorageLocation,
        rice: ProductTemplate,
        area_id: UUID,
    ) -> None:
        _rule(client, doc_auth_headers, rice, shelf_a)
        _receive(client, doc_auth_headers, doc_partner, warehouse, rice)
        _put_away(client, doc_auth_headers, _task(client, doc_auth_headers), shelf_b)

        made = _make_home(client, doc_auth_headers, rice, shelf_b)
        assert made.status_code == status.HTTP_200_OK, made.text

        _receive(client, doc_auth_headers, doc_partner, warehouse, rice)
        task = _task(client, doc_auth_headers)
        assert task['place_id'] == str(shelf_b.id)
        assert task['place_source'] == 'rule'
        # The act is in the organization log, against the product.
        entry = db_session.scalars(
            select(AuditLog).where(AuditLog.target_id == rice.id)
        ).one()
        assert entry.snapshot == {'home_shelf': 'Shelf B'}
        # The rule it rewrote is the one that was there: no second rule.
        rules = client.get(f'{API}/putaway-rules', headers=doc_auth_headers).json()
        assert len(rules['items']) == 1

    def test_the_suggested_shelf_asks_nothing(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        warehouse: StorageLocation,
        shelf_a: StorageLocation,
        rice: ProductTemplate,
        area_id: UUID,
    ) -> None:
        _rule(client, doc_auth_headers, rice, shelf_a)
        _receive(client, doc_auth_headers, doc_partner, warehouse, rice)

        moved = _put_away(
            client, doc_auth_headers, _task(client, doc_auth_headers), shelf_a
        )

        assert moved['home_shelf'] is None

    def test_a_product_without_a_suggestion_is_offered_the_shelf_it_was_put_on(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        warehouse: StorageLocation,
        shelf_a: StorageLocation,
        rice: ProductTemplate,
        area_id: UUID,
    ) -> None:
        _receive(client, doc_auth_headers, doc_partner, warehouse, rice)
        task = _task(client, doc_auth_headers)
        assert task['place_id'] is None

        moved = _put_away(client, doc_auth_headers, task, shelf_a)

        assert moved['home_shelf']['kind'] == 'set'
        assert moved['home_shelf']['location_id'] == str(shelf_a.id)
        made = _make_home(client, doc_auth_headers, rice, shelf_a)
        assert made.status_code == status.HTTP_200_OK, made.text

        _receive(client, doc_auth_headers, doc_partner, warehouse, rice)
        task = _task(client, doc_auth_headers)
        assert (task['place_id'], task['place_source']) == (str(shelf_a.id), 'rule')

    def test_a_receiving_area_is_never_a_home_shelf(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        rice: ProductTemplate,
        area_id: UUID,
    ) -> None:
        refused = _make_home(client, doc_auth_headers, rice, area_id)

        assert refused.status_code == status.HTTP_400_BAD_REQUEST, refused.text
        assert 'receiving' in refused.text.lower()

    def test_a_quarantine_location_is_neither_offered_nor_accepted(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        warehouse: StorageLocation,
        shelf_a: StorageLocation,
        shelf_b: StorageLocation,
        rice: ProductTemplate,
        area_id: UUID,
    ) -> None:
        named = client.put(
            f'{API}/profile',
            headers=doc_auth_headers,
            json={'quarantine_location_id': str(shelf_b.id)},
        )
        assert named.status_code == status.HTTP_200_OK, named.text
        _rule(client, doc_auth_headers, rice, shelf_a)
        _receive(client, doc_auth_headers, doc_partner, warehouse, rice)

        moved = _put_away(
            client, doc_auth_headers, _task(client, doc_auth_headers), shelf_b
        )

        assert moved['home_shelf']['kind'] == 'refused'
        assert moved['home_shelf']['reason'] == 'quarantine'
        refused = _make_home(client, doc_auth_headers, rice, shelf_b)
        assert refused.status_code == status.HTTP_400_BAD_REQUEST, refused.text
        assert 'quarantine' in refused.text.lower()

    def test_a_location_off_the_lists_is_refused_with_its_reason(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        shelf_b: StorageLocation,
        rice: ProductTemplate,
    ) -> None:
        shelf_b.settings = {'archived': True}
        db_session.commit()

        refused = _make_home(client, doc_auth_headers, rice, shelf_b)

        assert refused.status_code == status.HTTP_400_BAD_REQUEST, refused.text

    def test_a_warehouse_of_free_placement_never_asks(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        warehouse: StorageLocation,
        shelf_a: StorageLocation,
        shelf_b: StorageLocation,
        rice: ProductTemplate,
        area_id: UUID,
    ) -> None:
        _free_placement(client, doc_auth_headers, warehouse)
        _rule(client, doc_auth_headers, rice, shelf_a)
        _receive(client, doc_auth_headers, doc_partner, warehouse, rice)

        moved = _put_away(
            client, doc_auth_headers, _task(client, doc_auth_headers), shelf_b
        )

        assert moved['home_shelf'] is None
        listed = client.get(
            f'{API}/putaway/receiving-modes', headers=doc_auth_headers
        ).json()
        assert listed['items'][0]['free_placement'] is True

    def test_the_setting_defaults_to_asking_and_can_be_turned_back(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        warehouse: StorageLocation,
        area_id: UUID,
    ) -> None:
        listed = client.get(
            f'{API}/putaway/receiving-modes', headers=doc_auth_headers
        ).json()
        assert listed['items'][0]['free_placement'] is False

        _free_placement(client, doc_auth_headers, warehouse)
        back = client.put(
            f'{API}/putaway/receiving-modes/{warehouse.id}',
            headers=doc_auth_headers,
            json={'free_placement': False},
        )
        assert back.json()['free_placement'] is False
        assert back.json()['two_step'] is True

    def test_a_forced_choice_asks_nothing(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        warehouse: StorageLocation,
        shelf_a: StorageLocation,
        shelf_b: StorageLocation,
        rice: ProductTemplate,
        area_id: UUID,
    ) -> None:
        _rule(client, doc_auth_headers, rice, shelf_a)
        limit = client.post(
            f'{API}/putaway/capacity',
            headers=doc_auth_headers,
            json={
                'location_id': str(shelf_a.id),
                'product_template_id': str(rice.id),
                'max_quantity': '10',
            },
        )
        assert limit.status_code == status.HTTP_201_CREATED, limit.text
        # 40 kg into a shelf that holds 10: the shelf is full for this delivery.
        _receive(client, doc_auth_headers, doc_partner, warehouse, rice)

        moved = _put_away(
            client, doc_auth_headers, _task(client, doc_auth_headers), shelf_b
        )

        assert moved['home_shelf'] is None

    def test_do_not_ask_again_is_remembered_per_product_and_can_be_undone(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        warehouse: StorageLocation,
        shelf_a: StorageLocation,
        shelf_b: StorageLocation,
        rice: ProductTemplate,
        area_id: UUID,
    ) -> None:
        muted = client.put(
            f'{API}/putaway/home-shelf/silenced/{rice.id}', headers=doc_auth_headers
        )
        assert muted.status_code == status.HTTP_204_NO_CONTENT, muted.text
        # Twice is the same answer as once.
        again = client.put(
            f'{API}/putaway/home-shelf/silenced/{rice.id}', headers=doc_auth_headers
        )
        assert again.status_code == status.HTTP_204_NO_CONTENT, again.text
        silenced = client.get(
            f'{API}/putaway/home-shelf/silenced', headers=doc_auth_headers
        ).json()
        assert [row['product_template_id'] for row in silenced['items']] == [
            str(rice.id)
        ]
        assert silenced['items'][0]['product_name'] == 'Jasmine Rice'

        _rule(client, doc_auth_headers, rice, shelf_a)
        _receive(client, doc_auth_headers, doc_partner, warehouse, rice)
        moved = _put_away(
            client, doc_auth_headers, _task(client, doc_auth_headers), shelf_b
        )
        assert moved['home_shelf'] is None

        undone = client.delete(
            f'{API}/putaway/home-shelf/silenced/{rice.id}', headers=doc_auth_headers
        )
        assert undone.status_code == status.HTTP_204_NO_CONTENT, undone.text
        _receive(client, doc_auth_headers, doc_partner, warehouse, rice)
        moved = _put_away(
            client, doc_auth_headers, _task(client, doc_auth_headers), shelf_b
        )
        assert moved['home_shelf']['kind'] == 'change'

    def test_a_learned_home_is_ranked_like_any_other_product_rule(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        shelf_a: StorageLocation,
        shelf_b: StorageLocation,
        rice: ProductTemplate,
    ) -> None:
        """The home is an ordinary product rule, so the settings screen sees it
        and the rule list shows it at the head of the product's shelves."""
        assert (
            _make_home(client, doc_auth_headers, rice, shelf_a).status_code
            == status.HTTP_200_OK
        )
        assert (
            _make_home(client, doc_auth_headers, rice, shelf_b).status_code
            == status.HTTP_200_OK
        )

        (rule,) = client.get(f'{API}/putaway-rules', headers=doc_auth_headers).json()[
            'items'
        ]
        assert rule['product_template_id'] == str(rice.id)
        assert [loc['location_id'] for loc in rule['locations']] == [
            str(shelf_b.id),
            str(shelf_a.id),
        ]

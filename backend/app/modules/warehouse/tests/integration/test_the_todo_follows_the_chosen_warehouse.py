"""To do can be narrowed to one warehouse, and the tasks that stand in a place follow it.

A person who works in one of several warehouses chose it on the Start screen,
and the task list used to show every warehouse's work regardless. Documents
name the place they go to or come from, and a putaway task stands in the
receiving area of one warehouse, so those follow the choice. A task that names
no warehouse (an order, a production run, a count, a task typed in by hand)
stays in view, because hiding it would hide work nobody can find elsewhere.
"""

from __future__ import annotations

from datetime import date
from typing import Any, cast
from uuid import UUID

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.user import User


def _warehouse(
    h: ModuleTestHelper,
    org: Organization,
    storage_type: StorageType,
    user: User,
    name: str,
) -> StorageLocation:
    return h.create_storage_location(org, storage_type, user, name=name)


def _two_step(client: TestClient, headers: dict[str, str], warehouse_id: UUID) -> None:
    resp = client.put(
        f'/api/v1/warehouse/putaway/receiving-modes/{warehouse_id}',
        headers=headers,
        json={'two_step': True},
    )
    assert resp.status_code == status.HTTP_200_OK, resp.text


def _receive(
    client: TestClient,
    headers: dict[str, str],
    partner: Partner,
    warehouse: StorageLocation,
    template: ProductTemplate,
    *,
    post: bool,
) -> dict[str, Any]:
    resp = client.post(
        '/api/v1/warehouse/documents/post' if post else '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'IN',
            'partner_id': str(partner.id),
            'target_location_id': str(warehouse.id),
            'scheduled_date': date.today().isoformat(),
            'lines': [
                {'product_template_id': str(template.id), 'expected_quantity': 5}
            ],
        },
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    body = cast(dict[str, Any], resp.json())
    if not post:
        confirmed = client.patch(
            f'/api/v1/warehouse/documents/{body["id"]}/confirm', headers=headers
        )
        assert confirmed.status_code == status.HTTP_200_OK, confirmed.text
    return body


def _tasks(
    client: TestClient, headers: dict[str, str], **params: str
) -> list[dict[str, Any]]:
    resp = client.get(
        '/api/v1/warehouse/todo',
        headers=headers,
        params={'date_to': date.today().isoformat(), **params},
    )
    assert resp.status_code == status.HTTP_200_OK, resp.text
    return cast(list[dict[str, Any]], resp.json()['work_items']['items'])


@pytest.mark.integration
class TestTheTodoFollowsTheChosenWarehouse:
    def test_putaway_and_receipts_of_another_warehouse_are_left_out(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        doc_org: Organization,
        doc_user: User,
        doc_storage_type: StorageType,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
    ) -> None:
        north = _warehouse(h, doc_org, doc_storage_type, doc_user, 'North')
        south = _warehouse(h, doc_org, doc_storage_type, doc_user, 'South')
        rice = h.create_template(doc_org, name='Jasmine Rice')
        beans = h.create_template(doc_org, name='Black Beans')
        _two_step(client, doc_auth_headers, north.id)
        _two_step(client, doc_auth_headers, south.id)
        _receive(client, doc_auth_headers, doc_partner, north, rice, post=True)
        _receive(client, doc_auth_headers, doc_partner, south, beans, post=True)
        _receive(client, doc_auth_headers, doc_partner, north, beans, post=False)
        _receive(client, doc_auth_headers, doc_partner, south, rice, post=False)

        everything = _tasks(client, doc_auth_headers)
        assert {t['kind'] for t in everything} >= {'putaway', 'receive'}
        assert sum(t['kind'] == 'putaway' for t in everything) == 2
        assert sum(t['kind'] == 'receive' for t in everything) == 2

        north_only = _tasks(client, doc_auth_headers, location_id=str(north.id))
        assert sorted(t['subject'] for t in north_only if t['kind'] == 'putaway') == [
            'Jasmine Rice'
        ]
        receipts = [t for t in north_only if t['kind'] == 'receive']
        assert len(receipts) == 1
        south_only = _tasks(client, doc_auth_headers, location_id=str(south.id))
        assert sorted(t['subject'] for t in south_only if t['kind'] == 'putaway') == [
            'Black Beans'
        ]
        assert {t['key'] for t in receipts}.isdisjoint(
            t['key'] for t in south_only if t['kind'] == 'receive'
        )

    def test_a_task_that_names_no_warehouse_stays_in_view(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        doc_org: Organization,
        doc_user: User,
        doc_storage_type: StorageType,
        doc_auth_headers: dict[str, str],
    ) -> None:
        north = _warehouse(h, doc_org, doc_storage_type, doc_user, 'North')
        created = client.post(
            '/api/v1/warehouse/work-items/custom',
            headers=doc_auth_headers,
            json={'title': 'Wash the forklift'},
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        subjects = [
            t['subject']
            for t in _tasks(client, doc_auth_headers, location_id=str(north.id))
        ]
        assert subjects == ['Wash the forklift']

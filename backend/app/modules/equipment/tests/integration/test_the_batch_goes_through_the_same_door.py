"""Issuing forty assets is issuing one asset, forty times.

The bulk route is a second implementation of a checkout, and it did not
inherit what the single one had grown. Measured on `dev` before this file
existed: `POST /equipment/assignments` on a retired asset was refused by
name, and `PATCH /equipment/assets/bulk` handed the identical asset out and
set it DEPLOYED; the approvals queue was consulted on one route and not the
other; and a webhook subscribed to checkouts heard about assets given out
singly and nothing at all about a batch.

Every test here has a sibling assertion on the single route, so a future
change that fixes one and forgets the other reads as a failure rather than
as two different products.

Measured with the fix reverted: four go red -- the batch handing out a
retired asset (`assert 'DEPLOYED' == 'RETIRED'`, which is the defect as a
user meets it), the batch walking past the approval control, and the batch
announcing nothing. The three single-route assertions and
`test_a_refused_asset_announces_nothing` pass either way: they are pins on
behaviour that must not move, not measurements of this change.

The retire of an asset somebody is holding is the same shape one step
later: `test_the_batch_retire_emits_one_checkin_per_held_asset` goes red
with the fix reverted (`assert [] == [EquipmentEvent.CHECKIN]` — the return
that closed the assignment was announced to nobody), and the single-route
check-in pin beside it passes either way.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from fastapi import status
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
from starlette.testclient import TestClient

from app.core.testing import ModuleTestHelper
from app.models.item import Item


def _set_status(item: Item, db_session: Session, status: str) -> None:
    meta = dict(item.meta_data or {})
    meta['equipment'] = {
        **meta.get('equipment', {}),
        'equipment_status': status,
    }
    item.meta_data = meta
    flag_modified(item, 'meta_data')
    db_session.commit()


def _retire(item: Item, db_session: Session) -> None:
    _set_status(item, db_session, 'RETIRED')


def _issue_in_bulk(
    client: TestClient, headers: dict[str, str], item: Item, name: str = 'Alice'
) -> Any:
    return client.patch(
        '/api/v1/equipment/assets/bulk',
        headers=headers,
        json={
            'item_ids': [str(item.id)],
            'action': 'assign_to',
            'data': {'assigned_to_name': name},
        },
    )


@pytest.mark.integration
class TestARetiredAssetIsRefusedByBothRoutes:
    def test_the_single_checkout_refuses_it(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        _retire(eq_item, db_session)

        response = client.post(
            '/api/v1/equipment/assignments',
            headers=eq_auth_headers,
            json={'item_id': str(eq_item.id), 'assigned_to_name': 'Alice'},
        )

        assert response.status_code == status.HTTP_409_CONFLICT, response.text
        assert response.json()['detail']['code'] == 'EQUIPMENT_CANNOT_CHECKOUT_RETIRED'

    def test_the_batch_refuses_it_too(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        _retire(eq_item, db_session)

        response = _issue_in_bulk(client, eq_auth_headers, eq_item)

        assert response.status_code == status.HTTP_200_OK, response.text
        body = response.json()
        assert body['updated'] == 0
        assert len(body['errors']) == 1
        assert 'retired' in body['errors'][0]['error'].lower()

    def test_and_leaves_it_retired_and_unassigned(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        """The refusal that mattered: it used to write DEPLOYED over RETIRED."""
        from app.modules.equipment.models import EquipmentAssignment

        _retire(eq_item, db_session)

        _issue_in_bulk(client, eq_auth_headers, eq_item)

        db_session.refresh(eq_item)
        assert eq_item.meta_data is not None
        assert eq_item.meta_data['equipment']['equipment_status'] == 'RETIRED'
        assert (
            db_session.query(EquipmentAssignment)
            .filter(EquipmentAssignment.item_id == eq_item.id)
            .count()
            == 0
        )


@pytest.mark.integration
class TestAnAssetInMaintenanceIsRefusedByBothRoutes:
    """An asset in the workshop is not handed out by either route.

    The asset page offers no Check Out for it, but both checkouts refused
    only a retired asset: the batch wrote DEPLOYED over MAINTENANCE, the
    toast counted the asset as updated, and an open repair entry stayed open
    on an asset out on loan. Measured with the fix reverted: all three go
    red -- the single route answers 201, the batch reports one updated, and
    the status reads DEPLOYED.
    """

    def test_the_single_checkout_refuses_it(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        _set_status(eq_item, db_session, 'MAINTENANCE')

        response = client.post(
            '/api/v1/equipment/assignments',
            headers=eq_auth_headers,
            json={'item_id': str(eq_item.id), 'assigned_to_name': 'Alice'},
        )

        assert response.status_code == status.HTTP_409_CONFLICT, response.text
        assert (
            response.json()['detail']['code']
            == 'EQUIPMENT_CANNOT_CHECKOUT_IN_MAINTENANCE'
        )

    def test_the_batch_reports_it_failed_not_updated(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        _set_status(eq_item, db_session, 'MAINTENANCE')

        response = _issue_in_bulk(client, eq_auth_headers, eq_item)

        assert response.status_code == status.HTTP_200_OK, response.text
        body = response.json()
        assert body['updated'] == 0
        assert [e['code'] for e in body['errors']] == [
            'EQUIPMENT_CANNOT_CHECKOUT_IN_MAINTENANCE'
        ]

    def test_and_leaves_it_in_maintenance_and_unassigned(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        from app.modules.equipment.models import EquipmentAssignment

        _set_status(eq_item, db_session, 'MAINTENANCE')

        _issue_in_bulk(client, eq_auth_headers, eq_item)

        db_session.refresh(eq_item)
        assert eq_item.meta_data is not None
        assert eq_item.meta_data['equipment']['equipment_status'] == 'MAINTENANCE'
        assert (
            db_session.query(EquipmentAssignment)
            .filter(EquipmentAssignment.item_id == eq_item.id)
            .count()
            == 0
        )


@pytest.fixture
def org_with_a_checkout_workflow(
    h: ModuleTestHelper, client: TestClient
) -> dict[str, Any]:
    """An organization whose checkouts are under an approval control."""
    org = h.create_org(
        'Batch+Approvals Org',
        ['core', 'items', 'locations', 'categories', 'equipment', 'approvals'],
    )
    admin = h.create_user(org, email=f'adm_{uuid4().hex[:6]}@test.com', role='admin')
    response = client.post(
        '/api/v1/approvals/workflows',
        headers=h.get_auth_headers(admin),
        json={
            'target_type': 'equipment_checkout',
            'requester_scope': {'everyone': True},
            'name': 'Manager signs for equipment',
            'stages': [
                {
                    'order': 1,
                    'role': 'manager',
                    'label': 'Manager Approval',
                    'approver_user_ids': [],
                }
            ],
            'is_active': True,
            'expected_scope': {'holds': 'all'},
        },
    )
    assert response.status_code == status.HTTP_201_CREATED, response.text
    return {'org': org, 'admin': admin, 'h': h}


def _asset_in(db_session: Session, h: ModuleTestHelper, org: Any, admin: Any) -> Item:
    from app.models.category import Category

    storage_type = h.create_storage_type(
        f'IT Storage {uuid4().hex[:4]}', f'IT_{uuid4().hex[:4].upper()}'
    )
    location = h.create_storage_location(org, storage_type, admin, name='Loc')
    category = Category(
        name='Laptop',
        code=f'LAPTOP_{uuid4().hex[:4]}',
        context_tag='equipment',
        organization_id=org.id,
        field_definitions=[],
    )
    db_session.add(category)
    db_session.commit()
    item = Item(
        name='ThinkPad X1',
        organization_id=org.id,
        storage_location_id=location.id,
        category_id=category.id,
        quantity=1,
        meta_data={'equipment': {'equipment_status': 'AVAILABLE'}},
    )
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)
    return item


@pytest.mark.integration
class TestTheApprovalQueueIsNotAboutWhichButtonWasPressed:
    def test_the_single_checkout_is_blocked(
        self,
        client: TestClient,
        org_with_a_checkout_workflow: dict[str, Any],
        db_session: Session,
    ) -> None:
        org = org_with_a_checkout_workflow['org']
        admin = org_with_a_checkout_workflow['admin']
        h = org_with_a_checkout_workflow['h']
        item = _asset_in(db_session, h, org, admin)

        response = client.post(
            '/api/v1/equipment/assignments',
            headers=h.get_auth_headers(admin),
            json={'item_id': str(item.id), 'assigned_to_name': 'Bob'},
        )

        assert response.status_code == status.HTTP_409_CONFLICT, response.text

    def test_the_batch_is_blocked_by_the_same_control(
        self,
        client: TestClient,
        org_with_a_checkout_workflow: dict[str, Any],
        db_session: Session,
    ) -> None:
        from app.modules.equipment.models import EquipmentAssignment

        org = org_with_a_checkout_workflow['org']
        admin = org_with_a_checkout_workflow['admin']
        h = org_with_a_checkout_workflow['h']
        item = _asset_in(db_session, h, org, admin)

        response = _issue_in_bulk(client, h.get_auth_headers(admin), item, 'Bob')

        assert response.status_code == status.HTTP_200_OK, response.text
        body = response.json()
        assert body['updated'] == 0
        assert len(body['errors']) == 1
        assert 'approval' in body['errors'][0]['error'].lower()
        assert (
            db_session.query(EquipmentAssignment)
            .filter(EquipmentAssignment.item_id == item.id)
            .count()
            == 0
        )


@pytest.mark.integration
class TestASubscriberHearsAboutABatch:
    def test_the_batch_emits_one_checkout_event_per_asset(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The event the webhook documentation calls 'equipment was handed out'."""
        from app.modules.equipment import bulk_service
        from app.modules.equipment.events import EquipmentEvent

        emitted: list[tuple[Any, Any]] = []

        async def _record(event: Any, payload: Any, label: str = '') -> None:
            emitted.append((event, payload))

        monkeypatch.setattr('app.core.events.emit_safe', _record)
        assert bulk_service is not None

        response = _issue_in_bulk(client, eq_auth_headers, eq_item)

        assert response.status_code == status.HTTP_200_OK, response.text
        assert response.json()['updated'] == 1
        assert [event for event, _ in emitted] == [EquipmentEvent.CHECKOUT]
        payload = emitted[0][1]
        assert payload.item_id == str(eq_item.id)
        assert payload.assigned_to_name == 'Alice'

    def test_a_refused_asset_announces_nothing(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Events are handed to the caller and emitted after the commit, so a
        rolled-back asset never reaches a subscriber."""
        emitted: list[Any] = []

        async def _record(event: Any, payload: Any, label: str = '') -> None:
            emitted.append(event)

        monkeypatch.setattr('app.core.events.emit_safe', _record)
        _retire(eq_item, db_session)

        _issue_in_bulk(client, eq_auth_headers, eq_item)

        assert emitted == []


def _second_asset(
    db_session: Session,
    org: Any,
    location: Any,
    category: Any,
    name: str = 'Spare dock',
) -> Item:
    """Another asset in the same organization, so a batch has two rows."""
    item = Item(
        name=name,
        organization_id=org.id,
        storage_location_id=location.id,
        category_id=category.id,
        quantity=1,
        meta_data={'equipment': {'equipment_status': 'AVAILABLE'}},
    )
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)
    return item


def _retire_in_bulk(
    client: TestClient, headers: dict[str, str], items: list[Item]
) -> Any:
    return client.patch(
        '/api/v1/equipment/assets/bulk',
        headers=headers,
        json={
            'item_ids': [str(item.id) for item in items],
            'action': 'change_status',
            'data': {'status': 'RETIRED'},
        },
    )


@pytest.mark.integration
class TestARetiredAssetReturnsWhatItWasHolding:
    """The door that closes a checkout is the door that announces it.

    Retiring an asset closes the assignment it was under, and that fact
    reached the item history and nothing else: a webhook subscribed to
    returns never heard about an asset retired out of somebody's hands,
    while the same return made one at a time was announced in full.
    """

    def test_the_batch_retire_emits_one_checkin_per_held_asset(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_org: Any,
        eq_storage_location: Any,
        eq_category: Any,
        eq_item: Item,
        db_session: Session,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.modules.equipment.events import EquipmentEvent
        from app.modules.equipment.models import EquipmentAssignment

        free = _second_asset(db_session, eq_org, eq_storage_location, eq_category)
        held = _second_asset(
            db_session, eq_org, eq_storage_location, eq_category, name='ThinkPad X1'
        )
        refused = _second_asset(
            db_session, eq_org, eq_storage_location, eq_category, name='Old router'
        )
        _retire(refused, db_session)
        issued = _issue_in_bulk(client, eq_auth_headers, held, 'Alice')
        assert issued.status_code == status.HTTP_200_OK, issued.text
        assert issued.json()['updated'] == 1
        assignment = (
            db_session.query(EquipmentAssignment)
            .filter(EquipmentAssignment.item_id == held.id)
            .one()
        )

        emitted: list[tuple[Any, Any]] = []

        async def _record(event: Any, payload: Any, label: str = '') -> None:
            emitted.append((event, payload))

        monkeypatch.setattr('app.core.events.emit_safe', _record)

        response = _retire_in_bulk(client, eq_auth_headers, [held, free, refused])

        assert response.status_code == status.HTTP_200_OK, response.text
        body = response.json()
        assert body['updated'] == 2
        assert len(body['errors']) == 1, (
            'the asset that is already retired is refused, and refusing it '
            'must not stop the two that went through'
        )
        assert [event for event, _ in emitted] == [EquipmentEvent.CHECKIN], (
            'the asset that was out is announced as returned; the one that '
            'stood on the shelf and the one the batch refused have no return '
            'to announce'
        )
        payload = emitted[0][1]
        assert payload.item_id == str(held.id)
        assert payload.assignment_id == str(assignment.id)
        assert payload.assigned_to_name == 'Alice'
        assert payload.new_status == 'RETIRED'
        assert payload.checkin_condition is None, (
            'nothing inspected the asset on the way out, so no condition is '
            'invented for the subscriber'
        )
        db_session.refresh(assignment)
        assert assignment.checked_in_at is not None

    def test_the_single_checkin_says_the_same_thing(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The pin: the door the batch is being held to.

        Passes with the fix reverted — it holds the single route's shape
        still while the batch test above is the one that moves.
        """
        from app.modules.equipment.events import EquipmentEvent
        from app.modules.equipment.models import EquipmentAssignment

        _issue_in_bulk(client, eq_auth_headers, eq_item, 'Alice')
        assignment = (
            db_session.query(EquipmentAssignment)
            .filter(EquipmentAssignment.item_id == eq_item.id)
            .one()
        )

        emitted: list[tuple[Any, Any]] = []

        async def _record(event: Any, payload: Any, label: str = '') -> None:
            emitted.append((event, payload))

        monkeypatch.setattr('app.core.events.emit_safe', _record)

        response = client.post(
            f'/api/v1/equipment/assignments/{assignment.id}/checkin',
            headers=eq_auth_headers,
            json={'checkin_condition': 'GOOD'},
        )

        assert response.status_code == status.HTTP_200_OK, response.text
        assert [event for event, _ in emitted] == [EquipmentEvent.CHECKIN]
        payload = emitted[0][1]
        assert payload.item_id == str(eq_item.id)
        assert payload.assigned_to_name == 'Alice'
        assert payload.new_status == 'AVAILABLE'
        assert payload.checkin_condition == 'GOOD'

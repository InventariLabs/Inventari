"""
 integration tests: one attestation response and email per person.

Launching a campaign used to create one AuditResponse per active
assignment — seven assets held by four people produced seven emails. Now
responses are grouped by (case-insensitive) email: one envelope with one
token and several item rows; the public page confirms everything at once
and disputes a specific asset.
"""

from datetime import datetime
from typing import Any

import pytest
from fastapi import status
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models.category import Category
from app.models.item import Item
from app.models.organization import Organization
from app.models.storage_location import StorageLocation
from app.modules.equipment.models import AuditResponse, AuditResponseItem


def _make_deadline(days: int = 30) -> str:
    from datetime import UTC, datetime, timedelta

    return (datetime.now(UTC) + timedelta(days=days)).isoformat()


def _checkout(
    client: TestClient,
    headers: dict[str, str],
    item_id: Any,
    name: str = 'Anna Kowalska',
    email: str = 'anna@example.com',
) -> dict[str, Any]:
    r = client.post(
        '/api/v1/equipment/assignments',
        headers=headers,
        json={
            'item_id': str(item_id),
            'assigned_to_name': name,
            'assigned_to_email': email,
        },
    )
    assert r.status_code == status.HTTP_201_CREATED, r.text
    return r.json()  # type: ignore[no-any-return]


def _create_asset(
    db_session: Session,
    org_id: Any,
    storage_location_id: Any,
    category_id: Any,
    name: str,
) -> Item:
    item = Item(
        name=name,
        organization_id=org_id,
        storage_location_id=storage_location_id,
        category_id=category_id,
        quantity=1,
        meta_data={'equipment': {'equipment_status': 'AVAILABLE'}},
    )
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)
    return item


def _launch(
    client: TestClient, headers: dict[str, str], name: str = 'Grouped Audit'
) -> dict[str, Any]:
    create_r = client.post(
        '/api/v1/equipment/campaigns',
        headers=headers,
        json={'name': name, 'deadline': _make_deadline(14)},
    )
    assert create_r.status_code == status.HTTP_201_CREATED, create_r.text
    campaign_id = create_r.json()['id']
    launch_r = client.post(
        f'/api/v1/equipment/campaigns/{campaign_id}/launch', headers=headers
    )
    assert launch_r.status_code == status.HTTP_200_OK, launch_r.text
    return launch_r.json()  # type: ignore[no-any-return]


def _tokens(db_session: Session) -> list[str]:
    return list(db_session.scalars(select(AuditResponse.token)).all())


@pytest.mark.integration
class TestAttestationPerPerson:
    """One response + one email per person, one item row per asset."""

    def test_launch_groups_assignments_by_email(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_org: Organization,
        eq_storage_location: StorageLocation,
        eq_category: Category,
        db_session: Session,
    ) -> None:
        item_a = _create_asset(
            db_session, eq_org.id, eq_storage_location.id, eq_category.id, 'Laptop A'
        )
        item_b = _create_asset(
            db_session, eq_org.id, eq_storage_location.id, eq_category.id, 'Laptop B'
        )
        item_c = _create_asset(
            db_session, eq_org.id, eq_storage_location.id, eq_category.id, 'Monitor C'
        )

        _checkout(
            client, eq_auth_headers, item_a.id, 'Anna Kowalska', 'Anna@example.com'
        )
        _checkout(
            client, eq_auth_headers, item_b.id, 'Anna Kowalska', 'anna@example.com'
        )
        _checkout(client, eq_auth_headers, item_c.id, 'Bob Nowak', 'bob@example.com')

        data = _launch(client, eq_auth_headers)

        assert data['responses_created'] == 2
        assert data['skipped_no_email'] == 0

        responses = list(db_session.scalars(select(AuditResponse)).all())
        assert len(responses) == 2
        by_email = {r.assignee_email: r for r in responses}
        assert set(by_email) == {'anna@example.com', 'bob@example.com'}

        items = list(db_session.scalars(select(AuditResponseItem)).all())
        assert len(items) == 3
        anna_items = [
            i for i in items if i.response_id == by_email['anna@example.com'].id
        ]
        assert {i.item_name for i in anna_items} == {'Laptop A', 'Laptop B'}

    def test_public_confirm_confirms_all_items(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_org: Organization,
        eq_storage_location: StorageLocation,
        eq_category: Category,
        db_session: Session,
    ) -> None:
        item_a = _create_asset(
            db_session, eq_org.id, eq_storage_location.id, eq_category.id, 'Laptop A'
        )
        item_b = _create_asset(
            db_session, eq_org.id, eq_storage_location.id, eq_category.id, 'Laptop B'
        )
        _checkout(
            client, eq_auth_headers, item_a.id, 'Anna Kowalska', 'anna@example.com'
        )
        _checkout(
            client, eq_auth_headers, item_b.id, 'Anna Kowalska', 'anna@example.com'
        )
        _launch(client, eq_auth_headers)

        token = _tokens(db_session)[0]
        get_r = client.get(f'/public/attestation/{token}')
        assert get_r.status_code == status.HTTP_200_OK
        assert len(get_r.json()['items']) == 2

        confirm_r = client.post(f'/public/attestation/{token}/confirm')
        assert confirm_r.status_code == status.HTTP_200_OK

        db_session.expire_all()
        items = list(db_session.scalars(select(AuditResponseItem)).all())
        assert all(i.status == 'CONFIRMED' for i in items)

    def test_public_dispute_names_one_asset(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_org: Organization,
        eq_storage_location: StorageLocation,
        eq_category: Category,
        db_session: Session,
    ) -> None:
        item_a = _create_asset(
            db_session, eq_org.id, eq_storage_location.id, eq_category.id, 'Laptop A'
        )
        item_b = _create_asset(
            db_session, eq_org.id, eq_storage_location.id, eq_category.id, 'Laptop B'
        )
        _checkout(
            client, eq_auth_headers, item_a.id, 'Anna Kowalska', 'anna@example.com'
        )
        _checkout(
            client, eq_auth_headers, item_b.id, 'Anna Kowalska', 'anna@example.com'
        )
        _launch(client, eq_auth_headers)

        db_session.expire_all()
        response_row = db_session.scalars(select(AuditResponse)).first()
        assert response_row is not None
        target = next(i for i in response_row.items if i.item_name == 'Laptop B')

        dispute_r = client.post(
            f'/public/attestation/{response_row.token}/dispute',
            json={
                'dispute_type': 'DAMAGED',
                'reason': 'Screen cracked',
                'assignment_id': str(target.assignment_id),
            },
        )
        assert dispute_r.status_code == status.HTTP_200_OK

        db_session.expire_all()
        response_row = db_session.scalars(select(AuditResponse)).first()
        assert response_row is not None
        # Laptop A is still to be answered, so the request stays open.
        assert response_row.status == 'PENDING'
        items = {i.item_name: i for i in response_row.items}
        assert items['Laptop B'].status == 'DISPUTED'
        assert items['Laptop B'].dispute_reason == 'Screen cracked'
        assert items['Laptop A'].status == 'PENDING'

    def test_report_one_asset_then_confirm_the_rest(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_org: Organization,
        eq_storage_location: StorageLocation,
        eq_category: Category,
        db_session: Session,
    ) -> None:
        names = ['Laptop A', 'Laptop B', 'Laptop C']
        for name in names:
            item = _create_asset(
                db_session,
                eq_org.id,
                eq_storage_location.id,
                eq_category.id,
                name,
            )
            _checkout(
                client, eq_auth_headers, item.id, 'Anna Kowalska', 'anna@example.com'
            )
        _launch(client, eq_auth_headers)

        db_session.expire_all()
        response_row = db_session.scalars(select(AuditResponse)).first()
        assert response_row is not None
        token = response_row.token
        target = next(i for i in response_row.items if i.item_name == 'Laptop B')

        dispute_r = client.post(
            f'/public/attestation/{token}/dispute',
            json={
                'dispute_type': 'DAMAGED',
                'reason': 'Screen cracked in transit',
                'assignment_id': str(target.assignment_id),
            },
        )
        assert dispute_r.status_code == status.HTTP_200_OK
        # The link is still open for the two assets nobody has answered for.
        assert dispute_r.json()['status'] == 'PENDING'
        assert dispute_r.json()['closed_reason'] is None

        confirm_r = client.post(f'/public/attestation/{token}/confirm')
        assert confirm_r.status_code == status.HTTP_200_OK
        assert confirm_r.json()['status'] == 'DISPUTED'

        db_session.expire_all()
        by_name = {
            i.item_name: i.status for i in db_session.scalars(select(AuditResponseItem))
        }
        assert by_name == {
            'Laptop A': 'CONFIRMED',
            'Laptop B': 'DISPUTED',
            'Laptop C': 'CONFIRMED',
        }

        detail = client.get(
            f'/api/v1/equipment/campaigns/{response_row.campaign_id}',
            headers=eq_auth_headers,
        ).json()
        (row,) = detail['responses']
        assert row['dispute_reason'] == 'Laptop B — Screen cracked in transit'
        assert row['dispute_type'] == 'DAMAGED'
        noted = {i['item_name']: i['dispute_reason'] for i in row['items']}
        assert noted['Laptop B'] == 'Screen cracked in transit'
        assert noted['Laptop A'] is None

    def test_a_report_keeps_its_own_time_through_later_answers(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_org: Organization,
        eq_storage_location: StorageLocation,
        eq_category: Category,
        db_session: Session,
    ) -> None:
        for name in ['Laptop A', 'Laptop B', 'Laptop C']:
            item = _create_asset(
                db_session,
                eq_org.id,
                eq_storage_location.id,
                eq_category.id,
                name,
            )
            _checkout(
                client, eq_auth_headers, item.id, 'Anna Kowalska', 'anna@example.com'
            )
        _launch(client, eq_auth_headers)

        db_session.expire_all()
        response_row = db_session.scalars(select(AuditResponse)).first()
        assert response_row is not None
        token = response_row.token
        by_name = {i.item_name: i for i in response_row.items}

        def report(name: str) -> None:
            r = client.post(
                f'/public/attestation/{token}/dispute',
                json={
                    'dispute_type': 'DAMAGED',
                    'reason': f'{name} broken',
                    'assignment_id': str(by_name[name].assignment_id),
                },
            )
            assert r.status_code == status.HTTP_200_OK

        def reported_at(name: str) -> datetime:
            db_session.expire_all()
            row = db_session.scalars(
                select(AuditResponseItem).where(AuditResponseItem.item_name == name)
            ).one()
            assert row.responded_at is not None
            return row.responded_at

        def timeline_date(name: str) -> str:
            events = client.get(
                f'/api/v1/equipment/assets/{by_name[name].item_id}/timeline',
                headers=eq_auth_headers,
            ).json()['events']
            (event,) = [e for e in events if e['kind'] == 'attestation_disputed']
            return str(event['date'])

        report('Laptop B')
        b_at = reported_at('Laptop B')
        report('Laptop C')
        c_at = reported_at('Laptop C')
        assert c_at > b_at
        assert datetime.fromisoformat(timeline_date('Laptop B')) == b_at

        confirm_r = client.post(f'/public/attestation/{token}/confirm')
        assert confirm_r.status_code == status.HTTP_200_OK
        assert confirm_r.json()['status'] == 'DISPUTED'

        # Settling the envelope must not move the reports it contains.
        assert reported_at('Laptop B') == b_at
        assert reported_at('Laptop C') == c_at
        assert datetime.fromisoformat(timeline_date('Laptop B')) == b_at
        assert datetime.fromisoformat(timeline_date('Laptop C')) == c_at
        assert reported_at('Laptop A') > c_at

    def test_report_leaves_the_row_awaiting_while_assets_are_unanswered(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_org: Organization,
        eq_storage_location: StorageLocation,
        eq_category: Category,
        db_session: Session,
    ) -> None:
        for name in ('Laptop A', 'Laptop B'):
            item = _create_asset(
                db_session,
                eq_org.id,
                eq_storage_location.id,
                eq_category.id,
                name,
            )
            _checkout(
                client, eq_auth_headers, item.id, 'Anna Kowalska', 'anna@example.com'
            )
        _launch(client, eq_auth_headers)

        db_session.expire_all()
        response_row = db_session.scalars(select(AuditResponse)).first()
        assert response_row is not None
        target = next(i for i in response_row.items if i.item_name == 'Laptop A')
        client.post(
            f'/public/attestation/{response_row.token}/dispute',
            json={
                'dispute_type': 'MISSING',
                'reason': 'Left at the old office',
                'assignment_id': str(target.assignment_id),
            },
        )

        detail = client.get(
            f'/api/v1/equipment/campaigns/{response_row.campaign_id}',
            headers=eq_auth_headers,
        ).json()
        assert detail['stats']['disputed'] == 0
        assert detail['stats']['pending'] == 1
        assert detail['responses'][0]['status'] == 'PENDING'

    def test_public_dispute_without_assignment_returns_400(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_org: Organization,
        eq_storage_location: StorageLocation,
        eq_category: Category,
        db_session: Session,
    ) -> None:
        item_a = _create_asset(
            db_session, eq_org.id, eq_storage_location.id, eq_category.id, 'Laptop A'
        )
        item_b = _create_asset(
            db_session, eq_org.id, eq_storage_location.id, eq_category.id, 'Laptop B'
        )
        _checkout(
            client, eq_auth_headers, item_a.id, 'Anna Kowalska', 'anna@example.com'
        )
        _checkout(
            client, eq_auth_headers, item_b.id, 'Anna Kowalska', 'anna@example.com'
        )
        _launch(client, eq_auth_headers)

        db_session.expire_all()
        response_row = db_session.scalars(select(AuditResponse)).first()
        assert response_row is not None

        dispute_r = client.post(
            f'/public/attestation/{response_row.token}/dispute',
            json={'dispute_type': 'DAMAGED', 'reason': 'Missing'},
        )
        assert dispute_r.status_code == status.HTTP_400_BAD_REQUEST

"""Creating, switching on and deleting a workflow reach the log.

A workflow decides which documents stop and wait for somebody's answer, and
setting one up left no row in the organization log: an administrator who
created "Manager approval" and switched it on found the threshold change
beside it in the journal and nothing about the workflow itself. The rows the
requests write are about the requests; this is the rule they wait under.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import pytest
from fastapi import status
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.testing import ModuleTestHelper
from app.models.audit_log import AuditLog
from app.models.organization import Organization
from app.models.user import User

BASE = '/api/v1/approvals'


@pytest.fixture
def h(db_session: Session) -> ModuleTestHelper:
    return ModuleTestHelper(db_session)


@pytest.fixture
def org(h: ModuleTestHelper) -> Organization:
    return h.create_org('Workflow Journal Org', ['core', 'approvals'])


@pytest.fixture
def admin(h: ModuleTestHelper, org: Organization) -> User:
    user = h.create_user(org, email='workflow-journal@example.com', role='manager')
    h.grant_permissions(
        user, ['approvals:read', 'approvals:approve', 'approvals:configure']
    )
    return user


@pytest.fixture
def admin_auth(h: ModuleTestHelper, admin: User) -> dict[str, str]:
    return h.get_auth_headers(admin)


def _workflow_entries(db_session: Session, org_id: UUID) -> list[dict[str, Any]]:
    db_session.expire_all()
    rows = db_session.scalars(
        select(AuditLog)
        .where(AuditLog.organization_id == org_id, AuditLog.target_type == 'module')
        .order_by(AuditLog.created_at.asc())
    ).all()
    return [
        {**(row.snapshot or {}), 'user_id': row.user_id}
        for row in rows
        if (row.snapshot or {}).get('name') == 'approvals'
    ]


@pytest.mark.integration
class TestAWorkflowChangeReachesTheLog:
    def test_create_switch_on_and_delete_each_write_an_entry(
        self,
        client: TestClient,
        admin_auth: dict[str, str],
        admin: User,
        org: Organization,
        db_session: Session,
    ) -> None:
        created = client.post(
            f'{BASE}/workflows',
            headers=admin_auth,
            json={
                'target_type': 'document',
                'requester_scope': {'everyone': True},
                'name': 'Manager approval',
                'stages': [
                    {
                        'order': 1,
                        'role': 'manager',
                        'label': 'Manager',
                        'approver_user_ids': [],
                    }
                ],
            },
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        workflow_id = created.json()['id']
        switched_on = client.patch(
            f'{BASE}/workflows/{workflow_id}',
            headers=admin_auth,
            json={'is_active': True, 'expected_scope': {'holds': 'all'}},
        )
        assert switched_on.status_code == status.HTTP_200_OK, switched_on.text
        deleted = client.delete(f'{BASE}/workflows/{workflow_id}', headers=admin_auth)
        assert deleted.status_code == status.HTTP_200_OK, deleted.text

        entries = _workflow_entries(db_session, org.id)
        assert len(entries) == 3, entries
        made, on, gone = entries
        assert {entry['user_id'] for entry in entries} == {admin.id}
        assert made['subject'] == 'workflow:document'
        assert made['after']['name'] == 'Manager approval'
        assert made['after']['is_active'] is False
        assert on['before'] == {'is_active': False}
        assert on['after'] == {'is_active': True}
        assert gone['before']['name'] == 'Manager approval'
        assert set(gone['after'].values()) == {None}

    def test_an_approver_change_names_the_person(
        self,
        client: TestClient,
        admin_auth: dict[str, str],
        admin: User,
        org: Organization,
        db_session: Session,
    ) -> None:
        # The entry printed the stage list as written: `{"approver_user_ids":
        # ["b1235cdc-…"]}` — an id nobody reading the journal can look up.
        stage = {
            'order': 1,
            'role': 'manager',
            'label': 'Manager',
            'approver_user_ids': [],
        }
        created = client.post(
            f'{BASE}/workflows',
            headers=admin_auth,
            json={
                'target_type': 'document',
                'requester_scope': {'everyone': True},
                'name': 'Named approver',
                'stages': [stage],
            },
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        named = client.patch(
            f'{BASE}/workflows/{created.json()["id"]}',
            headers=admin_auth,
            json={'stages': [{**stage, 'approver_user_ids': [str(admin.id)]}]},
        )
        assert named.status_code == status.HTTP_200_OK, named.text

        changed = _workflow_entries(db_session, org.id)[-1]
        person = admin.full_name or admin.email
        assert changed['before']['stages']['1']['approvers'] == []
        assert changed['after']['stages']['1']['approvers'] == [person]
        assert changed['after']['stages']['1']['label'] == 'Manager'
        sides = {'before': changed['before'], 'after': changed['after']}
        assert str(admin.id) not in json.dumps(sides, default=str)

    def test_an_edit_that_changes_nothing_writes_nothing(
        self,
        client: TestClient,
        admin_auth: dict[str, str],
        org: Organization,
        db_session: Session,
    ) -> None:
        created = client.post(
            f'{BASE}/workflows',
            headers=admin_auth,
            json={
                'target_type': 'document',
                'requester_scope': {'everyone': True},
                'name': 'Same',
                'stages': [
                    {
                        'order': 1,
                        'role': 'manager',
                        'label': 'Manager',
                        'approver_user_ids': [],
                    }
                ],
            },
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        renamed = client.patch(
            f'{BASE}/workflows/{created.json()["id"]}',
            headers=admin_auth,
            json={'name': 'Same'},
        )
        assert renamed.status_code == status.HTTP_200_OK, renamed.text

        assert len(_workflow_entries(db_session, org.id)) == 1

    def test_resaving_what_the_screen_read_writes_nothing(
        self,
        client: TestClient,
        admin_auth: dict[str, str],
        org: Organization,
        db_session: Session,
    ) -> None:
        created = client.post(
            f'{BASE}/workflows',
            headers=admin_auth,
            json={
                'target_type': 'document',
                'requester_scope': {'everyone': True, 'role_ids': [], 'user_ids': []},
                'name': 'Resaved',
                'stages': [
                    {
                        'order': 1,
                        'role': 'manager',
                        'label': 'Manager',
                        'approver_user_ids': [],
                    }
                ],
            },
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        read = created.json()
        # The screen sends back what it read; a JSON object's keys may come
        # back in any order and still say the same thing.
        resaved = client.patch(
            f'{BASE}/workflows/{read["id"]}',
            headers=admin_auth,
            json={
                'stages': read['stages'],
                'requester_scope': dict(reversed(read['requester_scope'].items())),
            },
        )
        assert resaved.status_code == status.HTTP_200_OK, resaved.text

        assert len(_workflow_entries(db_session, org.id)) == 1

    def test_a_rename_and_a_switch_off_each_write_an_entry(
        self,
        client: TestClient,
        admin_auth: dict[str, str],
        org: Organization,
        db_session: Session,
    ) -> None:
        created = client.post(
            f'{BASE}/workflows',
            headers=admin_auth,
            json={
                'target_type': 'document',
                'requester_scope': {'everyone': True},
                'name': 'Before',
                'stages': [
                    {
                        'order': 1,
                        'role': 'manager',
                        'label': 'Manager',
                        'approver_user_ids': [],
                    }
                ],
            },
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        workflow_id = created.json()['id']
        on = client.patch(
            f'{BASE}/workflows/{workflow_id}',
            headers=admin_auth,
            json={'is_active': True, 'expected_scope': {'holds': 'all'}},
        )
        assert on.status_code == status.HTTP_200_OK, on.text
        renamed = client.patch(
            f'{BASE}/workflows/{workflow_id}',
            headers=admin_auth,
            json={'name': 'After'},
        )
        assert renamed.status_code == status.HTTP_200_OK, renamed.text
        off = client.patch(
            f'{BASE}/workflows/{workflow_id}',
            headers=admin_auth,
            json={'is_active': False},
        )
        assert off.status_code == status.HTTP_200_OK, off.text

        entries = _workflow_entries(db_session, org.id)
        assert len(entries) == 4, entries
        _, _, rename, switch_off = entries
        assert rename['before'] == {'name': 'Before'}
        assert rename['after'] == {'name': 'After'}
        assert switch_off['before'] == {'is_active': True}
        assert switch_off['after'] == {'is_active': False}

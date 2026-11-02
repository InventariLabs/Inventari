"""A workflow comes into force only under the scope its reader was shown.

The switch-on dialog sends the scope it showed and the server refuses when
the live one moved. That guarantee held for the dialog only: a script that
left ``expected_scope`` out, on PATCH or on a POST that creates the workflow
already on, brought the workflow into force under a rule it never read.
Both doors now ask for the same thing, and refuse with a 422 naming the field.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import status
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization

BASE = '/api/v1/approvals'

# An organization without a document profile: a document workflow holds
# every confirmed document.
SHOWN = {'holds': 'all'}
STALE = {'holds': 'nothing'}


@pytest.fixture
def h(db_session: Session) -> ModuleTestHelper:
    return ModuleTestHelper(db_session)


@pytest.fixture
def org(h: ModuleTestHelper) -> Organization:
    return h.create_org('Switch-on Scope Org', ['core', 'approvals'])


@pytest.fixture
def admin_auth(h: ModuleTestHelper, org: Organization) -> dict[str, str]:
    user = h.create_user(org, email='scope-admin@example.com', role='manager')
    h.grant_permissions(
        user, ['approvals:read', 'approvals:approve', 'approvals:configure']
    )
    return h.get_auth_headers(user)


def _payload(**extra: Any) -> dict[str, Any]:
    return {
        'target_type': 'document',
        'requester_scope': {'everyone': True},
        'name': 'Documents',
        'stages': [
            {
                'order': 1,
                'role': 'manager',
                'label': 'Manager Approval',
                'approver_user_ids': [],
            }
        ],
        **extra,
    }


def _create_off(client: TestClient, auth: dict[str, str]) -> str:
    created = client.post(f'{BASE}/workflows', headers=auth, json=_payload())
    assert created.status_code == status.HTTP_201_CREATED, created.text
    assert created.json()['is_active'] is False
    return str(created.json()['id'])


def _is_active(client: TestClient, auth: dict[str, str], workflow_id: str) -> bool:
    return bool(
        client.get(f'{BASE}/workflows/{workflow_id}', headers=auth).json()['is_active']
    )


@pytest.mark.integration
class TestSwitchingOnThroughPatch:
    def test_without_the_scope_it_is_refused_and_stays_off(
        self, client: TestClient, admin_auth: dict[str, str]
    ) -> None:
        workflow_id = _create_off(client, admin_auth)

        refused = client.patch(
            f'{BASE}/workflows/{workflow_id}',
            headers=admin_auth,
            json={'is_active': True},
        )

        assert refused.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT, (
            refused.text
        )
        assert refused.json()['detail']['code'] == 'APPROVAL_SCOPE_REQUIRED'
        assert 'expected_scope' in refused.json()['detail']['message']
        assert _is_active(client, admin_auth, workflow_id) is False

    def test_with_a_stale_scope_it_is_refused_and_stays_off(
        self, client: TestClient, admin_auth: dict[str, str]
    ) -> None:
        workflow_id = _create_off(client, admin_auth)

        refused = client.patch(
            f'{BASE}/workflows/{workflow_id}',
            headers=admin_auth,
            json={'is_active': True, 'expected_scope': STALE},
        )

        assert refused.status_code == status.HTTP_409_CONFLICT, refused.text
        assert refused.json()['detail']['code'] == 'APPROVAL_SCOPE_CHANGED'
        assert _is_active(client, admin_auth, workflow_id) is False

    def test_with_the_scope_it_showed_it_goes_through(
        self, client: TestClient, admin_auth: dict[str, str]
    ) -> None:
        workflow_id = _create_off(client, admin_auth)

        switched_on = client.patch(
            f'{BASE}/workflows/{workflow_id}',
            headers=admin_auth,
            json={'is_active': True, 'expected_scope': SHOWN},
        )

        assert switched_on.status_code == status.HTTP_200_OK, switched_on.text
        assert switched_on.json()['is_active'] is True

    def test_an_edit_of_a_workflow_already_on_needs_no_scope(
        self, client: TestClient, admin_auth: dict[str, str]
    ) -> None:
        workflow_id = _create_off(client, admin_auth)
        client.patch(
            f'{BASE}/workflows/{workflow_id}',
            headers=admin_auth,
            json={'is_active': True, 'expected_scope': SHOWN},
        )

        renamed = client.patch(
            f'{BASE}/workflows/{workflow_id}',
            headers=admin_auth,
            json={'name': 'Renamed', 'is_active': True},
        )

        assert renamed.status_code == status.HTTP_200_OK, renamed.text
        assert renamed.json()['name'] == 'Renamed'

    def test_switching_off_needs_no_scope(
        self, client: TestClient, admin_auth: dict[str, str]
    ) -> None:
        workflow_id = _create_off(client, admin_auth)
        client.patch(
            f'{BASE}/workflows/{workflow_id}',
            headers=admin_auth,
            json={'is_active': True, 'expected_scope': SHOWN},
        )

        off = client.patch(
            f'{BASE}/workflows/{workflow_id}',
            headers=admin_auth,
            json={'is_active': False},
        )

        assert off.status_code == status.HTTP_200_OK, off.text
        assert off.json()['is_active'] is False


@pytest.mark.integration
class TestCreatingAWorkflowAlreadyOn:
    def test_without_the_scope_nothing_is_created(
        self, client: TestClient, admin_auth: dict[str, str]
    ) -> None:
        refused = client.post(
            f'{BASE}/workflows', headers=admin_auth, json=_payload(is_active=True)
        )

        assert refused.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT, (
            refused.text
        )
        assert refused.json()['detail']['code'] == 'APPROVAL_SCOPE_REQUIRED'
        listed = client.get(f'{BASE}/workflows', headers=admin_auth)
        assert listed.json()['items'] == []

    def test_with_a_stale_scope_nothing_is_created(
        self, client: TestClient, admin_auth: dict[str, str]
    ) -> None:
        refused = client.post(
            f'{BASE}/workflows',
            headers=admin_auth,
            json=_payload(is_active=True, expected_scope=STALE),
        )

        assert refused.status_code == status.HTTP_409_CONFLICT, refused.text
        assert refused.json()['detail']['code'] == 'APPROVAL_SCOPE_CHANGED'
        listed = client.get(f'{BASE}/workflows', headers=admin_auth)
        assert listed.json()['items'] == []

    def test_with_the_scope_it_is_created_on(
        self, client: TestClient, admin_auth: dict[str, str]
    ) -> None:
        created = client.post(
            f'{BASE}/workflows',
            headers=admin_auth,
            json=_payload(is_active=True, expected_scope=SHOWN),
        )

        assert created.status_code == status.HTTP_201_CREATED, created.text
        assert created.json()['is_active'] is True

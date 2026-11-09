"""Each approval route that asks for a grant refuses a role without it.

The route guards are set on the route table. The workflow detail and the
workflow edit have their refusal pinned elsewhere; this file pins the other
four: creating a workflow, deleting one, reading what is waiting on one, and
raising a request. Each is refused with the translated reason of its own
grant, and answers the holder of that grant, and nothing else is read from
the refused call.
"""

from typing import Any

import pytest
from fastapi import status
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.testing import ModuleTestHelper
from app.i18n.service import get_error_message
from app.models.organization import Organization
from app.models.user import User

BASE = '/api/v1/approvals'

pytestmark = pytest.mark.integration


def _workflow(name: str = 'Above a thousand') -> dict[str, Any]:
    return {
        'target_type': 'document',
        'requester_scope': {'everyone': True},
        'is_active': False,
        'name': name,
        'stages': [{'order': 1, 'role': 'manager', 'label': 'Manager'}],
    }


@pytest.fixture
def h(db_session: Session) -> ModuleTestHelper:
    return ModuleTestHelper(db_session)


@pytest.fixture
def org(h: ModuleTestHelper) -> Organization:
    return h.create_org('Route Grants Org', ['core', 'approvals'])


@pytest.fixture(autouse=True)
def any_target_may_be_requested(monkeypatch: pytest.MonkeyPatch) -> None:
    """Raising a request here is about the grant, not about the target."""

    async def accept(*_args: object) -> None:
        return None

    monkeypatch.setattr('app.modules.approvals.router.require_target_exists', accept)


@pytest.fixture
def unrelated(h: ModuleTestHelper, org: Organization) -> User:
    """A member whose custom role holds no approvals grant at all."""
    user = h.create_user(org, email='unrelated@example.com', role='user')
    h.grant_permissions(user, ['items:read'])
    return user


@pytest.fixture
def approver(h: ModuleTestHelper, org: Organization) -> User:
    """Somebody who can decide, so a workflow's stage is not a dead end."""
    user = h.create_user(org, email='route-approver@example.com', role='user')
    h.grant_permissions(user, ['approvals:approve'])
    return user


@pytest.fixture
def configurer(h: ModuleTestHelper, org: Organization, approver: User) -> User:
    user = h.create_user(org, email='configurer@example.com', role='user')
    h.grant_permissions(user, ['approvals:configure'])
    return user


@pytest.fixture
def writer(h: ModuleTestHelper, org: Organization) -> User:
    user = h.create_user(org, email='request-writer@example.com', role='user')
    h.grant_permissions(user, ['approvals:write'])
    return user


@pytest.fixture
def workflow_id(client: TestClient, h: ModuleTestHelper, configurer: User) -> str:
    response = client.post(
        f'{BASE}/workflows', json=_workflow(), headers=h.get_auth_headers(configurer)
    )
    assert response.status_code == status.HTTP_201_CREATED, response.text
    return str(response.json()['id'])


def _refused_with(response: Any, key: str) -> None:
    assert response.status_code == status.HTTP_403_FORBIDDEN, response.text
    assert response.json()['detail']['message'] == get_error_message(key, 'en')


class TestCreatingAWorkflowAsksForConfigure:
    def test_a_role_without_the_grant_is_refused(
        self, client: TestClient, h: ModuleTestHelper, unrelated: User
    ) -> None:
        response = client.post(
            f'{BASE}/workflows',
            json=_workflow('Refused one'),
            headers=h.get_auth_headers(unrelated),
        )

        _refused_with(response, 'approvals_manage_admin_only')
        assert 'Refused one' not in response.text

    def test_a_holder_of_the_grant_creates_it(
        self, client: TestClient, h: ModuleTestHelper, configurer: User
    ) -> None:
        response = client.post(
            f'{BASE}/workflows',
            json=_workflow('Created one'),
            headers=h.get_auth_headers(configurer),
        )

        assert response.status_code == status.HTTP_201_CREATED, response.text
        assert response.json()['name'] == 'Created one'


class TestDeletingAWorkflowAsksForConfigure:
    def test_a_role_without_the_grant_is_refused_and_the_workflow_stays(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        unrelated: User,
        configurer: User,
        workflow_id: str,
    ) -> None:
        response = client.delete(
            f'{BASE}/workflows/{workflow_id}', headers=h.get_auth_headers(unrelated)
        )

        _refused_with(response, 'approvals_manage_admin_only')
        still_there = client.get(
            f'{BASE}/workflows/{workflow_id}', headers=h.get_auth_headers(configurer)
        )
        assert still_there.status_code == status.HTTP_200_OK

    def test_a_holder_of_the_grant_deletes_it(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        configurer: User,
        workflow_id: str,
    ) -> None:
        response = client.delete(
            f'{BASE}/workflows/{workflow_id}', headers=h.get_auth_headers(configurer)
        )

        assert response.status_code == status.HTTP_200_OK, response.text


class TestWhatIsWaitingOnAWorkflowAsksForConfigure:
    def test_a_role_without_the_grant_is_refused(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        unrelated: User,
        workflow_id: str,
    ) -> None:
        response = client.get(
            f'{BASE}/workflows/{workflow_id}/waiting',
            headers=h.get_auth_headers(unrelated),
        )

        _refused_with(response, 'approvals_manage_admin_only')

    def test_a_holder_of_the_grant_reads_it(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        configurer: User,
        workflow_id: str,
    ) -> None:
        response = client.get(
            f'{BASE}/workflows/{workflow_id}/waiting',
            headers=h.get_auth_headers(configurer),
        )

        assert response.status_code == status.HTTP_200_OK, response.text


class TestRaisingARequestAsksForWrite:
    _BODY = {
        'target_type': 'document',
        'target_id': '00000000-0000-4000-8000-000000000001',
    }

    def test_a_role_without_the_grant_is_refused(
        self, client: TestClient, h: ModuleTestHelper, unrelated: User
    ) -> None:
        response = client.post(
            f'{BASE}/requests', json=self._BODY, headers=h.get_auth_headers(unrelated)
        )

        _refused_with(response, 'approvals_write_forbidden')

    def test_configuring_alone_does_not_raise_a_request(
        self, client: TestClient, h: ModuleTestHelper, configurer: User
    ) -> None:
        response = client.post(
            f'{BASE}/requests', json=self._BODY, headers=h.get_auth_headers(configurer)
        )

        _refused_with(response, 'approvals_write_forbidden')

    def test_a_holder_of_the_grant_raises_one(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        writer: User,
        configurer: User,
    ) -> None:
        # A request needs a workflow that is on for its target.
        created = client.post(
            f'{BASE}/workflows',
            json={
                **_workflow('Switched on'),
                'is_active': True,
                'expected_scope': {'holds': 'all'},
            },
            headers=h.get_auth_headers(configurer),
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text

        response = client.post(
            f'{BASE}/requests', json=self._BODY, headers=h.get_auth_headers(writer)
        )

        assert response.status_code == status.HTTP_201_CREATED, response.text

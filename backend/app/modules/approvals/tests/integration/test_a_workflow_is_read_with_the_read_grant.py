"""One workflow's definition asks for the read grant, as the workflow list does.

``GET /approvals/workflows`` hands a role without ``approvals:read`` an empty
list, while ``GET /approvals/workflows/{id}`` handed the same role the whole
definition — its stages, its named approvers and its scope — for any id it
learned. The workflow writes answer to ``approvals:configure`` and raising a
request to ``approvals:write``, now as route guards rather than calls inside
the handler, so the route table says what each one asks.
"""

import pytest
from fastapi import status
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.testing import ModuleTestHelper
from app.i18n.service import get_error_message
from app.models.organization import Organization

BASE = '/api/v1/approvals'

pytestmark = pytest.mark.integration


@pytest.fixture
def h(db_session: Session) -> ModuleTestHelper:
    return ModuleTestHelper(db_session)


@pytest.fixture
def org(h: ModuleTestHelper) -> Organization:
    return h.create_org('Workflow Read Org', ['core', 'approvals'])


@pytest.fixture
def workflow_id(client: TestClient, h: ModuleTestHelper, org: Organization) -> str:
    admin = h.create_user(org, email='wf-admin@example.com')
    response = client.post(
        f'{BASE}/workflows',
        json={
            'target_type': 'document',
            'requester_scope': {'everyone': True},
            'is_active': False,
            'name': 'Above a thousand',
            'stages': [
                {'order': 1, 'role': 'manager', 'label': 'Manager'},
            ],
        },
        headers=h.get_auth_headers(admin),
    )
    assert response.status_code == status.HTTP_201_CREATED, response.text
    return str(response.json()['id'])


class TestOneWorkflowAsksForTheRead:
    def test_a_member_without_the_read_is_refused(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        org: Organization,
        workflow_id: str,
    ) -> None:
        member = h.create_user(org, email='wf-member@example.com', role='user')

        response = client.get(
            f'{BASE}/workflows/{workflow_id}', headers=h.get_auth_headers(member)
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json()['detail']['message'] == get_error_message(
            'approvals_read_forbidden', 'en'
        )
        assert 'Above a thousand' not in response.text

    def test_a_holder_of_the_read_reads_it(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        org: Organization,
        workflow_id: str,
    ) -> None:
        reader = h.create_user(org, email='wf-reader@example.com', role='user')
        h.grant_permissions(reader, ['approvals:read'])

        response = client.get(
            f'{BASE}/workflows/{workflow_id}', headers=h.get_auth_headers(reader)
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()['name'] == 'Above a thousand'

    def test_a_workflow_write_keeps_its_own_refusal(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        org: Organization,
        workflow_id: str,
    ) -> None:
        member = h.create_user(org, email='wf-writer@example.com', role='user')

        response = client.patch(
            f'{BASE}/workflows/{workflow_id}',
            json={'name': 'Renamed'},
            headers=h.get_auth_headers(member),
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json()['detail']['message'] == get_error_message(
            'approvals_manage_admin_only', 'en'
        )

    def test_the_workflow_editor_reads_what_it_edits(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        org: Organization,
        workflow_id: str,
    ) -> None:
        # The workflow list admits approvals:configure alone: configuring
        # implies reading, so the detail does too.
        editor = h.create_user(org, email='wf-editor@example.com', role='user')
        h.grant_permissions(editor, ['approvals:configure'])

        response = client.get(
            f'{BASE}/workflows/{workflow_id}', headers=h.get_auth_headers(editor)
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()['name'] == 'Above a thousand'

"""A workflow stage is its name and the people who decide it — no role.

The stage used to carry a ``role``: a free-form label the editor offered first
and the decision door never read. A stage is now saved without it, and a stage
saved with it before still loads, is listed and is decided as it was.
"""

import uuid

import pytest
from fastapi import status
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.user import User
from app.modules.approvals.models import ApprovalWorkflow

BASE = '/api/v1/approvals'


@pytest.fixture
def h(db_session: Session) -> ModuleTestHelper:
    return ModuleTestHelper(db_session)


@pytest.fixture
def org(h: ModuleTestHelper) -> Organization:
    return h.create_org('Stage Shape Org', ['core', 'approvals'])


@pytest.fixture
def admin(h: ModuleTestHelper, org: Organization) -> User:
    return h.create_user(org, email='stage-admin@example.com', role='admin')


@pytest.mark.integration
class TestAStageIsItsNameAndItsApprovers:
    def test_a_stage_without_a_role_is_saved_and_returned_as_sent(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        org: Organization,
        admin: User,
    ) -> None:
        approver = h.create_user(org, email='signer@example.com', role='user')
        h.grant_permissions(approver, ['approvals:read', 'approvals:approve'])

        resp = client.post(
            f'{BASE}/workflows',
            headers=h.get_auth_headers(admin),
            json={
                'target_type': 'document',
                'name': 'Documents',
                'requester_scope': {'everyone': True},
                'stages': [
                    {
                        'order': 1,
                        'label': 'Sign-off',
                        'approver_user_ids': [str(approver.id)],
                    }
                ],
            },
        )

        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        assert resp.json()['stages'] == [
            {'order': 1, 'label': 'Sign-off', 'approver_user_ids': [str(approver.id)]}
        ]

    def test_a_stage_saved_with_a_role_still_loads_and_is_decided(
        self,
        client: TestClient,
        db_session: Session,
        h: ModuleTestHelper,
        org: Organization,
        admin: User,
    ) -> None:
        requester = h.create_user(org, email='asker@example.com', role='user')
        h.grant_permissions(requester, ['approvals:write', 'approvals:read'])
        db_session.add(
            ApprovalWorkflow(
                organization_id=org.id,
                target_type='document',
                name='Saved before',
                is_active=True,
                stages=[
                    {
                        'order': 1,
                        'role': 'manager',
                        'label': 'Legacy review',
                        'approver_user_ids': [],
                    }
                ],
            )
        )
        db_session.commit()
        admin_auth = h.get_auth_headers(admin)

        listed = client.get(f'{BASE}/workflows', headers=admin_auth)
        assert listed.status_code == status.HTTP_200_OK, listed.text
        assert listed.json()['items'][0]['stages'] == [
            {'order': 1, 'label': 'Legacy review', 'approver_user_ids': []}
        ]

        raised = client.post(
            f'{BASE}/requests',
            headers=h.get_auth_headers(requester),
            json={'target_type': 'document', 'target_id': str(uuid.uuid4())},
        )
        assert raised.status_code == status.HTTP_201_CREATED, raised.text
        decided = client.post(
            f'{BASE}/requests/{raised.json()["id"]}/approve',
            headers=admin_auth,
            json={},
        )
        assert decided.status_code == status.HTTP_200_OK, decided.text
        assert decided.json()['status'] == 'APPROVED'

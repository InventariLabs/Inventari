"""Delegation: a named approver decides, even without the approve grant.

The workflow form promises "assign either, or both" — a stage approves when
its role matches or one of the named approvers decides. The endpoints used
to answer that promise with a 403 unless the named person also held
``approvals:approve`` (default: the manager role), so an organization
without managers could not resolve its own flows and nobody could see why.

The contract now: being named on the stage the request sits at carries the
decision, with ``approvals:read`` alone as the floor — a person must be able
to see what they decide on. Open stages still wait for the grant.
"""

import uuid

import pytest
from fastapi import status
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.user import User

BASE = '/api/v1/approvals'


@pytest.mark.integration
class TestNamedApproverDelegation:
    @pytest.fixture
    def h(self, db_session: Session) -> ModuleTestHelper:
        return ModuleTestHelper(db_session)

    @pytest.fixture
    def org(self, h: ModuleTestHelper) -> Organization:
        return h.create_org('Delegation Org', ['core', 'approvals'])

    @pytest.fixture
    def admin_headers(self, h: ModuleTestHelper, org: Organization) -> dict[str, str]:
        admin = h.create_user(org, email='boss@example.com', role='admin')
        return h.get_auth_headers(admin)

    def _make_request(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        org: Organization,
        admin_headers: dict[str, str],
        named: User,
    ) -> str:
        """A single-stage workflow naming *named*, with a live request."""
        resp = client.post(
            f'{BASE}/workflows',
            headers=admin_headers,
            json={
                'target_type': 'document',
                'requester_scope': {'everyone': True},
                'name': 'Peer review',
                'is_active': True,
                'expected_scope': {'holds': 'all'},
                'stages': [
                    {
                        'order': 1,
                        'role': 'manager',
                        'label': 'Peer review',
                        'approver_user_ids': [str(named.id)],
                    }
                ],
            },
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        resp = client.post(
            f'{BASE}/requests',
            headers=admin_headers,
            json={
                'target_type': 'document',
                'target_id': str(uuid.uuid4()),
            },
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        return str(resp.json()['id'])

    def test_named_approver_decides_with_read_grant_alone(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        org: Organization,
        admin_headers: dict[str, str],
    ) -> None:
        """The form's promise, kept: named decides without approvals:approve."""
        peer = h.create_user(org, email='peer@example.com', role='user')
        h.grant_permissions(peer, ['approvals:read'])
        request_id = self._make_request(client, h, org, admin_headers, peer)

        resp = client.post(
            f'{BASE}/requests/{request_id}/approve',
            headers=h.get_auth_headers(peer),
            json={},
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        assert resp.json()['status'] == 'APPROVED'

    def test_named_approver_without_read_is_refused(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        org: Organization,
        admin_headers: dict[str, str],
    ) -> None:
        """The read floor: a person who cannot see approvals decides nothing.

        The stage names two people, one with the read grant and one without,
        so the workflow itself is solvable and gets saved — and the one
        without the floor is still refused at the decision door.
        """
        peer = h.create_user(org, email='peer@example.com', role='user')
        h.grant_permissions(peer, ['approvals:read'])
        blind = h.create_user(org, email='blind@example.com', role='user')
        resp = client.post(
            f'{BASE}/workflows',
            headers=admin_headers,
            json={
                'target_type': 'document',
                'requester_scope': {'everyone': True},
                'name': 'Two names',
                'is_active': True,
                'expected_scope': {'holds': 'all'},
                'stages': [
                    {
                        'order': 1,
                        'role': 'manager',
                        'label': 'Peer review',
                        'approver_user_ids': [str(peer.id), str(blind.id)],
                    }
                ],
            },
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text

        resp = client.post(
            f'{BASE}/requests',
            headers=admin_headers,
            json={
                'target_type': 'document',
                'target_id': str(uuid.uuid4()),
            },
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        request_id = resp.json()['id']

        resp = client.post(
            f'{BASE}/requests/{request_id}/approve',
            headers=h.get_auth_headers(blind),
            json={},
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN, resp.text

    def test_queue_shows_the_delegated_approver_their_request(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        org: Organization,
        admin_headers: dict[str, str],
    ) -> None:
        """The named approver sees the request and the verdict."""
        peer = h.create_user(org, email='peer2@example.com', role='user')
        h.grant_permissions(peer, ['approvals:read'])
        request_id = self._make_request(client, h, org, admin_headers, peer)

        resp = client.get(
            f'{BASE}/requests?status=PENDING',
            headers=h.get_auth_headers(peer),
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        items = resp.json()['items']
        assert request_id in [item['id'] for item in items]
        mine = next(item for item in items if item['id'] == request_id)
        assert mine['viewer_can_decide'] is True

    def test_workflow_refuses_a_stage_nobody_can_decide(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        org: Organization,
        admin_headers: dict[str, str],
    ) -> None:
        """An unsolvable stage does not come into being silently."""
        blind = h.create_user(org, email='blind2@example.com', role='user')
        resp = client.post(
            f'{BASE}/workflows',
            headers=admin_headers,
            json={
                'target_type': 'document',
                'requester_scope': {'everyone': True},
                'name': 'Dead end',
                'is_active': True,
                'expected_scope': {'holds': 'all'},
                'stages': [
                    {
                        'order': 1,
                        'role': 'manager',
                        'label': 'Nobody stage',
                        'approver_user_ids': [str(blind.id)],
                    }
                ],
            },
        )
        # the workflow endpoints map ApprovalError to 409 (conflict=True)
        assert resp.status_code == status.HTTP_409_CONFLICT, resp.text
        assert 'Nobody stage' in resp.json()['detail']['message']

    def test_workflow_accepts_a_manager_who_holds_read_by_their_level(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        org: Organization,
        admin_headers: dict[str, str],
    ) -> None:
        """A manager holds ``approvals:read`` by the manifest default alone.

        No custom role row grants it — the level does, the same way the
        guards on the queue read it. The decidability gate asks the database
        and has to reach the same answer, or naming the very person the
        module nominates as approver is refused as a dead end.
        """
        boss = h.create_user(org, email='manager2@example.com', role='manager')
        resp = client.post(
            f'{BASE}/workflows',
            headers=admin_headers,
            json={
                'target_type': 'document',
                'requester_scope': {'everyone': True},
                'name': 'Manager stage',
                'is_active': True,
                'expected_scope': {'holds': 'all'},
                'stages': [
                    {
                        'order': 1,
                        'role': 'manager',
                        'label': 'Manager stage',
                        'approver_user_ids': [str(boss.id)],
                    }
                ],
            },
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text

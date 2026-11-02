"""Integration tests for the approvals HTTP router.

Covers:
- Workflow endpoints (list, create, get, update, delete)
- Request endpoints (list, get, approve, reject)
- Error mapping (ApprovalError -> 422, NotFound -> 404, auth -> 401, no org -> 403)
- Response shape (enriched DTOs with workflow_stages, decisions, user names)
"""

import uuid
from typing import Any, cast

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
def router_org(h: ModuleTestHelper) -> Organization:
    return h.create_org('Router Test Org', ['core', 'approvals'])


@pytest.fixture
def router_user(h: ModuleTestHelper, router_org: Organization) -> User:
    """A manager who actually holds the approvals permissions.

    Since the endpoints check the module's own permissions rather than the
       role name, so the grant has to be explicit — in production the manifest's
       ``default_roles`` puts this set on the org's manager role at enable.
    """
    user = h.create_user(router_org, email='router@example.com', role='manager')
    h.grant_permissions(
        user,
        [
            'approvals:read',
            'approvals:write',
            'approvals:approve',
            'approvals:configure',
        ],
    )
    return user


@pytest.fixture
def router_user2(h: ModuleTestHelper, router_org: Organization) -> User:
    return h.create_user(router_org, email='router2@example.com', role='admin')


@pytest.fixture
def requester(h: ModuleTestHelper, router_org: Organization) -> User:
    return h.create_user(router_org, email='requester@example.com', role='user')


@pytest.fixture
def router_auth(h: ModuleTestHelper, router_user: User) -> dict[str, str]:
    return h.get_auth_headers(router_user)


@pytest.fixture
def router_auth2(h: ModuleTestHelper, router_user2: User) -> dict[str, str]:
    return h.get_auth_headers(router_user2)


@pytest.fixture
def requester_auth(h: ModuleTestHelper, requester: User) -> dict[str, str]:
    return h.get_auth_headers(requester)


def _create_workflow_payload(target_type: str = 'document') -> dict[str, Any]:
    return {
        'target_type': target_type,
        'requester_scope': {'everyone': True},
        'name': 'Router Test Workflow',
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
    }


# ---------------------------------------------------------------------------
# Auth & tenancy
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestRouterAuth:
    def test_list_workflows_requires_auth(self, client: TestClient) -> None:
        response = client.get(f'{BASE}/workflows')
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_create_workflow_requires_auth(self, client: TestClient) -> None:
        response = client.post(f'{BASE}/workflows', json=_create_workflow_payload())
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_list_requests_requires_auth(self, client: TestClient) -> None:
        response = client.get(f'{BASE}/requests')
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


# ---------------------------------------------------------------------------
# Workflow CRUD
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestWorkflowEndpoints:
    def test_list_workflows_empty(
        self, client: TestClient, router_auth: dict[str, str]
    ) -> None:
        response = client.get(f'{BASE}/workflows', headers=router_auth)
        assert response.status_code == status.HTTP_200_OK
        assert response.json()['items'] == []

    def test_create_workflow_returns_201(
        self, client: TestClient, router_auth: dict[str, str], router_user: User
    ) -> None:
        response = client.post(
            f'{BASE}/workflows',
            headers=router_auth,
            json=_create_workflow_payload(),
        )
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data['name'] == 'Router Test Workflow'
        assert data['target_type'] == 'document'
        assert data['is_active'] is True
        assert len(data['stages']) == 1
        assert data['organization_id'] == str(router_user.organization_id)

    def test_create_workflow_without_stages_returns_409(
        self, client: TestClient, router_auth: dict[str, str]
    ) -> None:
        # Router maps ApprovalError -> ConflictException(409) for workflow endpoints,
        # answering with the refusal's own code.
        payload = {
            'target_type': 'document',
            'requester_scope': {'everyone': True},
            'name': 'Empty',
            'stages': [],
            'is_active': True,
            'expected_scope': {'holds': 'all'},
        }
        response = client.post(f'{BASE}/workflows', headers=router_auth, json=payload)
        assert response.status_code == status.HTTP_409_CONFLICT
        assert response.json()['detail']['code'] == 'APPROVAL_WORKFLOW_NEEDS_STAGE'

    def test_create_workflow_invalid_target_type_returns_422(
        self, client: TestClient, router_auth: dict[str, str]
    ) -> None:
        payload = _create_workflow_payload()
        payload['target_type'] = 'unknown_type'
        response = client.post(f'{BASE}/workflows', headers=router_auth, json=payload)
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_get_workflow_by_id_returns_200(
        self, client: TestClient, router_auth: dict[str, str]
    ) -> None:
        created = client.post(
            f'{BASE}/workflows',
            headers=router_auth,
            json=_create_workflow_payload(),
        ).json()
        response = client.get(f'{BASE}/workflows/{created["id"]}', headers=router_auth)
        assert response.status_code == status.HTTP_200_OK
        assert response.json()['id'] == created['id']

    def test_get_workflow_unknown_id_returns_404(
        self, client: TestClient, router_auth: dict[str, str]
    ) -> None:
        response = client.get(f'{BASE}/workflows/{uuid.uuid4()}', headers=router_auth)
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_update_workflow_name(
        self, client: TestClient, router_auth: dict[str, str]
    ) -> None:
        created = client.post(
            f'{BASE}/workflows',
            headers=router_auth,
            json=_create_workflow_payload(),
        ).json()
        response = client.patch(
            f'{BASE}/workflows/{created["id"]}',
            headers=router_auth,
            json={'name': 'Renamed Workflow'},
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()['name'] == 'Renamed Workflow'

    def test_update_workflow_unknown_id_returns_404(
        self, client: TestClient, router_auth: dict[str, str]
    ) -> None:
        # The router maps ApprovalNotFoundError -> 404 via NotFoundException.
        response = client.patch(
            f'{BASE}/workflows/{uuid.uuid4()}',
            headers=router_auth,
            json={'name': 'X'},
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_update_workflow_with_active_request_returns_409(
        self,
        client: TestClient,
        router_auth: dict[str, str],
        requester_auth: dict[str, str],
    ) -> None:
        created = client.post(
            f'{BASE}/workflows',
            headers=router_auth,
            json=_create_workflow_payload(),
        ).json()
        # Seed a pending request so the active-request guard has something
        # to find.
        client.post(
            f'{BASE}/requests',
            headers=requester_auth,
            json={'target_type': 'document', 'target_id': str(uuid.uuid4())},
        )
        # The service only fires the active-count guard when stages change or
        # the workflow is deactivated.  Trigger it by also changing the stages.
        new_stages = [
            {
                'order': 1,
                'role': 'admin',
                'label': 'Admin Only',
                'approver_user_ids': [],
            },
        ]
        response = client.patch(
            f'{BASE}/workflows/{created["id"]}',
            headers=router_auth,
            json={'name': 'Should fail', 'stages': new_stages},
        )
        assert response.status_code == status.HTTP_409_CONFLICT
        assert response.json()['detail']['code'] == 'APPROVAL_WORKFLOW_MODIFY_BLOCKED'

    def test_delete_unused_workflow_removes_it(
        self, client: TestClient, router_auth: dict[str, str]
    ) -> None:
        created = client.post(
            f'{BASE}/workflows',
            headers=router_auth,
            json=_create_workflow_payload(),
        ).json()
        response = client.delete(
            f'{BASE}/workflows/{created["id"]}', headers=router_auth
        )
        assert response.status_code == status.HTTP_200_OK, response.text
        assert response.json() == {'archived': False, 'requests_kept': 0}
        listed = client.get(f'{BASE}/workflows', headers=router_auth).json()['items']
        assert created['id'] not in [wf['id'] for wf in listed]

    def test_delete_used_workflow_archives_it(
        self,
        client: TestClient,
        router_auth: dict[str, str],
        requester_auth: dict[str, str],
    ) -> None:
        """the response says the history was kept, and the UI can too."""
        created = client.post(
            f'{BASE}/workflows',
            headers=router_auth,
            json=_create_workflow_payload(),
        ).json()
        request = client.post(
            f'{BASE}/requests',
            headers=requester_auth,
            json={'target_type': 'document', 'target_id': str(uuid.uuid4())},
        )
        assert request.status_code == status.HTTP_201_CREATED, request.text
        approved = client.post(
            f'{BASE}/requests/{request.json()["id"]}/approve', headers=router_auth
        )
        assert approved.status_code == status.HTTP_200_OK, approved.text

        response = client.delete(
            f'{BASE}/workflows/{created["id"]}', headers=router_auth
        )
        assert response.status_code == status.HTTP_200_OK, response.text
        assert response.json() == {'archived': True, 'requests_kept': 1}

        listed = client.get(f'{BASE}/workflows', headers=router_auth).json()['items']
        assert created['id'] not in [wf['id'] for wf in listed]
        archived = client.get(
            f'{BASE}/workflows/{created["id"]}', headers=router_auth
        ).json()
        assert archived['is_active'] is False
        assert archived['archived_at'] is not None
        assert (
            client.get(
                f'{BASE}/requests/{request.json()["id"]}', headers=router_auth
            ).status_code
            == status.HTTP_200_OK
        )

    def test_delete_workflow_unknown_id_returns_404(
        self, client: TestClient, router_auth: dict[str, str]
    ) -> None:
        # Same as test_update_workflow_unknown_id_returns_404: the router
        # maps ApprovalNotFoundError -> 404.
        response = client.delete(
            f'{BASE}/workflows/{uuid.uuid4()}', headers=router_auth
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_list_workflows_filters_by_organization(
        self, client: TestClient, router_auth: dict[str, str], h: ModuleTestHelper
    ) -> None:
        client.post(
            f'{BASE}/workflows',
            headers=router_auth,
            json=_create_workflow_payload(),
        )
        # A different org should not see the workflow in its listing.
        other_org = h.create_org('Other Org', ['core', 'approvals'])
        other_user = h.create_user(other_org, email='other@example.com')
        other_auth = h.get_auth_headers(other_user)
        response = client.get(f'{BASE}/workflows', headers=other_auth)
        assert response.status_code == status.HTTP_200_OK
        assert response.json()['items'] == []


# ---------------------------------------------------------------------------
# The one-bit answer the request door hangs on
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestWorkflowConfigured:
    """``GET /workflows/configured`` — would a request for this type land?

    Deliberately readable without ``approvals:read``: the account that
    composes a request may hold only the target module's write right, and
    the workflow list is filtered by the read grant — so for that account
    an empty list says nothing, and the refusal it met arrived only after
    the click.
    """

    def test_requires_auth(self, client: TestClient) -> None:
        response = client.get(
            f'{BASE}/workflows/configured', params={'target_type': 'document'}
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_missing_target_type_returns_422(
        self, client: TestClient, router_auth: dict[str, str]
    ) -> None:
        response = client.get(f'{BASE}/workflows/configured', headers=router_auth)
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_no_workflow_answers_false(
        self, client: TestClient, router_auth: dict[str, str]
    ) -> None:
        response = client.get(
            f'{BASE}/workflows/configured',
            headers=router_auth,
            params={'target_type': 'document'},
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {'configured': False}

    def test_an_active_workflow_with_a_stage_answers_true(
        self, client: TestClient, router_auth: dict[str, str]
    ) -> None:
        client.post(
            f'{BASE}/workflows',
            headers=router_auth,
            json=_create_workflow_payload(),
        )
        response = client.get(
            f'{BASE}/workflows/configured',
            headers=router_auth,
            params={'target_type': 'document'},
        )
        assert response.json() == {'configured': True}

    def test_an_off_workflow_answers_false(
        self, client: TestClient, router_auth: dict[str, str]
    ) -> None:
        payload = _create_workflow_payload()
        payload['is_active'] = False
        client.post(f'{BASE}/workflows', headers=router_auth, json=payload)
        response = client.get(
            f'{BASE}/workflows/configured',
            headers=router_auth,
            params={'target_type': 'document'},
        )
        assert response.json() == {'configured': False}

    def test_a_stage_less_workflow_answers_false(
        self,
        db_session: Session,
        client: TestClient,
        router_auth: dict[str, str],
        router_org: Organization,
    ) -> None:
        # The API refuses to create one, but the engine's refusal does not
        # depend on how it got there: ``request_approval`` answers
        # ``approval_workflow_no_stages`` for any active workflow without
        # stages, and the door has to say the same.
        db_session.add(
            ApprovalWorkflow(
                organization_id=router_org.id,
                target_type='document',
                name='Stage-less',
                stages=[],
                is_active=True,
            )
        )
        db_session.commit()
        response = client.get(
            f'{BASE}/workflows/configured',
            headers=router_auth,
            params={'target_type': 'document'},
        )
        assert response.json() == {'configured': False}

    def test_another_target_type_stays_false(
        self, client: TestClient, router_auth: dict[str, str]
    ) -> None:
        client.post(
            f'{BASE}/workflows',
            headers=router_auth,
            json=_create_workflow_payload('document'),
        )
        response = client.get(
            f'{BASE}/workflows/configured',
            headers=router_auth,
            params={'target_type': 'purchase_order'},
        )
        assert response.json() == {'configured': False}

    def test_a_role_without_any_approval_grant_still_gets_the_answer(
        self,
        client: TestClient,
        router_auth: dict[str, str],
        requester_auth: dict[str, str],
    ) -> None:
        # The default role composes requests in its target modules and holds
        # no approvals grant at all. The list answers it nothing; the door
        # still has to know, or it offers a refusal it cannot see.
        client.post(
            f'{BASE}/workflows',
            headers=router_auth,
            json=_create_workflow_payload(),
        )
        listed = client.get(f'{BASE}/workflows', headers=requester_auth)
        assert listed.status_code == status.HTTP_200_OK
        assert listed.json()['items'] == []

        response = client.get(
            f'{BASE}/workflows/configured',
            headers=requester_auth,
            params={'target_type': 'document'},
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {'configured': True}


# ---------------------------------------------------------------------------
# Request endpoints
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestRequestEndpoints:
    def _seed_workflow(
        self, client: TestClient, auth: dict[str, str]
    ) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            client.post(
                f'{BASE}/workflows',
                headers=auth,
                json=_create_workflow_payload(),
            ).json(),
        )

    def _seed_request(self, client: TestClient, auth: dict[str, str]) -> dict[str, Any]:
        """Create an approval request via the HTTP API (services are async-only)."""
        return cast(
            dict[str, Any],
            client.post(
                f'{BASE}/requests',
                headers=auth,
                json={'target_type': 'document', 'target_id': str(uuid.uuid4())},
            ).json(),
        )

    def test_list_requests_empty(
        self, client: TestClient, router_auth: dict[str, str]
    ) -> None:
        # Ensure a workflow exists so the list isn't empty for an unrelated reason
        self._seed_workflow(client, router_auth)
        response = client.get(f'{BASE}/requests', headers=router_auth)
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['items'] == []
        assert data['total'] == 0
        assert data['has_more'] is False

    def test_list_requests_filters_by_target_type(
        self,
        client: TestClient,
        router_auth: dict[str, str],
        requester_auth: dict[str, str],
    ) -> None:
        self._seed_workflow(client, router_auth)
        self._seed_request(client, requester_auth)
        response = client.get(
            f'{BASE}/requests?target_type=document', headers=router_auth
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()['items']
        assert len(data) == 1
        assert data[0]['target_type'] == 'document'

    def test_list_requests_filters_by_status(
        self,
        client: TestClient,
        router_auth: dict[str, str],
        requester_auth: dict[str, str],
    ) -> None:
        self._seed_workflow(client, router_auth)
        self._seed_request(client, requester_auth)
        response = client.get(f'{BASE}/requests?status=PENDING', headers=router_auth)
        assert response.status_code == status.HTTP_200_OK
        assert all(r['status'] == 'PENDING' for r in response.json()['items'])

    def test_list_requests_paginates(
        self,
        client: TestClient,
        router_auth: dict[str, str],
        requester_auth: dict[str, str],
    ) -> None:
        self._seed_workflow(client, router_auth)
        for _ in range(3):
            self._seed_request(client, requester_auth)

        page1 = client.get(
            f'{BASE}/requests?limit=2&offset=0', headers=router_auth
        ).json()
        page2 = client.get(
            f'{BASE}/requests?limit=2&offset=2', headers=router_auth
        ).json()

        ids1 = {r['id'] for r in page1['items']}
        ids2 = {r['id'] for r in page2['items']}
        assert page1['total'] == 3
        assert page1['has_more'] is True
        assert len(ids1) == 2
        assert len(ids2) == 1
        assert ids1.isdisjoint(ids2)

    def test_get_request_returns_enriched_shape(
        self,
        client: TestClient,
        router_auth: dict[str, str],
        requester_auth: dict[str, str],
    ) -> None:
        self._seed_workflow(client, router_auth)
        req = self._seed_request(client, requester_auth)
        response = client.get(f'{BASE}/requests/{req["id"]}', headers=router_auth)
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['id'] == str(req['id'])
        assert data['created_by_name'] == 'Requester'
        assert data['workflow_stages'] is not None
        assert len(data['decisions']) == 1
        assert data['decisions'][0]['status'] == 'PENDING'

    def test_get_request_unknown_id_returns_404(
        self, client: TestClient, router_auth: dict[str, str]
    ) -> None:
        unknown_id = str(uuid.uuid4())
        response = client.get(f'{BASE}/requests/{unknown_id}', headers=router_auth)
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_list_requests_response_includes_target_summary_key(
        self, client: TestClient, router_auth: dict[str, str]
    ) -> None:
        """Regression: response_model validates that target_summary is a dict,
        not a Pydantic DTO. Without ``.model_dump(mode='json')`` in the
        enrichment, FastAPI raises ResponseValidationError -> 500.
        """
        # Seed a workflow + request so the list has one row. The target_id is
        # a random UUID — the approvals request does not FK-validate it.
        self._seed_workflow(client, router_auth)
        create_resp = client.post(
            f'{BASE}/requests',
            headers=router_auth,
            json={
                'target_type': 'document',
                'target_id': str(uuid.uuid4()),
            },
        )
        assert create_resp.status_code == 201, create_resp.text

        list_resp = client.get(f'{BASE}/requests', headers=router_auth)
        assert list_resp.status_code == status.HTTP_200_OK
        data = list_resp.json()['items']
        assert len(data) >= 1
        # Every row must expose ``target_summary`` as null or dict (never a
        # raw Pydantic model that would trip response validation).
        for row in data:
            assert 'target_summary' in row
            assert row['target_summary'] is None or isinstance(
                row['target_summary'], dict
            )

    def test_approve_endpoint_marks_approved(
        self,
        client: TestClient,
        router_auth: dict[str, str],
        router_user: User,
        requester_auth: dict[str, str],
    ) -> None:
        self._seed_workflow(client, router_auth)
        req = self._seed_request(client, requester_auth)
        response = client.post(
            f'{BASE}/requests/{req["id"]}/approve',
            headers=router_auth,
            json={'notes': 'LGTM'},
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['status'] == 'APPROVED'
        assert data['decisions'][0]['status'] == 'APPROVED'
        assert data['decisions'][0]['notes'] == 'LGTM'
        assert data['decisions'][0]['approver_name'] == router_user.full_name

    def test_approve_endpoint_self_approval_returns_400(
        self,
        client: TestClient,
        router_auth: dict[str, str],
    ) -> None:
        # Router maps ApprovalError -> a 400 carrying the refusal's own code.
        # The request is created by the same user who then approves (self-approval).
        self._seed_workflow(client, router_auth)
        req = self._seed_request(client, router_auth)
        response = client.post(
            f'{BASE}/requests/{req["id"]}/approve', headers=router_auth
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert (
            response.json()['detail']['code'] == 'APPROVAL_CANNOT_APPROVE_OWN_REQUEST'
        )

    def test_approve_user_role_403(
        self,
        client: TestClient,
        router_auth: dict[str, str],
        requester_auth: dict[str, str],
    ) -> None:
        """Users without admin/manager role cannot approve requests.

        The previous code only checked ``get_current_user_context`` (auth +
        org membership). A regular user with no role in the workflow could
        hit /approve and either silently advance the request or hit a 500
        from a downstream check. The router now enforces the role gate
        before delegating to the service.
        """
        # Manager (router_user) creates a workflow + request as the requester.
        self._seed_workflow(client, router_auth)
        req = self._seed_request(client, requester_auth)

        # Regular user (role='user') tries to approve.
        response = client.post(
            f'{BASE}/requests/{req["id"]}/approve',
            headers=requester_auth,
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN, response.text
        assert response.json()['detail']['code'] == 'FORBIDDEN'

        # The request must still be PENDING — the rejected call had no effect.
        check_resp = client.get(f'{BASE}/requests/{req["id"]}', headers=router_auth)
        assert check_resp.status_code == status.HTTP_200_OK
        assert check_resp.json()['status'] == 'PENDING'

    def test_reject_endpoint_marks_rejected(
        self,
        client: TestClient,
        router_auth: dict[str, str],
        requester_auth: dict[str, str],
    ) -> None:
        self._seed_workflow(client, router_auth)
        req = self._seed_request(client, requester_auth)
        response = client.post(
            f'{BASE}/requests/{req["id"]}/reject',
            headers=router_auth,
            json={'notes': 'No'},
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['status'] == 'REJECTED'
        assert data['decisions'][0]['status'] == 'REJECTED'
        assert data['decisions'][0]['notes'] == 'No'

    def test_approve_unknown_request_returns_404(
        self, client: TestClient, router_auth: dict[str, str]
    ) -> None:
        # The router maps ApprovalNotFoundError -> 404 for the approve/reject
        # endpoints when the request id does not exist for the org.
        response = client.post(
            f'{BASE}/requests/{uuid.uuid4()}/approve', headers=router_auth
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_reject_unknown_request_returns_404(
        self, client: TestClient, router_auth: dict[str, str]
    ) -> None:
        response = client.post(
            f'{BASE}/requests/{uuid.uuid4()}/reject', headers=router_auth
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_approve_already_approved_returns_400(
        self,
        client: TestClient,
        router_auth: dict[str, str],
        requester_auth: dict[str, str],
    ) -> None:
        """Approve once (200), then approve again -> 400 (not 404).

        The first approve succeeds and the request becomes APPROVED.  There
        is no longer a PENDING decision, so a second approve hits the
        ``ApprovalError`` (not-found-decision) branch and the router returns
        400.  This documents the difference between the 404 (request missing)
        and 400 (no pending decision) cases.
        """
        self._seed_workflow(client, router_auth)
        req = self._seed_request(client, requester_auth)
        response = client.post(
            f'{BASE}/requests/{req["id"]}/approve', headers=router_auth
        )
        assert response.status_code == status.HTTP_200_OK
        response = client.post(
            f'{BASE}/requests/{req["id"]}/approve', headers=router_auth
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_approve_endpoint_uses_current_user_as_approver(
        self,
        client: TestClient,
        router_auth: dict[str, str],
        router_auth2: dict[str, str],
        requester_auth: dict[str, str],
    ) -> None:
        self._seed_workflow(client, router_auth)
        req = self._seed_request(client, requester_auth)
        # Approve with the second user's auth — the request should record
        # the second user as approver.
        response = client.post(
            f'{BASE}/requests/{req["id"]}/approve', headers=router_auth2
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['decisions'][0]['approver_name'] == 'Router2'


# ---------------------------------------------------------------------------
# Bug-fix regression tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestRouterBugFixes:
    """End-to-end coverage of the router-level bug fixes.

    Each test below reproduces a previously-broken behaviour and verifies
    the corrected contract.
    """

    def test_create_workflow_with_uuid_approvers_does_not_crash(
        self,
        client: TestClient,
        router_auth: dict[str, str],
        router_user: User,
    ) -> None:
        """Bug fix: ``model_dump()`` previously produced UUID objects which
        could not be stored in the JSONB ``stages`` column.  The fix is to
        use ``model_dump(mode='json')`` in the router so UUIDs are
        serialised to strings before insertion.
        """
        approver_uuid = str(router_user.id)
        payload = {
            'target_type': 'document',
            'requester_scope': {'everyone': True},
            'name': 'With Approvers',
            'stages': [
                {
                    'order': 1,
                    'role': 'admin',
                    'label': 'Admin',
                    'approver_user_ids': [approver_uuid],
                }
            ],
            'is_active': True,
            'expected_scope': {'holds': 'all'},
        }
        response = client.post(f'{BASE}/workflows', headers=router_auth, json=payload)
        assert response.status_code == status.HTTP_201_CREATED
        # The stage must round-trip back as a UUID object.
        assert response.json()['stages'][0]['approver_user_ids'] == [approver_uuid]

    def test_update_workflow_with_uuid_approvers_does_not_crash(
        self,
        client: TestClient,
        router_auth: dict[str, str],
        router_user: User,
    ) -> None:
        approver_uuid = str(router_user.id)
        created = client.post(
            f'{BASE}/workflows',
            headers=router_auth,
            json=_create_workflow_payload(),
        ).json()
        response = client.patch(
            f'{BASE}/workflows/{created["id"]}',
            headers=router_auth,
            json={
                'stages': [
                    {
                        'order': 1,
                        'role': 'admin',
                        'label': 'Admin',
                        'approver_user_ids': [approver_uuid],
                    }
                ]
            },
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()['stages'][0]['approver_user_ids'] == [approver_uuid]


@pytest.mark.integration
class TestSelfApproveAutoSkip:
    """A stage whose only configured approver is the requester is
    auto-approved on their behalf (with an audit entry) instead of deadlocking.
    """

    @pytest.fixture(autouse=True)
    def requester_can_see_approvals(self, h: ModuleTestHelper, requester: User) -> None:
        """The stage names the requester, and a named approver needs the read
        floor — a person who cannot see approvals cannot be relied on to
        decide, and such a workflow is refused outright now."""
        h.grant_permissions(requester, ['approvals:read', 'approvals:write'])

    def _seed_workflow(
        self,
        client: TestClient,
        auth: dict[str, str],
        stages: list[dict[str, Any]],
    ) -> dict[str, Any]:
        payload = {
            'target_type': 'document',
            'requester_scope': {'everyone': True},
            'name': f'Self-Skip WF {uuid.uuid4().hex[:6]}',
            'stages': stages,
            'is_active': True,
            'expected_scope': {'holds': 'all'},
        }
        return cast(
            dict[str, Any],
            client.post(f'{BASE}/workflows', headers=auth, json=payload).json(),
        )

    def _create_request(
        self, client: TestClient, auth: dict[str, str]
    ) -> dict[str, Any]:
        response = client.post(
            f'{BASE}/requests',
            headers=auth,
            json={'target_type': 'document', 'target_id': str(uuid.uuid4())},
        )
        assert response.status_code == status.HTTP_201_CREATED, response.text
        return cast(dict[str, Any], response.json())

    def test_solo_org_auto_skips_with_audit(
        self,
        client: TestClient,
        db_session: Session,
        router_auth: dict[str, str],
        requester: User,
        requester_auth: dict[str, str],
    ) -> None:
        from sqlalchemy import select

        from app.models.audit_log import AuditLog
        from app.modules.approvals.models import ApprovalDecision

        self._seed_workflow(
            client,
            router_auth,
            [
                {
                    'order': 1,
                    'role': 'manager',
                    'label': 'Manager',
                    'approver_user_ids': [str(requester.id)],
                }
            ],
        )

        data = self._create_request(client, requester_auth)
        # Single self-only stage -> fully auto-approved at creation.
        assert data['status'] == 'APPROVED'
        request_id = uuid.UUID(data['id'])

        decision = db_session.execute(
            select(ApprovalDecision).where(
                ApprovalDecision.approval_request_id == request_id
            )
        ).scalar_one()
        assert decision.status == 'APPROVED'
        assert decision.approver_id == requester.id
        assert 'Auto-approved' in (decision.notes or '')

        # Two rows: the request being made, then the stage the machine
        # walked past on the requester's behalf.
        asked, skipped = (
            db_session.execute(
                select(AuditLog)
                .where(
                    AuditLog.target_type == 'approval_request',
                    AuditLog.target_id == request_id,
                )
                .order_by(AuditLog.created_at.asc())
            )
            .scalars()
            .all()
        )
        assert asked.action == 'CREATE'
        assert skipped.action == 'UPDATE'
        assert (skipped.snapshot or {}).get('auto_skipped') is True

    def test_consecutive_self_only_stages_all_skipped(
        self,
        client: TestClient,
        db_session: Session,
        router_auth: dict[str, str],
        requester: User,
        requester_auth: dict[str, str],
    ) -> None:
        from sqlalchemy import select

        from app.models.audit_log import AuditLog
        from app.modules.approvals.models import ApprovalDecision

        self._seed_workflow(
            client,
            router_auth,
            [
                {
                    'order': i,
                    'role': 'manager',
                    'label': f'Stage {i}',
                    'approver_user_ids': [str(requester.id)],
                }
                for i in (1, 2)
            ],
        )

        data = self._create_request(client, requester_auth)
        assert data['status'] == 'APPROVED'
        request_id = uuid.UUID(data['id'])

        decisions = (
            db_session.execute(
                select(ApprovalDecision).where(
                    ApprovalDecision.approval_request_id == request_id
                )
            )
            .scalars()
            .all()
        )
        assert len(decisions) == 2
        assert all(d.status == 'APPROVED' for d in decisions)

        audits = (
            db_session.execute(
                select(AuditLog).where(
                    AuditLog.target_type == 'approval_request',
                    AuditLog.target_id == request_id,
                )
            )
            .scalars()
            .all()
        )
        # One row for the request, one for each stage the machine skipped.
        assert len(audits) == 3

    def test_self_only_first_stage_advances_to_human_stage(
        self,
        client: TestClient,
        router_auth: dict[str, str],
        router_user2: User,
        router_auth2: dict[str, str],
        requester: User,
        requester_auth: dict[str, str],
    ) -> None:
        # Stage 1: requester is sole approver (auto-skipped).
        # Stage 2: a different admin must approve normally.
        self._seed_workflow(
            client,
            router_auth,
            [
                {
                    'order': 1,
                    'role': 'manager',
                    'label': 'Self',
                    'approver_user_ids': [str(requester.id)],
                },
                {
                    'order': 2,
                    'role': 'admin',
                    'label': 'Admin',
                    'approver_user_ids': [str(router_user2.id)],
                },
            ],
        )

        data = self._create_request(client, requester_auth)
        # Stage 1 auto-skipped -> now waiting on stage 2.
        assert data['status'] == 'IN_PROGRESS'
        assert data['current_stage'] == 2

        # Stage 2: the assigned admin approves normally.
        approve = client.post(
            f'{BASE}/requests/{data["id"]}/approve',
            headers=router_auth2,
        )
        assert approve.status_code == status.HTTP_200_OK, approve.text
        assert approve.json()['status'] == 'APPROVED'


@pytest.mark.integration
class TestApprovalNotifications:
    """Creating an approval request notifies the pending-stage
    approvers (in-app notification + best-effort email)."""

    @staticmethod
    def _seed_workflow_with_approver(
        client: TestClient, auth: dict[str, str], approver_id: str
    ) -> dict[str, Any]:
        payload = {
            'target_type': 'document',
            'requester_scope': {'everyone': True},
            'name': f'Notify WF {uuid.uuid4().hex[:6]}',
            'stages': [
                {
                    'order': 1,
                    'role': 'manager',
                    'label': 'Manager',
                    'approver_user_ids': [approver_id],
                }
            ],
            'is_active': True,
            'expected_scope': {'holds': 'all'},
        }
        return cast(
            dict[str, Any],
            client.post(f'{BASE}/workflows', headers=auth, json=payload).json(),
        )

    def test_request_notifies_assigned_approver(
        self,
        client: TestClient,
        db_session: Session,
        router_auth: dict[str, str],
        router_user: User,
        requester_auth: dict[str, str],
    ) -> None:
        from sqlalchemy import select

        from app.models.notification import Notification

        self._seed_workflow_with_approver(client, router_auth, str(router_user.id))

        response = client.post(
            f'{BASE}/requests',
            headers=requester_auth,
            json={'target_type': 'document', 'target_id': str(uuid.uuid4())},
        )
        assert response.status_code == status.HTTP_201_CREATED, response.text

        notifs = (
            db_session.execute(
                select(Notification).where(Notification.user_id == router_user.id)
            )
            .scalars()
            .all()
        )
        assert len(notifs) == 1
        assert notifs[0].link == '/approvals?status=PENDING,IN_PROGRESS'
        assert notifs[0].type == 'info'
        assert 'approval_request_id' in (notifs[0].meta_data or {})

    def test_second_stage_approvers_are_notified_when_their_turn_opens(
        self,
        client: TestClient,
        db_session: Session,
        h: ModuleTestHelper,
        router_org: Organization,
        router_auth: dict[str, str],
        router_user: User,
        requester_auth: dict[str, str],
    ) -> None:
        """a two-stage workflow tells stage two it is up.

        Only the first stage was ever notified, so anything past stage one
        waited on someone who had no way to know — the workflow looked
        configured and behaved like a dead end.
        """
        from sqlalchemy import select

        from app.models.notification import Notification

        second = h.create_user(router_org, email='second-stage@example.com')
        h.grant_permissions(second, ['approvals:read', 'approvals:approve'])
        client.post(
            f'{BASE}/workflows',
            headers=router_auth,
            json={
                'target_type': 'document',
                'requester_scope': {'everyone': True},
                'name': 'Two stages',
                'stages': [
                    {
                        'order': 1,
                        'role': 'manager',
                        'label': 'First',
                        'approver_user_ids': [str(router_user.id)],
                    },
                    {
                        'order': 2,
                        'role': 'manager',
                        'label': 'Second',
                        'approver_user_ids': [str(second.id)],
                    },
                ],
                'is_active': True,
                'expected_scope': {'holds': 'all'},
            },
        )
        created = client.post(
            f'{BASE}/requests',
            headers=requester_auth,
            json={'target_type': 'document', 'target_id': str(uuid.uuid4())},
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text

        def _notifications_for(user: User) -> list[Notification]:
            return list(
                db_session.execute(
                    select(Notification).where(Notification.user_id == user.id)
                )
                .scalars()
                .all()
            )

        assert _notifications_for(second) == []

        approved = client.post(
            f'{BASE}/requests/{created.json()["id"]}/approve', headers=router_auth
        )
        assert approved.status_code == status.HTTP_200_OK, approved.text
        assert approved.json()['status'] == 'IN_PROGRESS'

        waiting = _notifications_for(second)
        assert len(waiting) == 1
        assert waiting[0].link == '/approvals?status=PENDING,IN_PROGRESS'

    @pytest.mark.parametrize('settle', ['approve', 'reject', 'cancel'])
    def test_settled_request_clears_its_waiting_notice(
        self,
        client: TestClient,
        db_session: Session,
        router_auth: dict[str, str],
        router_user: User,
        requester_auth: dict[str, str],
        settle: str,
    ) -> None:
        """Once nobody can decide a request, the bell stops counting it."""
        from sqlalchemy import select

        from app.models.notification import Notification

        self._seed_workflow_with_approver(client, router_auth, str(router_user.id))
        created = client.post(
            f'{BASE}/requests',
            headers=requester_auth,
            json={'target_type': 'document', 'target_id': str(uuid.uuid4())},
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text

        def _unread() -> int:
            db_session.expire_all()
            return len(
                db_session.execute(
                    select(Notification).where(
                        Notification.user_id == router_user.id,
                        Notification.is_read.is_(False),
                    )
                )
                .scalars()
                .all()
            )

        assert _unread() == 1

        auth = requester_auth if settle == 'cancel' else router_auth
        response = client.post(
            f'{BASE}/requests/{created.json()["id"]}/{settle}',
            headers=auth,
            json={'notes': 'No'} if settle == 'reject' else None,
        )
        assert response.status_code == status.HTTP_200_OK, response.text

        assert _unread() == 0

    def test_request_sends_email_to_approver(
        self,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
        router_auth: dict[str, str],
        router_user: User,
        requester_auth: dict[str, str],
    ) -> None:
        from app.core.public_api import core_api

        sent: list[tuple[str, uuid.UUID | None]] = []

        async def fake_send(
            to_email: str,
            subject: str,
            html_content: str,
            smtp_config: dict[str, Any] | None = None,
            *,
            organization_id: uuid.UUID | None = None,
        ) -> bool:
            sent.append((to_email, organization_id))
            return True

        monkeypatch.setattr(core_api.email, 'send_async', fake_send)

        self._seed_workflow_with_approver(client, router_auth, str(router_user.id))

        response = client.post(
            f'{BASE}/requests',
            headers=requester_auth,
            json={'target_type': 'document', 'target_id': str(uuid.uuid4())},
        )
        assert response.status_code == status.HTTP_201_CREATED, response.text
        # The address is half of it. A notification queued with no tenant is
        # one the organization's administrator can never be shown failing.
        assert (router_user.email, router_user.organization_id) in sent


@pytest.mark.integration
class TestApprovalVisibilityScope:
    """Who sees whose approval requests.

    An approval request carries the amount, the partner and the names of the
    people deciding on it. Every member of the organization could read all of
    it; now that is what ``approvals:read`` buys. Without the grant a member
    still sees their own requests — and, if they may decide, the ones waiting
    on them.
    """

    def _seed_workflow(self, client: TestClient, auth: dict[str, str]) -> None:
        client.post(f'{BASE}/workflows', headers=auth, json=_create_workflow_payload())

    def _seed_request(self, client: TestClient, auth: dict[str, str]) -> dict[str, Any]:
        resp = client.post(
            f'{BASE}/requests',
            headers=auth,
            json={'target_type': 'document', 'target_id': str(uuid.uuid4())},
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        return cast(dict[str, Any], resp.json())

    @pytest.fixture
    def colleague_auth(
        self, h: ModuleTestHelper, router_org: Organization
    ) -> dict[str, str]:
        user = h.create_user(router_org, email='colleague@example.com', role='user')
        return h.get_auth_headers(user)

    def test_member_sees_only_their_own_requests(
        self,
        client: TestClient,
        router_auth: dict[str, str],
        requester_auth: dict[str, str],
        colleague_auth: dict[str, str],
    ) -> None:
        self._seed_workflow(client, router_auth)
        mine = self._seed_request(client, requester_auth)
        theirs = self._seed_request(client, colleague_auth)

        listed = client.get(f'{BASE}/requests', headers=requester_auth)
        assert listed.status_code == status.HTTP_200_OK, listed.text
        ids = {row['id'] for row in listed.json()['items']}
        assert mine['id'] in ids
        assert theirs['id'] not in ids

    def test_grant_holder_sees_the_whole_organization(
        self,
        client: TestClient,
        router_auth: dict[str, str],
        requester_auth: dict[str, str],
        colleague_auth: dict[str, str],
    ) -> None:
        self._seed_workflow(client, router_auth)
        mine = self._seed_request(client, requester_auth)
        theirs = self._seed_request(client, colleague_auth)

        listed = client.get(f'{BASE}/requests', headers=router_auth)
        ids = {row['id'] for row in listed.json()['items']}
        assert {mine['id'], theirs['id']} <= ids

    def test_member_cannot_open_someone_elses_request(
        self,
        client: TestClient,
        router_auth: dict[str, str],
        requester_auth: dict[str, str],
        colleague_auth: dict[str, str],
    ) -> None:
        self._seed_workflow(client, router_auth)
        theirs = self._seed_request(client, colleague_auth)

        resp = client.get(f'{BASE}/requests/{theirs["id"]}', headers=requester_auth)
        assert resp.status_code == status.HTTP_403_FORBIDDEN, resp.text

    def test_member_can_open_their_own_request(
        self,
        client: TestClient,
        router_auth: dict[str, str],
        requester_auth: dict[str, str],
    ) -> None:
        self._seed_workflow(client, router_auth)
        mine = self._seed_request(client, requester_auth)

        resp = client.get(f'{BASE}/requests/{mine["id"]}', headers=requester_auth)
        assert resp.status_code == status.HTTP_200_OK, resp.text


@pytest.mark.integration
class TestWorkflowVisibilityScope:
    """The workflow list answers a role without grants the same way the
    request list does: 200 with what that role may see — for workflows,
    nothing at all.

    The two lists used to disagree at the same role: /requests filtered
    (200, zero) while /workflows refused (403). One module, one contract.
    """

    def _seed_workflow(self, client: TestClient, auth: dict[str, str]) -> None:
        client.post(f'{BASE}/workflows', headers=auth, json=_create_workflow_payload())

    def test_workflows_filter_for_a_role_without_grants(
        self,
        client: TestClient,
        router_auth: dict[str, str],
        requester_auth: dict[str, str],
    ) -> None:
        # The organization does have a workflow — the grantless role just
        # gets none of it.
        self._seed_workflow(client, router_auth)

        resp = client.get(f'{BASE}/workflows', headers=requester_auth)

        assert resp.status_code == status.HTTP_200_OK, resp.text
        assert resp.json()['items'] == []

    def test_workflows_list_for_a_read_grant(
        self,
        client: TestClient,
        router_auth: dict[str, str],
        h: ModuleTestHelper,
        router_org: Organization,
    ) -> None:
        reader = h.create_user(router_org, email='reader@example.com', role='user')
        h.grant_permissions(reader, ['approvals:read'])
        self._seed_workflow(client, router_auth)

        resp = client.get(f'{BASE}/workflows', headers=h.get_auth_headers(reader))

        assert resp.status_code == status.HTTP_200_OK, resp.text
        names = [wf['name'] for wf in resp.json()['items']]
        assert 'Router Test Workflow' in names

    def test_workflows_list_for_a_configure_only_grant(
        self,
        client: TestClient,
        router_auth: dict[str, str],
        h: ModuleTestHelper,
        router_org: Organization,
    ) -> None:
        # Configuring implies reading: an editor handed configure alone can
        # still open the workflows it edits.
        editor = h.create_user(router_org, email='editor@example.com', role='user')
        h.grant_permissions(editor, ['approvals:configure'])
        self._seed_workflow(client, router_auth)

        resp = client.get(f'{BASE}/workflows', headers=h.get_auth_headers(editor))

        assert resp.status_code == status.HTTP_200_OK, resp.text
        names = [wf['name'] for wf in resp.json()['items']]
        assert 'Router Test Workflow' in names

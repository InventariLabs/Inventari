"""The approvals module refuses in the reader's language, not in English.

Every refusal the engine raises used to travel as an English sentence inside
``ApprovalError`` and reach the toast verbatim, so a Polish, German, French or
Spanish interface answered "Cannot reject your own request". These tests drive
the real endpoints with ``Accept-Language: pl`` and pin the negotiated message.

They compare against ``get_error_message(key, 'pl')`` rather than a literal:
the point is that the negotiated language reaches the message, and the wording
belongs to the catalogue. Each case also asserts the answer differs from the
English one, so an ``en`` fallback cannot pass for a translation.
"""

import uuid
from typing import Any

import pytest
from fastapi import status
from httpx import Response
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.testing import ModuleTestHelper
from app.i18n.service import get_error_message
from app.models.organization import Organization
from app.models.user import User

BASE = '/api/v1/approvals'
PL = {'Accept-Language': 'pl'}

APPROVER_GRANTS = [
    'approvals:read',
    'approvals:write',
    'approvals:approve',
    'approvals:configure',
]


@pytest.fixture
def h(db_session: Session) -> ModuleTestHelper:
    return ModuleTestHelper(db_session)


@pytest.fixture
def org(h: ModuleTestHelper) -> Organization:
    return h.create_org('Approvals i18n Org', ['core', 'approvals'])


@pytest.fixture
def decider(h: ModuleTestHelper, org: Organization) -> User:
    """Holds every approvals grant — a manager, so no self-approve bypass."""
    user = h.create_user(org, email='decider@example.com', role='manager')
    h.grant_permissions(user, APPROVER_GRANTS)
    return user


@pytest.fixture
def other_decider(h: ModuleTestHelper, org: Organization) -> User:
    user = h.create_user(org, email='other-decider@example.com', role='manager')
    h.grant_permissions(user, APPROVER_GRANTS)
    return user


@pytest.fixture
def requester(h: ModuleTestHelper, org: Organization) -> User:
    user = h.create_user(org, email='i18n-requester@example.com', role='user')
    h.grant_permissions(user, ['approvals:read', 'approvals:write'])
    return user


@pytest.fixture
def decider_auth(h: ModuleTestHelper, decider: User) -> dict[str, str]:
    return {**h.get_auth_headers(decider), **PL}


@pytest.fixture
def other_auth(h: ModuleTestHelper, other_decider: User) -> dict[str, str]:
    return {**h.get_auth_headers(other_decider), **PL}


@pytest.fixture
def requester_auth(h: ModuleTestHelper, requester: User) -> dict[str, str]:
    return {**h.get_auth_headers(requester), **PL}


def _workflow(approver_ids: list[str] | None = None) -> dict[str, Any]:
    return {
        'target_type': 'document',
        'requester_scope': {'everyone': True},
        'name': 'i18n Workflow',
        'stages': [
            {
                'order': 1,
                'role': 'manager',
                'label': 'Manager Approval',
                'approver_user_ids': approver_ids or [],
            }
        ],
        'is_active': True,
        'expected_scope': {'holds': 'all'},
    }


def _assert_polish(response: Response, key: str) -> None:
    """The response carries the Polish message for *key*, not the English one.

    A 400 also carries *key* itself as the code, which reads the same in
    every language; a 409 keeps the module's conflict code.
    """
    if response.status_code == 400:
        assert response.json()['detail']['code'] == key.upper()
    message = response.json()['detail']['message']
    assert message == get_error_message(key, 'pl'), (
        f'expected the Polish message for {key!r}, got {message!r}'
    )
    assert message != get_error_message(key, 'en'), (
        f'{key!r} reads the same in Polish and English — the assertion above '
        'would pass on an untranslated fallback'
    )


@pytest.mark.integration
class TestDecisionRefusalsSpeakTheRequestLanguage:
    def test_rejecting_your_own_request_answers_in_polish(
        self,
        client: TestClient,
        decider_auth: dict[str, str],
    ) -> None:
        """The refusal a Polish reader met rejecting their own request."""
        client.post(f'{BASE}/workflows', headers=decider_auth, json=_workflow())
        request = client.post(
            f'{BASE}/requests',
            headers=decider_auth,
            json={'target_type': 'document', 'target_id': str(uuid.uuid4())},
        ).json()

        response = client.post(
            f'{BASE}/requests/{request["id"]}/reject',
            headers=decider_auth,
            json={'notes': 'nie zgadzam sie'},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.text
        _assert_polish(response, 'approval_cannot_reject_own_request')

    def test_approving_your_own_request_answers_in_polish(
        self,
        client: TestClient,
        decider_auth: dict[str, str],
    ) -> None:
        client.post(f'{BASE}/workflows', headers=decider_auth, json=_workflow())
        request = client.post(
            f'{BASE}/requests',
            headers=decider_auth,
            json={'target_type': 'document', 'target_id': str(uuid.uuid4())},
        ).json()

        response = client.post(
            f'{BASE}/requests/{request["id"]}/approve',
            headers=decider_auth,
            json={},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.text
        _assert_polish(response, 'approval_cannot_approve_own_request')

    def test_deciding_twice_answers_in_polish(
        self,
        client: TestClient,
        decider_auth: dict[str, str],
        requester_auth: dict[str, str],
    ) -> None:
        client.post(f'{BASE}/workflows', headers=decider_auth, json=_workflow())
        request = client.post(
            f'{BASE}/requests',
            headers=requester_auth,
            json={'target_type': 'document', 'target_id': str(uuid.uuid4())},
        ).json()
        first = client.post(
            f'{BASE}/requests/{request["id"]}/approve', headers=decider_auth, json={}
        )
        assert first.status_code == status.HTTP_200_OK, first.text

        response = client.post(
            f'{BASE}/requests/{request["id"]}/approve', headers=decider_auth, json={}
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.text
        _assert_polish(response, 'approval_approve_invalid_status')

    def test_deciding_on_a_stage_you_do_not_own_answers_in_polish(
        self,
        client: TestClient,
        decider: User,
        decider_auth: dict[str, str],
        other_auth: dict[str, str],
        requester_auth: dict[str, str],
    ) -> None:
        client.post(
            f'{BASE}/workflows',
            headers=decider_auth,
            json=_workflow([str(decider.id)]),
        )
        request = client.post(
            f'{BASE}/requests',
            headers=requester_auth,
            json={'target_type': 'document', 'target_id': str(uuid.uuid4())},
        ).json()

        response = client.post(
            f'{BASE}/requests/{request["id"]}/approve', headers=other_auth, json={}
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.text
        _assert_polish(response, 'approval_not_stage_approver')

    def test_withdrawing_someone_elses_request_answers_in_polish(
        self,
        client: TestClient,
        decider_auth: dict[str, str],
        requester_auth: dict[str, str],
    ) -> None:
        client.post(f'{BASE}/workflows', headers=decider_auth, json=_workflow())
        request = client.post(
            f'{BASE}/requests',
            headers=requester_auth,
            json={'target_type': 'document', 'target_id': str(uuid.uuid4())},
        ).json()

        response = client.post(
            f'{BASE}/requests/{request["id"]}/cancel', headers=decider_auth
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.text
        _assert_polish(response, 'approval_only_requester_can_cancel')


@pytest.mark.integration
class TestRequestAndWorkflowRefusalsSpeakTheRequestLanguage:
    def test_second_request_for_the_same_target_answers_in_polish(
        self,
        client: TestClient,
        decider_auth: dict[str, str],
        requester_auth: dict[str, str],
    ) -> None:
        client.post(f'{BASE}/workflows', headers=decider_auth, json=_workflow())
        target_id = str(uuid.uuid4())
        first = client.post(
            f'{BASE}/requests',
            headers=requester_auth,
            json={'target_type': 'document', 'target_id': target_id},
        )
        assert first.status_code == status.HTTP_201_CREATED, first.text

        response = client.post(
            f'{BASE}/requests',
            headers=requester_auth,
            json={'target_type': 'document', 'target_id': target_id},
        )

        assert response.status_code == status.HTTP_409_CONFLICT, response.text
        _assert_polish(response, 'approval_request_already_open')

    def test_workflow_without_stages_answers_in_polish(
        self, client: TestClient, decider_auth: dict[str, str]
    ) -> None:
        payload = _workflow()
        payload['stages'] = []

        response = client.post(f'{BASE}/workflows', headers=decider_auth, json=payload)

        assert response.status_code == status.HTTP_409_CONFLICT, response.text
        _assert_polish(response, 'approval_workflow_needs_stage')

    def test_editing_a_workflow_with_live_requests_answers_in_polish(
        self,
        client: TestClient,
        decider_auth: dict[str, str],
        requester_auth: dict[str, str],
    ) -> None:
        workflow = client.post(
            f'{BASE}/workflows', headers=decider_auth, json=_workflow()
        ).json()
        waiting_on = str(uuid.uuid4())
        client.post(
            f'{BASE}/requests',
            headers=requester_auth,
            json={'target_type': 'document', 'target_id': waiting_on},
        )

        response = client.patch(
            f'{BASE}/workflows/{workflow["id"]}',
            headers=decider_auth,
            json={
                'name': 'Renamed',
                'stages': [
                    {
                        'order': 1,
                        'role': 'admin',
                        'label': 'Admin Only',
                        'approver_user_ids': [],
                    }
                ],
            },
        )

        assert response.status_code == status.HTTP_409_CONFLICT, response.text
        message = response.json()['detail']['message']
        assert message == get_error_message(
            'approval_workflow_modify_blocked',
            'pl',
            count=1,
            documents=waiting_on[:8],
        )
        # The count is what makes the refusal actionable — "one request is in
        # the way" sends the reader to the queue; "some requests are" does not.
        assert '1' in message

"""The workflow list names whose submissions each workflow holds.

The card has to say it at all times — "Dokumenty składane przez: Magazynier,
Kasia" — so the list answers it by name rather than by ids the screen could
not read without the roles listing, which most readers may not open. A
scope naming somebody from another organization is refused, and a scope
changed while requests wait is taken: those requests were raised and stay
where they are.
"""

from typing import Any
from uuid import uuid5

import pytest
from fastapi import status
from starlette.testclient import TestClient

from app.core.public_api.roles import BUILTIN_ROLE_NAMESPACE
from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.user import User

BASE = '/api/v1/approvals'


def _scoped(payload: dict[str, Any], **scope: Any) -> dict[str, Any]:
    return {
        **payload,
        'requester_scope': {'everyone': False, 'user_ids': [], 'role_ids': [], **scope},
    }


@pytest.mark.integration
class TestAWorkflowNamesWhoseSubmissionsItHolds:
    def test_the_list_names_the_roles_then_the_people(
        self,
        client: TestClient,
        approval_auth2: dict[str, str],
        requester: User,
        single_stage_workflow_payload: dict[str, Any],
    ) -> None:
        created = client.post(
            f'{BASE}/workflows',
            headers=approval_auth2,
            json=_scoped(
                single_stage_workflow_payload,
                user_ids=[str(requester.id)],
                role_ids=[str(uuid5(BUILTIN_ROLE_NAMESPACE, 'user'))],
            ),
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        assert created.json()['requester_scope']['everyone'] is False

        listed = client.get(f'{BASE}/workflows', headers=approval_auth2).json()['items']
        row = next(r for r in listed if r['id'] == created.json()['id'])

        assert [(r['kind'], r['name'], r['is_system']) for r in row['requesters']] == [
            ('role', 'user', True),
            ('user', 'Requester', False),
        ]

    def test_a_workflow_holding_everyone_names_nobody(
        self,
        client: TestClient,
        approval_auth2: dict[str, str],
        single_stage_workflow_payload: dict[str, Any],
    ) -> None:
        created = client.post(
            f'{BASE}/workflows',
            headers=approval_auth2,
            json=single_stage_workflow_payload,
        )
        listed = client.get(f'{BASE}/workflows', headers=approval_auth2).json()['items']
        row = next(r for r in listed if r['id'] == created.json()['id'])

        assert row['requester_scope'] == {
            'everyone': True,
            'user_ids': [],
            'role_ids': [],
        }
        assert row['requesters'] == []

    def test_somebody_from_another_organization_is_refused(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        approval_auth2: dict[str, str],
        single_stage_workflow_payload: dict[str, Any],
    ) -> None:
        elsewhere = h.create_org('Elsewhere', ['core', 'approvals'])
        stranger = h.create_user(elsewhere, email='stranger@example.com')

        refused = client.post(
            f'{BASE}/workflows',
            headers=approval_auth2,
            json=_scoped(single_stage_workflow_payload, user_ids=[str(stranger.id)]),
        )

        assert refused.status_code == status.HTTP_409_CONFLICT, refused.text
        assert str(stranger.id) not in refused.text

    def test_the_scope_changes_while_a_request_waits_and_the_request_stays(
        self,
        client: TestClient,
        approval_org: Organization,
        approval_auth2: dict[str, str],
        requester: User,
        requester_auth: dict[str, str],
        single_stage_workflow_payload: dict[str, Any],
    ) -> None:
        workflow = client.post(
            f'{BASE}/workflows',
            headers=approval_auth2,
            json=single_stage_workflow_payload,
        ).json()
        target = '00000000-0000-4000-8000-000000000001'
        raised = client.post(
            f'{BASE}/requests',
            headers=requester_auth,
            json={'target_type': 'document', 'target_id': target},
        )
        assert raised.status_code == status.HTTP_201_CREATED, raised.text

        changed = client.patch(
            f'{BASE}/workflows/{workflow["id"]}',
            headers=approval_auth2,
            json={
                'requester_scope': {
                    'everyone': False,
                    'user_ids': [],
                    'role_ids': [str(uuid5(BUILTIN_ROLE_NAMESPACE, 'manager'))],
                }
            },
        )

        assert changed.status_code == status.HTTP_200_OK, changed.text
        assert changed.json()['requester_scope']['role_ids'] == [
            str(uuid5(BUILTIN_ROLE_NAMESPACE, 'manager'))
        ]
        still = client.get(
            f'{BASE}/requests/{raised.json()["id"]}', headers=approval_auth2
        ).json()
        assert still['status'] == 'PENDING'

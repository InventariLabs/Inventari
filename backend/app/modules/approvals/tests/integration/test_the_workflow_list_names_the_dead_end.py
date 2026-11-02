"""The workflow list says which of its rows nobody could ever decide.

The dead end is a property of the definition, not of the request that
discovers it: a stage naming people who cannot see approvals, or open to a
grant nobody in the organization holds, parks the first document that walks
into it. The request side already says so (``_services_solvability``); the
list is the earliest place the administrator could see it, and it used to
render the dead end exactly like the workflow next to it that works.

The reason codes travel under the same names the enriched request uses, so
the row and the parked request tell the reader the same story.
"""

from typing import Any

import pytest
from fastapi import status
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.user import User

BASE = '/api/v1/approvals'


def _open_stage(label: str = 'Manager Approval') -> dict[str, object]:
    return {
        'order': 1,
        'role': 'manager',
        'label': label,
        'approver_user_ids': [],
    }


def _named_stage(user_id: str, label: str = 'Peer review') -> dict[str, object]:
    return {
        'order': 1,
        'role': 'manager',
        'label': label,
        'approver_user_ids': [user_id],
    }


def _workflow_payload(
    stages: list[dict[str, object]],
    *,
    allow_undecidable: bool = False,
    name: str = 'Documents',
) -> dict[str, object]:
    payload: dict[str, object] = {
        'target_type': 'document',
        'requester_scope': {'everyone': True},
        'is_active': True,
        'expected_scope': {'holds': 'all'},
        'name': name,
        'stages': stages,
    }
    if allow_undecidable:
        payload['allow_undecidable_stages'] = True
    return payload


def _row(
    client: TestClient, headers: dict[str, str], workflow_id: str
) -> dict[str, Any]:
    listed = client.get(f'{BASE}/workflows', headers=headers)
    assert listed.status_code == status.HTTP_200_OK, listed.text
    return next(row for row in listed.json()['items'] if row['id'] == workflow_id)


@pytest.mark.integration
class TestTheWorkflowListNamesTheDeadEnd:
    @pytest.fixture
    def h(self, db_session: Session) -> ModuleTestHelper:
        return ModuleTestHelper(db_session)

    @pytest.fixture
    def org(self, h: ModuleTestHelper) -> Organization:
        return h.create_org('Workflow List Org', ['core', 'approvals'])

    @pytest.fixture
    def configurator(self, h: ModuleTestHelper, org: Organization) -> User:
        user = h.create_user(org, email='config@example.com', role='user')
        h.grant_permissions(
            user,
            [
                'approvals:configure',
                'approvals:read',
                'approvals:write',
                'approvals:approve',
            ],
        )
        return user

    @pytest.fixture
    def config_headers(self, h: ModuleTestHelper, configurator: User) -> dict[str, str]:
        return h.get_auth_headers(configurator)

    def test_a_healthy_workflow_is_listed_as_solvable(
        self,
        client: TestClient,
        config_headers: dict[str, str],
    ) -> None:
        created = client.post(
            f'{BASE}/workflows',
            headers=config_headers,
            json=_workflow_payload([_open_stage()]),
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text

        row = _row(client, config_headers, created.json()['id'])
        assert row['solvable'] is True
        assert row['undecidable_reason'] is None

    def test_a_named_stage_nobody_can_decide_is_named(
        self,
        client: TestClient,
        config_headers: dict[str, str],
        org: Organization,
        h: ModuleTestHelper,
    ) -> None:
        blind = h.create_user(org, email='blind@example.com', role='user')
        created = client.post(
            f'{BASE}/workflows',
            headers=config_headers,
            json=_workflow_payload(
                [_named_stage(str(blind.id))], allow_undecidable=True
            ),
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text

        row = _row(client, config_headers, created.json()['id'])
        assert row['solvable'] is False
        assert row['undecidable_reason'] == 'named_approvers_cannot_decide'

    def test_an_open_stage_without_an_approver_in_the_organization_is_named(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        org: Organization,
    ) -> None:
        # Nobody holds ``approvals:approve`` — the configurator does not
        # necessarily, and the dead end must be visible before a request
        # discovers it.
        configurator = h.create_user(org, email='solo@example.com', role='user')
        h.grant_permissions(
            configurator,
            ['approvals:configure', 'approvals:read', 'approvals:write'],
        )
        headers = h.get_auth_headers(configurator)
        created = client.post(
            f'{BASE}/workflows',
            headers=headers,
            json=_workflow_payload([_open_stage()], allow_undecidable=True),
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text

        row = _row(client, headers, created.json()['id'])
        assert row['solvable'] is False
        assert row['undecidable_reason'] == 'no_approver_in_organization'

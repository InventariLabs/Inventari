"""A workflow says which requests are standing on it, by the name their owner uses.

Two screens needed the same fact and had only a number. The refusal to change
or delete a workflow said how many requests were running through it and left
the reader to find them; the workflow list marked a stage nobody can decide
without saying that a document was already parked there. Both now name the
requests — the number the owning module prints on its record — so the reader
goes to a document rather than looking for one.
"""

import uuid
from types import SimpleNamespace

import pytest
from fastapi import status
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.user import User
from app.modules.approvals import target_summaries
from app.modules.approvals._services_waiting import (
    NAMED_IN_A_SENTENCE,
    WaitingRequest,
    name_waiting,
)

BASE = '/api/v1/approvals'


def _open_stage() -> dict[str, object]:
    return {
        'order': 1,
        'role': 'manager',
        'label': 'Manager Approval',
        'approver_user_ids': [],
    }


@pytest.fixture
def named_documents(monkeypatch: pytest.MonkeyPatch) -> dict[uuid.UUID, str]:
    """Teach the engine to name documents the way the warehouse module does."""
    numbers: dict[uuid.UUID, str] = {}

    async def provider(
        _db: object, _org_id: uuid.UUID, ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, SimpleNamespace]:
        return {i: SimpleNamespace(number=numbers[i]) for i in ids if i in numbers}

    monkeypatch.setitem(target_summaries._PROVIDERS, 'document', provider)
    return numbers


@pytest.mark.integration
class TestAWorkflowNamesTheRequestsWaitingOnIt:
    @pytest.fixture
    def h(self, db_session: Session) -> ModuleTestHelper:
        return ModuleTestHelper(db_session)

    @pytest.fixture
    def org(self, h: ModuleTestHelper) -> Organization:
        # Nobody among the ordinary members holds the approve grant, so the
        # open stage of the workflow below is a dead end the moment it is saved.
        return h.create_org('Waiting Org', ['core', 'approvals'])

    @pytest.fixture
    def admin_headers(self, h: ModuleTestHelper, org: Organization) -> dict[str, str]:
        user: User = h.create_user(org, email='config@example.com', role='user')
        h.grant_permissions(
            user, ['approvals:configure', 'approvals:read', 'approvals:write']
        )
        return h.get_auth_headers(user)

    def _stuck_workflow(
        self,
        client: TestClient,
        headers: dict[str, str],
        named_documents: dict[uuid.UUID, str],
        numbers: list[str],
    ) -> str:
        created = client.post(
            f'{BASE}/workflows',
            headers=headers,
            json={
                'target_type': 'document',
                'requester_scope': {'everyone': True},
                'name': 'Documents',
                'stages': [_open_stage()],
                'is_active': True,
                'expected_scope': {'holds': 'all'},
                'allow_undecidable_stages': True,
            },
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        for number in numbers:
            target_id = uuid.uuid4()
            named_documents[target_id] = number
            raised = client.post(
                f'{BASE}/requests',
                headers=headers,
                json={'target_type': 'document', 'target_id': str(target_id)},
            )
            assert raised.status_code == status.HTTP_201_CREATED, raised.text
        return str(created.json()['id'])

    def test_the_refusal_to_change_names_the_documents(
        self,
        client: TestClient,
        admin_headers: dict[str, str],
        named_documents: dict[uuid.UUID, str],
    ) -> None:
        workflow_id = self._stuck_workflow(
            client, admin_headers, named_documents, ['IN/2026/001', 'IN/2026/002']
        )

        refused = client.patch(
            f'{BASE}/workflows/{workflow_id}',
            headers=admin_headers,
            json={'stages': [_open_stage()], 'allow_undecidable_stages': True},
        )

        assert refused.status_code == status.HTTP_409_CONFLICT, refused.text
        message = refused.json()['detail']['message']
        assert '2' in message
        assert 'IN/2026/001' in message
        assert 'IN/2026/002' in message
        # The way out the sentence offers is one that exists: the requester
        # withdraws, an approver decides. Changing the workflow is not on offer.
        assert 'withdraw' in message

    def test_the_list_names_the_requests_parked_on_a_dead_end(
        self,
        client: TestClient,
        admin_headers: dict[str, str],
        named_documents: dict[uuid.UUID, str],
    ) -> None:
        workflow_id = self._stuck_workflow(
            client, admin_headers, named_documents, ['IN/2026/001', 'IN/2026/002']
        )

        listed = client.get(f'{BASE}/workflows', headers=admin_headers)

        row = next(r for r in listed.json()['items'] if r['id'] == workflow_id)
        assert row['solvable'] is False
        assert [w['label'] for w in row['waiting_requests']] == [
            'IN/2026/001',
            'IN/2026/002',
        ]
        assert {w['target_type'] for w in row['waiting_requests']} == {'document'}
        assert all(
            uuid.UUID(w['target_id']) in named_documents
            for w in row['waiting_requests']
        )

    def test_a_workflow_that_works_lists_none(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        org: Organization,
        admin_headers: dict[str, str],
        named_documents: dict[uuid.UUID, str],
    ) -> None:
        # Give the organization an approver: the same open stage now works,
        # and a request waiting on it is waiting its turn, not stuck.
        approver = h.create_user(org, email='approver@example.com', role='admin')
        assert approver.id
        workflow_id = self._stuck_workflow(
            client, admin_headers, named_documents, ['IN/2026/001']
        )

        listed = client.get(f'{BASE}/workflows', headers=admin_headers)

        row = next(r for r in listed.json()['items'] if r['id'] == workflow_id)
        assert row['solvable'] is True
        assert row['waiting_requests'] == []


def test_a_sentence_names_the_first_few_and_hints_at_the_rest() -> None:
    def waiting(label: str) -> WaitingRequest:
        return WaitingRequest(uuid.uuid4(), 'document', uuid.uuid4(), label)

    few = [waiting(f'IN/{i}') for i in range(NAMED_IN_A_SENTENCE)]
    assert name_waiting(few) == 'IN/0, IN/1, IN/2'
    assert name_waiting([*few, waiting('IN/3')]) == 'IN/0, IN/1, IN/2, …'

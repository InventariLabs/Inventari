"""A stage nobody can decide is refused where it would be saved, or marked.

Two dead ends, one shape: a request parked where no one can act on it. A
stage left open to "anyone with the grant" in an organization that has
granted it to nobody; a stage naming people who cannot see approvals at all.
Both used to save silently and produce a queue entry that looked exactly
like a decision waiting its turn.

The refusal is the default and the consent flag is the way past it — an
administrator who has read what it costs may save the stage, and the request
it produces then says on every screen that nobody can decide it
(``_services_solvability``; the reason codes travel on the enriched request).
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

UNSOLVABLE_CODE = 'APPROVAL_STAGE_UNSOLVABLE'


def _open_stage(label: str = 'Manager Approval') -> dict[str, object]:
    return {
        'order': 1,
        'role': 'manager',
        'label': label,
        'approver_user_ids': [],
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


@pytest.mark.integration
class TestNobodyInTheOrganizationCanDecide:
    """The open stage: decidable by whoever holds the grant, and nobody does."""

    @pytest.fixture
    def h(self, db_session: Session) -> ModuleTestHelper:
        return ModuleTestHelper(db_session)

    @pytest.fixture
    def org(self, h: ModuleTestHelper) -> Organization:
        # No managers, no admins among the ordinary members: the organization
        # configured its approval policy itself and granted the approve right
        # to nobody.
        return h.create_org('No Approvers Org', ['core', 'approvals'])

    @pytest.fixture
    def configurator(self, h: ModuleTestHelper, org: Organization) -> User:
        user = h.create_user(org, email='config@example.com', role='user')
        h.grant_permissions(
            user,
            ['approvals:configure', 'approvals:read', 'approvals:write'],
        )
        return user

    @pytest.fixture
    def config_headers(self, h: ModuleTestHelper, configurator: User) -> dict[str, str]:
        return h.get_auth_headers(configurator)

    def test_an_open_stage_is_refused(
        self,
        client: TestClient,
        config_headers: dict[str, str],
    ) -> None:
        resp = client.post(
            f'{BASE}/workflows',
            headers=config_headers,
            json=_workflow_payload([_open_stage()]),
        )
        assert resp.status_code == status.HTTP_409_CONFLICT, resp.text
        detail = resp.json()['detail']
        assert detail['code'] == UNSOLVABLE_CODE
        assert 'Manager Approval' in detail['message']

    def test_the_same_stage_saves_with_consent(
        self,
        client: TestClient,
        config_headers: dict[str, str],
    ) -> None:
        resp = client.post(
            f'{BASE}/workflows',
            headers=config_headers,
            json=_workflow_payload([_open_stage()], allow_undecidable=True),
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text

    def test_an_update_that_would_strand_the_workflow_is_refused(
        self,
        client: TestClient,
        config_headers: dict[str, str],
    ) -> None:
        created = client.post(
            f'{BASE}/workflows',
            headers=config_headers,
            json=_workflow_payload(
                [_open_stage('First')], allow_undecidable=True, name='Documents'
            ),
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        workflow_id = created.json()['id']

        refused = client.patch(
            f'{BASE}/workflows/{workflow_id}',
            headers=config_headers,
            json={'stages': [_open_stage('Second')]},
        )
        assert refused.status_code == status.HTTP_409_CONFLICT, refused.text
        assert refused.json()['detail']['code'] == UNSOLVABLE_CODE

        accepted = client.patch(
            f'{BASE}/workflows/{workflow_id}',
            headers=config_headers,
            json={
                'stages': [_open_stage('Second')],
                'allow_undecidable_stages': True,
            },
        )
        assert accepted.status_code == status.HTTP_200_OK, accepted.text

    def test_the_request_says_nobody_can_decide_it(
        self,
        client: TestClient,
        config_headers: dict[str, str],
    ) -> None:
        created = client.post(
            f'{BASE}/workflows',
            headers=config_headers,
            json=_workflow_payload([_open_stage()], allow_undecidable=True),
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text

        requested = client.post(
            f'{BASE}/requests',
            headers=config_headers,
            json={'target_type': 'document', 'target_id': str(uuid.uuid4())},
        )
        assert requested.status_code == status.HTTP_201_CREATED, requested.text

        listed = client.get(
            f'{BASE}/requests?status=PENDING,IN_PROGRESS', headers=config_headers
        )
        assert listed.status_code == status.HTTP_200_OK, listed.text
        item = next(
            row for row in listed.json()['items'] if row['id'] == requested.json()['id']
        )
        assert item['solvable'] is False
        assert item['undecidable_reason'] == 'no_approver_in_organization'


@pytest.mark.integration
class TestANamedStageNobodyCanDecide:
    """The other dead end: the people it names cannot see approvals."""

    @pytest.fixture
    def h(self, db_session: Session) -> ModuleTestHelper:
        return ModuleTestHelper(db_session)

    @pytest.fixture
    def org(self, h: ModuleTestHelper) -> Organization:
        return h.create_org('Named Dead End Org', ['core', 'approvals'])

    @pytest.fixture
    def admin_headers(self, h: ModuleTestHelper, org: Organization) -> dict[str, str]:
        admin = h.create_user(org, email='boss@example.com', role='admin')
        return h.get_auth_headers(admin)

    @pytest.fixture
    def blind(self, h: ModuleTestHelper, org: Organization) -> User:
        return h.create_user(org, email='blind@example.com', role='user')

    def test_it_is_refused_without_consent(
        self,
        client: TestClient,
        admin_headers: dict[str, str],
        blind: User,
    ) -> None:
        stages = [
            {
                'order': 1,
                'role': 'manager',
                'label': 'Peer review',
                'approver_user_ids': [str(blind.id)],
            }
        ]
        resp = client.post(
            f'{BASE}/workflows',
            headers=admin_headers,
            json=_workflow_payload(stages),
        )
        assert resp.status_code == status.HTTP_409_CONFLICT, resp.text
        assert resp.json()['detail']['code'] == UNSOLVABLE_CODE
        assert 'Peer review' in resp.json()['detail']['message']

    def test_it_saves_with_consent_and_the_request_says_so(
        self,
        client: TestClient,
        admin_headers: dict[str, str],
        blind: User,
    ) -> None:
        stages = [
            {
                'order': 1,
                'role': 'manager',
                'label': 'Peer review',
                'approver_user_ids': [str(blind.id)],
            }
        ]
        created = client.post(
            f'{BASE}/workflows',
            headers=admin_headers,
            json=_workflow_payload(stages, allow_undecidable=True),
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text

        requested = client.post(
            f'{BASE}/requests',
            headers=admin_headers,
            json={'target_type': 'document', 'target_id': str(uuid.uuid4())},
        )
        assert requested.status_code == status.HTTP_201_CREATED, requested.text

        enriched = client.get(
            f'{BASE}/requests/{requested.json()["id"]}', headers=admin_headers
        )
        assert enriched.status_code == status.HTTP_200_OK, enriched.text
        assert enriched.json()['solvable'] is False
        assert enriched.json()['undecidable_reason'] == 'named_approvers_cannot_decide'


@pytest.mark.integration
class TestOnlyTheRequesterHoldsTheGrant:
    """The third dead end: an open stage whose only decider is the asker.

    The default shape of a fresh solo organization — one admin, an open
    stage. The door refuses a self-decision, so the request parks; every
    surface used to read it as merely waiting its turn, which is how the
    scenario in the field report reproduced: confirm, silence, nobody to
    ask.
    """

    @pytest.fixture
    def h(self, db_session: Session) -> ModuleTestHelper:
        return ModuleTestHelper(db_session)

    @pytest.fixture
    def org(self, h: ModuleTestHelper) -> Organization:
        return h.create_org('Solo Org', ['core', 'approvals'])

    @pytest.fixture
    def boss(self, h: ModuleTestHelper, org: Organization) -> User:
        return h.create_user(org, email='boss@example.com', role='admin')

    @pytest.fixture
    def boss_headers(self, h: ModuleTestHelper, boss: User) -> dict[str, str]:
        return h.get_auth_headers(boss)

    def _open_workflow(self, client: TestClient, headers: dict[str, str]) -> None:
        created = client.post(
            f'{BASE}/workflows',
            headers=headers,
            json=_workflow_payload([_open_stage()]),
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text

    def _request(self, client: TestClient, headers: dict[str, str]) -> str:
        requested = client.post(
            f'{BASE}/requests',
            headers=headers,
            json={'target_type': 'document', 'target_id': str(uuid.uuid4())},
        )
        assert requested.status_code == status.HTTP_201_CREATED, requested.text
        return str(requested.json()['id'])

    def test_the_solo_request_reports_its_dead_end(
        self,
        client: TestClient,
        boss_headers: dict[str, str],
    ) -> None:
        self._open_workflow(client, boss_headers)
        request_id = self._request(client, boss_headers)

        enriched = client.get(f'{BASE}/requests/{request_id}', headers=boss_headers)
        assert enriched.status_code == status.HTTP_200_OK, enriched.text
        assert enriched.json()['solvable'] is False
        assert enriched.json()['undecidable_reason'] == 'only_the_requester_can_decide'

        listed = client.get(
            f'{BASE}/requests?status=PENDING,IN_PROGRESS', headers=boss_headers
        )
        assert listed.status_code == status.HTTP_200_OK, listed.text
        item = next(row for row in listed.json()['items'] if row['id'] == request_id)
        assert item['solvable'] is False
        assert item['undecidable_reason'] == 'only_the_requester_can_decide'

    def test_a_second_holder_makes_it_somebodys_turn(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        org: Organization,
        boss_headers: dict[str, str],
    ) -> None:
        # The grant's second holder — a manager holds approvals:approve by
        # the module's default_roles alone.
        h.create_user(org, email='second@example.com', role='manager')
        self._open_workflow(client, boss_headers)
        request_id = self._request(client, boss_headers)

        enriched = client.get(f'{BASE}/requests/{request_id}', headers=boss_headers)
        assert enriched.status_code == status.HTTP_200_OK, enriched.text
        assert enriched.json()['solvable'] is True
        assert enriched.json()['undecidable_reason'] is None

    def test_the_self_approval_opt_in_lets_the_solo_admin_through(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        org: Organization,
        boss_headers: dict[str, str],
    ) -> None:
        h.set_module_settings(org, 'approvals', {'allow_admin_self_approve': True})
        self._open_workflow(client, boss_headers)
        request_id = self._request(client, boss_headers)

        enriched = client.get(f'{BASE}/requests/{request_id}', headers=boss_headers)
        assert enriched.status_code == status.HTTP_200_OK, enriched.text
        assert enriched.json()['solvable'] is True
        assert enriched.json()['undecidable_reason'] is None


@pytest.mark.integration
class TestADecidableStageSaysNothing:
    """The control: a stage somebody can decide reports no dead end."""

    def test_a_manager_stage_is_solvable(
        self,
        client: TestClient,
        db_session: Session,
    ) -> None:
        h = ModuleTestHelper(db_session)
        org = h.create_org('Decidable Org', ['core', 'approvals'])
        manager = h.create_user(org, email='manager@example.com', role='manager')
        # A second holder of the grant: the door refuses a self-decision, so
        # with the asker as its only holder the stage would be the third dead
        # end, not a decidable one.
        h.create_user(org, email='peer@example.com', role='manager')
        headers = h.get_auth_headers(manager)

        # A manager holds ``approvals:approve`` by the module's default_roles
        # alone — no custom role row anywhere.
        created = client.post(
            f'{BASE}/workflows',
            headers=headers,
            json=_workflow_payload([_open_stage()]),
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text

        requested = client.post(
            f'{BASE}/requests',
            headers=headers,
            json={'target_type': 'document', 'target_id': str(uuid.uuid4())},
        )
        assert requested.status_code == status.HTTP_201_CREATED, requested.text

        enriched = client.get(
            f'{BASE}/requests/{requested.json()["id"]}', headers=headers
        )
        assert enriched.status_code == status.HTTP_200_OK, enriched.text
        assert enriched.json()['solvable'] is True
        assert enriched.json()['undecidable_reason'] is None

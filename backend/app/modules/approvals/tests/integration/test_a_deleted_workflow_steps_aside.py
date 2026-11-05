"""A workflow deleted with history behind it is archived, and steps aside.

Deleting a workflow that had requests used to switch it off and nothing more.
A workflow that was already off stayed on the list exactly as it was, while
the toast reported an archive; and the row kept the only place its target
type had, so the next workflow overwrote its name and stages, and every past
request — which reads its stage labels from its workflow — read the new ones.

Archived is now a state of its own: off the list, frozen, and the next
workflow for the target type is a new row beside it.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import status
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.db_isolation import isolated_db_url as _isolated_db_url
from app.core.module_migrations import run_module_migrations
from app.core.testing import ModuleTestHelper, error_message_pattern
from app.models.organization import Organization
from app.models.user import User

BASE = '/api/v1/approvals'


@pytest.fixture
def h(db_session: Session) -> ModuleTestHelper:
    return ModuleTestHelper(db_session)


@pytest.fixture
def org(h: ModuleTestHelper) -> Organization:
    return h.create_org('Archive Org', ['core', 'approvals'])


@pytest.fixture
def admin_auth(h: ModuleTestHelper, org: Organization) -> dict[str, str]:
    user = h.create_user(org, email='archive-admin@example.com', role='manager')
    h.grant_permissions(
        user,
        [
            'approvals:read',
            'approvals:write',
            'approvals:approve',
            'approvals:configure',
        ],
    )
    return h.get_auth_headers(user)


@pytest.fixture
def requester_auth(h: ModuleTestHelper, org: Organization) -> dict[str, str]:
    user: User = h.create_user(org, email='archive-requester@example.com', role='user')
    return h.get_auth_headers(user)


def _stage(label: str) -> dict[str, Any]:
    return {'order': 1, 'role': 'manager', 'label': label, 'approver_user_ids': []}


def _create(
    client: TestClient, auth: dict[str, str], name: str, label: str
) -> dict[str, Any]:
    response = client.post(
        f'{BASE}/workflows',
        headers=auth,
        json={
            'target_type': 'document',
            'requester_scope': {'everyone': True},
            'name': name,
            'stages': [_stage(label)],
            'is_active': True,
            'expected_scope': {'holds': 'all'},
        },
    )
    assert response.status_code == status.HTTP_201_CREATED, response.text
    created: dict[str, Any] = response.json()
    return created


def _raise(client: TestClient, auth: dict[str, str]) -> str:
    response = client.post(
        f'{BASE}/requests',
        headers=auth,
        json={'target_type': 'document', 'target_id': str(uuid.uuid4())},
    )
    assert response.status_code == status.HTTP_201_CREATED, response.text
    return str(response.json()['id'])


def _listed_ids(client: TestClient, auth: dict[str, str]) -> list[str]:
    response = client.get(f'{BASE}/workflows', headers=auth)
    assert response.status_code == status.HTTP_200_OK, response.text
    return [wf['id'] for wf in response.json()['items']]


def _archived_refusal() -> re.Pattern[str]:
    return re.compile(error_message_pattern('approval_workflow_archived'))


@pytest.mark.integration
class TestDeletingAWorkflowWithHistory:
    def test_it_leaves_the_list_and_says_where_the_history_is(
        self,
        client: TestClient,
        admin_auth: dict[str, str],
        requester_auth: dict[str, str],
    ) -> None:
        workflow = _create(client, admin_auth, 'Documents', 'Manager Approval')
        request_id = _raise(client, requester_auth)
        approved = client.post(
            f'{BASE}/requests/{request_id}/approve', headers=admin_auth
        )
        assert approved.status_code == status.HTTP_200_OK, approved.text

        response = client.delete(
            f'{BASE}/workflows/{workflow["id"]}', headers=admin_auth
        )

        assert response.status_code == status.HTTP_200_OK, response.text
        assert response.json() == {'archived': True, 'requests_kept': 1}
        assert workflow['id'] not in _listed_ids(client, admin_auth)
        kept = client.get(f'{BASE}/workflows/{workflow["id"]}', headers=admin_auth)
        assert kept.json()['archived_at'] is not None
        assert kept.json()['is_active'] is False

    def test_an_inactive_one_is_archived_too_not_left_as_it_was(
        self,
        client: TestClient,
        admin_auth: dict[str, str],
        requester_auth: dict[str, str],
    ) -> None:
        """The owner's case: switched off, one withdrawn request, no decision."""
        workflow = _create(client, admin_auth, 'Documents', 'Manager Approval')
        request_id = _raise(client, requester_auth)
        withdrawn = client.post(
            f'{BASE}/requests/{request_id}/cancel', headers=requester_auth
        )
        assert withdrawn.status_code == status.HTTP_200_OK, withdrawn.text
        switched_off = client.patch(
            f'{BASE}/workflows/{workflow["id"]}',
            headers=admin_auth,
            json={'is_active': False},
        )
        assert switched_off.status_code == status.HTTP_200_OK, switched_off.text

        response = client.delete(
            f'{BASE}/workflows/{workflow["id"]}', headers=admin_auth
        )

        assert response.status_code == status.HTTP_200_OK, response.text
        assert response.json() == {'archived': True, 'requests_kept': 1}
        assert workflow['id'] not in _listed_ids(client, admin_auth)
        request = client.get(f'{BASE}/requests/{request_id}', headers=admin_auth)
        assert request.status_code == status.HTTP_200_OK, request.text
        assert request.json()['status'] == 'CANCELLED'


@pytest.mark.integration
class TestTheNextWorkflowIsANewRow:
    def test_the_archived_one_keeps_its_name_and_stages(
        self,
        client: TestClient,
        admin_auth: dict[str, str],
        requester_auth: dict[str, str],
    ) -> None:
        old = _create(client, admin_auth, 'Documents', 'Manager Approval')
        request_id = _raise(client, requester_auth)
        client.post(f'{BASE}/requests/{request_id}/approve', headers=admin_auth)
        client.delete(f'{BASE}/workflows/{old["id"]}', headers=admin_auth)

        new = _create(client, admin_auth, 'Documents, second try', 'Finance Sign-off')

        assert new['id'] != old['id']
        kept = client.get(f'{BASE}/workflows/{old["id"]}', headers=admin_auth).json()
        assert kept['name'] == 'Documents'
        assert [stage['label'] for stage in kept['stages']] == ['Manager Approval']
        assert _listed_ids(client, admin_auth) == [new['id']]

    def test_a_decided_request_still_reads_the_stages_it_was_decided_under(
        self,
        client: TestClient,
        admin_auth: dict[str, str],
        requester_auth: dict[str, str],
    ) -> None:
        old = _create(client, admin_auth, 'Documents', 'Manager Approval')
        request_id = _raise(client, requester_auth)
        client.post(f'{BASE}/requests/{request_id}/approve', headers=admin_auth)
        client.delete(f'{BASE}/workflows/{old["id"]}', headers=admin_auth)
        _create(client, admin_auth, 'Documents, second try', 'Finance Sign-off')

        request = client.get(f'{BASE}/requests/{request_id}', headers=admin_auth)

        assert request.status_code == status.HTTP_200_OK, request.text
        assert request.json()['status'] == 'APPROVED'
        assert request.json()['workflow_id'] == old['id']
        assert [stage['label'] for stage in request.json()['workflow_stages']] == [
            'Manager Approval'
        ]

    def test_a_new_request_lands_on_the_new_workflow(
        self,
        client: TestClient,
        admin_auth: dict[str, str],
        requester_auth: dict[str, str],
    ) -> None:
        old = _create(client, admin_auth, 'Documents', 'Manager Approval')
        request_id = _raise(client, requester_auth)
        client.post(f'{BASE}/requests/{request_id}/approve', headers=admin_auth)
        client.delete(f'{BASE}/workflows/{old["id"]}', headers=admin_auth)
        new = _create(client, admin_auth, 'Documents, second try', 'Finance Sign-off')

        fresh = client.get(
            f'{BASE}/requests/{_raise(client, requester_auth)}', headers=admin_auth
        )

        assert fresh.json()['workflow_id'] == new['id']


@pytest.mark.integration
class TestAnArchivedWorkflowIsFrozen:
    @pytest.fixture
    def archived(
        self,
        client: TestClient,
        admin_auth: dict[str, str],
        requester_auth: dict[str, str],
    ) -> dict[str, Any]:
        workflow = _create(client, admin_auth, 'Documents', 'Manager Approval')
        request_id = _raise(client, requester_auth)
        client.post(f'{BASE}/requests/{request_id}/approve', headers=admin_auth)
        deleted = client.delete(
            f'{BASE}/workflows/{workflow["id"]}', headers=admin_auth
        )
        assert deleted.json()['archived'] is True
        return workflow

    @pytest.mark.parametrize(
        'change',
        [
            {'name': 'Renamed'},
            {'stages': [_stage('Rewritten')]},
            {'is_active': True},
            {
                'is_active': True,
                'expected_scope': {'holds': 'nothing'},
            },
        ],
        ids=['rename', 'restage', 'switch-on', 'switch-on-from-the-dialog'],
    )
    def test_no_edit_or_switch_on_goes_through(
        self,
        client: TestClient,
        admin_auth: dict[str, str],
        archived: dict[str, Any],
        change: dict[str, Any],
    ) -> None:
        response = client.patch(
            f'{BASE}/workflows/{archived["id"]}', headers=admin_auth, json=change
        )

        assert response.status_code == status.HTTP_409_CONFLICT, response.text
        assert _archived_refusal().search(response.json()['detail']['message'])
        kept = client.get(f'{BASE}/workflows/{archived["id"]}', headers=admin_auth)
        assert kept.json()['name'] == 'Documents'
        assert kept.json()['is_active'] is False
        assert kept.json()['stages'][0]['label'] == 'Manager Approval'

    def test_deleting_it_again_is_refused_not_repeated(
        self,
        client: TestClient,
        admin_auth: dict[str, str],
        archived: dict[str, Any],
    ) -> None:
        response = client.delete(
            f'{BASE}/workflows/{archived["id"]}', headers=admin_auth
        )

        assert response.status_code == status.HTTP_409_CONFLICT, response.text
        assert _archived_refusal().search(response.json()['detail']['message'])


@pytest.mark.integration
@pytest.mark.parametrize('save', ['patch', 'post'])
@pytest.mark.parametrize('outcome', ['approve', 'reject', 'cancel'])
def test_editing_stages_keeps_past_requests_and_replaces_the_live_workflow(
    client: TestClient,
    admin_auth: dict[str, str],
    requester_auth: dict[str, str],
    save: str,
    outcome: str,
) -> None:
    old = _create(client, admin_auth, 'Documents', 'Manager Approval')
    request_id = _raise(client, requester_auth)
    decided = client.post(
        f'{BASE}/requests/{request_id}/{outcome}',
        headers=requester_auth if outcome == 'cancel' else admin_auth,
    )
    assert decided.status_code == status.HTTP_200_OK, decided.text
    before = client.get(f'{BASE}/requests/{request_id}', headers=admin_auth).json()
    change = {
        'name': 'Updated documents',
        'stages': [
            {**_stage('Finance Sign-off'), 'role': 'admin'},
            {**_stage('Director'), 'order': 2},
        ],
    }
    if save == 'patch':
        response = client.patch(
            f'{BASE}/workflows/{old["id"]}', headers=admin_auth, json=change
        )
        assert response.status_code == status.HTTP_200_OK, response.text
    else:
        response = client.post(
            f'{BASE}/workflows',
            headers=admin_auth,
            json={
                **change,
                'target_type': 'document',
                'is_active': True,
                'expected_scope': {'holds': 'all'},
                'requester_scope': {'everyone': True},
            },
        )
        assert response.status_code == status.HTTP_201_CREATED, response.text
    new = response.json()
    assert new['id'] != old['id']
    assert new['name'] == 'Updated documents'
    assert new['is_active'] is True
    assert _listed_ids(client, admin_auth) == [new['id']]
    after = client.get(f'{BASE}/requests/{request_id}', headers=admin_auth).json()
    for field in (
        'workflow_id',
        'workflow_stages',
        'decisions',
        'status',
        'total_stages',
    ):
        assert after[field] == before[field]
    listed = client.get(f'{BASE}/requests', headers=admin_auth).json()['items']
    listed_request = next(r for r in listed if r['id'] == request_id)
    assert listed_request['workflow_stages'] == before['workflow_stages']
    archived = client.get(f'{BASE}/workflows/{old["id"]}', headers=admin_auth).json()
    assert archived['archived_at'] is not None
    assert archived['name'] == old['name']
    assert archived['stages'] == old['stages']
    fresh = client.get(
        f'{BASE}/requests/{_raise(client, requester_auth)}', headers=admin_auth
    ).json()
    assert fresh['workflow_id'] == new['id']
    assert fresh['workflow_stages'] == new['stages']
    assert fresh['total_stages'] == 2


@pytest.mark.integration
def test_an_unchanged_stage_definition_does_not_replace_a_used_workflow(
    client: TestClient,
    admin_auth: dict[str, str],
    requester_auth: dict[str, str],
) -> None:
    old = _create(client, admin_auth, 'Documents', 'Manager Approval')
    request_id = _raise(client, requester_auth)
    client.post(f'{BASE}/requests/{request_id}/approve', headers=admin_auth)
    response = client.patch(
        f'{BASE}/workflows/{old["id"]}',
        headers=admin_auth,
        json={'stages': old['stages'], 'name': 'Renamed', 'is_active': False},
    )
    assert response.status_code == status.HTTP_200_OK, response.text
    assert response.json()['id'] == old['id']
    assert response.json()['is_active'] is False
    assert response.json()['archived_at'] is None


@pytest.mark.integration
def test_a_workflow_that_never_ran_can_be_edited_in_place(
    client: TestClient, admin_auth: dict[str, str]
) -> None:
    old = _create(client, admin_auth, 'Documents', 'Manager Approval')
    response = client.patch(
        f'{BASE}/workflows/{old["id"]}',
        headers=admin_auth,
        json={'stages': [_stage('Finance Sign-off')]},
    )
    assert response.status_code == status.HTTP_200_OK, response.text
    assert response.json()['id'] == old['id']
    assert response.json()['stages'][0]['label'] == 'Finance Sign-off'


# ---------------------------------------------------------------------------
# The migration, over rows shaped like the ones production holds
# ---------------------------------------------------------------------------

_APPROVALS_TABLES = {'approval_workflows', 'approval_requests', 'approval_decisions'}


@pytest.fixture
def before_the_archive() -> Iterator[str]:
    """An empty database with the approvals tables as revision 004 left them."""
    import app.core.template_models
    import app.models
    import app.modules.approvals.models  # noqa: F401
    from app.database import Base

    with _isolated_db_url('wa') as url:
        engine = create_engine(url)
        Base.metadata.create_all(
            engine,
            tables=[
                t
                for t in Base.metadata.sorted_tables
                if t.name not in _APPROVALS_TABLES
            ],
        )
        engine.dispose()
        run_module_migrations(
            'approvals',
            'upgrade',
            db_url=url,
            revision='004_timestamps_carry_their_zone',
        )
        yield url


def _seed(url: str) -> dict[str, uuid.UUID]:
    ids = {
        name: uuid.uuid4()
        for name in (
            'home',
            'other',
            'user',
            'deleted',
            'switched_off_waiting',
            'live',
            'never_ran',
            'cancelled',
            'pending',
            'approved',
        )
    }
    stages = json.dumps([_stage('Kierownik')])
    engine = create_engine(url)
    with engine.begin() as conn:
        for org in ('home', 'other'):
            conn.execute(
                text(
                    'INSERT INTO organizations (id, name, enabled_modules, settings, created_at) '
                    'VALUES (:id, :name, \'["core","approvals"]\'::json, \'{}\'::json, now())'
                ),
                {'id': ids[org], 'name': org},
            )
        conn.execute(
            text(
                'INSERT INTO users (id, email, hashed_password, is_active, organization_id, '
                "role, created_at, updated_at) VALUES (:id, 'wa@example.com', 'x', true, "
                ":org, 'admin', now(), now())"
            ),
            {'id': ids['user'], 'org': ids['home']},
        )
        # The production row: deleted while already off, one withdrawn request.
        # Beside it, in the other organization, the rows the backfill must not
        # take: switched off with a request still open, on with history, and
        # off with no history at all.
        for workflow, org, target_type, active in (
            ('deleted', 'home', 'document', False),
            ('switched_off_waiting', 'other', 'document', False),
            ('live', 'other', 'purchase_order', True),
            ('never_ran', 'other', 'checkout', False),
        ):
            conn.execute(
                text(
                    'INSERT INTO approval_workflows (id, organization_id, target_type, name, '
                    'stages, is_active, created_at, updated_at) VALUES (:id, :org, :type, '
                    ':name, CAST(:stages AS json), :active, now(), now())'
                ),
                {
                    'id': ids[workflow],
                    'org': ids[org],
                    'type': target_type,
                    'name': workflow,
                    'stages': stages,
                    'active': active,
                },
            )
        for request, workflow, org, state in (
            ('cancelled', 'deleted', 'home', 'CANCELLED'),
            ('pending', 'switched_off_waiting', 'other', 'PENDING'),
            ('approved', 'live', 'other', 'APPROVED'),
        ):
            conn.execute(
                text(
                    'INSERT INTO approval_requests (id, organization_id, workflow_id, '
                    'target_type, target_id, status, current_stage, total_stages, '
                    'created_by, created_at) VALUES (:id, :org, :wf, '
                    "'document', :target, :state, 1, 1, :user, now())"
                ),
                {
                    'id': ids[request],
                    'org': ids[org],
                    'wf': ids[workflow],
                    'target': uuid.uuid4(),
                    'state': state,
                    'user': ids['user'],
                },
            )
    engine.dispose()
    return ids


@pytest.mark.integration
class TestTheMigration:
    def test_the_deleted_workflow_ends_up_archived_and_its_request_resolves(
        self, before_the_archive: str
    ) -> None:
        ids = _seed(before_the_archive)

        run_module_migrations('approvals', 'upgrade', db_url=before_the_archive)

        engine = create_engine(before_the_archive)
        with engine.connect() as conn:
            archived = {
                row.id: row.archived_at is not None
                for row in conn.execute(
                    text('SELECT id, archived_at FROM approval_workflows')
                )
            }
            resolved = conn.execute(
                text(
                    'SELECT wf.name, wf.stages FROM approval_requests r '
                    'JOIN approval_workflows wf ON wf.id = r.workflow_id '
                    'WHERE r.id = :id'
                ),
                {'id': ids['cancelled']},
            ).one()
        engine.dispose()

        assert archived == {
            ids['deleted']: True,
            ids['switched_off_waiting']: False,
            ids['live']: False,
            ids['never_ran']: False,
        }
        assert resolved.name == 'deleted'
        assert resolved.stages[0]['label'] == 'Kierownik'

    def test_the_slot_is_free_for_a_new_workflow_and_held_among_live_ones(
        self, before_the_archive: str
    ) -> None:
        ids = _seed(before_the_archive)
        run_module_migrations('approvals', 'upgrade', db_url=before_the_archive)

        insert = text(
            'INSERT INTO approval_workflows (id, organization_id, target_type, name, '
            "stages, is_active, created_at) VALUES (:id, :org, 'document', 'next', "
            "'[]'::json, false, now())"
        )
        engine = create_engine(before_the_archive)
        with engine.begin() as conn:
            conn.execute(insert, {'id': uuid.uuid4(), 'org': ids['home']})
        with pytest.raises(IntegrityError), engine.begin() as conn:
            conn.execute(insert, {'id': uuid.uuid4(), 'org': ids['home']})
        engine.dispose()

    def test_a_downgrade_refuses_rather_than_drop_history(
        self, before_the_archive: str
    ) -> None:
        ids = _seed(before_the_archive)
        run_module_migrations('approvals', 'upgrade', db_url=before_the_archive)
        engine = create_engine(before_the_archive)
        with engine.begin() as conn:
            conn.execute(
                text(
                    'INSERT INTO approval_workflows (id, organization_id, target_type, '
                    "name, stages, is_active, created_at) VALUES (:id, :org, 'document', "
                    "'next', '[]'::json, false, now())"
                ),
                {'id': uuid.uuid4(), 'org': ids['home']},
            )
        engine.dispose()

        with pytest.raises(RuntimeError, match='archived workflow beside another'):
            run_module_migrations(
                'approvals',
                'downgrade',
                db_url=before_the_archive,
                revision='004_timestamps_carry_their_zone',
            )

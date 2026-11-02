"""A notice about a request never promises a decision its recipient cannot take.

Measured on production (2026-10-10): a workflow named a person who could not
open the approval queue, and creating the request told them "waiting for your
decision" while the two people who could act — the requester (withdraw) and an
administrator (grant the access) — were told nothing. The stage a request
reaches is the decision door's own rule applied to the people a notice would
ring (``_services_solvability``): an approver the door refuses is not rung, and
a stage nobody can decide rings whoever can end the wait, with the way out in
plain words.
"""

import uuid
from typing import cast

import pytest
from fastapi import status
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.testing import ModuleTestHelper
from app.models.notification import Notification
from app.models.organization import Organization
from app.models.user import User

BASE = '/api/v1/approvals'
QUEUE_LINK = '/approvals?status=PENDING,IN_PROGRESS'
WAITING = 'waiting for your decision'


@pytest.fixture
def h(db_session: Session) -> ModuleTestHelper:
    return ModuleTestHelper(db_session)


@pytest.fixture
def org(h: ModuleTestHelper) -> Organization:
    return h.create_org('Approval Notice Org', ['core', 'approvals'])


@pytest.fixture
def admin(h: ModuleTestHelper, org: Organization) -> User:
    return h.create_user(org, email='boss@example.com', role='admin')


@pytest.fixture
def admin_auth(h: ModuleTestHelper, admin: User) -> dict[str, str]:
    return h.get_auth_headers(admin)


@pytest.fixture
def requester(h: ModuleTestHelper, org: Organization) -> User:
    return h.create_user(org, email='requester@example.com', role='user')


@pytest.fixture
def requester_auth(h: ModuleTestHelper, requester: User) -> dict[str, str]:
    return h.get_auth_headers(requester)


def _notifications(db_session: Session, user: User) -> list[Notification]:
    db_session.expire_all()
    return list(
        db_session.execute(select(Notification).where(Notification.user_id == user.id))
        .scalars()
        .all()
    )


def _named_stage(user: User, label: str = 'Peer review') -> dict[str, object]:
    return {
        'order': 1,
        'role': 'manager',
        'label': label,
        'approver_user_ids': [str(user.id)],
    }


def _create_workflow(
    client: TestClient,
    headers: dict[str, str],
    stages: list[dict[str, object]],
    *,
    allow_undecidable: bool = False,
) -> None:
    payload: dict[str, object] = {
        'target_type': 'document',
        'requester_scope': {'everyone': True},
        'is_active': True,
        'expected_scope': {'holds': 'all'},
        'name': 'Documents',
        'stages': stages,
    }
    if allow_undecidable:
        payload['allow_undecidable_stages'] = True
    resp = client.post(f'{BASE}/workflows', headers=headers, json=payload)
    assert resp.status_code == status.HTTP_201_CREATED, resp.text


def _raise_request(
    client: TestClient, requester_auth: dict[str, str]
) -> dict[str, object]:
    resp = client.post(
        f'{BASE}/requests',
        headers=requester_auth,
        json={'target_type': 'document', 'target_id': str(uuid.uuid4())},
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    return cast('dict[str, object]', resp.json())


@pytest.mark.integration
class TestANamedApproverWithoutAccess:
    """The stage names somebody the door refuses; they are not told it is theirs."""

    def test_the_blind_approver_is_not_told_and_the_others_are(
        self,
        client: TestClient,
        db_session: Session,
        h: ModuleTestHelper,
        org: Organization,
        admin: User,
        admin_auth: dict[str, str],
        requester: User,
        requester_auth: dict[str, str],
    ) -> None:
        blind = h.create_user(org, email='blind@example.com', role='user')
        # Can raise a request, cannot reach the decision door (no read/approve).
        h.grant_permissions(blind, ['approvals:write'])
        _create_workflow(
            client,
            admin_auth,
            [_named_stage(blind)],
            allow_undecidable=True,
        )

        _raise_request(client, requester_auth)

        assert all(
            WAITING not in n.content.lower() for n in _notifications(db_session, blind)
        )

        for who in (requester, admin):
            notices = _notifications(db_session, who)
            assert len(notices) == 1, (who.email, [n.content for n in notices])
            assert 'Peer review' in notices[0].content
            assert 'withdraw' in notices[0].content.lower()
            assert notices[0].link == QUEUE_LINK

    def test_a_custom_administration_role_hears_the_way_out(
        self,
        client: TestClient,
        db_session: Session,
        h: ModuleTestHelper,
        org: Organization,
        admin_auth: dict[str, str],
        requester_auth: dict[str, str],
    ) -> None:
        # The way out is granting the access, and a custom role carrying the
        # administration keys may do that. The notice went by the role's
        # name, so such a role was never told the request was stranded.
        blind = h.create_user(org, email='blind@example.com', role='user')
        h.grant_permissions(blind, ['approvals:write'])
        steward = h.create_user(org, email='steward@example.com', role='manager')
        h.grant_permissions(steward, ['system:config:write'])
        delegate = h.create_user(org, email='delegate@example.com', role='user')
        h.grant_permissions(delegate, ['admin:access'])
        _create_workflow(
            client,
            admin_auth,
            [_named_stage(blind)],
            allow_undecidable=True,
        )

        _raise_request(client, requester_auth)

        for who in (steward, delegate):
            notices = _notifications(db_session, who)
            assert len(notices) == 1, (who.email, [n.content for n in notices])
            assert 'withdraw' in notices[0].content.lower()
        assert _notifications(db_session, blind) == []


@pytest.mark.integration
class TestADecidableStageStillNotifies:
    """The ordinary case is unchanged: whoever can decide is told it is their turn."""

    def test_its_deciders_are_told_and_nobody_else_hears(
        self,
        client: TestClient,
        db_session: Session,
        h: ModuleTestHelper,
        org: Organization,
        admin: User,
        admin_auth: dict[str, str],
        requester: User,
        requester_auth: dict[str, str],
    ) -> None:
        approver = h.create_user(org, email='approver@example.com', role='manager')
        h.grant_permissions(approver, ['approvals:read', 'approvals:approve'])
        _create_workflow(client, admin_auth, [_named_stage(approver)])

        _raise_request(client, requester_auth)

        waiting = _notifications(db_session, approver)
        assert len(waiting) == 1
        assert WAITING in waiting[0].content.lower()
        assert waiting[0].link == QUEUE_LINK
        assert waiting[0].is_read is False

        assert _notifications(db_session, requester) == []
        assert _notifications(db_session, admin) == []


@pytest.mark.integration
class TestAnOpenStageRingsWhoeverHoldsTheApproveGrant:
    """An open stage is decided by the holders of the approve grant, and they are told.

    The open-stage notice used to ring members by role name — admins and
    managers — while the door decides by the grant. A custom role carrying the
    grant never heard, and a manager whose role stops short of it was told a
    decision was theirs that the door then refused.
    """

    def test_the_grant_holders_are_told_and_the_role_name_counts_for_nothing(
        self,
        client: TestClient,
        db_session: Session,
        h: ModuleTestHelper,
        org: Organization,
        admin: User,
        admin_auth: dict[str, str],
        requester: User,
        requester_auth: dict[str, str],
    ) -> None:
        h.grant_permissions(requester, ['approvals:write', 'approvals:read'])
        clerk = h.create_user(org, email='clerk@example.com', role='user')
        h.grant_permissions(clerk, ['approvals:read', 'approvals:approve'])
        manager = h.create_user(org, email='manager@example.com', role='manager')
        h.grant_permissions(manager, ['approvals:read'])
        _create_workflow(
            client,
            admin_auth,
            [{'order': 1, 'label': 'Sign-off', 'approver_user_ids': []}],
        )

        _raise_request(client, requester_auth)

        for who in (clerk, admin):
            notices = _notifications(db_session, who)
            assert len(notices) == 1, (who.email, [n.content for n in notices])
            assert WAITING in notices[0].content.lower()
        assert _notifications(db_session, manager) == []
        assert _notifications(db_session, requester) == []

    def test_a_deactivated_holder_is_not_told(
        self,
        client: TestClient,
        db_session: Session,
        h: ModuleTestHelper,
        org: Organization,
        admin: User,
        admin_auth: dict[str, str],
        requester: User,
        requester_auth: dict[str, str],
    ) -> None:
        # An account switched off cannot sign in, so it cannot decide either.
        h.grant_permissions(requester, ['approvals:write', 'approvals:read'])
        former = h.create_user(org, email='former@example.com', role='admin')
        former.is_active = False
        db_session.commit()
        _create_workflow(
            client,
            admin_auth,
            [{'order': 1, 'label': 'Sign-off', 'approver_user_ids': []}],
        )

        _raise_request(client, requester_auth)

        assert _notifications(db_session, former) == []
        assert len(_notifications(db_session, admin)) == 1

    def test_the_requester_holding_the_grant_is_not_told_about_their_own_request(
        self,
        client: TestClient,
        db_session: Session,
        h: ModuleTestHelper,
        org: Organization,
        admin: User,
        admin_auth: dict[str, str],
        requester: User,
        requester_auth: dict[str, str],
    ) -> None:
        h.grant_permissions(
            requester, ['approvals:write', 'approvals:read', 'approvals:approve']
        )
        _create_workflow(
            client,
            admin_auth,
            [{'order': 1, 'label': 'Sign-off', 'approver_user_ids': []}],
        )

        _raise_request(client, requester_auth)

        assert _notifications(db_session, requester) == []
        notices = _notifications(db_session, admin)
        assert len(notices) == 1
        assert WAITING in notices[0].content.lower()


@pytest.mark.integration
class TestADeactivatedNamedApprover:
    """A stage naming somebody whose account was switched off is a dead end."""

    def test_they_are_not_told_and_the_wait_is_reported(
        self,
        client: TestClient,
        db_session: Session,
        h: ModuleTestHelper,
        org: Organization,
        admin: User,
        admin_auth: dict[str, str],
        requester: User,
        requester_auth: dict[str, str],
    ) -> None:
        approver = h.create_user(org, email='leaver@example.com', role='manager')
        h.grant_permissions(approver, ['approvals:read', 'approvals:approve'])
        _create_workflow(client, admin_auth, [_named_stage(approver)])
        approver.is_active = False
        db_session.commit()

        _raise_request(client, requester_auth)

        assert _notifications(db_session, approver) == []
        for who in (requester, admin):
            notices = _notifications(db_session, who)
            assert len(notices) == 1, (who.email, [n.content for n in notices])
            assert 'withdraw' in notices[0].content.lower()

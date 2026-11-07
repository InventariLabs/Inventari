"""A request raised over HTTP has to point at something that is there.

``POST /approvals/requests`` takes the target id from the client. A mistyped
id used to answer 201 and store a pending request that no queue lists: every
queue reaches a request through the record it is about, and there was none, so
nobody could see the request and nobody could decide it. The module that owns
the target type already describes its targets for the queue; the same provider
now says whether the target exists before the request is stored.
"""

import uuid
from decimal import Decimal
from typing import Any

import pytest
from fastapi import status
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.user import User
from app.modules.approvals.models import ApprovalRequest
from app.modules.warehouse.models.document import Document

pytestmark = pytest.mark.integration

BASE = '/api/v1/approvals'


@pytest.fixture(autouse=True)
def any_target_may_be_requested() -> None:
    """Here the route's own check runs, over real and missing documents."""


@pytest.fixture
def writer(h: ModuleTestHelper, approval_org: Organization) -> User:
    user = h.create_user(approval_org, email='writer@example.com', role='manager')
    h.grant_permissions(user, ['approvals:read', 'approvals:write'])
    return user


@pytest.fixture
def writer_auth(h: ModuleTestHelper, writer: User) -> dict[str, str]:
    return h.get_auth_headers(writer)


@pytest.fixture
def workflow(
    client: TestClient,
    approval_auth: dict[str, str],
    h: ModuleTestHelper,
    approver: User,
    single_stage_workflow_payload: dict[str, Any],
) -> None:
    h.grant_permissions(
        approver,
        [
            'approvals:read',
            'approvals:write',
            'approvals:approve',
            'approvals:configure',
        ],
    )
    created = client.post(
        f'{BASE}/workflows', headers=approval_auth, json=single_stage_workflow_payload
    )
    assert created.status_code == status.HTTP_201_CREATED, created.text


def _requests_for(db_session: Session, target_id: str) -> int:
    db_session.expire_all()
    return (
        db_session.scalar(
            select(func.count())
            .select_from(ApprovalRequest)
            .where(ApprovalRequest.target_id == uuid.UUID(target_id))
        )
        or 0
    )


class TestARequestNamesATargetThatExists:
    def test_an_id_that_names_no_document_is_refused_and_stores_nothing(
        self,
        client: TestClient,
        db_session: Session,
        writer_auth: dict[str, str],
        workflow: None,
    ) -> None:
        typo = str(uuid.uuid4())

        response = client.post(
            f'{BASE}/requests',
            headers=writer_auth,
            json={'target_type': 'document', 'target_id': typo},
        )

        assert response.status_code == status.HTTP_409_CONFLICT, response.text
        assert response.json()['detail']['code'] == 'APPROVAL_TARGET_NOT_FOUND'
        assert _requests_for(db_session, typo) == 0

    def test_a_document_of_another_organization_counts_as_missing(
        self,
        client: TestClient,
        db_session: Session,
        h: ModuleTestHelper,
        writer: User,
        writer_auth: dict[str, str],
        workflow: None,
    ) -> None:
        other_org = h.create_org('Somebody Else', ['core', 'approvals'])
        other_user = h.create_user(other_org, email='other@example.com', role='admin')
        foreign = Document(
            organization_id=other_org.id,
            type='IN',
            number='FOREIGN/1',
            status='DRAFT',
            created_by=other_user.id,
            total_net=Decimal('1'),
            currency='PLN',
        )
        db_session.add(foreign)
        db_session.flush()

        response = client.post(
            f'{BASE}/requests',
            headers=writer_auth,
            json={'target_type': 'document', 'target_id': str(foreign.id)},
        )

        assert response.status_code == status.HTTP_409_CONFLICT, response.text
        assert _requests_for(db_session, str(foreign.id)) == 0

    def test_an_existing_document_is_still_accepted(
        self,
        client: TestClient,
        db_session: Session,
        approval_org: Organization,
        writer: User,
        writer_auth: dict[str, str],
        workflow: None,
    ) -> None:
        document = Document(
            organization_id=approval_org.id,
            type='IN',
            number='IN/1',
            status='CONFIRMED',
            created_by=writer.id,
            total_net=Decimal('1'),
            currency='PLN',
        )
        db_session.add(document)
        db_session.flush()

        response = client.post(
            f'{BASE}/requests',
            headers=writer_auth,
            json={'target_type': 'document', 'target_id': str(document.id)},
        )

        assert response.status_code == status.HTTP_201_CREATED, response.text
        assert _requests_for(db_session, str(document.id)) == 1

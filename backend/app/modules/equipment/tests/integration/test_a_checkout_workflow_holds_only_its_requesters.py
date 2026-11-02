"""A checkout workflow holds the checkouts of the people it names.

Equipment has no settings that filter checkouts, so an active workflow held
every checkout by anyone. The workflow now says whose checkouts it holds;
anybody else issues an asset without a request, and the asset card does not
offer them one.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from fastapi import status
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.testing import ModuleTestHelper
from app.models.user import User
from app.modules.equipment.tests.integration.test_an_approval_covers_one_checkout import (
    _make_item,
)


def _workflow_for(
    client: TestClient, h: ModuleTestHelper, admin: User, held: User
) -> None:
    resp = client.post(
        '/api/v1/approvals/workflows',
        headers=h.get_auth_headers(admin),
        json={
            'target_type': 'equipment_checkout',
            'name': 'Checkouts by the trainee',
            'requester_scope': {
                'everyone': False,
                'user_ids': [str(held.id)],
                'role_ids': [],
            },
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
        },
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text


@pytest.mark.integration
class TestACheckoutWorkflowHoldsOnlyItsRequesters:
    def test_the_named_person_waits_and_everybody_else_issues(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        db_session: Session,
    ) -> None:
        org = h.create_org(
            'Checkout Requesters Org',
            ['core', 'items', 'locations', 'categories', 'equipment', 'approvals'],
        )
        admin = h.create_user(org, email=f'adm_{uuid4().hex[:6]}@test.com')
        trainee = h.create_user(org, email=f'trainee_{uuid4().hex[:6]}@test.com')
        laptop = _make_item(h, org, admin, db_session)
        tablet = _make_item(h, org, admin, db_session)
        _workflow_for(client, h, admin, trainee)

        issued = client.post(
            '/api/v1/equipment/assignments',
            headers=h.get_auth_headers(admin),
            json={'item_id': str(laptop.id), 'assigned_to_name': 'Carol'},
        )
        held = client.post(
            '/api/v1/equipment/assignments',
            headers=h.get_auth_headers(trainee),
            json={'item_id': str(tablet.id), 'assigned_to_name': 'Dave'},
        )

        assert issued.status_code == status.HTTP_201_CREATED, issued.text
        assert held.status_code == status.HTTP_409_CONFLICT, held.text
        assert 'approval' in held.text.lower()

    def test_the_asset_card_offers_a_request_only_to_the_named_person(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        db_session: Session,
    ) -> None:
        org = h.create_org(
            'Checkout Card Org',
            ['core', 'items', 'locations', 'categories', 'equipment', 'approvals'],
        )
        admin = h.create_user(org, email=f'adm_{uuid4().hex[:6]}@test.com')
        trainee = h.create_user(org, email=f'trainee_{uuid4().hex[:6]}@test.com')
        laptop = _make_item(h, org, admin, db_session)
        _workflow_for(client, h, admin, trainee)

        def status_for(user: User) -> dict[str, Any]:
            resp = client.get(
                f'/api/v1/equipment/{laptop.id}/approval-status',
                headers=h.get_auth_headers(user),
            )
            assert resp.status_code == status.HTTP_200_OK, resp.text
            body: dict[str, Any] = resp.json()
            return body

        assert status_for(trainee)['has_workflow'] is True
        assert status_for(admin)['has_workflow'] is False

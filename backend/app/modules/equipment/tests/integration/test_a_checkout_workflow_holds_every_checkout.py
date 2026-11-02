"""The workflow list says a checkout workflow holds every checkout.

Equipment has no settings that filter checkouts: the assignment gate asks
approvals whenever a checkout workflow is active, so the switch-on dialog has
to say "every checkout of every asset" — and that sentence is equipment's to
give, not the engine's.
"""

from typing import Any
from uuid import uuid4

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.core.testing import ModuleTestHelper


@pytest.mark.integration
def test_the_listed_scope_of_a_checkout_workflow_is_every_checkout(
    client: TestClient, h: ModuleTestHelper
) -> None:
    org = h.create_org(
        'Checkout Scope Org',
        ['core', 'items', 'locations', 'categories', 'equipment', 'approvals'],
    )
    admin = h.create_user(org, email=f'adm_{uuid4().hex[:6]}@test.com', role='admin')
    headers = h.get_auth_headers(admin)

    created = client.post(
        '/api/v1/approvals/workflows',
        headers=headers,
        json={
            'target_type': 'equipment_checkout',
            'requester_scope': {'everyone': True},
            'name': 'Checkout sign-off',
            'stages': [
                {
                    'order': 1,
                    'role': 'manager',
                    'label': 'Manager Approval',
                    'approver_user_ids': [],
                }
            ],
        },
    )
    assert created.status_code == status.HTTP_201_CREATED, created.text

    listed = client.get('/api/v1/approvals/workflows', headers=headers)
    assert listed.status_code == status.HTTP_200_OK, listed.text
    row: dict[str, Any] = next(
        r for r in listed.json()['items'] if r['id'] == created.json()['id']
    )
    assert row['scope'] == {
        'holds': 'all',
        'conditions': [],
        'required_by_settings': [],
    }

"""Whether a purchase order needs approval is ``purchase_orders:manage``'s call.

``PUT /purchase-orders/settings`` decides whether an order needs anyone's
approval and above which total. It answered only to the module router's
``purchase_orders:write`` — the right every member holds — so a buyer could
lower or clear the control that is meant to stop their own orders. The switch
now answers to ``purchase_orders:manage``, the module's key "a step above
writing" that cancelling an order already asks for (manager by default,
administrators always). Reading the settings stays with ``:read``: the confirm
dialog of anyone who works with orders shows the threshold.
"""

import pytest
from fastapi import status
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.testing import ModuleTestHelper
from app.models.audit_log import AuditLog
from app.models.organization import Organization

SETTINGS = '/api/v1/purchase-orders/settings'


def _config_entries(db: Session, org: Organization) -> list[AuditLog]:
    rows = (
        db.query(AuditLog)
        .filter(
            AuditLog.organization_id == org.id,
            AuditLog.target_type == 'module',
        )
        .all()
    )
    return [r for r in rows if (r.snapshot or {}).get('name') == 'purchase_orders']


def _headers(h: ModuleTestHelper, org: Organization, role: str) -> dict[str, str]:
    return h.get_auth_headers(
        h.create_user(org, email=f'po-switch-{role}@example.com', role=role)
    )


@pytest.mark.integration
class TestTheApprovalSwitchAnswersToManage:
    @pytest.mark.parametrize('role', ['user', 'viewer'])
    def test_a_member_or_viewer_is_refused_and_nothing_changes(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        po_org: Organization,
        po_auth_headers: dict[str, str],
        role: str,
    ) -> None:
        set_by_admin = client.put(
            SETTINGS, headers=po_auth_headers, json={'approval_threshold': '5000'}
        )
        assert set_by_admin.status_code == status.HTTP_200_OK, set_by_admin.text
        journal_before = len(_config_entries(h.db, po_org))

        resp = client.put(
            SETTINGS,
            headers=_headers(h, po_org, role),
            json={'approval_threshold': '1234', 'approval_required': False},
        )

        assert resp.status_code == status.HTTP_403_FORBIDDEN, resp.text
        detail = resp.json()['detail']
        assert detail['code'] == 'FORBIDDEN'
        assert detail['message'], 'the refusal must carry a readable sentence'
        after = client.get(SETTINGS, headers=po_auth_headers).json()
        assert after['approval_threshold'] == '5000.00'
        # A refused write is not a configuration change: the journal keeps
        # only the administrator's entry.
        assert len(_config_entries(h.db, po_org)) == journal_before

    def test_write_without_manage_is_refused(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        po_org: Organization,
    ) -> None:
        """read+write pass the router's gate, so the 403 is the endpoint's."""
        user = h.create_user(po_org, email='po-switch-writer@example.com', role='user')
        h.grant_permissions(user, ['purchase_orders:read', 'purchase_orders:write'])

        resp = client.put(
            SETTINGS,
            headers=h.get_auth_headers(user),
            json={'approval_required': True},
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN, resp.text

    def test_a_custom_role_holding_manage_may_change_it(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        po_org: Organization,
    ) -> None:
        """The guard is the key, not a role name."""
        user = h.create_user(po_org, email='po-switch-mgr@example.com', role='user')
        h.grant_permissions(
            user,
            [
                'purchase_orders:read',
                'purchase_orders:write',
                'purchase_orders:manage',
            ],
        )

        resp = client.put(
            SETTINGS,
            headers=h.get_auth_headers(user),
            json={'approval_required': True},
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        assert resp.json()['approval_required'] is True

    def test_a_manager_may_change_it(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        po_org: Organization,
    ) -> None:
        resp = client.put(
            SETTINGS,
            headers=_headers(h, po_org, 'manager'),
            json={'approval_threshold': '750'},
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text

    @pytest.mark.parametrize('role', ['user', 'viewer'])
    def test_anyone_who_works_with_orders_still_reads_the_threshold(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        po_org: Organization,
        role: str,
    ) -> None:
        resp = client.get(SETTINGS, headers=_headers(h, po_org, role))
        assert resp.status_code == status.HTTP_200_OK, resp.text
        assert 'approval_threshold' in resp.json()

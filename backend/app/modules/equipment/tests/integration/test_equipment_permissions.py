"""Integration tests for equipment module RBAC enforcement.

Covers the regression guard that all mutating equipment endpoints require the
appropriate permission: a read-only user must get HTTP 403 on POST/PUT/DELETE,
a write user passes the RBAC gate, and an admin bypasses all checks. bulk-purge
requires items:purge, the same threshold as the core purge endpoint.

Every role here carries the equipment keys as well as the core item ones. The
module router gained require_read_write('equipment:read', 'equipment:write'),
so a role that names only the core keys is now stopped at the module boundary
before any endpoint's own check runs — which is the point of the module gate,
and would make these cases assert nothing about the endpoint.

Uses ModuleTestHelper so the test org has the equipment module enabled (the
router is gated by require_module('equipment')).
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.contracts import SystemPermission
from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.role import Role, UserRole
from app.models.user import User

_EQUIP_MODULES = ['core', 'items', 'locations', 'categories', 'equipment']


def _make_role_with(db: Session, org: Organization, perms: list[str]) -> Role:
    """A role belongs to an organisation — the column requires one."""
    role = Role(
        name=f'role_{uuid.uuid4().hex[:6]}',
        permissions=perms,
        is_system=False,
        organization_id=org.id,
    )
    db.add(role)
    db.flush()
    return role


def _assign(db: Session, user: User, role: Role) -> None:
    db.add(UserRole(user_id=user.id, role_id=role.id))
    db.commit()


def _read_only_user(h: ModuleTestHelper, org: Organization) -> User:
    """A user who may look at equipment and nothing else."""
    user = h.create_user(org, email=f'ro_{uuid.uuid4().hex[:6]}@test.com', role='user')
    _assign(
        h.db,
        user,
        _make_role_with(
            h.db, org, [SystemPermission.ITEMS_READ.value, 'equipment:read']
        ),
    )
    return user


def _write_user(h: ModuleTestHelper, org: Organization) -> User:
    """A user holding ITEMS_READ + ITEMS_WRITE — can mutate but not delete models."""
    user = h.create_user(org, email=f'rw_{uuid.uuid4().hex[:6]}@test.com', role='user')
    _assign(
        h.db,
        user,
        _make_role_with(
            h.db,
            org,
            [
                SystemPermission.ITEMS_READ.value,
                SystemPermission.ITEMS_WRITE.value,
                'equipment:read',
                'equipment:write',
            ],
        ),
    )
    return user


@pytest.mark.integration
class TestEquipmentWritePermissionEnforcement:
    """Mutating equipment endpoints must require ITEMS_WRITE."""

    def test_read_only_user_cannot_create_maintenance_log(
        self, client: TestClient, h: ModuleTestHelper
    ) -> None:
        org = h.create_org('Equip RO Org', _EQUIP_MODULES)
        viewer = _read_only_user(h, org)

        resp = client.post(
            '/api/v1/equipment/maintenance',
            headers=h.get_auth_headers(viewer),
            json={'item_id': str(uuid.uuid4()), 'action': 'INSPECTION'},
        )
        assert resp.status_code == 403

    def test_write_user_passes_permission_gate_on_maintenance(
        self, client: TestClient, h: ModuleTestHelper
    ) -> None:
        """A write user must pass the permission gate (status != 403)."""
        org = h.create_org('Equip RW Org', _EQUIP_MODULES)
        writer = _write_user(h, org)

        resp = client.post(
            '/api/v1/equipment/maintenance',
            headers=h.get_auth_headers(writer),
            json={'item_id': str(uuid.uuid4()), 'action': 'INSPECTION'},
        )
        # Not 403 — the permission gate passed. (404/422 expected from the
        # nonexistent item_id, which is fine — we only assert the RBAC gate.)
        assert resp.status_code != 403

    def test_read_only_user_cannot_checkout_asset(
        self, client: TestClient, h: ModuleTestHelper
    ) -> None:
        org = h.create_org('Equip Assign Org', _EQUIP_MODULES)
        viewer = _read_only_user(h, org)

        resp = client.post(
            '/api/v1/equipment/assignments',
            headers=h.get_auth_headers(viewer),
            json={'item_id': str(uuid.uuid4()), 'assigned_to': str(uuid.uuid4())},
        )
        assert resp.status_code == 403

    def test_read_only_user_cannot_create_model(
        self, client: TestClient, h: ModuleTestHelper
    ) -> None:
        org = h.create_org('Equip Model Org', _EQUIP_MODULES)
        viewer = _read_only_user(h, org)

        resp = client.post(
            '/api/v1/equipment/models',
            headers=h.get_auth_headers(viewer),
            json={'name': 'Test Model'},
        )
        assert resp.status_code == 403

    def test_read_only_user_cannot_create_template(
        self, client: TestClient, h: ModuleTestHelper
    ) -> None:
        org = h.create_org('Equip Tpl Org', _EQUIP_MODULES)
        viewer = _read_only_user(h, org)

        resp = client.post(
            '/api/v1/equipment/templates',
            headers=h.get_auth_headers(viewer),
            json={'name': 'T', 'document_type': 'CHECKOUT', 'body_html': '<p></p>'},
        )
        assert resp.status_code == 403

    def test_read_only_user_cannot_bulk_create(
        self, client: TestClient, h: ModuleTestHelper
    ) -> None:
        org = h.create_org('Equip Bulk Org', _EQUIP_MODULES)
        viewer = _read_only_user(h, org)

        resp = client.post(
            '/api/v1/equipment/items/bulk',
            headers=h.get_auth_headers(viewer),
            json={'items': []},
        )
        assert resp.status_code == 403

    # --- Attachment upload/delete + campaign create/launch/remind/complete ---

    def test_read_only_user_cannot_upload_attachment(
        self, client: TestClient, h: ModuleTestHelper
    ) -> None:
        org = h.create_org('Equip Attach Upload Org', _EQUIP_MODULES)
        viewer = _read_only_user(h, org)

        resp = client.post(
            f'/api/v1/equipment/{uuid.uuid4()}/attachments',
            headers=h.get_auth_headers(viewer),
            files={'file': ('hello.txt', b'hello world', 'text/plain')},
        )
        assert resp.status_code == 403

    def test_read_only_user_cannot_delete_attachment(
        self, client: TestClient, h: ModuleTestHelper
    ) -> None:
        org = h.create_org('Equip Attach Del Org', _EQUIP_MODULES)
        viewer = _read_only_user(h, org)

        resp = client.delete(
            f'/api/v1/equipment/{uuid.uuid4()}/attachments/{uuid.uuid4()}',
            headers=h.get_auth_headers(viewer),
        )
        assert resp.status_code == 403

    def test_read_only_user_cannot_create_campaign(
        self, client: TestClient, h: ModuleTestHelper
    ) -> None:
        org = h.create_org('Equip Camp Create Org', _EQUIP_MODULES)
        viewer = _read_only_user(h, org)

        from datetime import UTC, datetime, timedelta

        resp = client.post(
            '/api/v1/equipment/campaigns',
            headers=h.get_auth_headers(viewer),
            json={
                'name': 'Q1 Review',
                'scope_type': 'ALL',
                'deadline': (datetime.now(UTC) + timedelta(days=14)).isoformat(),
                'reminder_days_before': 3,
            },
        )
        assert resp.status_code == 403

    def test_read_only_user_cannot_launch_campaign(
        self, client: TestClient, h: ModuleTestHelper
    ) -> None:
        org = h.create_org('Equip Camp Launch Org', _EQUIP_MODULES)
        viewer = _read_only_user(h, org)

        resp = client.post(
            f'/api/v1/equipment/campaigns/{uuid.uuid4()}/launch',
            headers=h.get_auth_headers(viewer),
        )
        assert resp.status_code == 403

    def test_read_only_user_cannot_remind_campaign(
        self, client: TestClient, h: ModuleTestHelper
    ) -> None:
        org = h.create_org('Equip Camp Remind Org', _EQUIP_MODULES)
        viewer = _read_only_user(h, org)

        resp = client.post(
            f'/api/v1/equipment/campaigns/{uuid.uuid4()}/remind',
            headers=h.get_auth_headers(viewer),
        )
        assert resp.status_code == 403

    def test_read_only_user_cannot_take_an_attestation_link(
        self, client: TestClient, h: ModuleTestHelper
    ) -> None:
        """The link answers on the holder's behalf; reading the campaign
        does not entitle anybody to it."""
        org = h.create_org('Equip Camp Link Org', _EQUIP_MODULES)
        viewer = _read_only_user(h, org)

        resp = client.get(
            f'/api/v1/equipment/campaigns/{uuid.uuid4()}/responses/{uuid.uuid4()}/link',
            headers=h.get_auth_headers(viewer),
        )
        assert resp.status_code == 403

    def test_read_only_user_cannot_complete_campaign(
        self, client: TestClient, h: ModuleTestHelper
    ) -> None:
        org = h.create_org('Equip Camp Complete Org', _EQUIP_MODULES)
        viewer = _read_only_user(h, org)

        resp = client.post(
            f'/api/v1/equipment/campaigns/{uuid.uuid4()}/complete',
            headers=h.get_auth_headers(viewer),
        )
        assert resp.status_code == 403

    def test_write_user_passes_gate_on_attachment_upload(
        self, client: TestClient, h: ModuleTestHelper
    ) -> None:
        """A write user passes the RBAC gate (status != 403)."""
        org = h.create_org('Equip Attach RW Org', _EQUIP_MODULES)
        writer = _write_user(h, org)

        resp = client.post(
            f'/api/v1/equipment/{uuid.uuid4()}/attachments',
            headers=h.get_auth_headers(writer),
            files={'file': ('hello.txt', b'hello world', 'text/plain')},
        )
        # Gate passes — expect 400/404 from the nonexistent item, NOT 403.
        assert resp.status_code != 403

    def test_write_user_passes_gate_on_campaign_create(
        self, client: TestClient, h: ModuleTestHelper
    ) -> None:
        """A write user passes the RBAC gate (status != 403)."""
        org = h.create_org('Equip Camp RW Org', _EQUIP_MODULES)
        writer = _write_user(h, org)

        from datetime import UTC, datetime, timedelta

        resp = client.post(
            '/api/v1/equipment/campaigns',
            headers=h.get_auth_headers(writer),
            json={
                'name': 'Q1 Review',
                'scope_type': 'ALL',
                'deadline': (datetime.now(UTC) + timedelta(days=14)).isoformat(),
                'reminder_days_before': 3,
            },
        )
        # Gate passes — expect a service success/error response, NOT 403.
        assert resp.status_code != 403


@pytest.mark.integration
class TestEquipmentDeletePermissionEnforcement:
    """DELETE on equipment models must require ITEMS_DELETE."""

    def test_write_only_user_cannot_delete_model(
        self, client: TestClient, h: ModuleTestHelper
    ) -> None:
        """A user with ITEMS_WRITE but not ITEMS_DELETE must be denied delete."""
        org = h.create_org('Equip Del Org', _EQUIP_MODULES)
        writer = _write_user(h, org)

        resp = client.delete(
            f'/api/v1/equipment/models/{uuid.uuid4()}',
            headers=h.get_auth_headers(writer),
        )
        assert resp.status_code == 403


@pytest.mark.integration
class TestEquipmentBulkPurgePermission:
    """bulk-purge requires items:purge — one threshold with the core purge.

    The old gate (admin-only + items:write) was both stricter than the core
    endpoint and a different threshold for the same operation. Now the purge
    permission alone decides, exactly like DELETE /items/{id}/purge.
    """

    def test_user_without_purge_permission_cannot_bulk_purge(
        self, client: TestClient, h: ModuleTestHelper
    ) -> None:
        org = h.create_org('Equip Purge Org', _EQUIP_MODULES)
        writer = _write_user(h, org)

        resp = client.post(
            '/api/v1/equipment/items/bulk-purge',
            headers=h.get_auth_headers(writer),
            json=[str(uuid.uuid4())],
        )
        assert resp.status_code == 403

    def test_user_with_purge_permission_passes_bulk_purge_gate(
        self, client: TestClient, h: ModuleTestHelper
    ) -> None:
        """A non-admin role holding items:purge passes the gate."""
        org = h.create_org('Equip Purge Perm Org', _EQUIP_MODULES)
        purger = h.create_user(
            org, email=f'purg_{uuid.uuid4().hex[:6]}@test.com', role='user'
        )
        _assign(
            h.db,
            purger,
            _make_role_with(
                h.db,
                org,
                [
                    SystemPermission.ITEMS_PURGE.value,
                    'equipment:read',
                    'equipment:write',
                ],
            ),
        )

        resp = client.post(
            '/api/v1/equipment/items/bulk-purge',
            headers=h.get_auth_headers(purger),
            json=[str(uuid.uuid4())],
        )
        # Gate passed — a normal 200 result (empty purge ok), NOT 403.
        assert resp.status_code != 403

    def test_admin_passes_bulk_purge_gate(
        self, client: TestClient, h: ModuleTestHelper
    ) -> None:
        org = h.create_org('Equip Admin Purge Org', _EQUIP_MODULES)
        admin = h.create_user(
            org, email=f'adm_{uuid.uuid4().hex[:6]}@test.com', role='admin'
        )

        resp = client.post(
            '/api/v1/equipment/items/bulk-purge',
            headers=h.get_auth_headers(admin),
            json=[str(uuid.uuid4())],
        )
        # Admin passes the gate — expect a normal 200 result (empty purge ok),
        # NOT 403.
        assert resp.status_code != 403

"""Permission enforcement on the warehouse module endpoints.

The manifest declared ``warehouse:read`` / ``warehouse:write`` long before any
endpoint checked them: every member of an organization could move stock. The
guard is mounted once on the module router — safe methods need ``read``,
mutating ones need ``write`` — so these tests pin the boundary rather than the
individual endpoints.

Legacy installs keep working because the manifest hands the permissions to the
roles that already had the access (``manager``/``user`` write, ``viewer`` read)
and the user context falls back to those defaults when a member carries no
explicit role row.
"""

import pytest
from fastapi import status
from starlette.testclient import TestClient

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.storage_location import StorageLocation
from app.models.user import User

BASE = '/api/v1/warehouse/documents'
MODULE = '/api/v1/warehouse'


def _create_payload(target_location: StorageLocation) -> dict[str, object]:
    return {
        'type': 'IN',
        'target_location_id': str(target_location.id),
        'lines': [{'name': 'Widget', 'expected_quantity': 1}],
    }


@pytest.fixture
def operator(h: ModuleTestHelper, doc_org: Organization) -> User:
    """A plain member with no explicit role row — the legacy install shape."""
    return h.create_user(doc_org, email='operator@example.com', role='user')


@pytest.fixture
def viewer(h: ModuleTestHelper, doc_org: Organization) -> User:
    return h.create_user(doc_org, email='viewer@example.com', role='viewer')


@pytest.fixture
def read_only(h: ModuleTestHelper, doc_org: Organization) -> User:
    """An explicit role row that grants reading and nothing else."""
    user = h.create_user(doc_org, email='readonly@example.com', role='user')
    h.grant_permissions(user, ['warehouse:read'])
    return user


@pytest.mark.integration
class TestDocumentsPermissions:
    def test_operator_without_role_row_keeps_write_access(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        operator: User,
        doc_target_location: StorageLocation,
    ) -> None:
        resp = client.post(
            BASE,
            headers=h.get_auth_headers(operator),
            json=_create_payload(doc_target_location),
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text

    def test_viewer_reads_but_cannot_write(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        viewer: User,
        doc_target_location: StorageLocation,
    ) -> None:
        headers = h.get_auth_headers(viewer)
        assert client.get(BASE, headers=headers).status_code == status.HTTP_200_OK

        resp = client.post(
            BASE, headers=headers, json=_create_payload(doc_target_location)
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN, resp.text

    def test_read_grant_alone_cannot_create(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        read_only: User,
        doc_target_location: StorageLocation,
    ) -> None:
        headers = h.get_auth_headers(read_only)
        assert client.get(BASE, headers=headers).status_code == status.HTTP_200_OK

        resp = client.post(
            BASE, headers=headers, json=_create_payload(doc_target_location)
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN, resp.text

    def test_write_grant_alone_cannot_read(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        doc_org: Organization,
    ) -> None:
        user = h.create_user(doc_org, email='writeonly@example.com', role='user')
        h.grant_permissions(user, ['warehouse:write'])
        resp = client.get(BASE, headers=h.get_auth_headers(user))
        assert resp.status_code == status.HTTP_403_FORBIDDEN, resp.text

    def test_wms_session_start_needs_write(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        read_only: User,
    ) -> None:
        """The guard covers the sub-routers, not just the top-level CRUD."""
        resp = client.post(
            f'{BASE}/00000000-0000-0000-0000-000000000000/receiving/start',
            headers=h.get_auth_headers(read_only),
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN, resp.text


@pytest.mark.integration
class TestDocumentsSettingsPermissions:
    """Document profile and per-type configuration are administrative."""

    def test_operator_cannot_change_profile(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        operator: User,
    ) -> None:
        resp = client.put(
            f'{MODULE}/profile',
            headers=h.get_auth_headers(operator),
            json={'approval_threshold': '1000.00'},
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN, resp.text

    def test_manager_can_change_profile(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        doc_org: Organization,
    ) -> None:
        manager = h.create_user(doc_org, email='manager@example.com', role='manager')
        resp = client.put(
            f'{MODULE}/profile',
            headers=h.get_auth_headers(manager),
            json={'approval_threshold': '1000.00'},
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text


@pytest.mark.integration
class TestDocumentApprovalDoorsPermissions:
    """The approval doors of a document moved to the approvals module.

    Under ``/warehouse/documents`` they sat behind the warehouse guard; moved
    to ``/approvals/documents`` they carried only the module check, and a
    reader of the warehouse could hold a document by asking for its approval.
    The guard went with them: reading a document's approval needs
    ``warehouse:read``, acting on it ``warehouse:write`` — and a decision
    still ``approvals:approve`` on top. A document nobody has is enough: the
    guard answers before the handler looks for it.
    """

    DOORS = '/api/v1/approvals/documents/00000000-0000-0000-0000-000000000000'

    @pytest.mark.parametrize('door', ['request-approval', 'approve', 'reject'])
    def test_a_reader_cannot_act_on_a_document_approval(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        doc_org: Organization,
        door: str,
    ) -> None:
        user = h.create_user(doc_org, email='reader@example.com', role='user')
        h.grant_permissions(user, ['warehouse:read', 'approvals:approve'])
        resp = client.post(f'{self.DOORS}/{door}', headers=h.get_auth_headers(user))
        assert resp.status_code == status.HTTP_403_FORBIDDEN, resp.text

    @pytest.mark.parametrize('door', ['approval', 'approval-requirement'])
    def test_a_writer_without_read_cannot_see_a_document_approval(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        doc_org: Organization,
        door: str,
    ) -> None:
        user = h.create_user(doc_org, email='writer@example.com', role='user')
        h.grant_permissions(user, ['warehouse:write'])
        resp = client.get(f'{self.DOORS}/{door}', headers=h.get_auth_headers(user))
        assert resp.status_code == status.HTTP_403_FORBIDDEN, resp.text

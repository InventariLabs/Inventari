"""A read-only account may not write the registers the Core keeps.

Categories, storages, the label pool and the partner register carried no write
guard at all. For the first three the `categories:write` and `locations:write`
keys sat in the catalogue, were offered in the roles matrix, and were checked
by nothing; the partner register had no key to check in the first place, which
is why the manifest gate could not notice it either. A `viewer` could rename a
category every list and filter reads from, rename a storage whose name is
printed onto labels, generate a second pool of codes for stickers already on
shelves, and delete the supplier whose name and tax id are stamped onto every
document that mentions them.

The ordinary-member cases are here for the other half of the fix: enforcing a
permission means granting it, or the guard locks out everyone but the admin.
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.category import Category
from app.models.item import Item
from app.models.organization import Organization
from app.models.role import Role, UserRole
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.user import User
from app.services.auth_service import get_password_hash
from app.services.token_service import create_access_token


def _member(db: Session, org: Organization, role: str) -> User:
    """A member with no custom role row — the defaults their role name carries."""
    user = User(
        email=f'guard_{role}_{uuid.uuid4().hex[:8]}@test.com',
        hashed_password=get_password_hash('pass'),
        organization_id=org.id,
        role=role,
        is_active=True,
    )
    db.add(user)
    db.commit()
    return user


def _auth(user: User) -> dict:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


@pytest.fixture
def org(db_session: Session, test_user: User) -> Organization:
    return db_session.get(Organization, test_user.organization_id)


@pytest.fixture
def viewer(db_session: Session, org: Organization) -> User:
    return _member(db_session, org, 'viewer')


@pytest.fixture
def ordinary(db_session: Session, org: Organization) -> User:
    return _member(db_session, org, 'user')


def _member_with_role(db_session: Session, org: Organization, perms: list[str]) -> User:
    """A read-level member carrying one custom role's extra permissions."""
    role = Role(
        name=f'guard_{uuid.uuid4().hex[:6]}',
        permissions=perms,
        is_system=False,
        organization_id=org.id,
    )
    db_session.add(role)
    user = _member(db_session, org, 'viewer')
    db_session.add(UserRole(user_id=user.id, role_id=role.id))
    db_session.commit()
    return user


@pytest.mark.integration
class TestCategoryWriteGuard:
    def test_viewer_cannot_create_category(
        self, client: TestClient, viewer: User
    ) -> None:
        resp = client.post(
            '/api/v1/categories', json={'name': 'Spare parts'}, headers=_auth(viewer)
        )
        assert resp.status_code == 403

    def test_viewer_cannot_update_category(
        self, client: TestClient, viewer: User, test_category: Category
    ) -> None:
        resp = client.put(
            f'/api/v1/categories/{test_category.id}',
            json={'name': 'Renamed'},
            headers=_auth(viewer),
        )
        assert resp.status_code == 403

    def test_viewer_cannot_delete_category(
        self, client: TestClient, viewer: User, test_category: Category
    ) -> None:
        resp = client.delete(
            f'/api/v1/categories/{test_category.id}', headers=_auth(viewer)
        )
        assert resp.status_code == 403

    def test_ordinary_member_can_still_create_a_category(
        self, client: TestClient, ordinary: User
    ) -> None:
        """Filing things under a name is ordinary work, not administration."""
        resp = client.post(
            '/api/v1/categories', json={'name': 'Spare parts'}, headers=_auth(ordinary)
        )
        assert resp.status_code == 201, resp.text


@pytest.mark.integration
class TestStorageWriteGuard:
    def test_viewer_cannot_create_storage(
        self, client: TestClient, viewer: User, test_storage_type: StorageType
    ) -> None:
        resp = client.post(
            '/api/v1/locations',
            json={'name': 'Bay 12', 'location_type_id': str(test_storage_type.id)},
            headers=_auth(viewer),
        )
        assert resp.status_code == 403

    def test_viewer_cannot_rename_storage(
        self,
        client: TestClient,
        viewer: User,
        test_storage_location: StorageLocation,
    ) -> None:
        resp = client.put(
            f'/api/v1/locations/{test_storage_location.id}',
            json={'name': 'Renamed by a reader'},
            headers=_auth(viewer),
        )
        assert resp.status_code == 403

    def test_viewer_cannot_archive_storage(
        self,
        client: TestClient,
        viewer: User,
        test_storage_location: StorageLocation,
    ) -> None:
        resp = client.post(
            f'/api/v1/locations/{test_storage_location.id}/archive',
            json={},
            headers=_auth(viewer),
        )
        assert resp.status_code == 403

    def test_ordinary_member_can_still_create_a_storage(
        self, client: TestClient, ordinary: User, test_storage_type: StorageType
    ) -> None:
        resp = client.post(
            '/api/v1/locations',
            json={'name': 'Bay 12', 'location_type_id': str(test_storage_type.id)},
            headers=_auth(ordinary),
        )
        assert resp.status_code == 201, resp.text


@pytest.mark.integration
class TestLabelPoolWriteGuard:
    def test_viewer_cannot_generate_a_pool(
        self, client: TestClient, viewer: User
    ) -> None:
        resp = client.post(
            '/api/v1/labels/pool/generate',
            json={'count': 3, 'prefix': 'QA'},
            headers=_auth(viewer),
        )
        assert resp.status_code == 403

    def test_viewer_cannot_delete_a_label(
        self, client: TestClient, viewer: User, ordinary: User
    ) -> None:
        created = client.post(
            '/api/v1/labels/pool/generate',
            json={'count': 1, 'prefix': 'QA'},
            headers=_auth(ordinary),
        )
        assert created.status_code == 201, created.text
        label_id = created.json()[0]['id']

        resp = client.delete(f'/api/v1/labels/pool/{label_id}', headers=_auth(viewer))
        assert resp.status_code == 403

    def test_viewer_cannot_unassign_a_label(
        self, client: TestClient, viewer: User, ordinary: User
    ) -> None:
        created = client.post(
            '/api/v1/labels/pool/generate',
            json={'count': 1, 'prefix': 'QA'},
            headers=_auth(ordinary),
        )
        short_code = created.json()[0]['short_code']

        resp = client.post(
            f'/api/v1/labels/pool/{short_code}/unassign', headers=_auth(viewer)
        )
        assert resp.status_code == 403

    def test_viewer_can_still_read_the_pool(
        self, client: TestClient, viewer: User
    ) -> None:
        """The guard is on the writes — a reader still reads."""
        resp = client.get('/api/v1/labels/pool', headers=_auth(viewer))
        assert resp.status_code == 200


@pytest.mark.integration
class TestImportSideDoorGuard:
    """The import's create_missing_* flags must not grant what the front
    doors refuse.

    POST /categories and POST /locations refuse an account without the
    matching write permission, but POST /items/import took the same
    account's sheet and founded the category — or the whole location path —
    on its behalf: the bulk door asks for ``items:write`` only, and both
    flags default to true.
    """

    def test_import_cannot_found_categories_without_categories_write(
        self, client: TestClient, db_session: Session, org: Organization
    ) -> None:
        user = _member_with_role(db_session, org, ['items:write'])
        resp = client.post(
            '/api/v1/items/import',
            files={
                'file': (
                    'sheet.csv',
                    b'nazwa,kategoria\nBolt,Washers\n',
                    'text/csv',
                )
            },
            data={
                'mapping_json': '{"name": "nazwa", "category": "kategoria"}',
                'create_missing_locations': 'false',
            },
            headers=_auth(user),
        )
        assert resp.status_code == 403
        assert 'categories:write' in resp.text
        assert 'locations:write' not in resp.text

    def test_import_cannot_found_locations_without_storages_write(
        self, client: TestClient, db_session: Session, org: Organization
    ) -> None:
        user = _member_with_role(db_session, org, ['items:write'])
        resp = client.post(
            '/api/v1/items/import',
            files={
                'file': (
                    'sheet.csv',
                    b'nazwa,miejsce\nBolt,Bay 12\n',
                    'text/csv',
                )
            },
            data={
                'mapping_json': '{"name": "nazwa", "storage_location": "miejsce"}',
                'create_missing_categories': 'false',
            },
            headers=_auth(user),
        )
        assert resp.status_code == 403
        assert 'locations:write' in resp.text
        assert 'categories:write' not in resp.text

    def test_import_still_creates_for_a_role_that_holds_both(
        self,
        client: TestClient,
        db_session: Session,
        org: Organization,
        test_storage_location: StorageLocation,
    ) -> None:
        """Enforcing a permission means granting it: a role that holds both
        write keys imports with the flags on exactly as before."""
        user = _member_with_role(
            db_session, org, ['items:write', 'categories:write', 'locations:write']
        )
        resp = client.post(
            '/api/v1/items/import',
            files={
                'file': (
                    'sheet.csv',
                    b'nazwa,kategoria\nBolt,Washers\n',
                    'text/csv',
                )
            },
            data={'mapping_json': '{"name": "nazwa", "category": "kategoria"}'},
            headers=_auth(user),
        )
        assert resp.status_code == 200, resp.text
        assert 'Washers' in resp.json()['created_categories']


@pytest.mark.integration
class TestAiConnectionWriteGuard:
    """The organization's AI connections — which provider serves its
    purposes, whose key pays for them.

    One connection answers for every AI feature the organization runs, and
    its key is the org's money and its data's destination, so creating,
    rewiring, testing or deleting one is administration. The routes asked
    only for an organization — tenancy, not authority — and a read-only
    account could spend it.
    """

    def test_viewer_cannot_create_a_connection(
        self, client: TestClient, viewer: User
    ) -> None:
        resp = client.post(
            '/api/v1/ai-connections',
            json={'name': 'Probe key', 'provider': 'google'},
            headers=_auth(viewer),
        )
        assert resp.status_code == 403

    def test_viewer_cannot_rewire_a_purpose(
        self, client: TestClient, viewer: User
    ) -> None:
        resp = client.put(
            '/api/v1/ai-connections/bindings',
            json={'purpose_key': 'labels.text', 'connection_id': str(uuid.uuid4())},
            headers=_auth(viewer),
        )
        assert resp.status_code == 403

    def test_viewer_cannot_run_the_connection_test(
        self, client: TestClient, viewer: User
    ) -> None:
        resp = client.post(
            '/api/v1/ai-connections/test',
            json={'provider': 'google', 'api_key': 'probe'},
            headers=_auth(viewer),
        )
        assert resp.status_code == 403

    def test_viewer_cannot_delete_a_connection(
        self, client: TestClient, test_user: User, viewer: User
    ) -> None:
        created = client.post(
            '/api/v1/ai-connections',
            json={'name': 'Probe key', 'provider': 'google'},
            headers=_auth(test_user),
        )
        assert created.status_code == 200, created.text
        conn_id = created.json()['id']

        resp = client.delete(f'/api/v1/ai-connections/{conn_id}', headers=_auth(viewer))
        assert resp.status_code == 403

    def test_viewer_cannot_rename_a_connection(
        self, client: TestClient, test_user: User, viewer: User
    ) -> None:
        created = client.post(
            '/api/v1/ai-connections',
            json={'name': 'Probe key', 'provider': 'google'},
            headers=_auth(test_user),
        )
        conn_id = created.json()['id']

        resp = client.put(
            f'/api/v1/ai-connections/{conn_id}',
            json={'name': 'Renamed by a reader'},
            headers=_auth(viewer),
        )
        assert resp.status_code == 403

    def test_ordinary_member_cannot_create_one_either(
        self, client: TestClient, ordinary: User
    ) -> None:
        """Whose key pays and where data goes is administration, not
        filing work — the member level holds no org-settings key."""
        resp = client.post(
            '/api/v1/ai-connections',
            json={'name': 'Probe key', 'provider': 'google'},
            headers=_auth(ordinary),
        )
        assert resp.status_code == 403

    def test_an_account_with_the_settings_key_still_can(
        self, client: TestClient, db_session: Session, org: Organization
    ) -> None:
        """Enforcing a permission means granting it: a custom role built
        exactly for connection stewardship opens every door."""
        user = _member_with_role(db_session, org, ['org:settings:write'])
        resp = client.post(
            '/api/v1/ai-connections',
            json={'name': 'Probe key', 'provider': 'google'},
            headers=_auth(user),
        )
        assert resp.status_code == 200, resp.text


def _partner_of(client: TestClient, user: User, name: str) -> str:
    created = client.post(
        '/api/v1/partners',
        json={'name': name, 'type': 'SUPPLIER'},
        headers=_auth(user),
    )
    assert created.status_code == 201, created.text
    return str(created.json()['id'])


@pytest.mark.integration
class TestPartnerWriteGuard:
    """The five writes the pass walked through, one test each.

    A partner's name and tax id are copied onto every document that names
    them (`partner_snapshot`), so renaming or deleting one is not a change to
    a list — it is a change to what the paperwork will say next time.
    """

    def test_viewer_cannot_create_partner(
        self, client: TestClient, viewer: User
    ) -> None:
        resp = client.post(
            '/api/v1/partners',
            json={'name': 'Acme Supplies', 'type': 'SUPPLIER'},
            headers=_auth(viewer),
        )
        assert resp.status_code == 403

    def test_viewer_cannot_rename_partner(
        self, client: TestClient, viewer: User, ordinary: User
    ) -> None:
        partner_id = _partner_of(client, ordinary, 'Acme Supplies')
        resp = client.put(
            f'/api/v1/partners/{partner_id}',
            json={'name': 'Renamed by a reader'},
            headers=_auth(viewer),
        )
        assert resp.status_code == 403

    def test_viewer_cannot_deactivate_partner(
        self, client: TestClient, viewer: User, ordinary: User
    ) -> None:
        partner_id = _partner_of(client, ordinary, 'Deactivate Me')
        resp = client.patch(
            f'/api/v1/partners/{partner_id}/deactivate', headers=_auth(viewer)
        )
        assert resp.status_code == 403

    def test_viewer_cannot_activate_partner(
        self, client: TestClient, viewer: User, ordinary: User
    ) -> None:
        partner_id = _partner_of(client, ordinary, 'Activate Me')
        resp = client.patch(
            f'/api/v1/partners/{partner_id}/activate', headers=_auth(viewer)
        )
        assert resp.status_code == 403

    def test_viewer_cannot_delete_partner(
        self, client: TestClient, viewer: User, ordinary: User
    ) -> None:
        partner_id = _partner_of(client, ordinary, 'Delete Me')
        resp = client.delete(f'/api/v1/partners/{partner_id}', headers=_auth(viewer))
        assert resp.status_code == 403

    def test_viewer_can_still_read_the_register(
        self, client: TestClient, viewer: User
    ) -> None:
        resp = client.get('/api/v1/partners', headers=_auth(viewer))
        assert resp.status_code == 200

    def test_ordinary_member_can_still_keep_the_register(
        self, client: TestClient, ordinary: User
    ) -> None:
        """Recording who you buy from is ordinary work, not administration."""
        partner_id = _partner_of(client, ordinary, 'Acme Supplies')

        renamed = client.put(
            f'/api/v1/partners/{partner_id}',
            json={'name': 'Acme Supplies Ltd'},
            headers=_auth(ordinary),
        )
        assert renamed.status_code == 200, renamed.text


def _template_of(client: TestClient, user: User, name: str) -> str:
    created = client.post(
        '/api/v1/items/product-templates',
        json={'name': name},
        headers=_auth(user),
    )
    assert created.status_code == 201, created.text
    return str(created.json()['id'])


@pytest.mark.integration
class TestStorageTypeWriteGuard:
    """The kinds of place stock can sit — a Core dictionary, not a module's.

    Every location points at one, the picker on the location form is built
    from it, and a type carries the field definitions the form then asks for.
    Renaming or deleting one reaches every location of that kind.
    """

    def test_viewer_cannot_create_storage_type(
        self, client: TestClient, viewer: User
    ) -> None:
        resp = client.post(
            '/api/v1/location-types',
            json={'name': 'Cage', 'type_code': 'CAGE'},
            headers=_auth(viewer),
        )
        assert resp.status_code == 403

    def test_viewer_cannot_update_storage_type(
        self, client: TestClient, viewer: User, test_storage_type: StorageType
    ) -> None:
        resp = client.put(
            f'/api/v1/location-types/{test_storage_type.id}',
            json={'name': 'Renamed by a reader'},
            headers=_auth(viewer),
        )
        assert resp.status_code == 403

    def test_viewer_cannot_delete_storage_type(
        self, client: TestClient, viewer: User, test_storage_type: StorageType
    ) -> None:
        resp = client.delete(
            f'/api/v1/location-types/{test_storage_type.id}', headers=_auth(viewer)
        )
        assert resp.status_code == 403

    def test_viewer_can_still_read_the_types(
        self, client: TestClient, viewer: User
    ) -> None:
        resp = client.get('/api/v1/location-types', headers=_auth(viewer))
        assert resp.status_code == 200

    def test_ordinary_member_can_still_add_a_type(
        self, client: TestClient, ordinary: User
    ) -> None:
        """Same authority as adding a shelf — the type is what the shelf is."""
        resp = client.post(
            '/api/v1/location-types',
            json={'name': 'Cage', 'type_code': 'CAGE'},
            headers=_auth(ordinary),
        )
        assert resp.status_code == 201, resp.text


@pytest.mark.integration
class TestProductTemplateWriteGuard:
    """The product catalogue every item is an instance of.

    A template carries the name, barcode and SKU that items inherit and that
    documents print, so creating or cloning one is the same authority as
    creating an item — which `items:write` has guarded all along.
    """

    def test_viewer_cannot_create_template(
        self, client: TestClient, viewer: User
    ) -> None:
        resp = client.post(
            '/api/v1/items/product-templates',
            json={'name': 'Bolt M8'},
            headers=_auth(viewer),
        )
        assert resp.status_code == 403

    def test_viewer_cannot_clone_template(
        self, client: TestClient, viewer: User, ordinary: User
    ) -> None:
        template_id = _template_of(client, ordinary, 'Bolt M8')
        resp = client.post(
            f'/api/v1/items/product-templates/{template_id}/clone',
            json={'name': 'Bolt M8 copy'},
            headers=_auth(viewer),
        )
        assert resp.status_code == 403

    def test_viewer_cannot_edit_nutrition(
        self, client: TestClient, viewer: User, ordinary: User
    ) -> None:
        template_id = _template_of(client, ordinary, 'Oat Flakes')
        resp = client.patch(
            f'/api/v1/items/product-templates/{template_id}/nutrition',
            json={'nutrition_info': {'energy_kcal': 370}},
            headers=_auth(viewer),
        )
        assert resp.status_code == 403

    def test_viewer_cannot_set_the_sku_schema(
        self, client: TestClient, viewer: User
    ) -> None:
        resp = client.put(
            '/api/v1/items/product-templates/sku-schema',
            json={'prefix': 'QA'},
            headers=_auth(viewer),
        )
        assert resp.status_code == 403

    def test_ordinary_member_cannot_set_the_sku_schema(
        self, client: TestClient, ordinary: User
    ) -> None:
        """The docstring said admin-only and nothing made it so.

        How every SKU in the organization is spelled is a setting, not a
        record — a member who may add a product may not redefine the naming
        of the ones already there.
        """
        resp = client.put(
            '/api/v1/items/product-templates/sku-schema',
            json={'prefix': 'QA'},
            headers=_auth(ordinary),
        )
        assert resp.status_code == 403

    def test_viewer_can_still_search_the_catalogue(
        self, client: TestClient, viewer: User
    ) -> None:
        resp = client.get(
            '/api/v1/items/product-templates',
            params={'search': 'Bo'},
            headers=_auth(viewer),
        )
        assert resp.status_code == 200

    def test_ordinary_member_can_still_add_a_template(
        self, client: TestClient, ordinary: User
    ) -> None:
        template_id = _template_of(client, ordinary, 'Bolt M8')
        cloned = client.post(
            f'/api/v1/items/product-templates/{template_id}/clone',
            json={'name': 'Bolt M8 copy'},
            headers=_auth(ordinary),
        )
        assert cloned.status_code == 201, cloned.text


@pytest.mark.integration
class TestBulkDoorWriteGuard:
    """The bulk door asks for the same permission the single door does.

    POST /items refused a viewer while POST /items/import took the same
    account's hundred rows and wrote them — adding one product was a
    permission, adding a sheet of them was an oversight. The item
    attachments routes sat in the same gap: uploading or removing a file on
    a product is a write to the product register, wherever the bytes land,
    and no guard stood behind the form.
    """

    def test_viewer_cannot_analyze_an_import_sheet(
        self, client: TestClient, viewer: User
    ) -> None:
        resp = client.post(
            '/api/v1/items/import/analyze',
            files={'file': ('sheet.csv', b'nazwa,ilosc\n', 'text/csv')},
            headers=_auth(viewer),
        )
        assert resp.status_code == 403

    def test_viewer_cannot_import_items(self, client: TestClient, viewer: User) -> None:
        resp = client.post(
            '/api/v1/items/import',
            files={'file': ('sheet.csv', b'nazwa\n', 'text/csv')},
            data={'mapping_json': '{"name": "nazwa"}'},
            headers=_auth(viewer),
        )
        assert resp.status_code == 403

    def test_ordinary_member_can_still_analyze_a_sheet(
        self, client: TestClient, ordinary: User
    ) -> None:
        """Enforcing a permission means granting it: the default member role
        carries ``items:write``, so the bulk door must open for them."""
        resp = client.post(
            '/api/v1/items/import/analyze',
            files={'file': ('sheet.csv', b'nazwa,ilosc\n', 'text/csv')},
            headers=_auth(ordinary),
        )
        assert resp.status_code == 200

    def test_viewer_cannot_upload_an_item_attachment(
        self, client: TestClient, viewer: User, test_item: Item
    ) -> None:
        resp = client.post(
            f'/api/v1/items/{test_item.id}/attachments',
            files={'file': ('note.txt', b'hello', 'text/plain')},
            headers=_auth(viewer),
        )
        assert resp.status_code == 403

    def test_viewer_cannot_delete_an_item_attachment(
        self, client: TestClient, test_user: User, viewer: User, test_item: Item
    ) -> None:
        upload = client.post(
            f'/api/v1/items/{test_item.id}/attachments',
            files={'file': ('note.txt', b'hello', 'text/plain')},
            headers=_auth(test_user),
        )
        assert upload.status_code == 201, upload.text
        attachment_id = upload.json()['id']
        resp = client.delete(
            f'/api/v1/attachments/{attachment_id}',
            headers=_auth(viewer),
        )
        assert resp.status_code == 403

    def test_ordinary_member_can_still_attach_a_file(
        self, client: TestClient, ordinary: User, test_item: Item
    ) -> None:
        resp = client.post(
            f'/api/v1/items/{test_item.id}/attachments',
            files={'file': ('note.txt', b'hello', 'text/plain')},
            headers=_auth(ordinary),
        )
        assert resp.status_code == 201, resp.text

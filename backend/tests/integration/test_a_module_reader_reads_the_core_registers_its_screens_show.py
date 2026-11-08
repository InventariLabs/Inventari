"""A module reader reads the Core registers the module's screens show.

A custom role is a deliberate narrowing, and an administrator may hand one
out holding a single module's read: ``equipment:read`` for the person who
keeps the register, ``warehouse:read`` for the one who works the shelves.
Those screens still ask Core for the registers they display — the location
tree, the category list, the archive of the module's own records and the
label sheet — and since every Core read gained a key of its own, each of them
refused the module's reader with 403.

Measured before the fix with custom roles and the modules enabled:

* ``[equipment:read]`` on ``/equipment/assets`` -> ``GET /categories``,
  ``GET /locations``, ``GET /items/archived?module_scope=equipment`` and
  ``GET /labels/pool/export/png`` all 403. The category filter read empty,
  the Archive tab read "An error occurred", location names were missing and
  Print labels downloaded nothing.
* ``[warehouse:read]`` on ``/warehouse/location-settings`` ->
  ``GET /locations?top_level=true`` 403, so the page found no warehouse and
  listed nothing to print.

The decision is the print queue's (``app/modules/printing/router.py``): the
module read admits the Core *reads* its screens make, because the screens are
useless without them. Writes stay behind the Core write keys — a module that
shows a location list does not hand out the right to change it.
"""

import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper
from app.models.label_pool import LabelPool
from app.models.organization import Organization
from app.models.storage_location import StorageLocation
from app.models.user import User

pytestmark = pytest.mark.integration

_MODULES = ['core', 'items', 'locations', 'categories', 'equipment', 'warehouse']

_PNG_MAGIC = b'\x89PNG'


@pytest.fixture
def h(db_session: Session) -> ModuleTestHelper:
    return ModuleTestHelper(db_session)


@pytest.fixture
def org(h: ModuleTestHelper) -> Organization:
    return h.create_org('Module Reader Org', _MODULES)


@pytest.fixture
def admin(h: ModuleTestHelper, org: Organization) -> User:
    return h.create_user(org, email=f'mr_admin_{uuid.uuid4().hex[:6]}@test.com')


@pytest.fixture
def warehouse(h: ModuleTestHelper, org: Organization, admin: User) -> StorageLocation:
    kind = h.create_storage_type('Warehouse', 'WAREHOUSE', organization_id=org.id)
    place = h.create_storage_location(org, kind, admin, name='Warehouse A')
    place.short_code = 'WH-A'
    h.db.commit()
    return place


@pytest.fixture
def shelf(
    h: ModuleTestHelper,
    org: Organization,
    admin: User,
    warehouse: StorageLocation,
) -> StorageLocation:
    kind = h.create_storage_type('Shelf', 'SHELF', organization_id=org.id)
    location = h.create_storage_location(
        org, kind, admin, name='Shelf A', parent_id=warehouse.id
    )
    location.short_code = 'SHELF-A'
    h.db.commit()
    return location


@pytest.fixture
def equipment_category(client: TestClient, h: ModuleTestHelper, admin: User) -> str:
    """The category that makes a record the equipment module's own."""
    category = client.post(
        '/api/v1/categories',
        headers=h.get_auth_headers(admin),
        json={'name': 'Laptops', 'context_tag': 'equipment'},
    )
    assert category.status_code == 201, category.text
    return category.json()['id']


@pytest.fixture
def archived_asset(
    client: TestClient,
    h: ModuleTestHelper,
    admin: User,
    shelf: StorageLocation,
    equipment_category: str,
) -> str:
    """An equipment record in the archive, filed under the module's category."""
    created = client.post(
        '/api/v1/items',
        headers=h.get_auth_headers(admin),
        json={
            'name': 'Laptop',
            'location_id': str(shelf.id),
            'category_id': equipment_category,
            'quantity': 1,
        },
    )
    assert created.status_code == 201, created.text
    item_id = created.json()['id']
    archived = client.delete(
        f'/api/v1/items/{item_id}', headers=h.get_auth_headers(admin)
    )
    assert archived.status_code == 204, archived.text
    return item_id


@pytest.fixture
def live_asset(
    client: TestClient,
    h: ModuleTestHelper,
    admin: User,
    shelf: StorageLocation,
    equipment_category: str,
) -> str:
    """An equipment record the register lists, and whose label it can print."""
    created = client.post(
        '/api/v1/items',
        headers=h.get_auth_headers(admin),
        json={
            'name': 'Live laptop',
            'location_id': str(shelf.id),
            'category_id': equipment_category,
            'quantity': 1,
        },
    )
    assert created.status_code == 201, created.text
    return created.json()['id']


@pytest.fixture
def plain_item(
    client: TestClient,
    h: ModuleTestHelper,
    admin: User,
    shelf: StorageLocation,
) -> str:
    """An ordinary product, which no module claims as its own."""
    created = client.post(
        '/api/v1/items',
        headers=h.get_auth_headers(admin),
        json={
            'name': 'Plain product',
            'location_id': str(shelf.id),
            'quantity': 1,
        },
    )
    assert created.status_code == 201, created.text
    return created.json()['id']


@pytest.fixture
def archived_plain_item(
    client: TestClient,
    h: ModuleTestHelper,
    admin: User,
    plain_item: str,
) -> str:
    """The ordinary product in the archive, where the register's tab looks."""
    archived = client.delete(
        f'/api/v1/items/{plain_item}', headers=h.get_auth_headers(admin)
    )
    assert archived.status_code == 204, archived.text
    return plain_item


@pytest.fixture
def pool_label(h: ModuleTestHelper, org: Organization, admin: User) -> LabelPool:
    """A label nobody has assigned, which the free pool offers."""
    label = LabelPool(
        short_code=f'EQ-{uuid.uuid4().hex[:6]}',
        organization_id=org.id,
        created_by=admin.id,
    )
    h.db.add(label)
    h.db.commit()
    return label


def _assigned_label(
    h: ModuleTestHelper, org: Organization, admin: User, item_id: str
) -> LabelPool:
    label = LabelPool(
        short_code=f'EQ-{uuid.uuid4().hex[:6]}',
        organization_id=org.id,
        created_by=admin.id,
        item_id=uuid.UUID(item_id),
        is_assigned=True,
        assigned_at=datetime.now(UTC),
    )
    h.db.add(label)
    h.db.commit()
    return label


@pytest.fixture
def asset_label(
    h: ModuleTestHelper, org: Organization, admin: User, live_asset: str
) -> LabelPool:
    """The label stuck on one of the register's own assets."""
    return _assigned_label(h, org, admin, live_asset)


@pytest.fixture
def plain_label(
    h: ModuleTestHelper, org: Organization, admin: User, plain_item: str
) -> LabelPool:
    """The label of an ordinary product, which no module claims."""
    return _assigned_label(h, org, admin, plain_item)


def _with_role(
    h: ModuleTestHelper, org: Organization, permissions: list[str]
) -> dict[str, str]:
    user = h.create_user(org, email=f'mr_{uuid.uuid4().hex[:8]}@test.com', role='user')
    h.grant_permissions(user, permissions)
    return h.get_auth_headers(user)


class TestAnEquipmentReaderReadsWhatTheRegisterShows:
    def test_the_asset_screen_renders_its_categories_locations_and_archive(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        org: Organization,
        shelf: StorageLocation,
        archived_asset: str,
    ) -> None:
        headers = _with_role(h, org, ['equipment:read'])

        categories = client.get('/api/v1/categories', headers=headers)
        locations = client.get(
            '/api/v1/locations', headers=headers, params={'limit': 5}
        )
        archived = client.get(
            '/api/v1/items/archived',
            headers=headers,
            params={'module_scope': 'equipment'},
        )

        assert categories.status_code == 200, categories.text
        assert locations.status_code == 200, locations.text
        assert archived.status_code == 200, archived.text
        assert [row['id'] for row in archived.json()['items']] == [archived_asset]

    def test_the_asset_card_opens_the_registers_record(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        org: Organization,
        archived_asset: str,
    ) -> None:
        headers = _with_role(h, org, ['equipment:read'])

        response = client.get(
            f'/api/v1/items/{archived_asset}',
            headers=headers,
            params={'include_archived': True},
        )

        assert response.status_code == 200, response.text
        assert response.json()['id'] == archived_asset

    def test_the_register_downloads_its_labels(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        org: Organization,
        asset_label: LabelPool,
    ) -> None:
        headers = _with_role(h, org, ['equipment:read'])

        response = client.get(
            '/api/v1/labels/pool/export/png',
            headers=headers,
            params={'short_codes': [asset_label.short_code]},
        )

        assert response.status_code == 200, response.text
        assert response.content.startswith(_PNG_MAGIC)

    def test_the_register_does_not_gain_the_core_writes(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        org: Organization,
    ) -> None:
        headers = _with_role(h, org, ['equipment:read'])

        category = client.post(
            '/api/v1/categories', headers=headers, json={'name': 'Printers'}
        )
        location = client.post(
            '/api/v1/locations', headers=headers, json={'name': 'Store room'}
        )

        assert category.status_code == 403, category.text
        assert location.status_code == 403, location.text


class TestAnEquipmentReaderReadsOnlyTheRegistersRecords:
    """The module's read bounds the answer to the module's own records.

    The archive, the card and the label sheet are Core routes whose data is
    not the module's alone: the same route serves every product of the
    organization. Admitting ``equipment:read`` there without a scope handed a
    register reader the organization's whole product list by the back door —
    the archive unscoped, a card by any id and a label carrying any product's
    name, with the free pool to spend. The reach is the module's records.
    """

    def test_the_equipment_archive_serves_only_the_equipment_scope(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        org: Organization,
        archived_asset: str,
        archived_plain_item: str,
    ) -> None:
        headers = _with_role(h, org, ['equipment:read'])

        unscoped = client.get('/api/v1/items/archived', headers=headers)
        another_scope = client.get(
            '/api/v1/items/archived',
            headers=headers,
            params={'module_scope': 'food'},
        )
        equipment_scope = client.get(
            '/api/v1/items/archived',
            headers=headers,
            params={'module_scope': 'equipment'},
        )

        assert unscoped.status_code == 403, unscoped.text
        assert another_scope.status_code == 403, another_scope.text
        assert equipment_scope.status_code == 200, equipment_scope.text
        assert [row['id'] for row in equipment_scope.json()['items']] == [
            archived_asset
        ]

    def test_the_equipment_card_is_404_for_a_product_outside_the_register(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        org: Organization,
        plain_item: str,
        archived_plain_item: str,
    ) -> None:
        headers = _with_role(h, org, ['equipment:read'])

        live = client.get(f'/api/v1/items/{plain_item}', headers=headers)
        archived = client.get(
            f'/api/v1/items/{archived_plain_item}',
            headers=headers,
            params={'include_archived': True},
        )

        assert live.status_code == 404, live.text
        assert archived.status_code == 404, archived.text

    def test_the_label_sheet_draws_only_the_registers_labels(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        org: Organization,
        asset_label: LabelPool,
        plain_label: LabelPool,
    ) -> None:
        headers = _with_role(h, org, ['equipment:read'])

        own = client.get(
            '/api/v1/labels/pool/export/png',
            headers=headers,
            params={'short_codes': [asset_label.short_code]},
        )
        another = client.get(
            '/api/v1/labels/pool/export/png',
            headers=headers,
            params={'short_codes': [plain_label.short_code]},
        )

        assert own.status_code == 200, own.text
        assert own.content.startswith(_PNG_MAGIC)
        assert another.status_code == 404, another.text
        h.db.refresh(asset_label)
        h.db.refresh(plain_label)
        assert asset_label.printed_at is not None
        assert plain_label.printed_at is None

    def test_the_label_sheet_refuses_the_free_pool(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        org: Organization,
        pool_label: LabelPool,
    ) -> None:
        headers = _with_role(h, org, ['equipment:read'])

        response = client.get(
            '/api/v1/labels/pool/export/png',
            headers=headers,
            params={'count': 3},
        )

        assert response.status_code == 403, response.text
        h.db.refresh(pool_label)
        assert pool_label.printed_at is None


class TestAWarehouseReaderReadsWhatTheCodesPageShows:
    def test_the_codes_page_finds_and_reads_its_warehouse(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        org: Organization,
        warehouse: StorageLocation,
        shelf: StorageLocation,
    ) -> None:
        headers = _with_role(h, org, ['warehouse:read'])

        top_level = client.get(
            '/api/v1/locations',
            headers=headers,
            params={'top_level': True, 'counts': False, 'limit': 1},
        )
        detail = client.get(f'/api/v1/locations/{warehouse.id}', headers=headers)
        codes = client.get(f'/api/v1/locations/{warehouse.id}/codes', headers=headers)
        breadcrumb = client.get(
            f'/api/v1/locations/{shelf.id}/breadcrumb', headers=headers
        )
        contents = client.get(f'/api/v1/locations/{shelf.id}/items', headers=headers)

        assert top_level.status_code == 200, top_level.text
        assert [row['id'] for row in top_level.json()['items']] == [str(warehouse.id)]
        assert detail.status_code == 200, detail.text
        assert codes.status_code == 200, codes.text
        assert breadcrumb.status_code == 200, breadcrumb.text
        assert contents.status_code == 200, contents.text

    def test_the_putaway_screen_reads_the_category_list(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        org: Organization,
    ) -> None:
        headers = _with_role(h, org, ['warehouse:read'])

        response = client.get('/api/v1/categories', headers=headers)

        assert response.status_code == 200, response.text

    def test_the_warehouse_does_not_gain_the_core_writes(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        org: Organization,
    ) -> None:
        headers = _with_role(h, org, ['warehouse:read'])

        category = client.post(
            '/api/v1/categories', headers=headers, json={'name': 'Pallets'}
        )
        location = client.post(
            '/api/v1/locations', headers=headers, json={'name': 'Dock'}
        )

        assert category.status_code == 403, category.text
        assert location.status_code == 403, location.text


class TestAnUnrelatedReadStillRefusesTheCoreRegisters:
    def test_a_role_holding_no_relevant_read_is_refused_them_all(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        org: Organization,
    ) -> None:
        headers = _with_role(h, org, ['stock_takes:read'])

        answers = {
            'GET /categories': client.get('/api/v1/categories', headers=headers),
            'GET /locations': client.get('/api/v1/locations', headers=headers),
            'GET /items/archived': client.get(
                '/api/v1/items/archived', headers=headers
            ),
            'GET /labels/pool/export/png': client.get(
                '/api/v1/labels/pool/export/png', headers=headers
            ),
        }

        assert {name: response.status_code for name, response in answers.items()} == (
            dict.fromkeys(answers, 403)
        )


class TestAModuleReadDoesNotOpenAnotherModulesScreens:
    def test_a_warehouse_reader_is_refused_the_equipment_register(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        org: Organization,
    ) -> None:
        headers = _with_role(h, org, ['warehouse:read'])

        response = client.get('/api/v1/equipment/assets', headers=headers)

        assert response.status_code == 403, response.text

    def test_a_warehouse_reader_is_refused_a_products_card(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        org: Organization,
        archived_asset: str,
    ) -> None:
        headers = _with_role(h, org, ['warehouse:read'])

        response = client.get(f'/api/v1/items/{archived_asset}', headers=headers)

        assert response.status_code == 403, response.text

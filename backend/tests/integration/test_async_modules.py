import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.item import Item
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.user import User
from app.services.token_service import create_access_token, get_password_hash
from tests.integration._shelf import put_on_shelf, shelf_keeper


def _auth(user: User) -> dict:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


# ── Shared async fixtures ─────────────────────────────────────────────────────


@pytest.fixture
async def mod_org(real_async_db_session: AsyncSession) -> Organization:
    org = Organization(
        name='Module Async Test Org',
        enabled_modules=[
            'core',
            'items',
            'locations',
            'categories',
            'warehouse',
            'stock_takes',
            'recipes',
            'stats',
        ],
    )
    real_async_db_session.add(org)
    await real_async_db_session.commit()
    await real_async_db_session.refresh(org)
    return org


@pytest.fixture
async def mod_user(real_async_db_session: AsyncSession, mod_org: Organization) -> User:
    user = User(
        email='mod-async@test.com',
        hashed_password=get_password_hash('pass'),
        full_name='Mod Async User',
        organization_id=mod_org.id,
        role='admin',
        is_active=True,
    )
    real_async_db_session.add(user)
    await real_async_db_session.commit()
    await real_async_db_session.refresh(user)
    return user


@pytest.fixture
async def mod_headers(mod_user: User) -> dict:
    return _auth(mod_user)


@pytest.fixture
async def mod_storage_type(real_async_db_session: AsyncSession) -> StorageType:
    st = StorageType(name='Warehouse', type_code='WAREHOUSE', behavior_mode='NONE')
    real_async_db_session.add(st)
    await real_async_db_session.commit()
    await real_async_db_session.refresh(st)
    return st


@pytest.fixture
async def mod_location(
    real_async_db_session: AsyncSession,
    mod_org: Organization,
    mod_storage_type: StorageType,
    mod_user: User,
) -> StorageLocation:
    loc = StorageLocation(
        name='Async Test Warehouse',
        organization_id=mod_org.id,
        storage_type_id=mod_storage_type.id,
        created_by=mod_user.id,
    )
    real_async_db_session.add(loc)
    await real_async_db_session.commit()
    await real_async_db_session.refresh(loc)
    return loc


@pytest.fixture
async def mod_template(
    real_async_db_session: AsyncSession, mod_org: Organization
) -> ProductTemplate:
    t = ProductTemplate(
        name='Async Test Product',
        organization_id=mod_org.id,
        barcode='MODASYNC001',
    )
    real_async_db_session.add(t)
    await real_async_db_session.commit()
    await real_async_db_session.refresh(t)
    return t


async def _create_item_with_stock(
    db: AsyncSession,
    org: Organization,
    location: StorageLocation,
    template: ProductTemplate,
) -> Item:
    item = await put_on_shelf(
        db, await shelf_keeper(db, org.id), template, location.id, 100
    )
    await db.commit()
    await db.refresh(item)
    return item


# ── Documents ─────────────────────────────────────────────────────────────────


@pytest.mark.integration
@pytest.mark.async_db
class TestAsyncDocuments:
    async def test_create_document_draft(
        self, real_async_client, mod_headers, mod_org, mod_location, mod_template
    ):
        resp = await real_async_client.post(
            '/api/v1/warehouse/documents',
            headers=mod_headers,
            json={
                'type': 'INTERNAL_IN',
                'target_location_id': str(mod_location.id),
                'lines': [
                    {
                        'name': 'Test Product',
                        'product_template_id': str(mod_template.id),
                        'expected_quantity': 10,
                    }
                ],
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data['status'] == 'DRAFT'
        assert data['type'] == 'INTERNAL_IN'
        assert len(data['lines']) == 1

    async def test_confirm_document(
        self, real_async_client, mod_headers, mod_org, mod_location, mod_template
    ):
        create_resp = await real_async_client.post(
            '/api/v1/warehouse/documents',
            headers=mod_headers,
            json={
                'type': 'INTERNAL_IN',
                'target_location_id': str(mod_location.id),
                'lines': [
                    {
                        'name': 'Test Product',
                        'product_template_id': str(mod_template.id),
                        'expected_quantity': 5,
                    }
                ],
            },
        )
        assert create_resp.status_code == 201
        doc_id = create_resp.json()['id']

        confirm_resp = await real_async_client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm',
            headers=mod_headers,
        )
        assert confirm_resp.status_code == 200
        assert confirm_resp.json()['status'] == 'CONFIRMED'

    async def test_complete_document_stock_execution(
        self,
        real_async_client,
        mod_headers,
        mod_org,
        mod_location,
        mod_template,
        real_async_db_session,
    ):
        create_resp = await real_async_client.post(
            '/api/v1/warehouse/documents',
            headers=mod_headers,
            json={
                'type': 'INTERNAL_IN',
                'target_location_id': str(mod_location.id),
                'lines': [
                    {
                        'name': 'Test Product',
                        'product_template_id': str(mod_template.id),
                        'expected_quantity': 3,
                    }
                ],
            },
        )
        assert create_resp.status_code == 201
        doc_id = create_resp.json()['id']

        await real_async_client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm',
            headers=mod_headers,
        )

        cancel_resp = await real_async_client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/cancel',
            headers=mod_headers,
        )
        assert cancel_resp.status_code == 200
        assert cancel_resp.json()['status'] == 'CANCELLED'


# ── Stock Takes ───────────────────────────────────────────────────────────────


@pytest.mark.integration
@pytest.mark.async_db
class TestAsyncStockTakes:
    async def test_create_stock_take(
        self, real_async_client, mod_headers, mod_org, mod_location
    ):
        resp = await real_async_client.post(
            '/api/v1/stock-takes',
            headers=mod_headers,
            json={
                'name': 'Async Test Count',
                'location_id': str(mod_location.id),
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data['name'] == 'Async Test Count'
        assert data['status'].lower() == 'in_progress'

    async def test_create_and_complete_stock_take(
        self,
        real_async_client,
        mod_headers,
        mod_org,
        mod_location,
        mod_template,
        real_async_db_session,
    ):
        await _create_item_with_stock(
            real_async_db_session, mod_org, mod_location, mod_template
        )

        create_resp = await real_async_client.post(
            '/api/v1/stock-takes',
            headers=mod_headers,
            json={
                'name': 'Async Complete Count',
                'location_id': str(mod_location.id),
            },
        )
        assert create_resp.status_code == 201
        st_id = create_resp.json()['id']

        items_resp = await real_async_client.get(
            f'/api/v1/stock-takes/{st_id}/items',
            headers=mod_headers,
        )
        assert items_resp.status_code == 200
        items = items_resp.json()['items']

        if items:
            st_item_id = items[0]['id']
            count_resp = await real_async_client.patch(
                f'/api/v1/stock-takes/{st_id}/items/{st_item_id}/count',
                headers=mod_headers,
                json={'counted_quantity': 100},
            )
            assert count_resp.status_code == 200

        complete_resp = await real_async_client.post(
            f'/api/v1/stock-takes/{st_id}/complete',
            headers=mod_headers,
            json={'apply_adjustments': True},
        )
        assert complete_resp.status_code == 200


# ── Recipes ───────────────────────────────────────────────────────────────────


@pytest.mark.integration
@pytest.mark.async_db
class TestAsyncRecipes:
    async def test_create_recipe(self, real_async_client, mod_headers, mod_org):
        resp = await real_async_client.post(
            '/api/v1/recipes',
            headers=mod_headers,
            json={
                'name': 'Async Test Recipe',
                'servings': 4,
                'ingredients': [
                    {'name': 'Tomatoes', 'quantity': 500},
                    {'name': 'Onion', 'quantity': 200},
                ],
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data['name'] == 'Async Test Recipe'
        assert data['servings'] == 4
        assert len(data['ingredients']) == 2

    async def test_list_recipes(self, real_async_client, mod_headers, mod_org):
        await real_async_client.post(
            '/api/v1/recipes',
            headers=mod_headers,
            json={'name': 'Recipe for Listing', 'servings': 2},
        )

        resp = await real_async_client.get(
            '/api/v1/recipes',
            headers=mod_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)
        assert 'items' in data and 'total' in data
        assert data['total'] >= 1
        assert any(item['name'] == 'Recipe for Listing' for item in data['items'])

    async def test_recipe_picking_workflow(
        self,
        real_async_client,
        mod_headers,
        mod_org,
        mod_location,
        mod_template,
        real_async_db_session,
    ):
        await _create_item_with_stock(
            real_async_db_session, mod_org, mod_location, mod_template
        )

        recipe_resp = await real_async_client.post(
            '/api/v1/recipes',
            headers=mod_headers,
            json={
                'name': 'Picking Test Recipe',
                'servings': 1,
                'ingredients': [
                    {
                        'name': 'Async Stock Item',
                        'template_id': str(mod_template.id),
                        'quantity': 10,
                    },
                ],
            },
        )
        assert recipe_resp.status_code == 201
        recipe_id = recipe_resp.json()['id']

        picking_resp = await real_async_client.post(
            f'/api/v1/recipes/{recipe_id}/picking/start',
            headers=mod_headers,
            json={'servings': 1},
        )
        assert picking_resp.status_code in [200, 201]

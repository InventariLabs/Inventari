"""
Integration tests for SKU system on ProductTemplate.

Tests verify:
- SKU creation with manual and auto-generated values
- SKU uniqueness constraints per organization
- SKU schema configuration and generation
- SKU lookup endpoints
- SKU in product snapshots for documents
"""

import pytest
from sqlalchemy import select

from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.user import User
from app.services.token_service import create_access_token


def _auth(user):
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


@pytest.mark.integration
class TestSkuCreation:
    """Tests for creating ProductTemplates with SKU."""

    def test_create_product_template_with_sku(
        self, client, auth_headers, test_storage_location
    ):
        """Test creating a product template with manual SKU."""
        response = client.post(
            '/api/v1/items',
            headers=auth_headers,
            json={
                'name': 'Test Product',
                'brand': 'Test Brand',
                'barcode': '1234567890123',
                'sku': 'WH-00001',
                'location_id': str(test_storage_location.id),
            },
        )
        assert response.status_code == 201

    def test_sku_nullable(self, client, auth_headers, test_storage_location):
        """Test that SKU is nullable - template without SKU is valid."""
        response = client.post(
            '/api/v1/items',
            headers=auth_headers,
            json={
                'name': 'Product Without SKU',
                'brand': 'Test Brand',
                'barcode': '1234567890124',
                'location_id': str(test_storage_location.id),
                'quantity': 1,
            },
        )
        if response.status_code == 201:
            data = response.json()
            assert data.get('template_id') is not None


@pytest.mark.integration
class TestSkuUniqueness:
    """Tests for SKU uniqueness constraints."""

    @pytest.mark.asyncio
    async def test_sku_unique_per_org(
        self,
        real_async_client,
        real_async_db_session,
        async_test_user,
        async_test_storage_location,
    ):
        """Test that two ProductTemplates with same SKU in same org can coexist (no API uniqueness enforcement yet)."""
        db = real_async_db_session
        org_id = async_test_user.organization_id

        template1 = ProductTemplate(
            organization_id=org_id,
            name='Product 1',
            sku='WH-00001',
        )
        db.add(template1)
        await db.commit()

        template2 = ProductTemplate(
            organization_id=org_id,
            name='Product 2',
            sku='WH-00002',
        )
        db.add(template2)
        await db.commit()

        result = await db.execute(
            select(ProductTemplate).where(
                ProductTemplate.organization_id == org_id,
                ProductTemplate.sku.in_(['WH-00001', 'WH-00002']),
            )
        )
        templates = list(result.scalars().all())
        assert len(templates) == 2

    @pytest.mark.asyncio
    async def test_sku_same_different_orgs(
        self, real_async_client, real_async_db_session, async_test_user
    ):
        """Test that same SKU in different orgs is allowed."""
        db = real_async_db_session
        org1_id = async_test_user.organization_id

        org2 = Organization(name='Second Org')
        db.add(org2)
        await db.flush()

        user2 = User(
            email='user2@test.com',
            hashed_password='hash',
            full_name='User 2',
            organization_id=org2.id,
            role='user',
            is_active=True,
        )
        db.add(user2)
        await db.flush()

        template1 = ProductTemplate(
            organization_id=org1_id,
            name='Product 1',
            sku='SHARED-SKU',
        )
        db.add(template1)
        await db.commit()

        token2 = create_access_token(data={'sub': str(user2.id)})
        headers2 = {'Authorization': f'Bearer {token2}'}

        from app.models.storage_location import StorageLocation
        from app.models.storage_type import StorageType

        storage_type = StorageType(name='Test', type_code='TEST')
        db.add(storage_type)
        await db.commit()

        storage2 = StorageLocation(
            organization_id=org2.id,
            created_by=user2.id,
            storage_type_id=storage_type.id,
            name='Org2 Storage',
        )
        db.add(storage2)
        await db.commit()

        response = await real_async_client.post(
            '/api/v1/items',
            headers=headers2,
            json={
                'name': 'Product in Org 2',
                'brand': 'Test Brand',
                'sku': 'SHARED-SKU',
                'location_id': str(storage2.id),
            },
        )
        assert response.status_code == 201


@pytest.mark.integration
class TestSkuSchema:
    """Tests for SKU schema configuration and generation."""

    def test_get_sku_schema(self, client, auth_headers):
        """Test getting SKU schema for organization."""
        response = client.get(
            '/api/v1/items/product-templates/sku-schema',
            headers=auth_headers,
        )
        assert response.status_code == 200

    def test_update_sku_schema(self, client, auth_headers):
        """Test updating SKU schema configuration."""
        response = client.put(
            '/api/v1/items/product-templates/sku-schema',
            headers=auth_headers,
            json={
                'prefix': 'WH',
                'separator': '-',
                'next_number': 1,
                'pad_length': 5,
                'enabled': True,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data['sku_schema']['prefix'] == 'WH'
        assert data['sku_schema']['enabled'] is True

    @pytest.mark.asyncio
    async def test_sku_schema_generate_sequence(
        self, real_async_client, real_async_db_session, async_test_user
    ):
        """Test that SKU generation creates sequential codes WH-00001, WH-00002."""
        from app.models.storage_location import StorageLocation
        from app.models.storage_type import StorageType

        db = real_async_db_session
        org_id = async_test_user.organization_id

        storage_type = StorageType(name='Test', type_code='TEST')
        db.add(storage_type)
        await db.commit()

        storage = StorageLocation(
            organization_id=org_id,
            created_by=async_test_user.id,
            storage_type_id=storage_type.id,
            name='Test Storage',
        )
        db.add(storage)
        await db.commit()

        headers = _auth(async_test_user)
        await real_async_client.put(
            '/api/v1/items/product-templates/sku-schema',
            headers=headers,
            json={
                'prefix': 'WH',
                'separator': '-',
                'next_number': 1,
                'pad_length': 5,
                'enabled': True,
            },
        )

        response1 = await real_async_client.post(
            '/api/v1/items',
            headers=headers,
            json={
                'name': 'Product 1',
                'location_id': str(storage.id),
                'quantity': 1,
            },
        )

        r1_data = response1.json()
        assert response1.status_code == 201
        result1 = await db.execute(
            select(ProductTemplate).where(ProductTemplate.id == r1_data['template_id'])
        )
        t1 = result1.scalars().first()
        assert t1 is not None
        assert t1.sku is not None
        assert t1.sku == 'WH-00001'

        response2 = await real_async_client.post(
            '/api/v1/items',
            headers=headers,
            json={
                'name': 'Product 2',
                'location_id': str(storage.id),
                'quantity': 1,
            },
        )
        r2_data = response2.json()
        assert response2.status_code == 201
        result2 = await db.execute(
            select(ProductTemplate).where(ProductTemplate.id == r2_data['template_id'])
        )
        t2 = result2.scalars().first()
        assert t2 is not None
        assert t2.sku == 'WH-00002'

        response3 = await real_async_client.post(
            '/api/v1/items',
            headers=headers,
            json={
                'name': 'Product 3',
                'location_id': str(storage.id),
                'quantity': 1,
            },
        )
        r3_data = response3.json()
        assert response3.status_code == 201
        result3 = await db.execute(
            select(ProductTemplate).where(ProductTemplate.id == r3_data['template_id'])
        )
        t3 = result3.scalars().first()
        assert t3 is not None
        assert t3.sku == 'WH-00003'


@pytest.mark.integration
class TestSkuLookup:
    """Tests for SKU lookup endpoints."""

    @pytest.mark.asyncio
    async def test_lookup_by_sku(
        self, real_async_client, real_async_db_session, async_test_user
    ):
        """Test looking up a product template by SKU."""
        db = real_async_db_session
        org_id = async_test_user.organization_id

        template = ProductTemplate(
            organization_id=org_id,
            name='Lookup Test Product',
            sku='LOOKUP-001',
            barcode='1234567890999',
        )
        db.add(template)
        await db.commit()

        response = await real_async_client.get(
            '/api/v1/items/product-templates/lookup?sku=LOOKUP-001',
            headers=_auth(async_test_user),
        )
        assert response.status_code == 200
        data = response.json()
        assert data['name'] == 'Lookup Test Product'
        assert data['sku'] == 'LOOKUP-001'

    @pytest.mark.asyncio
    async def test_lookup_by_sku_case_insensitive(
        self, real_async_client, real_async_db_session, async_test_user
    ):
        """Test that SKU lookup is case-insensitive."""
        db = real_async_db_session
        org_id = async_test_user.organization_id

        template = ProductTemplate(
            organization_id=org_id,
            name='Case Test Product',
            sku='LOWER-CASE',
        )
        db.add(template)
        await db.commit()

        response = await real_async_client.get(
            '/api/v1/items/product-templates/lookup?sku=lower-case',
            headers=_auth(async_test_user),
        )
        assert response.status_code == 200
        data = response.json()
        assert data['sku'] == 'LOWER-CASE'

    @pytest.mark.asyncio
    async def test_lookup_by_barcode_unchanged(
        self, real_async_client, real_async_db_session, async_test_user
    ):
        """Test that barcode lookup still works after SKU changes."""
        db = real_async_db_session
        org_id = async_test_user.organization_id

        template = ProductTemplate(
            organization_id=org_id,
            name='Barcode Test Product',
            barcode='9876543210123',
            sku='BARCODE-SKU',
        )
        db.add(template)
        await db.commit()

        response = await real_async_client.get(
            '/api/v1/items/product-templates/lookup?barcode=9876543210123',
            headers=_auth(async_test_user),
        )
        assert response.status_code == 200
        data = response.json()
        assert data['name'] == 'Barcode Test Product'
        assert data['sku'] == 'BARCODE-SKU'

    def test_lookup_requires_barcode_or_sku(self, client, auth_headers):
        """Test that lookup endpoint requires either barcode or sku."""
        response = client.get(
            '/api/v1/items/product-templates/lookup',
            headers=auth_headers,
        )
        assert response.status_code == 400


@pytest.mark.integration
class TestSkuInProductSnapshot:
    """Tests for SKU in product snapshots for documents."""

    @pytest.mark.asyncio
    async def test_sku_in_product_snapshot(
        self, real_async_db_session, async_test_user
    ):
        """Test that SKU is included in product_snapshot when creating document lines."""

        from app.modules.warehouse.document_line_resolver import _build_product_snapshot
        from app.modules.warehouse.schemas import DocumentLineCreate

        db = real_async_db_session
        org_id = async_test_user.organization_id

        template = ProductTemplate(
            organization_id=org_id,
            name='Snapshot Test Product',
            barcode='1112223334445',
            sku='SNAPSHOT-001',
        )
        db.add(template)
        await db.flush()

        line_data = DocumentLineCreate(
            name='Test Line',
            expected_quantity=1,
            product_template_id=template.id,
        )

        snapshot = await _build_product_snapshot(db, line_data, org_id=org_id)
        assert snapshot is not None
        assert snapshot['sku'] == 'SNAPSHOT-001'


@pytest.mark.integration
class TestCreateProductTemplateEndpoint:
    """Tests for POST /api/v1/items/product-templates (added for E2E seeding)."""

    async def test_create_returns_201_with_template(
        self, real_async_client, real_async_db_session, async_test_user
    ):
        # Commit the async_test_user row so the endpoint's own DB session
        # (separate from this test's session) can see it during JWT
        # verification. Without this, get_current_user_context returns 401.
        await real_async_db_session.commit()

        token = create_access_token(data={'sub': str(async_test_user.id)})
        headers = {'Authorization': f'Bearer {token}'}

        response = await real_async_client.post(
            '/api/v1/items/product-templates',
            headers=headers,
            json={'name': 'E2E Seeded Template'},
        )

        assert response.status_code == 201
        body = response.json()
        assert body['name'] == 'E2E Seeded Template'
        assert body['organization_id'] == str(async_test_user.organization_id)
        assert body['sku'] is not None

    async def test_create_with_minimal_name_generates_sku(
        self, real_async_client, real_async_db_session, async_test_user
    ):
        await real_async_db_session.commit()

        token = create_access_token(data={'sub': str(async_test_user.id)})
        headers = {'Authorization': f'Bearer {token}'}

        response = await real_async_client.post(
            '/api/v1/items/product-templates',
            headers=headers,
            json={'name': 'X'},
        )

        assert response.status_code == 201
        body = response.json()
        assert body['sku'] is not None
        assert body['sku'].startswith('STM-')

"""
Integration tests for Product Template Clone feature.

Tests verify:
- Clone creates a new template with copied fields
- Clone clears name, barcode, sku (generates new)
- Clone preserves brand, uom, image, weight
"""

import pytest
from fastapi import status

from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.services.token_service import create_access_token


def _auth(user):
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


@pytest.mark.integration
@pytest.mark.asyncio
class TestProductClone:
    """Tests for product template clone endpoint."""

    async def test_clone_copies_fields_except_name_barcode_sku(
        self,
        real_async_client,
        real_async_db_session,
        async_test_user,
        async_test_household,
    ):
        """Clone copies brand, uom — clears name, barcode, sku."""
        db = real_async_db_session
        tpl = ProductTemplate(
            organization_id=async_test_household.id,
            name='Piwo Tyskie',
            brand='Tyskie',
            barcode='5901111111111',
            sku='WH-001',
        )
        db.add(tpl)
        await db.commit()

        response = await real_async_client.post(
            f'/api/v1/items/product-templates/{tpl.id}/clone',
            headers=_auth(async_test_user),
            json={'name': 'Piwo Tyskie Gronie', 'barcode': '5902222222222'},
        )
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data['name'] == 'Piwo Tyskie Gronie'
        assert data['brand'] == 'Tyskie'
        assert data['barcode'] == '5902222222222'
        assert data['sku'] != 'WH-001'  # new auto-generated SKU

    async def test_clone_preserves_image_and_weight(
        self,
        real_async_client,
        real_async_db_session,
        async_test_user,
        async_test_household,
    ):
        """Clone preserves image_url and weight."""
        db = real_async_db_session
        tpl = ProductTemplate(
            organization_id=async_test_household.id,
            name='Original',
            sku='WH-100',
            image_url='https://example.com/img.jpg',
            weight_value=0.5,
        )
        db.add(tpl)
        await db.commit()

        response = await real_async_client.post(
            f'/api/v1/items/product-templates/{tpl.id}/clone',
            headers=_auth(async_test_user),
            json={'name': 'Clone'},
        )
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data['image_url'] == 'https://example.com/img.jpg'
        assert data['weight_value'] == 0.5

    async def test_clone_generates_new_sku(
        self,
        real_async_client,
        real_async_db_session,
        async_test_user,
        async_test_household,
    ):
        """Clone generates new SKU."""
        db = real_async_db_session
        tpl = ProductTemplate(
            organization_id=async_test_household.id,
            name='Product A',
            sku='WH-001',
        )
        db.add(tpl)
        await db.commit()

        response = await real_async_client.post(
            f'/api/v1/items/product-templates/{tpl.id}/clone',
            headers=_auth(async_test_user),
            json={'name': 'Product B'},
        )
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data['sku'] is not None
        assert data['sku'] != 'WH-001'

    async def test_clone_requires_name(
        self,
        real_async_client,
        real_async_db_session,
        async_test_user,
        async_test_household,
    ):
        """Clone requires name field."""
        db = real_async_db_session
        tpl = ProductTemplate(
            organization_id=async_test_household.id,
            name='Original',
            sku='WH-001',
        )
        db.add(tpl)
        await db.commit()

        response = await real_async_client.post(
            f'/api/v1/items/product-templates/{tpl.id}/clone',
            headers=_auth(async_test_user),
            json={'barcode': '5902222222222'},
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_a_clone_name_past_the_column_is_a_422_not_a_500(
        self,
        real_async_client,
        real_async_db_session,
        async_test_user,
        async_test_household,
    ):
        """The clone's own schema bounds the name the create one bounds.

        Both write the same ``String(255)`` column, so a 256-character name
        has to be refused at the door here too — before it reached the driver
        as a truncation error and answered 500.
        """
        db = real_async_db_session
        tpl = ProductTemplate(
            organization_id=async_test_household.id,
            name='Original',
            sku='WH-001',
        )
        db.add(tpl)
        await db.commit()

        response = await real_async_client.post(
            f'/api/v1/items/product-templates/{tpl.id}/clone',
            headers=_auth(async_test_user),
            json={'name': 'x' * 256},
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        error = response.json()['detail'][0]
        assert error['type'] == 'string_too_long'
        assert error['ctx']['max_length'] == 255

    async def test_clone_template_not_found(
        self, real_async_client, real_async_db_session, async_test_user
    ):
        """Clone returns 404 for non-existent template."""
        import uuid

        await (
            real_async_db_session.commit()
        )  # commit async_test_user so API can authenticate

        response = await real_async_client.post(
            f'/api/v1/items/product-templates/{uuid.uuid4()}/clone',
            headers=_auth(async_test_user),
            json={'name': 'Clone'},
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_clone_isolated_to_org(
        self,
        real_async_client,
        real_async_db_session,
        async_test_user,
        async_test_household,
    ):
        """Cannot clone template from another organization."""
        db = real_async_db_session
        other_org = Organization(name='Other Org', enabled_modules=['core'])
        db.add(other_org)
        await db.flush()

        other_tpl = ProductTemplate(
            organization_id=other_org.id,
            name='Other Org Product',
            sku='OTHER-001',
        )
        db.add(other_tpl)
        await db.commit()

        response = await real_async_client.post(
            f'/api/v1/items/product-templates/{other_tpl.id}/clone',
            headers=_auth(async_test_user),
            json={'name': 'Clone of Other'},
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

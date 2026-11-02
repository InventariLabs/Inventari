"""
Integration tests for logistics fields on POST /items/product-templates.

Regression for the silent drop: ``ProductTemplateCreate`` accepted
``uom_id`` / ``weight_value`` / ``weight_uom_id`` / ``volume_value`` /
``volume_uom_id`` (and ``min_quantity``), but the handler never forwarded
them, so a request carrying ``weight_value: 400`` got 201 and a template
with ``weight_value: null``. The piece↔measure bridge used by recipes
availability only works for templates with a pack measure, so the drop
was not cosmetic.
"""

import pytest
from fastapi import status

from app.models.uom import Uom, UomCategory
from app.services.token_service import create_access_token


def _auth(user):
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


@pytest.mark.integration
@pytest.mark.asyncio
class TestProductTemplateCreateLogisticsFields:
    """POST /items/product-templates persists the logistics fields."""

    async def test_create_persists_uom_and_pack_measures(
        self,
        real_async_client,
        real_async_db_session,
        async_test_user,
        async_test_household,
    ):
        db = real_async_db_session
        weight_cat = UomCategory(organization_id=async_test_household.id, name='Weight')
        count_cat = UomCategory(organization_id=async_test_household.id, name='Count')
        volume_cat = UomCategory(organization_id=async_test_household.id, name='Volume')
        db.add_all([weight_cat, count_cat, volume_cat])
        await db.flush()
        gram = Uom(
            organization_id=async_test_household.id,
            category_id=weight_cat.id,
            name='gram',
            symbol='g',
        )
        piece = Uom(
            organization_id=async_test_household.id,
            category_id=count_cat.id,
            name='piece',
            symbol='pcs',
        )
        liter = Uom(
            organization_id=async_test_household.id,
            category_id=volume_cat.id,
            name='liter',
            symbol='l',
        )
        db.add_all([gram, piece, liter])
        await db.commit()

        response = await real_async_client.post(
            '/api/v1/items/product-templates',
            headers=_auth(async_test_user),
            json={
                'name': 'Canned Chickpeas',
                'uom_id': str(piece.id),
                'weight_value': 400,
                'weight_uom_id': str(gram.id),
                'volume_value': 0.4,
                'volume_uom_id': str(liter.id),
                'min_quantity': 2,
            },
        )
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data['uom_id'] == str(piece.id)
        assert data['weight_value'] == 400
        assert data['weight_uom_id'] == str(gram.id)
        assert data['volume_value'] == 0.4
        assert data['volume_uom_id'] == str(liter.id)
        assert data['min_quantity'] == 2

        # Re-read: the values must survive the round trip, not just echo.
        reread = await real_async_client.get(
            f'/api/v1/items/product-templates/{data["id"]}',
            headers=_auth(async_test_user),
        )
        assert reread.status_code == status.HTTP_200_OK
        again = reread.json()
        assert again['uom_id'] == str(piece.id)
        assert again['weight_value'] == 400
        assert again['weight_uom_id'] == str(gram.id)
        assert again['volume_value'] == 0.4
        assert again['volume_uom_id'] == str(liter.id)
        assert again['min_quantity'] == 2


@pytest.mark.integration
class TestProductTemplateTextBounds:
    """A string longer than its column is refused at the door, not by Postgres.

    The schema carried no ``max_length`` while the columns are ``String(n)``,
    so a 5000-character name reached the driver and came back as a 500
    (``StringDataRightTruncation``) with the generic fallback on the screen.
    Each bound below mirrors the column it lands in.
    """

    @pytest.mark.parametrize(
        ('field', 'length', 'column'),
        [
            pytest.param('name', 256, 255, id='name-over-255'),
            pytest.param('brand', 256, 255, id='brand-over-255'),
            pytest.param('barcode', 51, 50, id='barcode-over-50'),
            pytest.param('description', 501, 500, id='description-over-500'),
            pytest.param('image_url', 501, 500, id='image-url-over-500'),
        ],
    )
    def test_a_field_past_its_column_is_a_422_not_a_500(
        self, client, auth_headers, field, length, column
    ):
        payload = {'name': 'Canned Chickpeas'}
        payload[field] = 'x' * length

        response = client.post(
            '/api/v1/items/product-templates',
            headers=auth_headers,
            json=payload,
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        error = response.json()['detail'][0]
        assert error['type'] == 'string_too_long'
        assert error['loc'][-1] == field
        # The limit quoted back is the column's own length, not a guess.
        assert error['ctx']['max_length'] == column

    def test_the_refusal_speaks_the_sessions_language(self, client, auth_headers):
        """A bound only helps if its sentence is translated like every other 422."""
        response = client.post(
            '/api/v1/items/product-templates',
            headers={**auth_headers, 'Accept-Language': 'pl-PL,pl;q=0.9'},
            json={'name': 'x' * 256},
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        messages = [error['msg'] for error in response.json()['detail']]
        assert 'Może mieć najwyżej 255 znaków' in messages

    def test_a_name_the_column_can_hold_still_lands(self, client, auth_headers):
        """255 characters fit — the bound mirrors the column, it is not shorter."""
        response = client.post(
            '/api/v1/items/product-templates',
            headers=auth_headers,
            json={'name': 'x' * 255},
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert len(response.json()['name']) == 255

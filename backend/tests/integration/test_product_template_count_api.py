"""Integration tests for GET /items/product-templates/count.

The count answers "is the product catalog empty" before a form opens —
the search endpoint needs a 2-char query, so an empty catalog used to be
discoverable only inside an open picker. The count covers the same
visibility set as the picker: org-scoped + global templates.
"""

import pytest
from fastapi import status

from app.models.product_template import ProductTemplate
from app.services.token_service import create_access_token


def _auth(user) -> dict[str, str]:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


@pytest.mark.integration
@pytest.mark.asyncio
class TestProductTemplateCount:
    async def test_count_starts_at_zero(
        self,
        real_async_client,
        real_async_db_session,
        async_test_user,
        async_test_household,
    ):
        # The app's session is a separate connection — commit the fixture
        # session so the user is visible to the request (same pattern as
        # test_roles_router).
        await real_async_db_session.commit()
        response = await real_async_client.get(
            '/api/v1/items/product-templates/count', headers=_auth(async_test_user)
        )
        assert response.status_code == status.HTTP_200_OK, response.text
        assert response.json() == {'count': 0}

    async def test_count_includes_org_and_global_templates(
        self,
        real_async_client,
        real_async_db_session,
        async_test_user,
        async_test_household,
    ):
        db = real_async_db_session
        db.add_all(
            [
                ProductTemplate(
                    organization_id=async_test_household.id,
                    name='Org Template',
                ),
                ProductTemplate(
                    organization_id=async_test_household.id,
                    name='Org Template 2',
                ),
                # Global templates are visible to every org's pickers.
                ProductTemplate(organization_id=None, name='Global Template'),
            ]
        )
        await db.flush()
        await db.commit()

        response = await real_async_client.get(
            '/api/v1/items/product-templates/count', headers=_auth(async_test_user)
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {'count': 3}

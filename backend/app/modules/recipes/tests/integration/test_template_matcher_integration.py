"""Integration test for template_matcher catalog ordering.

Verifies that templates referenced by this org's recipes surface first in the
LLM-matching catalog, ahead of alphabetically-earlier but unused templates.

Tier 2 migration: tests the CoreAPI surface
``core_api.product_templates.list_for_org_with_recipe_usage_async``
instead of the deleted module-local ``_fetch_templates`` helper.
"""

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.public_api import core_api
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.user import User
from app.modules.recipes.models import Recipe, RecipeIngredient
from app.services.auth_service import get_password_hash


@pytest.fixture
async def tm_org(real_async_db_session: AsyncSession) -> Organization:
    org = Organization(
        name='Template Matcher Org',
        enabled_modules=['core', 'items', 'locations', 'categories', 'recipes'],
    )
    real_async_db_session.add(org)
    await real_async_db_session.commit()
    await real_async_db_session.refresh(org)
    return org


@pytest.fixture
async def tm_user(real_async_db_session: AsyncSession, tm_org: Organization) -> User:
    user = User(
        email=f'tm_{uuid4().hex[:8]}@test.com',
        hashed_password=get_password_hash('pass'),
        full_name='TM User',
        organization_id=tm_org.id,
        role='admin',
        is_active=True,
    )
    real_async_db_session.add(user)
    await real_async_db_session.commit()
    await real_async_db_session.refresh(user)
    return user


@pytest.mark.integration
class TestTemplateMatcherOrdering:
    async def test_used_templates_surface_first(
        self,
        real_async_db_session: AsyncSession,
        tm_org: Organization,
        tm_user: User,
    ) -> None:
        """Templates referenced by this org's recipes rank above unused ones,
        regardless of alphabetical order."""
        org_id = tm_org.id

        # 'Aaa Unused' sorts alphabetically before 'Zzz Used' but is unreferenced.
        unused = ProductTemplate(organization_id=org_id, name='Aaa Unused Template')
        used = ProductTemplate(organization_id=org_id, name='Zzz Used Template')
        real_async_db_session.add_all([unused, used])
        await real_async_db_session.commit()
        await real_async_db_session.refresh(unused)
        await real_async_db_session.refresh(used)

        recipe = Recipe(
            organization_id=org_id,
            created_by=tm_user.id,
            name='Ranking Recipe',
            servings=2,
        )
        real_async_db_session.add(recipe)
        await real_async_db_session.commit()
        await real_async_db_session.refresh(recipe)
        real_async_db_session.add(
            RecipeIngredient(
                recipe_id=recipe.id,
                template_id=used.id,
                name='Zzz Used Template',
                quantity=Decimal('100'),
            )
        )
        await real_async_db_session.commit()

        templates = (
            await core_api.product_templates.list_for_org_with_recipe_usage_async(
                real_async_db_session, org_id
            )
        )
        names = [t.name for t in templates]
        assert 'Aaa Unused Template' in names
        assert 'Zzz Used Template' in names
        assert names.index('Zzz Used Template') < names.index('Aaa Unused Template')

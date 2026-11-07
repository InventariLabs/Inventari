"""Integration tests for ``recipes._picking_document``.

The document-registration helper is cross-module orchestration: it reads its
``core_api`` dependencies and the documents public API, and only the
``RecipeIngredient`` lookup plus the final ``db.commit`` touch the database.
Those DB parts run on ``real_async_db_session``; the CoreAPI and documents
API calls are mocked so the tests stay focused on this file's branches.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.user import User
from app.modules.recipes._picking_document import register_picking_as_document_async
from app.modules.recipes.models import Recipe, RecipeIngredient
from app.modules.warehouse.warehouse_api import warehouse_api


@pytest.fixture
async def pick_doc_org(real_async_db_session: AsyncSession) -> Organization:
    org = Organization(
        name='Picking Doc Org', enabled_modules=['core', 'recipes', 'warehouse']
    )
    real_async_db_session.add(org)
    await real_async_db_session.flush()
    return org


@pytest.fixture
async def pick_doc_user(
    real_async_db_session: AsyncSession, pick_doc_org: Organization
) -> User:
    return await ModuleTestHelper.create_user_async(
        real_async_db_session,
        pick_doc_org,
        email='pick-doc@example.com',
        role='admin',
    )


async def _recipe_and_ingredient(
    db: AsyncSession, org: Organization, user: User
) -> tuple[Recipe, RecipeIngredient]:
    recipe = Recipe(
        organization_id=org.id,
        name='Test Recipe',
        servings=1,
        created_by=user.id,
    )
    db.add(recipe)
    await db.flush()

    ingredient = RecipeIngredient(
        recipe_id=recipe.id,
        name='Flour',
        quantity=Decimal('1'),
        sort_order=0,
    )
    db.add(ingredient)
    await db.flush()
    return recipe, ingredient


def _session_with_picked(
    recipe: Recipe, ingredient: RecipeIngredient, *, recipe_loaded: bool = True
) -> tuple[MagicMock, MagicMock]:
    session = MagicMock()
    session.id = uuid.uuid4()
    session.recipe_id = recipe.id
    session.recipe = recipe if recipe_loaded else None
    session.notes = None

    item = MagicMock()
    item.status = 'picked'
    item.item_id = uuid.uuid4()
    item.ingredient_id = ingredient.id
    item.quantity_consumed = Decimal('1')
    item.consumed_valuation_rate = Decimal('5.00')
    session.items = [item]
    return session, item


def _core_mock(*, feature_on: bool, docs_enabled: bool) -> MagicMock:
    mock_core = MagicMock()
    mock_core.settings.get_async = AsyncMock(return_value=feature_on)
    mock_core.organizations.is_module_enabled_async = AsyncMock(
        return_value=docs_enabled
    )
    return mock_core


class _ItemIdThatBecomesNone:
    """A picked item whose ``item_id`` is truthy for the filter, then None.

    ``register_picking_as_document_async`` filters on ``i.item_id`` before
    reading ``picked[0].item_id`` again inside the block. This double is
    used to cover the defensive ``if first_item_id is None`` branch.
    """

    status = 'picked'

    def __init__(self, ingredient_id: uuid.UUID) -> None:
        self.ingredient_id = ingredient_id
        self._reads = 0

    @property
    def item_id(self) -> uuid.UUID | None:
        self._reads += 1
        return uuid.uuid4() if self._reads == 1 else None


@pytest.mark.integration
class TestRegisterPickingAsDocument:
    async def test_feature_off_returns_none(
        self,
        real_async_db_session: AsyncSession,
        pick_doc_org: Organization,
        pick_doc_user: User,
    ) -> None:
        recipe, ingredient = await _recipe_and_ingredient(
            real_async_db_session, pick_doc_org, pick_doc_user
        )
        session, _ = _session_with_picked(recipe, ingredient)
        mock_core = _core_mock(feature_on=False, docs_enabled=True)

        with patch('app.modules.recipes._picking_document.core_api', mock_core):
            result = await register_picking_as_document_async(
                real_async_db_session, session, pick_doc_org.id, pick_doc_user.id
            )

        assert result is None

    async def test_warehouse_module_disabled_returns_none(
        self,
        real_async_db_session: AsyncSession,
        pick_doc_org: Organization,
        pick_doc_user: User,
    ) -> None:
        recipe, ingredient = await _recipe_and_ingredient(
            real_async_db_session, pick_doc_org, pick_doc_user
        )
        session, _ = _session_with_picked(recipe, ingredient)
        mock_core = _core_mock(feature_on=True, docs_enabled=False)

        with patch('app.modules.recipes._picking_document.core_api', mock_core):
            result = await register_picking_as_document_async(
                real_async_db_session, session, pick_doc_org.id, pick_doc_user.id
            )

        assert result is None

    async def test_no_picked_items_returns_none(
        self,
        real_async_db_session: AsyncSession,
        pick_doc_org: Organization,
        pick_doc_user: User,
    ) -> None:
        recipe, ingredient = await _recipe_and_ingredient(
            real_async_db_session, pick_doc_org, pick_doc_user
        )
        session, _ = _session_with_picked(recipe, ingredient)
        session.items = []
        mock_core = _core_mock(feature_on=True, docs_enabled=True)

        with patch('app.modules.recipes._picking_document.core_api', mock_core):
            result = await register_picking_as_document_async(
                real_async_db_session, session, pick_doc_org.id, pick_doc_user.id
            )

        assert result is None

    async def test_first_item_without_location_returns_none(
        self,
        real_async_db_session: AsyncSession,
        pick_doc_org: Organization,
        pick_doc_user: User,
    ) -> None:
        recipe, ingredient = await _recipe_and_ingredient(
            real_async_db_session, pick_doc_org, pick_doc_user
        )
        session, _ = _session_with_picked(recipe, ingredient)
        mock_core = _core_mock(feature_on=True, docs_enabled=True)
        first_item = MagicMock()
        first_item.location_id = None
        mock_core.items.get_async = AsyncMock(return_value=first_item)

        with patch('app.modules.recipes._picking_document.core_api', mock_core):
            result = await register_picking_as_document_async(
                real_async_db_session, session, pick_doc_org.id, pick_doc_user.id
            )

        assert result is None

    async def test_happy_path_creates_document_and_links_session(
        self,
        real_async_db_session: AsyncSession,
        pick_doc_org: Organization,
        pick_doc_user: User,
    ) -> None:
        recipe, ingredient = await _recipe_and_ingredient(
            real_async_db_session, pick_doc_org, pick_doc_user
        )
        session, _ = _session_with_picked(recipe, ingredient)
        mock_core = _core_mock(feature_on=True, docs_enabled=True)
        first_item = MagicMock()
        first_item.location_id = uuid.uuid4()
        mock_core.items.get_async = AsyncMock(return_value=first_item)

        doc = MagicMock()
        doc.id = uuid.uuid4()
        with (
            patch('app.modules.recipes._picking_document.core_api', mock_core),
            patch.object(
                warehouse_api,
                'create_document_draft_async',
                new_callable=AsyncMock,
                return_value=doc,
            ) as mock_create,
        ):
            result = await register_picking_as_document_async(
                real_async_db_session, session, pick_doc_org.id, pick_doc_user.id
            )

        assert result == str(doc.id)
        assert f'document: {doc.id}' in (session.notes or '')
        mock_create.assert_awaited_once()

    async def test_recipe_relation_missing_falls_back_to_id(
        self,
        real_async_db_session: AsyncSession,
        pick_doc_org: Organization,
        pick_doc_user: User,
    ) -> None:
        recipe, ingredient = await _recipe_and_ingredient(
            real_async_db_session, pick_doc_org, pick_doc_user
        )
        session, _ = _session_with_picked(recipe, ingredient, recipe_loaded=False)
        mock_core = _core_mock(feature_on=True, docs_enabled=True)
        first_item = MagicMock()
        first_item.location_id = uuid.uuid4()
        mock_core.items.get_async = AsyncMock(return_value=first_item)

        doc = MagicMock()
        doc.id = uuid.uuid4()
        with (
            patch('app.modules.recipes._picking_document.core_api', mock_core),
            patch.object(
                warehouse_api,
                'create_document_draft_async',
                new_callable=AsyncMock,
                return_value=doc,
            ) as mock_create,
        ):
            await register_picking_as_document_async(
                real_async_db_session, session, pick_doc_org.id, pick_doc_user.id
            )

        data = cast(Any, mock_create.call_args.args[2])
        assert str(recipe.id) in data.notes

    async def test_document_creation_error_returns_none(
        self,
        real_async_db_session: AsyncSession,
        pick_doc_org: Organization,
        pick_doc_user: User,
    ) -> None:
        recipe, ingredient = await _recipe_and_ingredient(
            real_async_db_session, pick_doc_org, pick_doc_user
        )
        session, _ = _session_with_picked(recipe, ingredient)
        mock_core = _core_mock(feature_on=True, docs_enabled=True)
        first_item = MagicMock()
        first_item.location_id = uuid.uuid4()
        mock_core.items.get_async = AsyncMock(return_value=first_item)

        with (
            patch('app.modules.recipes._picking_document.core_api', mock_core),
            patch.object(
                warehouse_api,
                'create_document_draft_async',
                new_callable=AsyncMock,
                side_effect=RuntimeError('document creation failed'),
            ),
        ):
            result = await register_picking_as_document_async(
                real_async_db_session, session, pick_doc_org.id, pick_doc_user.id
            )

        assert result is None

    async def test_item_id_becoming_none_returns_none(
        self,
        real_async_db_session: AsyncSession,
        pick_doc_org: Organization,
        pick_doc_user: User,
    ) -> None:
        recipe, ingredient = await _recipe_and_ingredient(
            real_async_db_session, pick_doc_org, pick_doc_user
        )
        session = MagicMock()
        session.id = uuid.uuid4()
        session.recipe_id = recipe.id
        session.recipe = recipe
        session.notes = None
        session.items = [_ItemIdThatBecomesNone(ingredient.id)]
        mock_core = _core_mock(feature_on=True, docs_enabled=True)

        with patch('app.modules.recipes._picking_document.core_api', mock_core):
            result = await register_picking_as_document_async(
                real_async_db_session, session, pick_doc_org.id, pick_doc_user.id
            )

        assert result is None

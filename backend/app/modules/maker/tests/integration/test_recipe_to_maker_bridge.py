"""Integration tests for the recipes → maker bridge (one-way snapshot).

Test contract:
  - Happy path: culinary recipe → ``POST /maker/recipes/from-recipe`` creates
    a maker recipe stamped with ``source_recipe_id`` + ``source_snapshot_at``
    and BOM lines derived from template-linked ingredients
  - Free-text ingredients (no template_id) are skipped — no stock to consume
  - Defaults: name → culinary name, batch_yield_qty → culinary servings
  - Idempotency: same (output_template_id, source_recipe_id) reuses the snapshot
  - Missing culinary recipe / wrong org → 404 (graceful degradation)
  - recipes_api.get_recipe_snapshot_async is org-scoped and returns None
    for missing recipes (never raises)
  - No synchronisation: the snapshot is frozen (source_recipe_id is a plain
    UUID without FK — later recipe edits never propagate)
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.uom import Uom, UomCategory
from app.models.user import User
from app.modules.maker.models import MakerRecipe
from app.modules.recipes.models.recipe import Recipe, RecipeIngredient

pytestmark = pytest.mark.integration


def _make_template(db: Session, org: Organization, name: str) -> ProductTemplate:
    template = ProductTemplate(organization_id=org.id, name=name)
    db.add(template)
    db.commit()
    db.refresh(template)
    return template


def _make_uom(db: Session, symbol: str, name: str = '') -> Uom:
    category = UomCategory(name='Test Category')
    db.add(category)
    db.flush()
    uom = Uom(
        category_id=category.id,
        name=name or symbol,
        symbol=symbol,
        factor=1.0,
        is_reference=True,
        is_system=False,
    )
    db.add(uom)
    db.commit()
    db.refresh(uom)
    return uom


def _make_culinary_recipe(
    db: Session,
    org: Organization,
    *,
    name: str = 'Fruit Jam',
    servings: int = 6,
    ingredients: list[RecipeIngredient] | None = None,
    created_by: uuid.UUID,
) -> Recipe:
    recipe = Recipe(
        organization_id=org.id,
        name=name,
        servings=servings,
        created_by=created_by,
    )
    db.add(recipe)
    db.flush()
    for ing in ingredients or []:
        ing.recipe_id = recipe.id
        db.add(ing)
    db.commit()
    db.refresh(recipe)
    return recipe


class TestFromRecipeEndpoint:
    """POST /maker/recipes/from-recipe."""

    def test_from_recipe_creates_snapshot_with_lines(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_user: User,
        db_session: Session,
    ) -> None:
        fruit = _make_template(db_session, mk_org, 'Fruit')
        output = _make_template(db_session, mk_org, 'Jam Jar')
        uom_kg = _make_uom(db_session, 'kg')

        culinary = _make_culinary_recipe(
            db_session,
            mk_org,
            ingredients=[
                RecipeIngredient(
                    name='fruit',
                    template_id=fruit.id,
                    quantity=Decimal('2.000'),
                    uom_id=uom_kg.id,
                ),
                # Free-text ingredient — no template, must be skipped.
                RecipeIngredient(name='a pinch of love', quantity=Decimal('1')),
            ],
            created_by=mk_user.id,
        )

        resp = client.post(
            '/api/v1/maker/recipes/from-recipe',
            headers=mk_auth_headers,
            json={
                'source_recipe_id': str(culinary.id),
                'output_template_id': str(output.id),
            },
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body['name'] == 'Fruit Jam'  # default = culinary name
        assert body['batch_yield_qty'] == '6.0000'  # default = servings
        assert body['is_default'] is True
        assert body['source_recipe_id'] == str(culinary.id)
        assert body['source_snapshot_at'] is not None
        assert body['output_template_name'] == 'Jam Jar'

        # BOM lines: only template-linked ingredients, correct mapping.
        lines = body['lines']
        assert len(lines) == 1
        line = lines[0]
        assert line['child_template_id'] == str(fruit.id)
        assert line['qty_per_batch'] == '2.0000'
        assert line['uom_id'] == str(uom_kg.id)
        assert line['unit'] == 'kg'
        assert line['parent_template_id'] == str(output.id)

    def test_from_recipe_defaults_to_pieces_without_uom(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_user: User,
        db_session: Session,
    ) -> None:
        egg = _make_template(db_session, mk_org, 'Egg')
        output = _make_template(db_session, mk_org, 'Cake')

        culinary = _make_culinary_recipe(
            db_session,
            mk_org,
            name='Sponge Cake',
            servings=8,
            ingredients=[
                RecipeIngredient(
                    name='egg',
                    template_id=egg.id,
                    quantity=Decimal('3'),
                    uom_id=None,
                ),
            ],
            created_by=mk_user.id,
        )

        resp = client.post(
            '/api/v1/maker/recipes/from-recipe',
            headers=mk_auth_headers,
            json={
                'source_recipe_id': str(culinary.id),
                'output_template_id': str(output.id),
            },
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body['batch_yield_qty'] == '8.0000'
        assert body['lines'][0]['unit'] == 'szt'
        assert body['lines'][0]['uom_id'] is None

    def test_from_recipe_honours_explicit_overrides(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_user: User,
        db_session: Session,
    ) -> None:
        output = _make_template(db_session, mk_org, 'Jam Jar XL')
        culinary = _make_culinary_recipe(
            db_session,
            mk_org,
            name='Fruit Jam',
            servings=6,
            created_by=mk_user.id,
        )

        resp = client.post(
            '/api/v1/maker/recipes/from-recipe',
            headers=mk_auth_headers,
            json={
                'source_recipe_id': str(culinary.id),
                'output_template_id': str(output.id),
                'name': 'Commercial Jam',
                'batch_yield_qty': '24',
            },
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body['name'] == 'Commercial Jam'
        assert body['batch_yield_qty'] == '24.0000'
        assert body['source_recipe_id'] == str(culinary.id)

    def test_from_recipe_is_idempotent(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_user: User,
        db_session: Session,
    ) -> None:
        fruit = _make_template(db_session, mk_org, 'Fruit')
        output = _make_template(db_session, mk_org, 'Jam Jar')
        culinary = _make_culinary_recipe(
            db_session,
            mk_org,
            ingredients=[
                RecipeIngredient(
                    name='fruit',
                    template_id=fruit.id,
                    quantity=Decimal('2'),
                ),
            ],
            created_by=mk_user.id,
        )
        payload = {
            'source_recipe_id': str(culinary.id),
            'output_template_id': str(output.id),
        }

        first = client.post(
            '/api/v1/maker/recipes/from-recipe',
            headers=mk_auth_headers,
            json=payload,
        )
        assert first.status_code == 201, first.text
        second = client.post(
            '/api/v1/maker/recipes/from-recipe',
            headers=mk_auth_headers,
            json=payload,
        )
        assert second.status_code == 201, second.text
        assert first.json()['id'] == second.json()['id']
        # Only the first call made anything. A caller that abandons the second
        # half of the bridge cleans up after itself, and must not delete a
        # snapshot that was already there.
        assert first.json()['created'] is True
        assert second.json()['created'] is False
        # Still exactly one snapshot recipe + one line for this pair.
        recipes = (
            db_session.query(MakerRecipe)
            .filter_by(
                organization_id=mk_org.id,
                output_template_id=output.id,
                source_recipe_id=culinary.id,
            )
            .all()
        )
        assert len(recipes) == 1
        assert len(recipes[0].lines) == 1

    def test_from_recipe_missing_culinary_recipe_returns_404(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        output = _make_template(db_session, mk_org, 'Jam Jar')
        resp = client.post(
            '/api/v1/maker/recipes/from-recipe',
            headers=mk_auth_headers,
            json={
                'source_recipe_id': str(uuid.uuid4()),
                'output_template_id': str(output.id),
            },
        )
        assert resp.status_code == 404, resp.text

    def test_from_recipe_is_org_scoped(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        h: ModuleTestHelper,
        db_session: Session,
    ) -> None:
        other_org = h.create_org('Other Org', ['core', 'maker'])
        other_user = h.create_user(other_org, email='other@example.com')
        output = _make_template(db_session, mk_org, 'Jam Jar')
        foreign_culinary = _make_culinary_recipe(
            db_session,
            other_org,
            name='Foreign Jam',
            created_by=other_user.id,
        )

        resp = client.post(
            '/api/v1/maker/recipes/from-recipe',
            headers=mk_auth_headers,
            json={
                'source_recipe_id': str(foreign_culinary.id),
                'output_template_id': str(output.id),
            },
        )
        # Culinary recipe of another org is invisible → 404, no data leak.
        assert resp.status_code == 404, resp.text

    def test_from_recipe_missing_output_template_returns_404(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_user: User,
        db_session: Session,
    ) -> None:
        culinary = _make_culinary_recipe(db_session, mk_org, created_by=mk_user.id)
        resp = client.post(
            '/api/v1/maker/recipes/from-recipe',
            headers=mk_auth_headers,
            json={
                'source_recipe_id': str(culinary.id),
                'output_template_id': str(uuid.uuid4()),
            },
        )
        assert resp.status_code == 404, resp.text

    def test_from_recipe_second_snapshot_for_same_product_is_not_default(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_user: User,
        db_session: Session,
    ) -> None:
        """Bridging a DIFFERENT culinary recipe to a product that already has
        a default maker recipe must not hit the partial unique index (500/409)
        — the new snapshot is created as non-default instead."""
        output = _make_template(db_session, mk_org, 'Jam Jar')
        culinary_a = _make_culinary_recipe(
            db_session, mk_org, name='Jam A', created_by=mk_user.id
        )
        culinary_b = _make_culinary_recipe(
            db_session, mk_org, name='Jam B', created_by=mk_user.id
        )

        first = client.post(
            '/api/v1/maker/recipes/from-recipe',
            headers=mk_auth_headers,
            json={
                'source_recipe_id': str(culinary_a.id),
                'output_template_id': str(output.id),
            },
        )
        assert first.status_code == 201, first.text
        assert first.json()['is_default'] is True

        second = client.post(
            '/api/v1/maker/recipes/from-recipe',
            headers=mk_auth_headers,
            json={
                'source_recipe_id': str(culinary_b.id),
                'output_template_id': str(output.id),
            },
        )
        assert second.status_code == 201, second.text
        assert second.json()['is_default'] is False

        # Invariant "exactly one default" still holds for the product.
        defaults = (
            db_session.query(MakerRecipe)
            .filter_by(
                organization_id=mk_org.id,
                output_template_id=output.id,
                is_default=True,
            )
            .all()
        )
        assert len(defaults) == 1
        assert str(defaults[0].id) == first.json()['id']


class TestRecipeSnapshotApi:
    """recipes_api.get_recipe_snapshot_async — org-scoped read model."""

    def test_snapshot_maps_ingredients(
        self,
        mk_org: Organization,
        mk_user: User,
        db_session: Session,
        async_engine_fixture: Any,
    ) -> None:
        import asyncio

        from sqlalchemy.ext.asyncio import async_sessionmaker

        from app.modules.recipes.recipes_api import recipes_api

        fruit = _make_template(db_session, mk_org, 'Fruit')
        uom_kg = _make_uom(db_session, 'kg')
        culinary = _make_culinary_recipe(
            db_session,
            mk_org,
            servings=4,
            ingredients=[
                RecipeIngredient(
                    name='fruit',
                    template_id=fruit.id,
                    quantity=Decimal('1.5'),
                    uom_id=uom_kg.id,
                ),
                RecipeIngredient(name='salt', quantity=Decimal('1')),
            ],
            created_by=mk_user.id,
        )

        maker = async_sessionmaker(bind=async_engine_fixture, expire_on_commit=False)

        async def _fetch() -> tuple[Any, Any]:
            async with maker() as session:
                snapshot = await recipes_api.get_recipe_snapshot_async(
                    session, mk_org.id, culinary.id
                )
                return (
                    snapshot,
                    [
                        (i.template_id, i.quantity, i.uom_id, i.uom_symbol)
                        for i in snapshot.ingredients
                    ]
                    if snapshot is not None
                    else None,
                )

        snapshot, ingredients = asyncio.run(_fetch())
        assert snapshot is not None
        assert snapshot.name == 'Fruit Jam'
        assert snapshot.servings == 4
        assert len(ingredients) == 2
        linked = ingredients[0]
        assert linked == (fruit.id, Decimal('1.5'), uom_kg.id, 'kg')
        free_text = ingredients[1]
        assert free_text[0] is None  # template_id
        assert free_text[3] is None  # uom_symbol

    def test_snapshot_is_org_scoped(
        self,
        mk_org: Organization,
        h: ModuleTestHelper,
        db_session: Session,
        async_engine_fixture: Any,
    ) -> None:
        import asyncio

        from sqlalchemy.ext.asyncio import async_sessionmaker

        from app.modules.recipes.recipes_api import recipes_api

        other_org = h.create_org('Other Org', ['core', 'recipes'])
        other_user = h.create_user(other_org, email='other@example.com')
        foreign = _make_culinary_recipe(db_session, other_org, created_by=other_user.id)

        maker = async_sessionmaker(bind=async_engine_fixture, expire_on_commit=False)

        async def _fetch() -> bool:
            async with maker() as session:
                return (
                    await recipes_api.get_recipe_snapshot_async(
                        session, mk_org.id, foreign.id
                    )
                    is None
                )

        assert asyncio.run(_fetch()) is True

    def test_snapshot_missing_recipe_returns_none(
        self,
        mk_org: Organization,
        db_session: Session,
        async_engine_fixture: Any,
    ) -> None:
        import asyncio

        from sqlalchemy.ext.asyncio import async_sessionmaker

        from app.modules.recipes.recipes_api import recipes_api

        maker = async_sessionmaker(bind=async_engine_fixture, expire_on_commit=False)

        async def _fetch() -> bool:
            async with maker() as session:
                return (
                    await recipes_api.get_recipe_snapshot_async(
                        session, mk_org.id, uuid.uuid4()
                    )
                    is None
                )

        assert asyncio.run(_fetch()) is True


class TestGenericCreateStampsSnapshot:
    """POST /maker/recipes with source_recipe_id stamps source_snapshot_at."""

    def test_create_with_source_recipe_id_stamps_time(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        output = _make_template(db_session, mk_org, 'Jam Jar')
        source_id = uuid.uuid4()
        before = datetime.now(tz=UTC)

        resp = client.post(
            '/api/v1/maker/recipes',
            headers=mk_auth_headers,
            json={
                'output_template_id': str(output.id),
                'name': 'Snapshot Jam',
                'source_recipe_id': str(source_id),
            },
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body['source_recipe_id'] == str(source_id)
        assert body['source_snapshot_at'] is not None
        stamp = datetime.fromisoformat(
            body['source_snapshot_at'].replace('Z', '+00:00')
        )
        assert stamp >= before

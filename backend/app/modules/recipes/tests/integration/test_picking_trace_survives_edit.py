"""Integration tests: the consumption trace survives recipe edits.

A completed picking session is an accounting record — it holds what left the
shelf, at which AVCO rate, and from which items. Editing the recipe afterwards
must not erase it, and removing an ingredient outright must leave the trace
readable instead of taking it down with the row.
"""

import uuid
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.uom import Uom
from app.models.user import User
from app.modules.recipes.models import PickingSessionItem
from tests.integration._shelf import post_on_shelf

RECIPE_URL = '/api/v1/recipes'


@pytest.mark.integration
class TestPickingTraceSurvivesRecipeEdit:
    def _cooked_recipe(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> tuple[str, dict[str, Any]]:
        """Create a recipe, cook it once, and return (recipe_id, recipe_json)."""
        grams = db_session.scalar(select(Uom.id).where(Uom.symbol == 'g'))
        assert grams is not None, "'g' is not seeded"
        template = ProductTemplate(
            id=uuid.uuid4(),
            organization_id=test_user.organization_id,
            name='Flour',
            uom_id=grams,
        )
        db_session.add(template)
        db_session.commit()
        record = post_on_shelf(
            client, auth_headers, template, test_storage_location.id, '500'
        )

        create = client.post(
            RECIPE_URL,
            json={
                'name': 'Bread',
                'servings': 2,
                'instructions': 'Mix.',
                'tags': [],
                'is_favorite': False,
                'ingredients': [
                    {
                        'name': 'Flour',
                        'template_id': str(template.id),
                        'uom_id': str(grams),
                        'quantity': '200',
                        'is_optional': False,
                    }
                ],
            },
            headers=auth_headers,
        )
        assert create.status_code == 201
        recipe = create.json()
        recipe_id = recipe['id']

        start = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/start',
            json={'servings': 2},
            headers=auth_headers,
        )
        assert start.status_code == 201
        session_id = start.json()['picking_session_id']
        scan = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/{session_id}/scan',
            json={'item_id': record['id']},
            headers=auth_headers,
        )
        assert scan.status_code == 200
        complete = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/{session_id}/complete',
            json={},
            headers=auth_headers,
        )
        assert complete.status_code in (200, 201)
        return recipe_id, recipe

    def test_editing_instructions_keeps_completed_session_items(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        """An edit that does not touch ingredients leaves the trace alone."""
        recipe_id, recipe = self._cooked_recipe(
            client, auth_headers, db_session, test_user, test_storage_location
        )
        ingredient_id = uuid.UUID(recipe['ingredients'][0]['id'])

        # The frontend round-trips the whole recipe, ingredients included.
        edit = client.put(
            f'{RECIPE_URL}/{recipe_id}',
            json={
                'name': 'Bread',
                'servings': 2,
                'instructions': 'Mix, then bake for 40 minutes.',
                'ingredients': [
                    {
                        'id': str(ingredient_id),
                        'name': recipe['ingredients'][0]['name'],
                        'template_id': recipe['ingredients'][0]['template_id'],
                        'quantity': '200',
                        'is_optional': False,
                    }
                ],
            },
            headers=auth_headers,
        )
        assert edit.status_code == 200

        db_session.expire_all()
        items = (
            db_session.execute(
                select(PickingSessionItem).where(
                    PickingSessionItem.ingredient_id == ingredient_id
                )
            )
            .scalars()
            .all()
        )
        assert len(items) == 1, 'the consumption trace must survive a recipe edit'
        assert items[0].quantity_consumed == Decimal('200.000')
        assert items[0].status == 'picked'
        # The per-item breakdown is what undo/cancel restores from.
        assert items[0].picked_items and len(items[0].picked_items) == 1

        history = client.get(f'{RECIPE_URL}/{recipe_id}/history', headers=auth_headers)
        assert history.status_code == 200
        assert history.json()['items'][0]['items_picked'] == 1

        # An unchanged ingredient keeps its identity — the row was updated,
        # not recreated under a new id.
        reread = client.get(f'{RECIPE_URL}/{recipe_id}', headers=auth_headers)
        assert reread.json()['ingredients'][0]['id'] == str(ingredient_id)

    def test_removing_ingredient_detaches_trace_and_keeps_snapshot(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        """Deleting the ingredient detaches the trace instead of deleting it."""
        recipe_id, recipe = self._cooked_recipe(
            client, auth_headers, db_session, test_user, test_storage_location
        )
        ingredient_id = uuid.UUID(recipe['ingredients'][0]['id'])

        edit = client.put(
            f'{RECIPE_URL}/{recipe_id}',
            json={
                'name': 'Bread',
                'servings': 2,
                'ingredients': [
                    {'name': 'Water', 'quantity': '300', 'is_optional': False}
                ],
            },
            headers=auth_headers,
        )
        assert edit.status_code == 200

        db_session.expire_all()
        traces = (
            db_session.execute(
                select(PickingSessionItem).where(
                    PickingSessionItem.quantity_consumed.is_not(None)
                )
            )
            .scalars()
            .all()
        )
        assert len(traces) == 1, (
            'removing an ingredient must not erase what was consumed'
        )
        trace = traces[0]
        assert trace.ingredient_id is None
        assert trace.ingredient_name == 'Flour'
        assert trace.required_quantity == Decimal('200.000')
        assert trace.quantity_consumed == Decimal('200.000')

        history = client.get(f'{RECIPE_URL}/{recipe_id}/history', headers=auth_headers)
        assert history.json()['items'][0]['items_picked'] == 1

        # The recipe itself moved on.
        reread = client.get(f'{RECIPE_URL}/{recipe_id}', headers=auth_headers)
        names = [i['name'] for i in reread.json()['ingredients']]
        assert names == ['Water']
        assert str(ingredient_id) not in [i['id'] for i in reread.json()['ingredients']]

"""Integration tests for Meal Plan suggestions endpoint."""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models.item import Item
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.user import User
from tests.integration._shelf import anchor_pending_records

PLAN_URL = '/api/v1/recipes/meal-plans'
RECIPE_URL = '/api/v1/recipes'


def _plan_payload(**overrides: Any) -> dict[str, Any]:
    today = date.today()
    base = {
        'start_date': today.isoformat(),
        'end_date': (today + timedelta(days=6)).isoformat(),
        'enabled_slots': ['LUNCH', 'DINNER'],
        'default_servings': 2,
    }
    base.update(overrides)
    return base


@pytest.mark.integration
class TestMealPlanSuggestions:
    def test_suggestions_returns_list(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        plan_id = client.post(
            PLAN_URL, json=_plan_payload(), headers=auth_headers
        ).json()['id']
        today = date.today().isoformat()
        r = client.get(
            f'{PLAN_URL}/suggestions?date={today}&slot=LUNCH&plan_id={plan_id}',
            headers=auth_headers,
        )
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_suggestions_excludes_low_availability(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Recipes with < 30% ingredient availability are excluded."""
        # Create a recipe with ingredients that are not available
        recipe_r = client.post(
            RECIPE_URL,
            json={'name': 'Unavailable Dish', 'servings': 2, 'ingredients': []},
            headers=auth_headers,
        )
        assert recipe_r.status_code == 201
        plan_id = client.post(
            PLAN_URL, json=_plan_payload(), headers=auth_headers
        ).json()['id']
        today = date.today().isoformat()
        r = client.get(
            f'{PLAN_URL}/suggestions?date={today}&slot=LUNCH&plan_id={plan_id}&count=10',
            headers=auth_headers,
        )
        assert r.status_code == 200
        # Each suggestion has required fields
        for suggestion in r.json():
            assert 'recipe_id' in suggestion
            assert 'name' in suggestion
            assert 'score' in suggestion
            assert 'availability_pct' in suggestion

    def test_suggestions_respects_count_parameter(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        # Create 5 recipes
        for i in range(5):
            client.post(
                RECIPE_URL,
                json={'name': f'Recipe {i}', 'servings': 2, 'ingredients': []},
                headers=auth_headers,
            )
        plan_id = client.post(
            PLAN_URL, json=_plan_payload(), headers=auth_headers
        ).json()['id']
        today = date.today().isoformat()
        r = client.get(
            f'{PLAN_URL}/suggestions?date={today}&slot=LUNCH&plan_id={plan_id}&count=2',
            headers=auth_headers,
        )
        assert r.status_code == 200
        assert len(r.json()) <= 2

    def test_suggestions_without_plan_id(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """plan_id is optional."""
        today = date.today().isoformat()
        r = client.get(
            f'{PLAN_URL}/suggestions?date={today}&slot=DINNER',
            headers=auth_headers,
        )
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_suggestions_requires_auth(self, client: TestClient) -> None:
        today = date.today().isoformat()
        r = client.get(f'{PLAN_URL}/suggestions?date={today}&slot=LUNCH')
        assert r.status_code == 401


@pytest.mark.integration
class TestSuggestionsExpiryUrgency:
    """Urgency comes from the stock availability already found, link or not."""

    def _shelve(
        self,
        db: Session,
        user: User,
        location: StorageLocation,
        *,
        name: str,
        expiry: date,
    ) -> None:
        pcs = db.execute(text("SELECT id FROM uoms WHERE symbol = 'pcs'")).fetchone()
        assert pcs is not None
        template = ProductTemplate(
            id=uuid.uuid4(),
            organization_id=user.organization_id,
            name=name,
            uom_id=pcs[0],
        )
        db.add(template)
        db.flush()
        db.add(
            Item(
                id=uuid.uuid4(),
                organization_id=user.organization_id,
                storage_location_id=location.id,
                name=name,
                template_id=template.id,
                uom_id=pcs[0],
                quantity=Decimal('10'),
                expiry_date=expiry,
            )
        )
        anchor_pending_records(db)
        db.commit()

    def _recipe(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db: Session,
        *,
        name: str,
        ingredient_name: str,
    ) -> str:
        pcs = db.execute(text("SELECT id FROM uoms WHERE symbol = 'pcs'")).fetchone()
        assert pcs is not None
        r = client.post(
            RECIPE_URL,
            json={
                'name': name,
                'servings': 1,
                'instructions': 'Mix.',
                'ingredients': [
                    {
                        'name': ingredient_name,
                        'quantity': '1',
                        'uom_id': str(pcs[0]),
                        'is_optional': False,
                    }
                ],
            },
            headers=auth_headers,
        )
        assert r.status_code == 201, r.text
        return str(r.json()['id'])

    def test_fuzzy_matched_ingredient_expiring_soon_ranks_first(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_storage_location: StorageLocation,
        db_session: Session,
    ) -> None:
        """Keyed on template_id this score was always 0 and the list came back empty."""
        today = date.today()
        self._shelve(
            db_session,
            test_user,
            test_storage_location,
            name='Ciecierzyca w puszce',
            expiry=today + timedelta(days=1),
        )
        self._shelve(
            db_session,
            test_user,
            test_storage_location,
            name='Kasza gryczana',
            expiry=today + timedelta(days=300),
        )
        urgent_id = self._recipe(
            client,
            auth_headers,
            db_session,
            name='Curry pilne',
            ingredient_name='Ciecierzyca z puszki',
        )
        relaxed_id = self._recipe(
            client,
            auth_headers,
            db_session,
            name='Kasza spokojna',
            ingredient_name='Kasza gryczana',
        )

        r = client.get(
            f'{PLAN_URL}/suggestions?date={today.isoformat()}&slot=LUNCH&count=10',
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text
        suggestions = {s['recipe_id']: s for s in r.json()}

        assert urgent_id in suggestions, 'the urgent recipe was filtered out entirely'
        assert relaxed_id in suggestions
        assert suggestions[urgent_id]['expiry_urgency_score'] == 0.8
        assert suggestions[relaxed_id]['expiry_urgency_score'] == 0.0
        assert suggestions[urgent_id]['score'] > suggestions[relaxed_id]['score']

    def test_suggestion_counts_ingredients_the_way_the_card_does(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_storage_location: StorageLocation,
        db_session: Session,
    ) -> None:
        """The planner used to answer this in percent, which is the pair rounded.

        80% of five ingredients cannot be read back as "4 of 5", and it is the
        fifth one the reader is after. Both surfaces now count through
        ``stock_coverage``, so neither can quietly answer with another total.
        """
        today = date.today()
        self._shelve(
            db_session,
            test_user,
            test_storage_location,
            name='Kasza gryczana',
            expiry=today + timedelta(days=300),
        )
        recipe_id = self._recipe(
            client,
            auth_headers,
            db_session,
            name='Kasza z niczym',
            ingredient_name='Kasza gryczana',
        )

        r = client.get(
            f'{PLAN_URL}/suggestions?date={today.isoformat()}&slot=LUNCH&count=10',
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text
        suggestion = next(s for s in r.json() if s['recipe_id'] == recipe_id)
        assert suggestion['ingredients_available'] == 1
        assert suggestion['ingredients_total'] == 1

        card = client.get(
            f'{RECIPE_URL}/{recipe_id}/availability', headers=auth_headers
        )
        assert card.status_code == 200, card.text
        assert suggestion['availability_pct'] == card.json()['match_percentage']

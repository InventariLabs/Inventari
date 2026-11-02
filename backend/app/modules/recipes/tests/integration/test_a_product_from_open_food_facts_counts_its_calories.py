"""A product filled from Open Food Facts counts its calories in a recipe.

The provider names the figure ``energy_kcal``. The recipe estimate read its
macros under the provider's names and its calories under every name but that
one, so a product showing 321 kcal added protein, fat and carbohydrates to the
recipe and no calories — and a day holding that recipe lost its totals, since
a day only adds a recipe that answers for all four.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from sqlalchemy import select
from starlette.testclient import TestClient

from app.models.uom import Uom
from app.models.user import User

pytestmark = [pytest.mark.integration]

PROVIDER_SHAPE = {
    'energy_kcal': 321,
    'proteins': 12,
    'fat': 5,
    'carbohydrates': 45,
}
MANUAL_SHAPE = {
    'calories_kcal': 321,
    'protein_g': 12,
    'fat_g': 5,
    'carbs_g': 45,
}


def _one_serving_recipe_of(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Any,
    meta_data: dict[str, Any],
) -> str:
    """100 g of a product created through the catalogue's own door."""
    uom = db_session.scalar(select(Uom).where(Uom.symbol == 'g'))
    assert uom is not None
    template = client.post(
        '/api/v1/items/product-templates',
        json={'name': 'Scanned oat bar', 'uom_id': str(uom.id), 'meta_data': meta_data},
        headers=auth_headers,
    )
    assert template.status_code in (200, 201), template.text
    recipe = client.post(
        '/api/v1/recipes',
        json={
            'name': 'Oat bar plate',
            'servings': 1,
            'ingredients': [
                {
                    'name': 'Scanned oat bar',
                    'template_id': template.json()['id'],
                    'quantity': '100',
                    'uom_id': str(uom.id),
                    'is_optional': False,
                }
            ],
        },
        headers=auth_headers,
    )
    assert recipe.status_code in (200, 201), recipe.text
    return str(recipe.json()['id'])


@pytest.mark.parametrize(
    'nutrition',
    [PROVIDER_SHAPE, MANUAL_SHAPE],
    ids=['open_food_facts', 'typed_in'],
)
def test_the_recipe_estimate_carries_the_calories_alongside_the_macros(
    client: TestClient,
    auth_headers: dict[str, str],
    test_user: User,
    db_session: Any,
    nutrition: dict[str, float],
) -> None:
    recipe_id = _one_serving_recipe_of(
        client,
        auth_headers,
        db_session,
        {'source': 'local_off_db', 'nutrition': nutrition},
    )

    estimate = client.get(
        f'/api/v1/recipes/{recipe_id}/nutrition', headers=auth_headers
    )

    assert estimate.status_code == 200
    per_serving = estimate.json()['per_serving']
    assert per_serving['calories_kcal'] == pytest.approx(321)
    assert per_serving['protein_g'] == pytest.approx(12)
    assert per_serving['fat_g'] == pytest.approx(5)
    assert per_serving['carbs_g'] == pytest.approx(45)


def test_a_figure_typed_on_the_product_outranks_the_providers(
    client: TestClient,
    auth_headers: dict[str, str],
    test_user: User,
    db_session: Any,
) -> None:
    """A correction someone typed stays the answer over what was imported."""
    recipe_id = _one_serving_recipe_of(
        client,
        auth_headers,
        db_session,
        {'nutrition': {**PROVIDER_SHAPE, 'calories_kcal': 300}},
    )

    estimate = client.get(
        f'/api/v1/recipes/{recipe_id}/nutrition', headers=auth_headers
    )

    assert estimate.json()['per_serving']['calories_kcal'] == pytest.approx(300)


def test_the_day_holding_that_recipe_has_its_totals(
    client: TestClient,
    auth_headers: dict[str, str],
    test_user: User,
    db_session: Any,
) -> None:
    recipe_id = _one_serving_recipe_of(
        client,
        auth_headers,
        db_session,
        {'source': 'local_off_db', 'nutrition': PROVIDER_SHAPE},
    )
    today = date.today().isoformat()
    plans = '/api/v1/recipes/meal-plans'
    plan_id = client.post(
        plans,
        json={
            'name': 'Scanned week',
            'start_date': today,
            'end_date': today,
            'enabled_slots': ['LUNCH'],
            'default_servings': 1,
        },
        headers=auth_headers,
    ).json()['id']
    client.post(
        f'{plans}/{plan_id}/entries',
        json={'date': today, 'slot': 'LUNCH', 'recipe_id': recipe_id, 'order': 0},
        headers=auth_headers,
    )

    plan = client.get(f'{plans}/{plan_id}', headers=auth_headers).json()

    day = plan['daily_nutrition_summary'][0]
    assert day['calories_kcal'] == pytest.approx(321)
    assert day['protein_g'] == pytest.approx(12)
    assert day['fat_g'] == pytest.approx(5)
    assert day['carbs_g'] == pytest.approx(45)
    assert day['coverage'] == 1.0

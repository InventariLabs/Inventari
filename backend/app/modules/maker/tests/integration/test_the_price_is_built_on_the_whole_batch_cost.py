"""The suggested price, the cost estimate and the recipe quote one cost.

A batch costs its ingredients, its fixed cost lines and the labour its timed
steps take. The recipe page, the run preview and the completed run added all
three; the pricing calculator and the per-product cost estimate stopped at the
ingredients, so a price suggested from them sat below what the run cost.
"""

import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from tests.integration._shelf import post_on_shelf

pytestmark = pytest.mark.integration

#: 2 kg at 2.00, 5.00 of packaging, 120 minutes at 20.00 an hour — per batch
#: of ten units, so the whole batch is 49.00 and a unit 4.90.
INGREDIENTS = Decimal('4.00')
FIXED = Decimal('5.00')
LABOUR = Decimal('40.00')
TOTAL = Decimal('49.00')
UNIT = Decimal('4.90')


@pytest.fixture
def timed_batch_with_a_fixed_cost(
    client: TestClient,
    mk_auth_headers: dict[str, str],
    mk_org: Organization,
    mk_input_loc: StorageLocation,
    db_session: Session,
) -> tuple[ProductTemplate, str]:
    output = ProductTemplate(
        organization_id=mk_org.id, name='Soap', sku=f'SKU-{uuid.uuid4().hex[:8]}'
    )
    ingredient = ProductTemplate(
        organization_id=mk_org.id, name='Oil', sku=f'SKU-{uuid.uuid4().hex[:8]}'
    )
    db_session.add_all([output, ingredient])
    db_session.commit()
    post_on_shelf(
        client,
        mk_auth_headers,
        ingredient,
        mk_input_loc.id,
        '10',
        purchase_price='2.00',
    )
    recipe = client.post(
        '/api/v1/maker/recipes',
        headers=mk_auth_headers,
        json={
            'output_template_id': str(output.id),
            'name': 'Timed batch',
            'batch_yield_qty': '10',
            'is_default': True,
            'process_steps': [
                {'text': 'Mix', 'minutes': '30'},
                {'text': 'Cure', 'minutes': '90'},
            ],
        },
    )
    assert recipe.status_code == 201, recipe.text
    recipe_id = recipe.json()['id']
    line = client.post(
        f'/api/v1/maker/recipes/{recipe_id}/bom-lines',
        headers=mk_auth_headers,
        json={
            'child_template_id': str(ingredient.id),
            'qty_per_batch': '2',
            'unit': 'kg',
        },
    )
    assert line.status_code == 201, line.text
    cost_line = client.post(
        f'/api/v1/maker/recipes/{recipe_id}/cost-lines',
        headers=mk_auth_headers,
        json={'kind': 'PACKAGING', 'label': 'Jar', 'amount': str(FIXED)},
    )
    assert cost_line.status_code == 201, cost_line.text
    settings = client.patch(
        '/api/v1/maker/settings',
        headers=mk_auth_headers,
        json={'labor_hourly_rate': '20.00'},
    )
    assert settings.status_code == 200, settings.text
    return output, recipe_id


def test_the_calculator_prices_ingredients_fixed_costs_and_labour(
    client: TestClient,
    mk_auth_headers: dict[str, str],
    timed_batch_with_a_fixed_cost: tuple[ProductTemplate, str],
) -> None:
    output, recipe_id = timed_batch_with_a_fixed_cost

    resp = client.post(
        '/api/v1/maker/pricing/compute',
        headers=mk_auth_headers,
        json={
            'template_id': str(output.id),
            'produced_qty': '10',
            'target_margin_pct': '50',
        },
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert Decimal(body['total_cost']) == TOTAL
    assert Decimal(body['unit_cost']) == UNIT
    assert Decimal(body['unit_sale_price']) == Decimal('9.80')
    assert Decimal(body['ingredients_cost']) == INGREDIENTS
    assert Decimal(body['fixed_cost']) == FIXED
    assert Decimal(body['labour_cost']) == LABOUR
    # The unit cost is the one the recipe page quotes for the same batch.
    recipe = client.get(f'/api/v1/maker/recipes/{recipe_id}', headers=mk_auth_headers)
    assert Decimal(body['unit_cost']) == Decimal(recipe.json()['estimated_unit_cost'])


def test_the_cost_estimate_carries_the_whole_batch_cost(
    client: TestClient,
    mk_auth_headers: dict[str, str],
    timed_batch_with_a_fixed_cost: tuple[ProductTemplate, str],
) -> None:
    output, _recipe_id = timed_batch_with_a_fixed_cost

    resp = client.get(
        f'/api/v1/maker/bom/{output.id}/cost-estimate',
        headers=mk_auth_headers,
        params={'qty': '10'},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert Decimal(body['total_cost']) == TOTAL
    assert Decimal(body['unit_cost']) == UNIT
    assert Decimal(body['ingredients_cost']) == INGREDIENTS
    assert Decimal(body['fixed_cost']) == FIXED
    assert Decimal(body['labour_cost']) == LABOUR


def test_the_run_preview_total_is_the_cost_of_its_unit_cost(
    client: TestClient,
    mk_auth_headers: dict[str, str],
    mk_output_loc: StorageLocation,
    timed_batch_with_a_fixed_cost: tuple[ProductTemplate, str],
) -> None:
    output, recipe_id = timed_batch_with_a_fixed_cost

    resp = client.post(
        '/api/v1/maker/production/orders/preview',
        headers=mk_auth_headers,
        json={
            'output_template_id': str(output.id),
            'recipe_id': recipe_id,
            'planned_qty': '10',
            'output_location_id': str(mk_output_loc.id),
        },
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert Decimal(body['total_cost']) == TOTAL
    assert Decimal(body['unit_cost']) * 10 == Decimal(body['total_cost'])
    assert Decimal(body['ingredients_cost']) == INGREDIENTS

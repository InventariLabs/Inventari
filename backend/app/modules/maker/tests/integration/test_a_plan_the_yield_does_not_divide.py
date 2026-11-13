"""A run with exactly enough stock is not short when the yield does not divide the plan.

Planning 5 of a recipe that yields 3 per batch with 3 pieces per batch needs
5 pieces. Dividing the plan by the yield first (5 / 3) and multiplying the
per-batch need back left 5.000000000000000000000000001 and a "shortage" of a
trillionth of a piece against exactly five on the shelf — in the needs panel,
in the create refusal and in the completion refusal alike. The same holds
one level down: a sub-assembly yielding 3 with 5 pieces per batch, planned 3,
needs exactly 5, and its per-batch need of 5 / 3 cannot be scaled back.
"""

from __future__ import annotations

import re
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.storage_location import StorageLocation
from app.modules.maker.tests.integration.test_production_availability_and_shortage import (
    _bom_line,
    _recipe,
    _set_settings,
    _stock,
    _template,
)

pytestmark = pytest.mark.integration

ORDERS = '/api/v1/maker/production/orders'
# A whole JSON string that is a number in exponent notation (1E-27, 1e-27) —
# never a figure for a person. Anchored on the quotes: a UUID holds "3e-8" too.
EXPONENT = re.compile(r'"\d[\d.]*[eE][-+]?\d+"')


def _plan_of_five_with_exactly_enough(
    client: TestClient,
    headers: dict[str, str],
    db: Session,
    org: Organization,
    input_loc: StorageLocation,
) -> dict[str, str]:
    cake = _template(db, org, name='Cake')
    egg = _template(db, org, name='Egg')
    recipe = _recipe(db, org, cake.id, batch_yield_qty='3')
    _bom_line(db, org, recipe_id=recipe.id, parent_id=cake.id, child_id=egg.id, qty='3')
    _set_settings(db, org.id, create_on_shortage_strategy='WARN')
    _stock(client, headers, egg, input_loc, '5')
    return {'output_template_id': str(cake.id), 'planned_qty': '5'}


def test_exact_stock_shows_no_shortage_and_nothing_to_buy(
    client: TestClient,
    mk_auth_headers: dict[str, str],
    db_session: Session,
    mk_org: Organization,
    mk_input_loc: StorageLocation,
    mk_output_loc: StorageLocation,
) -> None:
    plan = _plan_of_five_with_exactly_enough(
        client, mk_auth_headers, db_session, mk_org, mk_input_loc
    )

    response = client.post(
        f'{ORDERS}/preview',
        headers=mk_auth_headers,
        json={**plan, 'output_location_id': str(mk_output_loc.id)},
    )

    assert response.status_code == 200, response.text
    assert not EXPONENT.search(response.text)
    body = response.json()
    assert body['has_shortage'] is False
    (egg,) = body['ingredients']
    assert Decimal(egg['needed']) == 5
    assert Decimal(egg['shortage'] or '0') == 0
    assert Decimal(egg['to_buy'] or '0') == 0


def test_exact_stock_creates_without_a_warning_and_completes(
    client: TestClient,
    mk_auth_headers: dict[str, str],
    db_session: Session,
    mk_org: Organization,
    mk_input_loc: StorageLocation,
    mk_output_loc: StorageLocation,
) -> None:
    plan = _plan_of_five_with_exactly_enough(
        client, mk_auth_headers, db_session, mk_org, mk_input_loc
    )

    created = client.post(
        ORDERS,
        headers=mk_auth_headers,
        json={**plan, 'output_location_id': str(mk_output_loc.id)},
    )
    assert created.status_code == 201, created.text

    completed = client.post(
        f'{ORDERS}/{created.json()["id"]}/complete', headers=mk_auth_headers
    )
    assert completed.status_code == 200, completed.text


def _sub_assembly_plan_with_exactly_enough(
    client: TestClient,
    headers: dict[str, str],
    db: Session,
    org: Organization,
    input_loc: StorageLocation,
) -> dict[str, str]:
    """Cake = 1 sub-assembly per unit; the sub-assembly yields 3 from 5 eggs."""
    cake = _template(db, org, name='Cake')
    batter = _template(db, org, name='Batter')
    egg = _template(db, org, name='Egg')
    cake_recipe = _recipe(db, org, cake.id, batch_yield_qty='1')
    _bom_line(db, org, recipe_id=cake_recipe.id, parent_id=cake.id, child_id=batter.id)
    batter_recipe = _recipe(db, org, batter.id, batch_yield_qty='3', name='Batter')
    _bom_line(
        db,
        org,
        recipe_id=batter_recipe.id,
        parent_id=batter.id,
        child_id=egg.id,
        qty='5',
    )
    _set_settings(db, org.id, create_on_shortage_strategy='WARN')
    _stock(client, headers, egg, input_loc, '5')
    return {'output_template_id': str(cake.id), 'planned_qty': '3'}


def test_exact_stock_through_a_sub_assembly_shows_no_shortage(
    client: TestClient,
    mk_auth_headers: dict[str, str],
    db_session: Session,
    mk_org: Organization,
    mk_input_loc: StorageLocation,
    mk_output_loc: StorageLocation,
) -> None:
    plan = _sub_assembly_plan_with_exactly_enough(
        client, mk_auth_headers, db_session, mk_org, mk_input_loc
    )

    response = client.post(
        f'{ORDERS}/preview',
        headers=mk_auth_headers,
        json={**plan, 'output_location_id': str(mk_output_loc.id)},
    )

    assert response.status_code == 200, response.text
    assert not EXPONENT.search(response.text)
    body = response.json()
    assert body['has_shortage'] is False
    (egg,) = body['ingredients']
    assert Decimal(egg['needed']) == 5
    assert Decimal(egg['shortage'] or '0') == 0
    assert Decimal(egg['to_buy'] or '0') == 0


def test_exact_stock_through_a_sub_assembly_lists_clean_and_completes(
    client: TestClient,
    mk_auth_headers: dict[str, str],
    db_session: Session,
    mk_org: Organization,
    mk_input_loc: StorageLocation,
    mk_output_loc: StorageLocation,
) -> None:
    plan = _sub_assembly_plan_with_exactly_enough(
        client, mk_auth_headers, db_session, mk_org, mk_input_loc
    )

    created = client.post(
        ORDERS,
        headers=mk_auth_headers,
        json={**plan, 'output_location_id': str(mk_output_loc.id)},
    )
    assert created.status_code == 201, created.text
    assert created.json()['shortage_count'] == 0

    listed = client.get(ORDERS, headers=mk_auth_headers)
    assert listed.status_code == 200, listed.text
    (row,) = listed.json()['items']
    assert row['shortage_count'] == 0

    completed = client.post(
        f'{ORDERS}/{created.json()["id"]}/complete', headers=mk_auth_headers
    )
    assert completed.status_code == 200, completed.text


def test_recipe_availability_counts_the_batch_exact_stock_covers(
    client: TestClient,
    mk_auth_headers: dict[str, str],
    db_session: Session,
    mk_org: Organization,
    mk_input_loc: StorageLocation,
) -> None:
    """The BOM card: 5 eggs hold three cakes, and asking for three is no shortage."""
    cake = _template(db_session, mk_org, name='Cake')
    batter = _template(db_session, mk_org, name='Batter')
    egg = _template(db_session, mk_org, name='Egg')
    cake_recipe = _recipe(db_session, mk_org, cake.id, batch_yield_qty='1')
    _bom_line(
        db_session,
        mk_org,
        recipe_id=cake_recipe.id,
        parent_id=cake.id,
        child_id=batter.id,
    )
    batter_recipe = _recipe(db_session, mk_org, batter.id, batch_yield_qty='3')
    _bom_line(
        db_session,
        mk_org,
        recipe_id=batter_recipe.id,
        parent_id=batter.id,
        child_id=egg.id,
        qty='5',
    )
    _stock(client, mk_auth_headers, egg, mk_input_loc, '5')
    url = f'/api/v1/maker/recipes/{cake_recipe.id}/availability'

    without = client.get(url, headers=mk_auth_headers)
    assert without.status_code == 200, without.text
    assert Decimal(without.json()['max_batches']) == 3

    asked = client.get(f'{url}?batches=3', headers=mk_auth_headers)
    assert asked.status_code == 200, asked.text
    assert not EXPONENT.search(asked.text)
    body = asked.json()
    assert body['has_shortage'] is False
    (line,) = body['ingredients']
    assert Decimal(line['needed']) == 5
    assert Decimal(line['to_buy'] or '0') == 0

"""A run with exactly enough stock is not short when the yield does not divide the plan.

Planning 5 of a recipe that yields 3 per batch with 3 pieces per batch needs
5 pieces. Dividing the plan by the yield first (5 / 3) and multiplying the
per-batch need back left 5.000000000000000000000000001 and a "shortage" of a
trillionth of a piece against exactly five on the shelf — in the needs panel,
in the create refusal and in the completion refusal alike.
"""

from __future__ import annotations

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
    assert 'E-' not in response.text
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

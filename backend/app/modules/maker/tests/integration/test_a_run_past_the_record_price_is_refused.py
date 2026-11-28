"""A run whose cost per output unit passes the record's price ceiling is refused.

The output of a run opens a stock record at what the run cost per unit, and
that column keeps prices up to ``PRICE_MAX``. A run whose overheads make a
unit dearer than that had nothing to put its output on: the record's create
refused the price as an invalid input after the ingredients had been drawn,
and the run reported a failure nobody could read. The refusal now names the
run's cost and the ceiling before anything is written.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi import status
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from tests.integration._shelf import post_on_shelf

pytestmark = pytest.mark.integration


def _template(db: Session, org: Organization, name: str) -> ProductTemplate:
    template = ProductTemplate(
        organization_id=org.id,
        name=name,
        sku=f'SKU-{uuid.uuid4().hex[:8]}',
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    return template


def test_a_run_past_the_record_price_ceiling_is_refused(
    client: TestClient,
    mk_auth_headers: dict[str, str],
    mk_org: Organization,
    mk_input_loc: StorageLocation,
    mk_output_loc: StorageLocation,
    db_session: Session,
) -> None:
    """One unit carrying a ten-thousand-million batch cost is past the column."""
    ingredient = _template(db_session, mk_org, 'Wax Nobody Priced')
    output = _template(db_session, mk_org, 'A Very Costly Candle')
    recipe = client.post(
        '/api/v1/maker/recipes',
        headers=mk_auth_headers,
        json={
            'output_template_id': str(output.id),
            'name': 'A very costly candle',
            'batch_yield_qty': '1',
            'is_default': True,
        },
    )
    assert recipe.status_code == status.HTTP_201_CREATED, recipe.text
    recipe_id = recipe.json()['id']
    line = client.post(
        f'/api/v1/maker/recipes/{recipe_id}/bom-lines',
        headers=mk_auth_headers,
        json={
            'child_template_id': str(ingredient.id),
            'qty_per_batch': '1',
            'unit': 'pcs',
        },
    )
    assert line.status_code == status.HTTP_201_CREATED, line.text
    cost = client.post(
        f'/api/v1/maker/recipes/{recipe_id}/cost-lines',
        headers=mk_auth_headers,
        json={
            'kind': 'OVERHEAD',
            'label': 'A batch that costs a fortune',
            'amount': '9999999999.99',
        },
    )
    assert cost.status_code == status.HTTP_201_CREATED, cost.text
    post_on_shelf(client, mk_auth_headers, ingredient, mk_input_loc.id, 1)
    created: Any = client.post(
        '/api/v1/maker/production/orders',
        headers=mk_auth_headers,
        json={
            'output_template_id': str(output.id),
            'planned_qty': '1',
            'input_storage_location_id': str(mk_input_loc.id),
            'output_location_id': str(mk_output_loc.id),
        },
    )
    assert created.status_code == status.HTTP_201_CREATED, created.text

    completed = client.post(
        f'/api/v1/maker/production/orders/{created.json()["id"]}/complete',
        headers=mk_auth_headers,
    )

    assert completed.status_code == status.HTTP_400_BAD_REQUEST, completed.text
    detail = completed.json()['detail']
    assert detail['code'] == 'PRODUCTION_UNIT_COST_ABOVE_CEILING'
    assert '99999999.99' in detail['message'], detail['message']
    assert output.name in detail['message'], detail['message']

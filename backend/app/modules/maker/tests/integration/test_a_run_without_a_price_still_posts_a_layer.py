"""Goods that reach the shelf are on the books, priced or not.

`_receive_output` posted a valuation layer only when the run had a positive
unit cost. A run whose ingredients carry no price -- nothing bought yet, a
count that seeded the shelf, a recipe of things somebody grew -- put the
goods on the shelf and wrote nothing, so the shelf and the sum of the layers
stopped agreeing and every valuation report was short by whatever production
had made.

The receipt path closed this hole already: `unit_cost=None` means "nobody
named a price", and the answer is this organization's own rate or, failing
that, a layer marked `unknown`. "Unknown" is an answer a report can act on;
a missing row is not.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.testing import ShelfRow
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.stock_valuation_layer import StockValuationLayer
from app.models.storage_location import StorageLocation
from app.modules.maker.models import BoMLine, MakerRecipe
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


def _recipe(
    db: Session, org: Organization, *, output_id: UUID, child_id: UUID
) -> MakerRecipe:
    recipe = MakerRecipe(
        organization_id=org.id,
        output_template_id=output_id,
        name='One line',
        batch_yield_qty=Decimal('1'),
        is_default=True,
    )
    db.add(recipe)
    db.commit()
    db.refresh(recipe)
    db.add(
        BoMLine(
            organization_id=org.id,
            recipe_id=recipe.id,
            parent_template_id=output_id,
            child_template_id=child_id,
            qty_per_batch=Decimal('1'),
            unit='pcs',
        )
    )
    db.commit()
    return recipe


def _layers(db: Session, template_id: UUID) -> list[StockValuationLayer]:
    db.expire_all()
    return list(
        db.scalars(
            select(StockValuationLayer).where(
                StockValuationLayer.product_template_id == template_id,
                StockValuationLayer.direction == 'IN',
            )
        ).all()
    )


def _complete_a_run(
    client: TestClient,
    headers: dict[str, str],
    *,
    output_id: UUID,
    input_loc: StorageLocation,
    output_loc: StorageLocation,
) -> None:
    created = client.post(
        '/api/v1/maker/production/orders',
        headers=headers,
        json={
            'output_template_id': str(output_id),
            'planned_qty': '2',
            'input_storage_location_id': str(input_loc.id),
            'output_location_id': str(output_loc.id),
        },
    )
    assert created.status_code == 201, created.text
    completed = client.post(
        f'/api/v1/maker/production/orders/{created.json()["id"]}/complete',
        headers=headers,
    )
    assert completed.status_code == 200, completed.text


def test_a_run_from_priceless_ingredients_still_reaches_the_ledger(
    client: TestClient,
    mk_auth_headers: dict[str, str],
    mk_org: Organization,
    mk_input_loc: StorageLocation,
    mk_output_loc: StorageLocation,
    db_session: Session,
) -> None:
    """Stock on the shelf nobody put a price on: the run costs nothing.

    The quantity is still real, so the layer is still posted -- marked as
    a value nobody knows rather than a value of zero.
    """
    ingredient = _template(db_session, mk_org, 'Ingredient nobody priced')
    output = _template(db_session, mk_org, 'Output')
    _recipe(db_session, mk_org, output_id=output.id, child_id=ingredient.id)
    post_on_shelf(client, mk_auth_headers, ingredient, mk_input_loc.id, 10)

    _complete_a_run(
        client,
        mk_auth_headers,
        output_id=output.id,
        input_loc=mk_input_loc,
        output_loc=mk_output_loc,
    )

    (layer,) = _layers(db_session, output.id)
    assert Decimal(str(layer.quantity)) == Decimal('2')
    assert layer.cost_basis == 'unknown'
    assert Decimal(str(layer.unit_cost)) == Decimal('0')


def test_the_shelf_and_the_layers_agree_afterwards(
    client: TestClient,
    mk_auth_headers: dict[str, str],
    mk_org: Organization,
    mk_input_loc: StorageLocation,
    mk_output_loc: StorageLocation,
    db_session: Session,
) -> None:
    """The equality the unpriced path exists to keep."""
    ingredient = _template(db_session, mk_org, 'Ingredient nobody priced')
    output = _template(db_session, mk_org, 'Output')
    _recipe(db_session, mk_org, output_id=output.id, child_id=ingredient.id)
    post_on_shelf(client, mk_auth_headers, ingredient, mk_input_loc.id, 10)

    _complete_a_run(
        client,
        mk_auth_headers,
        output_id=output.id,
        input_loc=mk_input_loc,
        output_loc=mk_output_loc,
    )

    db_session.expire_all()
    on_shelf = db_session.scalars(
        select(ShelfRow).where(ShelfRow.product_template_id == output.id)
    ).first()
    assert on_shelf is not None
    layered = sum(Decimal(str(x.quantity)) for x in _layers(db_session, output.id))
    assert layered == Decimal(str(on_shelf.quantity))

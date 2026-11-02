"""A recipe line with no unit of its own is counted in its ingredient's unit.

The stock move of such a line has always consumed the number in the
product's unit — it cannot do anything else, a quant carries no unit — while
the order's consumed lines, the cost breakdown and the availability check
printed the line's free-text unit beside the same number: "0.082 kg" of
cinnamon above "0.082 pcs." of cinnamon, one event and two measures. The
line's number and its label now agree with the move.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.uom import Uom
from app.models.user import User
from app.modules.maker.models import BoMLine, MakerRecipe
from tests.integration._shelf import put_on_shelf, run_in_async_session

pytestmark = pytest.mark.integration


def _uom(db: Session, symbol: str) -> Uom:
    uom = db.scalars(select(Uom).where(Uom.symbol == symbol)).first()
    assert uom is not None, f'the seed has no {symbol!r} unit'
    return uom


def _template(
    db: Session, org: Organization, *, name: str, uom_id: UUID | None
) -> ProductTemplate:
    template = ProductTemplate(
        organization_id=org.id,
        name=name,
        sku=f'SKU-{uuid.uuid4().hex[:8]}',
        uom_id=uom_id,
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    return template


@pytest.fixture
def cinnamon_recipe(
    db_session: Session,
    mk_org: Organization,
    mk_user: User,
    mk_input_loc: StorageLocation,
    async_engine_fixture: AsyncEngine,
) -> MakerRecipe:
    """Plum butter whose cinnamon line says "kg" in text and names no unit."""
    pcs = _uom(db_session, 'pcs')
    kg = _uom(db_session, 'kg')
    output = _template(db_session, mk_org, name='Plum Butter', uom_id=kg.id)
    cinnamon = _template(db_session, mk_org, name='Ground Cinnamon', uom_id=pcs.id)
    recipe = MakerRecipe(
        organization_id=mk_org.id,
        output_template_id=output.id,
        name='Plum Butter',
        batch_yield_qty=Decimal('1'),
        is_default=True,
    )
    db_session.add(recipe)
    db_session.commit()
    db_session.add(
        BoMLine(
            organization_id=mk_org.id,
            recipe_id=recipe.id,
            parent_template_id=output.id,
            child_template_id=cinnamon.id,
            qty_per_batch=Decimal('0.05'),
            unit='kg',
            uom_id=None,
        )
    )
    db_session.commit()
    run_in_async_session(
        async_engine_fixture,
        lambda session: put_on_shelf(session, mk_user, cinnamon, mk_input_loc.id, 20),
    )
    db_session.expire_all()
    db_session.refresh(recipe)
    return recipe


def test_the_consumed_line_and_its_stock_move_name_one_unit(
    client: TestClient,
    mk_auth_headers: dict[str, str],
    mk_output_loc: StorageLocation,
    cinnamon_recipe: MakerRecipe,
) -> None:
    create = client.post(
        '/api/v1/maker/production/orders',
        headers=mk_auth_headers,
        json={
            'output_template_id': str(cinnamon_recipe.output_template_id),
            'planned_qty': '2',
            'output_location_id': str(mk_output_loc.id),
        },
    )
    assert create.status_code == 201, create.text
    order_id = create.json()['id']
    complete = client.post(
        f'/api/v1/maker/production/orders/{order_id}/complete',
        headers=mk_auth_headers,
    )
    assert complete.status_code == 200, complete.text

    order = client.get(
        f'/api/v1/maker/production/orders/{order_id}', headers=mk_auth_headers
    ).json()
    moves = client.get(
        f'/api/v1/maker/production/orders/{order_id}/stock-moves',
        headers=mk_auth_headers,
    ).json()['items']

    [line] = order['lines']
    [consumed] = [m for m in moves if m['product_template_name'] == 'Ground Cinnamon']
    assert Decimal(line['consumed_qty']) == Decimal(consumed['quantity'])
    assert line['unit'] == 'pcs'
    assert consumed['uom_symbol'] == 'pcs'


def test_availability_names_the_unit_the_line_is_counted_in(
    client: TestClient,
    mk_auth_headers: dict[str, str],
    cinnamon_recipe: MakerRecipe,
) -> None:
    resp = client.get(
        f'/api/v1/maker/recipes/{cinnamon_recipe.id}/availability?batches=1',
        headers=mk_auth_headers,
    )

    assert resp.status_code == 200, resp.text
    [ingredient] = resp.json()['ingredients']
    assert ingredient['uom_symbol'] == 'pcs'


def test_the_cost_breakdown_names_the_same_unit(
    client: TestClient,
    mk_auth_headers: dict[str, str],
    cinnamon_recipe: MakerRecipe,
) -> None:
    breakdown = client.get(
        f'/api/v1/maker/breakdown/{cinnamon_recipe.output_template_id}?qty=2',
        headers=mk_auth_headers,
    )

    assert breakdown.status_code == 200, breakdown.text
    [entry] = breakdown.json()['entries']
    assert entry['unit'] == 'pcs'

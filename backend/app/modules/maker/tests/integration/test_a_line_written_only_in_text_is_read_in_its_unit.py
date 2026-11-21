"""A recipe line naming its unit only in text is read in that unit.

The stock move of such a line can only consume a number — a quant carries no
unit — so the unit has to be resolved before it gets there. It was not: the
line's free text was decoration, the number was taken for the stock unit, and
a line reading "50 g" of a product kept in kilograms took fifty kilograms off
the shelf. The text now names the unit the way an id does (the catalogue
resolves symbols and the spellings buyers and older screens wrote), and the
consumed line, its stock move, the availability answer and the cost breakdown
all read the same converted quantity in the ingredient's stock unit.
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
    """Plum butter whose cinnamon line says "50 g" in text and names no unit."""
    kg = _uom(db_session, 'kg')
    output = _template(db_session, mk_org, name='Plum Butter', uom_id=kg.id)
    cinnamon = _template(db_session, mk_org, name='Ground Cinnamon', uom_id=kg.id)
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
            qty_per_batch=Decimal('50'),
            unit='g',
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
    # 50 g a batch, two batches: a tenth of a kilogram off the shelf.
    assert Decimal(line['consumed_qty']) == Decimal('0.1')
    assert Decimal(line['consumed_qty']) == Decimal(consumed['quantity'])
    assert line['unit'] == 'kg'
    assert consumed['uom_symbol'] == 'kg'


def test_availability_names_the_unit_the_line_is_written_in(
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
    assert ingredient['uom_symbol'] == 'g'
    assert Decimal(ingredient['needed']) == Decimal('50')


def test_the_cost_breakdown_names_the_unit_the_shelf_gives(
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
    assert entry['unit'] == 'kg'
    assert Decimal(entry['consumed_qty']) == Decimal('0.1')

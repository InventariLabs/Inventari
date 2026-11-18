"""An intermediate with stock of its own is taken from it before it is made.

Dough in the bread: a formula line whose ingredient has a recipe takes what the
shelf holds of the intermediate and makes only the rest through its recipe; the
availability, the preview, the shortage list, the draw and the recipe tree all
read that one split. A line marked fresh is exploded to its leaves, not taken
from the shelf.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.item import Item
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.uom import Uom
from app.modules.maker.models import BoMLine, MakerRecipe
from tests.integration._shelf import post_on_shelf

pytestmark = pytest.mark.integration

API = '/api/v1/maker'


def _template(db: Session, org: Organization, name: str) -> ProductTemplate:
    template = ProductTemplate(
        organization_id=org.id, name=name, sku=f'SKU-{uuid.uuid4().hex[:8]}'
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    return template


def _recipe(
    db: Session,
    org: Organization,
    output: ProductTemplate,
    lines: list[tuple[ProductTemplate, str, bool]],
) -> MakerRecipe:
    recipe = MakerRecipe(
        organization_id=org.id,
        output_template_id=output.id,
        name=f'{output.name} formula',
        batch_yield_qty=Decimal('1'),
        is_default=True,
    )
    db.add(recipe)
    db.commit()
    for child, qty, fresh in lines:
        db.add(
            BoMLine(
                organization_id=org.id,
                recipe_id=recipe.id,
                parent_template_id=output.id,
                child_template_id=child.id,
                qty_per_batch=Decimal(qty),
                unit='pcs',
                make_fresh=fresh,
            )
        )
    db.commit()
    db.refresh(recipe)
    return recipe


class _Bakery:
    """Bread = 1 dough per piece; dough = 2 flour per piece."""

    def __init__(
        self,
        db: Session,
        org: Organization,
        client: TestClient,
        headers: dict[str, str],
        shelf: StorageLocation,
        *,
        dough: str,
        flour: str,
        fresh: bool = False,
    ) -> None:
        self.db = db
        self.client = client
        self.headers = headers
        self.flour = _template(db, org, 'Flour')
        self.dough = _template(db, org, 'Dough')
        self.bread = _template(db, org, 'Bread')
        _recipe(db, org, self.dough, [(self.flour, '2', False)])
        self.bread_recipe = _recipe(db, org, self.bread, [(self.dough, '1', fresh)])
        if Decimal(dough) > 0:
            post_on_shelf(
                client, headers, self.dough, shelf.id, dough, purchase_price='5'
            )
        if Decimal(flour) > 0:
            post_on_shelf(
                client, headers, self.flour, shelf.id, flour, purchase_price='1'
            )

    def on_shelf(self, template: ProductTemplate) -> Decimal:
        self.db.expire_all()
        return self.db.scalar(
            select(func.coalesce(func.sum(Item.quantity), 0)).where(
                Item.template_id == template.id,
                Item.location_id.is_not(None),
                Item.deleted_at.is_(None),
            )
        ) or Decimal('0')

    def draft(self, shelf: StorageLocation, qty: str) -> str:
        created = self.client.post(
            f'{API}/production/orders',
            headers=self.headers,
            json={
                'output_template_id': str(self.bread.id),
                'planned_qty': qty,
                'output_location_id': str(shelf.id),
                'confirm_shortage': True,
            },
        )
        assert created.status_code == 201, created.text
        return str(created.json()['id'])


def _needed(ingredients: list[dict[str, object]], template: ProductTemplate) -> Decimal:
    (row,) = [i for i in ingredients if i['child_template_id'] == str(template.id)]
    return Decimal(str(row['needed']))


def test_a_run_takes_the_dough_on_the_shelf_and_makes_only_the_rest(
    client: TestClient,
    mk_auth_headers: dict[str, str],
    mk_org: Organization,
    mk_input_loc: StorageLocation,
    mk_output_loc: StorageLocation,
    db_session: Session,
) -> None:
    bakery = _Bakery(
        db_session, mk_org, client, mk_auth_headers, mk_input_loc, dough='3', flour='10'
    )
    order_id = bakery.draft(mk_output_loc, '5')

    done = client.post(
        f'{API}/production/orders/{order_id}/complete', headers=mk_auth_headers
    )

    assert done.status_code == 200, done.text
    # Five bread need five dough: three are on the shelf, two are made from
    # four flour.
    assert bakery.on_shelf(bakery.dough) == Decimal('0')
    assert bakery.on_shelf(bakery.flour) == Decimal('6')
    assert bakery.on_shelf(bakery.bread) == Decimal('5')
    detail = client.get(f'{API}/production/orders/{order_id}', headers=mk_auth_headers)
    lines = {
        line['child_template_id']: Decimal(str(line['consumed_qty']))
        for line in detail.json()['lines']
    }
    assert lines == {
        str(bakery.dough.id): Decimal('3'),
        str(bakery.flour.id): Decimal('4'),
    }


def test_a_line_marked_fresh_is_made_every_time(
    client: TestClient,
    mk_auth_headers: dict[str, str],
    mk_org: Organization,
    mk_input_loc: StorageLocation,
    mk_output_loc: StorageLocation,
    db_session: Session,
) -> None:
    bakery = _Bakery(
        db_session,
        mk_org,
        client,
        mk_auth_headers,
        mk_input_loc,
        dough='3',
        flour='10',
        fresh=True,
    )
    order_id = bakery.draft(mk_output_loc, '5')

    done = client.post(
        f'{API}/production/orders/{order_id}/complete', headers=mk_auth_headers
    )

    assert done.status_code == 200, done.text
    assert bakery.on_shelf(bakery.dough) == Decimal('3')
    assert bakery.on_shelf(bakery.flour) == Decimal('0')


def test_the_preview_and_the_shortage_list_read_the_same_split(
    client: TestClient,
    mk_auth_headers: dict[str, str],
    mk_org: Organization,
    mk_input_loc: StorageLocation,
    mk_output_loc: StorageLocation,
    db_session: Session,
) -> None:
    bakery = _Bakery(
        db_session, mk_org, client, mk_auth_headers, mk_input_loc, dough='3', flour='3'
    )

    preview = client.post(
        f'{API}/production/orders/preview',
        headers=mk_auth_headers,
        json={
            'output_template_id': str(bakery.bread.id),
            'planned_qty': '5',
            'output_location_id': str(mk_output_loc.id),
        },
    )

    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert _needed(body['ingredients'], bakery.dough) == Decimal('3')
    assert _needed(body['ingredients'], bakery.flour) == Decimal('4')
    # Flour for two doughs is four and the shelf holds three: one flour short,
    # and the dough the shelf covers is not.
    short = {
        row['child_template_id']
        for row in body['ingredients']
        if row['shortage'] and Decimal(str(row['shortage'])) > 0
    }
    assert short == {str(bakery.flour.id)}
    # The cost is the three doughs at their own layer rate plus the flour.
    assert Decimal(str(body['total_cost'])) == Decimal('19.00')

    refused = client.post(
        f'{API}/production/orders/{bakery.draft(mk_output_loc, "5")}/complete',
        headers=mk_auth_headers,
    )
    assert refused.status_code == 422
    assert [s['child_template_id'] for s in refused.json()['detail']['shortages']] == [
        str(bakery.flour.id)
    ]


def test_the_shelf_supports_more_batches_than_its_flour_alone(
    client: TestClient,
    mk_auth_headers: dict[str, str],
    mk_org: Organization,
    mk_input_loc: StorageLocation,
    db_session: Session,
) -> None:
    bakery = _Bakery(
        db_session, mk_org, client, mk_auth_headers, mk_input_loc, dough='3', flour='4'
    )

    availability = client.get(
        f'{API}/recipes/{bakery.bread_recipe.id}/availability',
        headers=mk_auth_headers,
    )

    assert availability.status_code == 200, availability.text
    # Three batches from the dough, two more from the four flour.
    assert Decimal(str(availability.json()['max_batches'])) == Decimal('5')


def test_the_recipe_tree_names_what_the_shelf_holds_of_an_intermediate(
    client: TestClient,
    mk_auth_headers: dict[str, str],
    mk_org: Organization,
    mk_input_loc: StorageLocation,
    db_session: Session,
) -> None:
    bakery = _Bakery(
        db_session, mk_org, client, mk_auth_headers, mk_input_loc, dough='3', flour='4'
    )

    tree = client.get(f'{API}/bom/tree/{bakery.bread.id}', headers=mk_auth_headers)

    assert tree.status_code == 200, tree.text
    (dough_node,) = tree.json()['root']['children']
    assert Decimal(str(dough_node['line']['stock_on_hand'])) == Decimal('3')
    assert dough_node['line']['make_fresh'] is False
    (flour_node,) = dough_node['children']
    assert flour_node['line']['stock_on_hand'] is None


def test_the_recipe_tree_reads_what_the_shelf_holds_in_the_lines_own_unit(
    client: TestClient,
    mk_auth_headers: dict[str, str],
    mk_org: Organization,
    mk_input_loc: StorageLocation,
    db_session: Session,
) -> None:
    kg = db_session.scalars(select(Uom).where(Uom.symbol == 'kg')).first()
    g = db_session.scalars(select(Uom).where(Uom.symbol == 'g')).first()
    assert kg is not None
    assert g is not None
    sauce = _template(db_session, mk_org, 'Sauce')
    sauce.uom_id = kg.id
    dish = _template(db_session, mk_org, 'Dish')
    tomato = _template(db_session, mk_org, 'Tomato')
    _recipe(db_session, mk_org, sauce, [(tomato, '1', False)])
    recipe = _recipe(db_session, mk_org, dish, [(sauce, '200', False)])
    db_session.query(BoMLine).filter(
        BoMLine.recipe_id == recipe.id, BoMLine.child_template_id == sauce.id
    ).update({'uom_id': g.id, 'unit': 'g'})
    db_session.commit()
    post_on_shelf(
        client, mk_auth_headers, sauce, mk_input_loc.id, '2', purchase_price='5'
    )

    tree = client.get(f'{API}/bom/tree/{dish.id}', headers=mk_auth_headers)

    assert tree.status_code == 200, tree.text
    (sauce_node,) = tree.json()['root']['children']
    # Two kilograms on the shelf, read against a line that counts in grams.
    assert Decimal(str(sauce_node['line']['stock_on_hand'])) == Decimal('2000')


def test_a_line_is_marked_fresh_through_the_recipe_endpoint(
    client: TestClient,
    mk_auth_headers: dict[str, str],
    mk_org: Organization,
    mk_input_loc: StorageLocation,
    db_session: Session,
) -> None:
    bakery = _Bakery(
        db_session, mk_org, client, mk_auth_headers, mk_input_loc, dough='0', flour='0'
    )
    line = db_session.scalar(
        select(BoMLine.id).where(BoMLine.recipe_id == bakery.bread_recipe.id)
    )

    patched = client.patch(
        f'{API}/recipes/{bakery.bread_recipe.id}/bom-lines/{line}',
        headers=mk_auth_headers,
        json={'make_fresh': True},
    )

    assert patched.status_code == 200, patched.text
    assert patched.json()['make_fresh'] is True

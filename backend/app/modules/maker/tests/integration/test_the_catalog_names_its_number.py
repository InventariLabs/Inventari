"""The catalog names its number, and a never-run recipe shows one.

The catalog card and the cost tab both said "Unit cost" about two different
quantities — the last run's actual cost here, today's estimate from layer
rates there. And a recipe that had never run read as a dash on the very
screen people visit to ask what a batch costs, one click before the same
application showed the number. The card now names which of the two it is
showing — the run's figure "after last run", today's estimate under
"estimated" — and a recipe with nothing rateable keeps the dash, because
there the system really does not know.

The estimate also has to be computed once for the page, not once per
recipe: a rollup per row paid the BoM explosion, the unit catalogue and
the rates for every row, and the page's query count grew with its size.
"""

from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.storage_location import StorageLocation
from app.modules.maker.models import BoMLine, MakerRecipe
from app.modules.maker.tests.integration.test_a_run_opens_the_card_at_its_cost import (
    _complete_a_run,
    _recipe,
    _template,
)
from tests.integration._shelf import post_on_shelf

pytestmark = pytest.mark.integration


def _catalog(client: TestClient, headers: dict[str, str]) -> dict[str, dict[str, Any]]:
    listed = client.get('/api/v1/maker/recipes', headers=headers)
    assert listed.status_code == 200, listed.text
    items = listed.json()['items']
    return {item['name']: item for item in items}


def _recipe_with_yield(
    db: Session,
    org: Organization,
    *,
    output_id: Any,
    child_id: Any,
    name: str,
    yield_qty: str,
    qty_per_batch: str,
) -> MakerRecipe:
    """A recipe whose yield and line quantity are not both 1.

    With ``batch_yield_qty = 1`` and ``qty_per_batch = 1`` an estimate that
    skipped the division by the yield would still print the right number;
    the pair (yield 2, 4 per batch) makes the two answers differ by the
    factor the division is responsible for.
    """
    recipe = MakerRecipe(
        organization_id=org.id,
        output_template_id=output_id,
        name=name,
        batch_yield_qty=Decimal(yield_qty),
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
            qty_per_batch=Decimal(qty_per_batch),
            unit='pcs',
        )
    )
    db.commit()
    return recipe


class TestTheCatalogNamesItsNumber:
    def test_a_never_run_recipe_shows_todays_estimate(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_input_loc: StorageLocation,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        ingredient = _template(db_session, mk_org, 'Flour priced for estimate')
        output = _template(db_session, mk_org, 'Output never run')
        # 4 units of flour at 2.50 per batch of 2 → 10.00 a batch, 5.00 a unit.
        _recipe_with_yield(
            db_session,
            mk_org,
            output_id=output.id,
            child_id=ingredient.id,
            name='One line',
            yield_qty='2',
            qty_per_batch='4',
        )
        post_on_shelf(
            client,
            mk_auth_headers,
            ingredient,
            mk_input_loc.id,
            10,
            purchase_price='2.50',
        )

        rows = _catalog(client, mk_auth_headers)
        row = rows['One line']

        assert row['unit_cost'] is None
        assert Decimal(str(row['estimated_unit_cost'])) == Decimal('5.00')
        assert row['estimated_uncosted_ingredients'] == 0

    def test_the_estimate_keeps_the_runs_four_decimals(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_input_loc: StorageLocation,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        """A raw division printed 4.200000 next to the run's 4.2000 and read
        as a different precision rather than a different time — the estimate
        carries the same four decimals the run's snapshot does."""
        ingredient = _template(db_session, mk_org, 'Flour priced in decimals')
        output = _template(db_session, mk_org, 'Output with scale')
        _recipe_with_yield(
            db_session,
            mk_org,
            output_id=output.id,
            child_id=ingredient.id,
            name='One line',
            yield_qty='3',
            qty_per_batch='2',
        )
        # 2 × 2.10 = 4.20 a batch of 3 → 1.40 a unit, exactly four decimals.
        post_on_shelf(
            client,
            mk_auth_headers,
            ingredient,
            mk_input_loc.id,
            10,
            purchase_price='2.10',
        )

        rows = _catalog(client, mk_auth_headers)
        row = rows['One line']

        assert Decimal(str(row['estimated_unit_cost'])) == Decimal('1.40')
        assert str(row['estimated_unit_cost']) == '1.4000'

    def test_a_recipe_with_a_run_keeps_the_runs_number(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        mk_input_loc: StorageLocation,
        mk_output_loc: StorageLocation,
        db_session: Session,
    ) -> None:
        ingredient = _template(db_session, mk_org, 'Flour priced for run')
        output = _template(db_session, mk_org, 'Output with a run')
        _recipe(db_session, mk_org, output_id=output.id, child_id=ingredient.id)
        post_on_shelf(
            client,
            mk_auth_headers,
            ingredient,
            mk_input_loc.id,
            10,
            purchase_price='2.50',
        )
        _complete_a_run(
            client,
            mk_auth_headers,
            output_id=output.id,
            input_loc=mk_input_loc,
            output_loc=mk_output_loc,
        )

        rows = _catalog(client, mk_auth_headers)
        row = rows['One line']

        assert row['unit_cost'] is not None
        assert row['estimated_unit_cost'] is None

    def test_an_unrated_recipe_keeps_its_dash(
        self,
        client: TestClient,
        mk_auth_headers: dict[str, str],
        mk_org: Organization,
        db_session: Session,
    ) -> None:
        ingredient = _template(db_session, mk_org, 'Flour nobody priced')
        output = _template(db_session, mk_org, 'Output unratable')
        _recipe(db_session, mk_org, output_id=output.id, child_id=ingredient.id)

        rows = _catalog(client, mk_auth_headers)
        row = rows['One line']

        assert row['unit_cost'] is None
        assert row['estimated_unit_cost'] is None

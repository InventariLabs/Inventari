"""A typed price costs an ingredient the records do not hold.

The outside visitor in the demo built a formula from products created on the
spot. None of them had a cost layer and none had a supplier price, so the
formula's cost read as zero and its margin said nothing. A price typed once
on the product is the fallback every estimate agrees on — after the layers,
which know what the stock actually cost, and after a supplier's quote, which
is a live offer.
"""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.public_api import core_api
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.user import User
from app.modules.maker.cost_breakdown import compute_breakdown
from app.modules.maker.cost_rollup import compute_cost_rollup
from app.modules.maker.models import BoMLine, MakerIngredientPrice, MakerRecipe
from app.modules.purchase_orders.models import PartnerPricelist
from app.modules.recipes.cost_service import get_recipe_cost
from app.modules.recipes.models.recipe import Recipe, RecipeIngredient

pytestmark = pytest.mark.integration


async def _org_with_dimension(
    db: AsyncSession, org: Organization, user: User
) -> tuple[ProductTemplate, MakerRecipe]:
    ingredient = ProductTemplate(
        organization_id=org.id, name='Ingredient', sku=f'I-{uuid4().hex}'
    )
    output = ProductTemplate(
        organization_id=org.id, name='Output', sku=f'O-{uuid4().hex}'
    )
    db.add_all([ingredient, output])
    await db.flush()
    maker = MakerRecipe(
        organization_id=org.id,
        output_template_id=output.id,
        name='Two units',
        batch_yield_qty=Decimal('1'),
        is_default=True,
    )
    db.add(maker)
    await db.flush()
    db.add(
        BoMLine(
            organization_id=org.id,
            recipe_id=maker.id,
            parent_template_id=output.id,
            child_template_id=ingredient.id,
            qty_per_batch=Decimal('2'),
            unit='pc',
        )
    )
    return ingredient, maker


@pytest.mark.asyncio
async def test_a_typed_price_costs_an_ingredient_the_records_do_not_hold(
    real_async_db_session: AsyncSession,
    async_test_household: Organization,
    async_test_user: User,
) -> None:
    db = real_async_db_session
    org = async_test_household
    org.currency = 'USD'
    ingredient, maker = await _org_with_dimension(db, org, async_test_user)
    db.add(
        MakerIngredientPrice(
            organization_id=org.id,
            product_template_id=ingredient.id,
            unit_price=Decimal('2.50'),
        )
    )
    recipe = Recipe(
        organization_id=org.id,
        created_by=async_test_user.id,
        name='Two units',
        servings=1,
        ingredients=[
            RecipeIngredient(
                template_id=ingredient.id,
                name='Ingredient',
                quantity=Decimal('2'),
            )
        ],
    )
    db.add(recipe)
    await db.commit()

    rollup = await compute_cost_rollup(
        db, org.id, maker.output_template_id, Decimal('1')
    )
    culinary = await get_recipe_cost(db, recipe, org.id, servings=1)
    breakdown = await compute_breakdown(
        db, org.id, maker.output_template_id, Decimal('1')
    )

    # 2 units × 2.50 — the same fallback in every estimate, whichever module asks.
    assert rollup.total == Decimal('5.00')
    assert rollup.unrated_count == 0
    assert Decimal(str(culinary['estimated_cost'])) == Decimal('5.00')
    assert breakdown.total_cost == Decimal('5.00')
    assert breakdown.entries[0].cost_source == 'typed'
    assert breakdown.missing_cost_lines == []


@pytest.mark.asyncio
async def test_the_layers_and_the_supplier_outrank_the_typed_price(
    real_async_db_session: AsyncSession,
    async_test_household: Organization,
    async_test_user: User,
) -> None:
    db = real_async_db_session
    org = async_test_household
    org.currency = 'USD'
    ingredient, maker = await _org_with_dimension(db, org, async_test_user)
    supplier = Partner(
        organization_id=org.id,
        name='Supplier',
        type='SUPPLIER',
        created_by=async_test_user.id,
    )
    db.add(supplier)
    await db.flush()
    db.add(
        PartnerPricelist(
            organization_id=org.id,
            partner_id=supplier.id,
            product_template_id=ingredient.id,
            unit_price=Decimal('4.20'),
            currency='USD',
            valid_from=date(2000, 1, 1),
        )
    )
    db.add(
        MakerIngredientPrice(
            organization_id=org.id,
            product_template_id=ingredient.id,
            unit_price=Decimal('2.50'),
        )
    )
    await db.commit()

    # No layer: the live quote wins over the price typed once.
    supplier_rollup = await compute_cost_rollup(
        db, org.id, maker.output_template_id, Decimal('1')
    )
    assert supplier_rollup.total == Decimal('8.40')

    # A layer is what the stock actually cost; it outranks both.
    await core_api.valuation.record_receipt_async(
        db, org.id, ingredient.id, Decimal('10'), Decimal('3.00')
    )
    await db.commit()
    layer_rollup = await compute_cost_rollup(
        db, org.id, maker.output_template_id, Decimal('1')
    )
    assert layer_rollup.total == Decimal('6.00')


def test_the_recipe_editor_types_a_price_and_the_line_reads_it_back(
    client: TestClient,
    mk_auth_headers: dict[str, str],
    mk_org: Organization,
    db_session: Session,
) -> None:
    """The price is typed from the formula's screen, on the ingredient's card.

    A recipe line carries the product's typed price, so the editor can show
    what it is and offer to set it; clearing it removes the fallback instead
    of leaving a stale number behind.
    """
    from app.modules.maker.tests.integration.conftest import post_bom_line

    output = ProductTemplate(organization_id=mk_org.id, name='Soap')
    ingredient = ProductTemplate(organization_id=mk_org.id, name='Lye')
    db_session.add_all([output, ingredient])
    db_session.commit()
    db_session.refresh(output)
    db_session.refresh(ingredient)

    recipe = client.post(
        '/api/v1/maker/recipes',
        headers=mk_auth_headers,
        json={
            'output_template_id': str(output.id),
            'name': 'Lye soap',
            'batch_yield_qty': '10',
        },
    )
    assert recipe.status_code == 201, recipe.text
    recipe_id = recipe.json()['id']
    line = post_bom_line(
        client,
        mk_auth_headers,
        db_session,
        mk_org.id,
        {
            'parent_template_id': str(output.id),
            'child_template_id': str(ingredient.id),
            'qty_per_batch': '0.5',
            'unit': 'kg',
        },
    )
    assert line.status_code == 201, line.text

    typed = client.put(
        f'/api/v1/maker/recipes/ingredient-prices/{ingredient.id}',
        headers=mk_auth_headers,
        json={'unit_price': '8.25'},
    )
    assert typed.status_code == 200, typed.text
    assert typed.json() == {
        'product_template_id': str(ingredient.id),
        'unit_price': '8.25',
    }

    detail = client.get(f'/api/v1/maker/recipes/{recipe_id}', headers=mk_auth_headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()['lines'][0]['typed_unit_price'] == '8.2500'
    # The estimate the recipe detail prints is the typed price at the line's
    # quantity, not a zero nobody can plan from.
    assert detail.json()['estimated_unit_cost'] == '0.412500'

    cleared = client.put(
        f'/api/v1/maker/recipes/ingredient-prices/{ingredient.id}',
        headers=mk_auth_headers,
        json={'unit_price': None},
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()['unit_price'] is None
    detail = client.get(f'/api/v1/maker/recipes/{recipe_id}', headers=mk_auth_headers)
    assert detail.json()['lines'][0]['typed_unit_price'] is None

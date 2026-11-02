"""Recipe and production estimates ask one price policy; completion uses layers.

Without the shared policy the supplier-only case costs 8.40 in recipes and
zero in maker. A stated zero-cost layer also used to fall through to an offer
in recipes, although maker correctly kept it at zero.
"""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.public_api import core_api
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.uom import Uom
from app.models.user import User
from app.modules.maker.cost_breakdown import compute_breakdown
from app.modules.maker.cost_rollup import (
    compute_cost_rollup,
    compute_cost_rollups_for_recipes,
)
from app.modules.maker.models import BoMLine, MakerRecipe
from app.modules.purchase_orders.models import PartnerPricelist
from app.modules.recipes.cost_service import get_recipe_cost
from app.modules.recipes.models.recipe import Recipe, RecipeIngredient

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.mark.parametrize('layer_rate', [None, Decimal('3'), Decimal('0')])
async def test_both_estimates_use_the_same_unit_cost(
    real_async_db_session: AsyncSession,
    async_test_household: Organization,
    async_test_user: User,
    layer_rate: Decimal | None,
) -> None:
    db = real_async_db_session
    org = async_test_household
    org.currency = 'USD'
    ingredient = ProductTemplate(
        organization_id=org.id, name='Ingredient', sku=f'I-{uuid4().hex}'
    )
    output = ProductTemplate(
        organization_id=org.id, name='Output', sku=f'O-{uuid4().hex}'
    )
    supplier = Partner(
        organization_id=org.id,
        name='Supplier',
        type='SUPPLIER',
        created_by=async_test_user.id,
    )
    db.add_all([ingredient, output, supplier])
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
    maker = MakerRecipe(
        organization_id=org.id,
        output_template_id=output.id,
        name='Two units',
        batch_yield_qty=Decimal('1'),
        is_default=True,
    )
    db.add_all([recipe, maker])
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
    if layer_rate is not None:
        await core_api.valuation.record_receipt_async(
            db,
            org.id,
            ingredient.id,
            Decimal('10'),
            layer_rate,
        )
    await db.commit()

    expected = (layer_rate if layer_rate is not None else Decimal('4.20')) * 2
    culinary = await get_recipe_cost(db, recipe, org.id, servings=1)
    rollup = await compute_cost_rollup(db, org.id, output.id, Decimal('1'))
    page = await compute_cost_rollups_for_recipes(db, org.id, [(maker, Decimal('1'))])
    breakdown = await compute_breakdown(db, org.id, output.id, Decimal('1'))

    assert Decimal(str(culinary['estimated_cost'])) == expected
    assert rollup.total == expected
    assert rollup.unrated_count == 0
    assert page[maker.id] == rollup
    assert breakdown.total_cost == expected
    assert breakdown.entries[0].cost_source == (
        'supplier' if layer_rate is None else 'avco'
    )


@pytest.mark.parametrize(
    'case',
    [
        'converted',
        'best',
        'incompatible',
        'foreign',
        'expired',
        'future',
        'disabled',
        'absent',
    ],
)
async def test_supplier_rates_preserve_units_currency_and_module_scope(
    real_async_db_session: AsyncSession,
    async_test_household: Organization,
    async_test_user: User,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    """Only a current, enabled, house-currency, convertible offer is a rate."""
    from app.core import cost_estimates

    db = real_async_db_session
    org = async_test_household
    org.currency = 'USD'
    uoms = {uom.symbol: uom for uom in (await db.scalars(select(Uom))).all()}
    ingredient = ProductTemplate(
        organization_id=org.id,
        name='Ingredient',
        sku=f'I-{uuid4().hex}',
        uom_id=uoms['kg'].id,
    )
    supplier = Partner(
        organization_id=org.id,
        name='Supplier',
        type='SUPPLIER',
        created_by=async_test_user.id,
    )
    db.add_all([ingredient, supplier])
    await db.flush()
    db.add(
        PartnerPricelist(
            organization_id=org.id,
            partner_id=supplier.id,
            product_template_id=ingredient.id,
            unit_price=Decimal('0.0042'),
            currency='EUR' if case == 'foreign' else 'USD',
            uom_id=uoms['pcs' if case == 'incompatible' else 'g'].id,
            valid_from=date(2099, 1, 1) if case == 'future' else date(2000, 1, 1),
            valid_to=date(2000, 1, 2) if case == 'expired' else None,
        )
    )
    if case == 'best':
        db.add(
            PartnerPricelist(
                organization_id=org.id,
                partner_id=supplier.id,
                product_template_id=ingredient.id,
                unit_price=Decimal('2'),
                currency='USD',
                uom_id=uoms['kg'].id,
                valid_from=date(1999, 1, 1),
            )
        )
    if case == 'disabled':
        org.enabled_modules = [
            name for name in org.enabled_modules if name != 'purchase_orders'
        ]
    if case == 'absent':
        monkeypatch.setattr(cost_estimates, '_supplier_provider', None)
    await db.commit()

    result = await core_api.valuation.estimate_unit_cost_async(
        db, org.id, [ingredient.id]
    )
    estimate = result[ingredient.id]
    if case in ('converted', 'best'):
        assert estimate.unit_cost == (
            Decimal('2') if case == 'best' else Decimal('4.20')
        )
        assert estimate.currency == 'USD'
        assert estimate.source == 'supplier'
    else:
        assert estimate.unit_cost is None
        assert estimate.currency is None
        assert estimate.source == 'unknown'


async def test_other_organizations_prices_do_not_supply_an_estimate(
    real_async_db_session: AsyncSession,
    async_test_household: Organization,
    async_test_user: User,
) -> None:
    db = real_async_db_session
    org = async_test_household
    other = Organization(
        name='Other', currency='USD', enabled_modules=['purchase_orders']
    )
    ingredient = ProductTemplate(
        organization_id=None,
        name='Shared catalogue entry',
        sku=f'G-{uuid4().hex}',
    )
    db.add_all([other, ingredient])
    await db.flush()
    supplier = Partner(
        organization_id=other.id,
        name='Other supplier',
        type='SUPPLIER',
        created_by=async_test_user.id,
    )
    db.add(supplier)
    await db.flush()
    db.add(
        PartnerPricelist(
            organization_id=other.id,
            partner_id=supplier.id,
            product_template_id=ingredient.id,
            unit_price=Decimal('9'),
            currency='USD',
            valid_from=date(2000, 1, 1),
        )
    )
    await core_api.valuation.record_receipt_async(
        db,
        other.id,
        ingredient.id,
        Decimal('10'),
        Decimal('5'),
    )
    await db.commit()

    result = await core_api.valuation.estimate_unit_cost_async(
        db, org.id, [ingredient.id, ingredient.id, uuid4()]
    )
    assert len(result) == 2
    assert all(estimate.unit_cost is None for estimate in result.values())
    assert await core_api.valuation.estimate_unit_cost_async(db, org.id, []) == {}

"""Tests for the recipes cost_service price fallback chain.

Fallback chain:
    1. Layer-average rate
    2. Supplier price (registered by the purchase_orders module)
    3. None (missing; legacy record prices never become rates)

Each tier is exercised through the shared Core policy and the public
``get_recipe_cost`` end-to-end.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.public_api import core_api
from app.models.item import Item
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.services.valuation_service import ValuationService
from tests.integration._shelf import anchor_pending_records


async def _seed_template(
    db: AsyncSession,
    org: Organization,
    name: str,
    *,
    current_valuation_rate: Decimal | None = None,
) -> ProductTemplate:
    template = ProductTemplate(
        organization_id=org.id,
        name=name,
        sku=f'SKU-COST-{uuid4().hex[:8]}',
    )
    db.add(template)
    await db.flush()
    if current_valuation_rate is not None:
        # A rate comes from this organization's own valuation layers. It used
        # to be a column on the template row — which a global template shares
        # with every organization — so seeding it here was seeding a number
        # that belonged to nobody in particular.
        from app.services.valuation_service import ValuationService

        await ValuationService._record_receipt_async(
            db, template, Decimal('1000'), current_valuation_rate, org.id
        )
        await db.flush()
    return template


async def _seed_internal_item(
    db: AsyncSession,
    org: Organization,
    location: StorageLocation,
    template: ProductTemplate,
    *,
    quantity: Decimal,
    purchase_price: Decimal | None,
    currency: str | None = None,
) -> Item:
    """Create an Item with the given pricing in INTERNAL storage."""
    item = Item(
        organization_id=org.id,
        storage_location_id=location.id,
        template_id=template.id,
        name=template.name,
        quantity=quantity,
        purchase_price=purchase_price,
        currency=currency,
    )
    db.add(item)
    await db.run_sync(anchor_pending_records)
    await db.flush()
    return item


async def _shared_price(
    db: AsyncSession, org_id: UUID, template_id: UUID
) -> tuple[Decimal | None, str | None, str]:
    """Read the shared product policy; end-to-end tests below pin the recipe adapter."""
    estimate = (
        await core_api.valuation.estimate_unit_cost_async(db, org_id, [template_id])
    )[template_id]
    return estimate.unit_cost, estimate.currency, estimate.source


@pytest.mark.integration
@pytest.mark.asyncio
class TestResolveUnitPriceFallback:
    """Direct tests of the shared stock-unit price policy."""

    async def test_tier1_avco_wins_when_template_has_valuation_rate(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
    ) -> None:

        template = await _seed_template(
            real_async_db_session,
            async_test_household,
            'AvcoTemplate',
            current_valuation_rate=Decimal('7.50'),
        )
        await real_async_db_session.commit()

        price, currency, source = await _shared_price(
            real_async_db_session, async_test_household.id, template.id
        )

        assert price == Decimal('7.50')
        assert currency == 'USD'  # the actual organization, not a caller's label
        assert source == 'layers'

    async def test_avco_from_stock_bought_in_one_foreign_currency_is_refused(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
    ) -> None:
        """Stock bought in one foreign currency is not priced as the org's.

        The mixed batch of supplier prices was already short-circuited, and a
        unanimous foreign currency slipped past the valuation guard: one
        currency agrees with itself, so the AVCO rate came back and this
        service attributed it to the org currency — 100 × 40.10 złoty read as
        40.10 USD. The valuation service now refuses that rate like a mixed
        batch, so the chain falls through instead of blending.
        """

        async_test_household.currency = 'USD'
        real_async_db_session.add(async_test_household)
        await real_async_db_session.flush()

        template = ProductTemplate(
            organization_id=async_test_household.id,
            name='Foreign Stock',
            sku=f'SKU-COST-{uuid4().hex[:8]}',
        )
        real_async_db_session.add(template)
        await real_async_db_session.flush()
        await ValuationService._record_receipt_async(
            real_async_db_session,
            template,
            Decimal('100'),
            Decimal('40.10'),
            async_test_household.id,
            currency='PLN',
        )
        await real_async_db_session.commit()

        price, currency, source = await _shared_price(
            real_async_db_session, async_test_household.id, template.id
        )

        # Tier 1 is dead, and with no supplier offer and no priced items
        # behind it the ingredient is honestly unpriced — never "40.10 USD".
        assert (price, currency, source) == (None, None, 'unknown')

    async def test_tier2_supplier_used_when_no_avco(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
    ) -> None:
        from app.modules.purchase_orders.pricelist_service import create_async

        template = await _seed_template(
            real_async_db_session, async_test_household, 'SupplierTemplate'
        )
        partner = Partner(
            organization_id=async_test_household.id,
            name='Test Supplier',
            type='SUPPLIER',
            created_by=async_test_user.id,
        )
        real_async_db_session.add(partner)
        await real_async_db_session.flush()

        await create_async(
            real_async_db_session,
            organization_id=async_test_household.id,
            partner_id=partner.id,
            product_template_id=template.id,
            unit_price=Decimal('4.20'),
            currency='USD',
            valid_from=date.today(),
        )
        await real_async_db_session.commit()

        price, currency, source = await _shared_price(
            real_async_db_session, async_test_household.id, template.id
        )

        assert price == Decimal('4.20')
        assert currency == 'USD'  # supplier currency wins
        assert source == 'supplier'

    async def test_record_purchase_price_without_a_layer_is_unknown(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
        async_test_storage_location: StorageLocation,
    ) -> None:

        template = await _seed_template(
            real_async_db_session, async_test_household, 'StaticTemplate'
        )
        await _seed_internal_item(
            real_async_db_session,
            async_test_household,
            async_test_storage_location,
            template,
            quantity=Decimal('2'),
            purchase_price=Decimal('6'),
            currency='EUR',
        )
        await real_async_db_session.commit()

        price, currency, source = await _shared_price(
            real_async_db_session, async_test_household.id, template.id
        )

        assert (price, currency, source) == (None, None, 'unknown')

    async def test_tier4_returns_none_when_no_data(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
    ) -> None:

        template = await _seed_template(
            real_async_db_session, async_test_household, 'EmptyTemplate'
        )
        await real_async_db_session.commit()

        price, currency, source = await _shared_price(
            real_async_db_session, async_test_household.id, template.id
        )

        assert price is None
        assert currency is None
        assert source == 'unknown'

    async def test_avco_beats_supplier_and_purchase_price(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
        async_test_storage_location: StorageLocation,
    ) -> None:
        """When all three tiers are populated, AVCO wins."""
        from app.modules.purchase_orders.pricelist_service import create_async

        template = await _seed_template(
            real_async_db_session,
            async_test_household,
            'MultiTier',
            current_valuation_rate=Decimal('9.99'),
        )
        partner = Partner(
            organization_id=async_test_household.id,
            name='Multi Supplier',
            type='SUPPLIER',
            created_by=async_test_user.id,
        )
        real_async_db_session.add(partner)
        await real_async_db_session.flush()

        await create_async(
            real_async_db_session,
            organization_id=async_test_household.id,
            partner_id=partner.id,
            product_template_id=template.id,
            unit_price=Decimal('1.00'),
            currency='USD',
            valid_from=date.today(),
        )
        await _seed_internal_item(
            real_async_db_session,
            async_test_household,
            async_test_storage_location,
            template,
            quantity=Decimal('5'),
            purchase_price=Decimal('100'),
            currency='EUR',
        )
        await real_async_db_session.commit()

        price, currency, source = await _shared_price(
            real_async_db_session, async_test_household.id, template.id
        )

        assert source == 'layers'
        assert price == Decimal('9.99')
        assert currency == 'USD'

    async def test_supplier_beats_purchase_price_when_no_avco(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
        async_test_storage_location: StorageLocation,
    ) -> None:
        from app.modules.purchase_orders.pricelist_service import create_async

        template = await _seed_template(
            real_async_db_session, async_test_household, 'SupplierBeats'
        )
        partner = Partner(
            organization_id=async_test_household.id,
            name='Beats Supplier',
            type='SUPPLIER',
            created_by=async_test_user.id,
        )
        real_async_db_session.add(partner)
        await real_async_db_session.flush()

        await create_async(
            real_async_db_session,
            organization_id=async_test_household.id,
            partner_id=partner.id,
            product_template_id=template.id,
            unit_price=Decimal('2.50'),
            currency='USD',
            valid_from=date.today(),
        )
        await _seed_internal_item(
            real_async_db_session,
            async_test_household,
            async_test_storage_location,
            template,
            quantity=Decimal('10'),
            purchase_price=Decimal('100'),
            currency='EUR',
        )
        await real_async_db_session.commit()

        price, currency, source = await _shared_price(
            real_async_db_session, async_test_household.id, template.id
        )

        assert source == 'supplier'
        assert price == Decimal('2.50')
        assert currency == 'USD'

    async def test_mixed_currencies_in_static_batch_returns_none(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
        async_test_storage_location: StorageLocation,
    ) -> None:
        """Unlayered record prices cannot supply a rate, in any currency."""

        template = await _seed_template(
            real_async_db_session, async_test_household, 'MixedCurrency'
        )
        await _seed_internal_item(
            real_async_db_session,
            async_test_household,
            async_test_storage_location,
            template,
            quantity=Decimal('2'),
            purchase_price=Decimal('6'),
            currency='EUR',
        )
        await _seed_internal_item(
            real_async_db_session,
            async_test_household,
            async_test_storage_location,
            template,
            quantity=Decimal('3'),
            purchase_price=Decimal('9'),
            currency='USD',
        )
        await real_async_db_session.commit()

        price, currency, source = await _shared_price(
            real_async_db_session, async_test_household.id, template.id
        )

        assert price is None
        assert currency is None
        assert source == 'unknown'


@pytest.mark.integration
@pytest.mark.asyncio
class TestGetRecipeCostEndToEnd:
    """End-to-end tests of get_recipe_cost with the fallback chain."""

    async def test_recipe_cost_uses_avco_rate_for_all_ingredients(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
    ) -> None:
        from app.modules.recipes.cost_service import get_recipe_cost
        from app.modules.recipes.models.recipe import Recipe, RecipeIngredient

        template_a = await _seed_template(
            real_async_db_session,
            async_test_household,
            'CostAvcoA',
            current_valuation_rate=Decimal('5'),
        )
        template_b = await _seed_template(
            real_async_db_session,
            async_test_household,
            'CostAvcoB',
            current_valuation_rate=Decimal('3'),
        )
        await real_async_db_session.flush()

        recipe = Recipe(
            organization_id=async_test_household.id,
            created_by=async_test_user.id,
            name='AVCO Recipe',
            servings=2,
            ingredients=[
                RecipeIngredient(
                    template_id=template_a.id,
                    name='A',
                    quantity=Decimal('4'),
                ),
                RecipeIngredient(
                    template_id=template_b.id,
                    name='B',
                    quantity=Decimal('6'),
                ),
            ],
        )
        real_async_db_session.add(recipe)
        await real_async_db_session.commit()

        result = await get_recipe_cost(
            real_async_db_session, recipe, async_test_household.id, servings=2
        )

        # 4 * 5 + 6 * 3 = 20 + 18 = 38
        assert result['estimated_cost'] == 38.0
        assert result['currency'] == 'USD'  # default org currency
        assert result['missing_cost_ingredients'] == []
        assert result['mixed_currencies'] is False
        assert result['cost_coverage'] == 1.0

        sources = {
            ing['ingredient_name']: ing['price_source'] for ing in result['ingredients']
        }
        assert sources == {'A': 'avco', 'B': 'avco'}

    async def test_recipe_cost_falls_back_to_supplier_when_no_avco(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
    ) -> None:
        from app.modules.purchase_orders.pricelist_service import create_async
        from app.modules.recipes.cost_service import get_recipe_cost
        from app.modules.recipes.models.recipe import Recipe, RecipeIngredient

        async_test_household.currency = 'EUR'
        template = await _seed_template(
            real_async_db_session, async_test_household, 'CostSupplier'
        )
        partner = Partner(
            organization_id=async_test_household.id,
            name='Cost Supplier',
            type='SUPPLIER',
            created_by=async_test_user.id,
        )
        real_async_db_session.add(partner)
        await real_async_db_session.flush()

        await create_async(
            real_async_db_session,
            organization_id=async_test_household.id,
            partner_id=partner.id,
            product_template_id=template.id,
            unit_price=Decimal('8'),
            currency='EUR',
            valid_from=date.today(),
        )
        await real_async_db_session.flush()

        recipe = Recipe(
            organization_id=async_test_household.id,
            created_by=async_test_user.id,
            name='Supplier Recipe',
            servings=1,
            ingredients=[
                RecipeIngredient(
                    template_id=template.id,
                    name='Only',
                    quantity=Decimal('5'),
                ),
            ],
        )
        real_async_db_session.add(recipe)
        await real_async_db_session.commit()

        result = await get_recipe_cost(
            real_async_db_session, recipe, async_test_household.id, servings=1
        )

        assert result['estimated_cost'] == 40.0  # 5 * 8
        assert result['currency'] == 'EUR'
        assert result['ingredients'][0]['price_source'] == 'supplier'

    async def test_recipe_cost_does_not_invent_a_rate_from_record_prices(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
        async_test_storage_location: StorageLocation,
    ) -> None:
        from app.modules.recipes.cost_service import get_recipe_cost
        from app.modules.recipes.models.recipe import Recipe, RecipeIngredient

        template = await _seed_template(
            real_async_db_session, async_test_household, 'CostStatic'
        )
        await _seed_internal_item(
            real_async_db_session,
            async_test_household,
            async_test_storage_location,
            template,
            quantity=Decimal('2'),
            purchase_price=Decimal('10'),
            currency='PLN',
        )
        await real_async_db_session.flush()

        recipe = Recipe(
            organization_id=async_test_household.id,
            created_by=async_test_user.id,
            name='Static Recipe',
            servings=1,
            ingredients=[
                RecipeIngredient(
                    template_id=template.id,
                    name='StaticOnly',
                    quantity=Decimal('3'),
                ),
            ],
        )
        real_async_db_session.add(recipe)
        await real_async_db_session.commit()

        result = await get_recipe_cost(
            real_async_db_session, recipe, async_test_household.id, servings=1
        )

        assert result['estimated_cost'] is None
        assert result['currency'] is None
        assert result['missing_cost_ingredients'] == ['StaticOnly']
        assert result['ingredients'][0]['price_source'] == 'none'

    async def test_recipe_cost_reports_missing_when_no_data(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
    ) -> None:
        from app.modules.recipes.cost_service import get_recipe_cost
        from app.modules.recipes.models.recipe import Recipe, RecipeIngredient

        template = await _seed_template(
            real_async_db_session, async_test_household, 'CostMissing'
        )
        await real_async_db_session.flush()

        recipe = Recipe(
            organization_id=async_test_household.id,
            created_by=async_test_user.id,
            name='Missing Recipe',
            servings=1,
            ingredients=[
                RecipeIngredient(
                    template_id=template.id,
                    name='Nothing',
                    quantity=Decimal('1'),
                ),
            ],
        )
        real_async_db_session.add(recipe)
        await real_async_db_session.commit()

        result = await get_recipe_cost(
            real_async_db_session, recipe, async_test_household.id, servings=1
        )

        assert result['estimated_cost'] is None
        assert result['missing_cost_ingredients'] == ['Nothing']
        assert result['ingredients'][0]['price_source'] == 'none'
        assert result['ingredients'][0]['has_price_data'] is False

    async def test_record_prices_do_not_inflate_coverage(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
        async_test_storage_location: StorageLocation,
    ) -> None:
        """A priced layer plus a legacy unlayered record is only half covered."""
        from app.modules.recipes.cost_service import get_recipe_cost
        from app.modules.recipes.models.recipe import Recipe, RecipeIngredient

        # Org default = USD. AVCO gets attributed to USD.
        template_a = await _seed_template(
            real_async_db_session,
            async_test_household,
            'MixedA',
            current_valuation_rate=Decimal('4'),
        )
        # No AVCO; static items priced in USD.
        template_b = await _seed_template(
            real_async_db_session, async_test_household, 'MixedB'
        )
        await _seed_internal_item(
            real_async_db_session,
            async_test_household,
            async_test_storage_location,
            template_b,
            quantity=Decimal('2'),
            purchase_price=Decimal('6'),
            currency='USD',
        )
        await real_async_db_session.flush()

        recipe = Recipe(
            organization_id=async_test_household.id,
            created_by=async_test_user.id,
            name='Mixed Recipe',
            servings=1,
            ingredients=[
                RecipeIngredient(
                    template_id=template_a.id,
                    name='A',
                    quantity=Decimal('2'),
                ),
                RecipeIngredient(
                    template_id=template_b.id,
                    name='B',
                    quantity=Decimal('3'),
                ),
            ],
        )
        real_async_db_session.add(recipe)
        await real_async_db_session.commit()

        result = await get_recipe_cost(
            real_async_db_session, recipe, async_test_household.id, servings=1
        )

        assert result['estimated_cost'] == 8.0
        assert result['cost_coverage'] == 0.5
        assert result['missing_cost_ingredients'] == ['B']
        assert result['currency'] == 'USD'
        assert result['mixed_currencies'] is False
        sources = {
            ing['ingredient_name']: ing['price_source'] for ing in result['ingredients']
        }
        assert sources == {'A': 'avco', 'B': 'none'}


@pytest.mark.integration
@pytest.mark.asyncio
class TestCostStopsLyingAboutCoverage:
    """A costing that quietly drops most of the recipe is worse than none."""

    async def test_unpriceable_ingredients_count_in_the_denominator(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
    ) -> None:
        """One costed ingredient out of six reports 1/6, not full coverage."""
        from app.modules.recipes.cost_service import get_recipe_cost
        from app.modules.recipes.models.recipe import Recipe, RecipeIngredient

        template = await _seed_template(
            real_async_db_session,
            async_test_household,
            'CostCoverageOnly',
            current_valuation_rate=Decimal('5'),
        )
        await real_async_db_session.flush()

        recipe = Recipe(
            organization_id=async_test_household.id,
            created_by=async_test_user.id,
            name='Mostly Unpriced Recipe',
            servings=1,
            ingredients=[
                RecipeIngredient(
                    template_id=template.id, name='Priced', quantity=Decimal('2')
                ),
                *[
                    RecipeIngredient(name=name, quantity=Decimal('1'))
                    for name in (
                        'Szpinak baby',
                        'Pasta curry',
                        'Mleko kokosowe',
                        'Kolendra',
                        'Kardamon',
                    )
                ],
            ],
        )
        real_async_db_session.add(recipe)
        await real_async_db_session.commit()

        result = await get_recipe_cost(
            real_async_db_session, recipe, async_test_household.id, servings=1
        )

        assert result['cost_coverage'] == round(1 / 6, 4)
        assert len(result['missing_cost_ingredients']) == 5
        assert 'Priced' not in result['missing_cost_ingredients']
        assert result['estimated_cost'] == 10.0

    async def test_a_price_per_can_is_not_multiplied_by_grams(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
    ) -> None:
        """400 g of chickpeas from a 400 g can priced at 6 costs 6, not 2400."""
        from sqlalchemy import text

        from app.modules.recipes.cost_service import get_recipe_cost
        from app.modules.recipes.models.recipe import Recipe, RecipeIngredient

        pcs = (
            await real_async_db_session.execute(
                text("SELECT id FROM uoms WHERE symbol = 'pcs'")
            )
        ).fetchone()
        grams = (
            await real_async_db_session.execute(
                text("SELECT id FROM uoms WHERE symbol = 'g'")
            )
        ).fetchone()
        assert pcs is not None and grams is not None

        template = ProductTemplate(
            organization_id=async_test_household.id,
            name='Ciecierzyca w puszce',
            sku=f'SKU-COST-{uuid4().hex[:8]}',
            uom_id=pcs[0],
            weight_value=Decimal('400'),
            weight_uom_id=grams[0],
        )
        real_async_db_session.add(template)
        await real_async_db_session.flush()
        # A rate comes from this organization's own valuation layers.
        await ValuationService._record_receipt_async(
            real_async_db_session,
            template,
            Decimal('1000'),
            Decimal('6'),
            async_test_household.id,
        )
        await real_async_db_session.flush()

        recipe = Recipe(
            organization_id=async_test_household.id,
            created_by=async_test_user.id,
            name='Curry wyceniane',
            servings=1,
            ingredients=[
                RecipeIngredient(
                    name='Ciecierzyca z puszki',
                    quantity=Decimal('400'),
                    uom_id=grams[0],
                ),
            ],
        )
        real_async_db_session.add(recipe)
        await real_async_db_session.commit()

        result = await get_recipe_cost(
            real_async_db_session, recipe, async_test_household.id, servings=1
        )

        assert result['estimated_cost'] == 6.0
        assert result['cost_coverage'] == 1.0
        assert result['missing_cost_ingredients'] == []

    async def test_incomparable_measures_are_unpriced_rather_than_inflated(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
    ) -> None:
        """No pack size: report the ingredient as unpriced, never as 400 cans."""
        from sqlalchemy import text

        from app.modules.recipes.cost_service import get_recipe_cost
        from app.modules.recipes.models.recipe import Recipe, RecipeIngredient

        pcs = (
            await real_async_db_session.execute(
                text("SELECT id FROM uoms WHERE symbol = 'pcs'")
            )
        ).fetchone()
        grams = (
            await real_async_db_session.execute(
                text("SELECT id FROM uoms WHERE symbol = 'g'")
            )
        ).fetchone()
        assert pcs is not None and grams is not None

        template = ProductTemplate(
            organization_id=async_test_household.id,
            name='Ciecierzyca w puszce',
            sku=f'SKU-COST-{uuid4().hex[:8]}',
            uom_id=pcs[0],
        )
        real_async_db_session.add(template)
        await real_async_db_session.flush()
        # A rate comes from this organization's own valuation layers.
        await ValuationService._record_receipt_async(
            real_async_db_session,
            template,
            Decimal('1000'),
            Decimal('6'),
            async_test_household.id,
        )
        await real_async_db_session.flush()

        recipe = Recipe(
            organization_id=async_test_household.id,
            created_by=async_test_user.id,
            name='Curry bez wagi opakowania',
            servings=1,
            ingredients=[
                RecipeIngredient(
                    name='Ciecierzyca z puszki',
                    quantity=Decimal('400'),
                    uom_id=grams[0],
                ),
            ],
        )
        real_async_db_session.add(recipe)
        await real_async_db_session.commit()

        result = await get_recipe_cost(
            real_async_db_session, recipe, async_test_household.id, servings=1
        )

        assert result['estimated_cost'] is None
        assert result['missing_cost_ingredients'] == ['Ciecierzyca z puszki']
        assert result['cost_coverage'] == 0.0

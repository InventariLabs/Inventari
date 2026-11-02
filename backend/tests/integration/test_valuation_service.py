"""
Integration tests for ValuationService.

Covers:
- record_receipt: create SVL layers
- record_delivery: FIFO consumption of SVL layers
- record_receipt_by_id / record_delivery_by_id: by-template-id helpers
- the AVCO rate itself, which is computed per organization from its own layers

The rate used to be cached on ``ProductTemplate.current_valuation_rate`` and
these tests read it straight off the row — several of them wrote it there by
hand as a shortcut. That shortcut is why the sharing was invisible for so long:
a global template is one row every organization uses, so the cached number
belonged to whichever one wrote last. The column is gone; the rate is asked for
the way the application asks for it.
"""

from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product_template import ProductTemplate
from app.models.stock_valuation_layer import CostBasis
from app.services.valuation_service import ValuationService
from tests.integration._shelf import anchor_pending_records


async def _rate(
    db: AsyncSession, org_id: UUID, template: ProductTemplate
) -> Decimal | None:
    """This organization's AVCO rate for *template*, as a caller would ask."""
    return await ValuationService.get_current_valuation_rate_async(
        db, org_id, template.id
    )


@pytest.mark.integration
@pytest.mark.asyncio
class TestRecordReceipt:
    async def test_creates_svl_and_updates_avco(
        self, real_async_db_session: AsyncSession, async_test_household
    ):
        db = real_async_db_session
        template = ProductTemplate(
            organization_id=async_test_household.id,
            name='Widget',
            sku=f'W-{uuid4().hex[:8]}',
        )
        db.add(template)
        await db.flush()
        await db.refresh(template)

        svl = await ValuationService._record_receipt_async(
            db, template, Decimal('10'), Decimal('5.00'), async_test_household.id
        )
        await db.flush()
        await db.refresh(template)

        assert svl is not None
        assert svl.quantity == Decimal('10')
        assert svl.remaining_qty == Decimal('10')
        assert svl.unit_cost == Decimal('5.00')
        assert svl.total_value == Decimal('50.00')
        assert svl.direction == 'IN'
        assert await _rate(db, async_test_household.id, template) == Decimal('5.00')

    async def test_zero_quantity_returns_none(
        self, real_async_db_session: AsyncSession, async_test_household
    ):
        db = real_async_db_session
        template = ProductTemplate(
            organization_id=async_test_household.id,
            name='ZeroQty',
            sku=f'ZQ-{uuid4().hex[:8]}',
        )
        db.add(template)
        await db.flush()
        await db.refresh(template)

        result = await ValuationService._record_receipt_async(
            db, template, Decimal('0'), Decimal('5.00'), async_test_household.id
        )
        assert result is None

    async def test_negative_quantity_returns_none(
        self, real_async_db_session: AsyncSession, async_test_household
    ):
        db = real_async_db_session
        template = ProductTemplate(
            organization_id=async_test_household.id,
            name='NegQty',
            sku=f'NQ-{uuid4().hex[:8]}',
        )
        db.add(template)
        await db.flush()
        await db.refresh(template)

        result = await ValuationService._record_receipt_async(
            db, template, Decimal('-5'), Decimal('5.00'), async_test_household.id
        )
        assert result is None

    async def test_no_stated_cost_still_posts_a_layer(
        self, real_async_db_session: AsyncSession, async_test_household
    ):
        """No price is not no receipt — see the cost-basis policy.

        This used to assert ``None``: an inflow nobody priced left no layer at
        all, so the shelf and the sum of the layers stopped agreeing and
        nothing looked for the gap.
        """
        db = real_async_db_session
        template = ProductTemplate(
            organization_id=async_test_household.id,
            name='NoCost',
            sku=f'NC-{uuid4().hex[:8]}',
        )
        db.add(template)
        await db.flush()
        await db.refresh(template)

        result = await ValuationService._record_receipt_async(
            db, template, Decimal('10'), None, async_test_household.id
        )
        assert result is not None
        assert result.quantity == Decimal('10')
        assert result.cost_basis == CostBasis.UNKNOWN

    async def test_multiple_receipts_compute_weighted_average(
        self, real_async_db_session: AsyncSession, async_test_household
    ):
        db = real_async_db_session
        template = ProductTemplate(
            organization_id=async_test_household.id,
            name='MultiReceipt',
            sku=f'MR-{uuid4().hex[:8]}',
        )
        db.add(template)
        await db.flush()
        await db.refresh(template)

        await ValuationService._record_receipt_async(
            db, template, Decimal('10'), Decimal('5.00'), async_test_household.id
        )
        await ValuationService._record_receipt_async(
            db, template, Decimal('10'), Decimal('7.00'), async_test_household.id
        )
        await db.flush()
        await db.refresh(template)

        # AVCO = (10*5 + 10*7) / (10+10) = 120/20 = 6.00
        assert await _rate(db, async_test_household.id, template) == Decimal('6.00')

    async def test_receipt_with_document_line_id(
        self, real_async_db_session: AsyncSession, async_test_household
    ):
        db = real_async_db_session
        template = ProductTemplate(
            organization_id=async_test_household.id,
            name='DocLine',
            sku=f'DL-{uuid4().hex[:8]}',
        )
        db.add(template)
        await db.flush()
        await db.refresh(template)

        svl = await ValuationService._record_receipt_async(
            db,
            template,
            Decimal('5'),
            Decimal('3.00'),
            async_test_household.id,
            document_line_id=None,
        )
        assert svl.document_line_id is None
        assert svl.quantity == Decimal('5')


@pytest.mark.integration
@pytest.mark.asyncio
class TestRecordDelivery:
    async def _setup_template_with_stock(self, db: AsyncSession, org_id, qty, cost):
        template = ProductTemplate(
            organization_id=org_id,
            name='DeliveryTest',
            sku=f'DT-{uuid4().hex[:8]}',
        )
        db.add(template)
        await db.flush()
        await db.refresh(template)
        await ValuationService._record_receipt_async(db, template, qty, cost, org_id)
        await db.flush()
        return template

    async def test_delivery_consumes_layers(
        self, real_async_db_session: AsyncSession, async_test_household
    ):
        db = real_async_db_session
        template = await self._setup_template_with_stock(
            db, async_test_household.id, Decimal('20'), Decimal('5.00')
        )
        consumed = await ValuationService._post_delivery_async(
            db, template, Decimal('5'), async_test_household.id
        )
        await db.flush()

        assert len(consumed.consumed_layers) == 1
        assert consumed.consumed_layers[0].remaining_qty == Decimal('15')

    async def test_zero_delivery_returns_empty(
        self, real_async_db_session: AsyncSession, async_test_household
    ):
        db = real_async_db_session
        template = await self._setup_template_with_stock(
            db, async_test_household.id, Decimal('10'), Decimal('3.00')
        )
        result = await ValuationService._post_delivery_async(
            db, template, Decimal('0'), async_test_household.id
        )
        assert result.consumed_layers == []

    async def test_negative_delivery_returns_empty(
        self, real_async_db_session: AsyncSession, async_test_household
    ):
        db = real_async_db_session
        template = await self._setup_template_with_stock(
            db, async_test_household.id, Decimal('10'), Decimal('3.00')
        )
        result = await ValuationService._post_delivery_async(
            db, template, Decimal('-1'), async_test_household.id
        )
        assert result.consumed_layers == []

    async def test_full_delivery_consumes_entire_layer(
        self, real_async_db_session: AsyncSession, async_test_household
    ):
        db = real_async_db_session
        template = await self._setup_template_with_stock(
            db, async_test_household.id, Decimal('10'), Decimal('4.00')
        )
        consumed = await ValuationService._post_delivery_async(
            db, template, Decimal('10'), async_test_household.id
        )
        await db.flush()

        assert len(consumed.consumed_layers) == 1
        assert consumed.consumed_layers[0].remaining_qty == Decimal('0')

    async def test_partial_delivery_leaves_remaining(
        self, real_async_db_session: AsyncSession, async_test_household
    ):
        db = real_async_db_session
        template = await self._setup_template_with_stock(
            db, async_test_household.id, Decimal('10'), Decimal('4.00')
        )
        consumed = await ValuationService._post_delivery_async(
            db, template, Decimal('3'), async_test_household.id
        )
        await db.flush()

        assert len(consumed.consumed_layers) == 1
        assert consumed.consumed_layers[0].remaining_qty == Decimal('7')

    async def test_delivery_spanning_multiple_layers_fifo(
        self, real_async_db_session: AsyncSession, async_test_household
    ):
        db = real_async_db_session
        template = ProductTemplate(
            organization_id=async_test_household.id,
            name='FIFO Test',
            sku=f'FT-{uuid4().hex[:8]}',
        )
        db.add(template)
        await db.flush()
        await db.refresh(template)

        await ValuationService._record_receipt_async(
            db, template, Decimal('5'), Decimal('3.00'), async_test_household.id
        )
        await ValuationService._record_receipt_async(
            db, template, Decimal('5'), Decimal('6.00'), async_test_household.id
        )
        await db.flush()

        consumed = await ValuationService._post_delivery_async(
            db, template, Decimal('8'), async_test_household.id
        )
        await db.flush()

        assert len(consumed.consumed_layers) == 2
        # First layer fully consumed
        assert consumed.consumed_layers[0].remaining_qty == Decimal('0')
        # Second layer partially consumed (5 - 3 = 2 remaining)
        assert consumed.consumed_layers[1].remaining_qty == Decimal('2')

    async def test_delivery_with_no_layers_returns_empty(
        self, real_async_db_session: AsyncSession, async_test_household
    ):
        db = real_async_db_session
        template = ProductTemplate(
            organization_id=async_test_household.id,
            name='Empty Stock',
            sku=f'ES-{uuid4().hex[:8]}',
        )
        db.add(template)
        await db.flush()
        await db.refresh(template)

        result = await ValuationService._post_delivery_async(
            db, template, Decimal('5'), async_test_household.id
        )
        assert result.consumed_layers == []


@pytest.mark.integration
@pytest.mark.asyncio
class TestRecordReceiptById:
    async def test_creates_svl_for_valid_template(
        self, real_async_db_session: AsyncSession, async_test_household
    ):
        db = real_async_db_session
        template = ProductTemplate(
            organization_id=async_test_household.id,
            name='By ID',
            sku=f'BI-{uuid4().hex[:8]}',
        )
        db.add(template)
        await db.flush()
        await db.refresh(template)

        svl = await ValuationService.record_receipt_by_id_async(
            db, async_test_household.id, template.id, Decimal('10'), Decimal('2.50')
        )
        await db.flush()

        assert svl is not None
        assert svl.product_template_id == template.id
        assert svl.quantity == Decimal('10')
        assert svl.unit_cost == Decimal('2.50')

    async def test_returns_none_for_missing_template(
        self, real_async_db_session: AsyncSession, async_test_household
    ):
        db = real_async_db_session
        result = await ValuationService.record_receipt_by_id_async(
            db, async_test_household.id, uuid4(), Decimal('10'), Decimal('5.00')
        )
        assert result is None

    async def test_returns_none_for_zero_quantity(
        self, real_async_db_session: AsyncSession, async_test_household
    ):
        db = real_async_db_session
        template = ProductTemplate(
            organization_id=async_test_household.id,
            name='ZeroQtyById',
            sku=f'ZQB-{uuid4().hex[:8]}',
        )
        db.add(template)
        await db.flush()
        await db.refresh(template)

        result = await ValuationService.record_receipt_by_id_async(
            db, async_test_household.id, template.id, Decimal('0'), Decimal('5.00')
        )
        assert result is None

    async def test_no_stated_cost_still_posts_a_layer(
        self, real_async_db_session: AsyncSession, async_test_household
    ):
        db = real_async_db_session
        template = ProductTemplate(
            organization_id=async_test_household.id,
            name='NoCostById',
            sku=f'NCB-{uuid4().hex[:8]}',
        )
        db.add(template)
        await db.flush()
        await db.refresh(template)

        result = await ValuationService.record_receipt_by_id_async(
            db, async_test_household.id, template.id, Decimal('10'), None
        )
        assert result is not None
        assert result.cost_basis == CostBasis.UNKNOWN


@pytest.mark.integration
@pytest.mark.asyncio
class TestRecordDeliveryById:
    async def _setup_template_with_stock(self, db: AsyncSession, org_id, qty, cost):
        template = ProductTemplate(
            organization_id=org_id,
            name='DelivById',
            sku=f'DBI-{uuid4().hex[:8]}',
        )
        db.add(template)
        await db.flush()
        await db.refresh(template)
        await ValuationService._record_receipt_async(db, template, qty, cost, org_id)
        await db.flush()
        return template

    async def test_delivery_by_id_consume_stock(
        self, real_async_db_session: AsyncSession, async_test_household
    ):
        db = real_async_db_session
        template = await self._setup_template_with_stock(
            db, async_test_household.id, Decimal('15'), Decimal('4.00')
        )
        consumed = await ValuationService.post_delivery_by_id_async(
            db, async_test_household.id, template.id, Decimal('5')
        )
        await db.flush()

        assert len(consumed.consumed_layers) == 1
        assert consumed.consumed_layers[0].remaining_qty == Decimal('10')

    async def test_delivery_by_id_missing_template_returns_empty(
        self, real_async_db_session: AsyncSession, async_test_household
    ):
        db = real_async_db_session
        result = await ValuationService.post_delivery_by_id_async(
            db, async_test_household.id, uuid4(), Decimal('5')
        )
        assert result.consumed_layers == []

    async def test_delivery_by_id_zero_qty_returns_empty(
        self, real_async_db_session: AsyncSession, async_test_household
    ):
        db = real_async_db_session
        template = await self._setup_template_with_stock(
            db, async_test_household.id, Decimal('10'), Decimal('3.00')
        )
        result = await ValuationService.post_delivery_by_id_async(
            db, async_test_household.id, template.id, Decimal('0')
        )
        assert result.consumed_layers == []


@pytest.mark.integration
@pytest.mark.asyncio
class TestTheRate:
    async def test_no_layers_means_no_rate(
        self, real_async_db_session: AsyncSession, async_test_household
    ):
        db = real_async_db_session
        template = ProductTemplate(
            organization_id=async_test_household.id,
            name='NoLayers',
            sku=f'NL-{uuid4().hex[:8]}',
        )
        db.add(template)
        await db.flush()
        await db.refresh(template)

        # A product holding no stock has no average cost. It used to be
        # possible to seed a stale one onto the row, which is what this test
        # did — the number then survived every recompute that never ran.
        assert await _rate(db, async_test_household.id, template) is None

    async def test_avco_after_full_delivery_clears_rate(
        self, real_async_db_session: AsyncSession, async_test_household
    ):
        db = real_async_db_session
        template = ProductTemplate(
            organization_id=async_test_household.id,
            name='FullDeliv',
            sku=f'FD-{uuid4().hex[:8]}',
        )
        db.add(template)
        await db.flush()
        await db.refresh(template)

        await ValuationService._record_receipt_async(
            db, template, Decimal('10'), Decimal('5.00'), async_test_household.id
        )
        await db.flush()
        await db.refresh(template)
        assert await _rate(db, async_test_household.id, template) == Decimal('5.00')

        await ValuationService._post_delivery_async(
            db, template, Decimal('10'), async_test_household.id
        )
        await db.flush()

        # Delivering all the stock drains every layer, so there is no average
        # left to take — not a stale last value.
        assert await _rate(db, async_test_household.id, template) is None

    async def test_avco_weighted_three_receipts(
        self, real_async_db_session: AsyncSession, async_test_household
    ):
        db = real_async_db_session
        template = ProductTemplate(
            organization_id=async_test_household.id,
            name='ThreeReceipts',
            sku=f'TR-{uuid4().hex[:8]}',
        )
        db.add(template)
        await db.flush()
        await db.refresh(template)

        await ValuationService._record_receipt_async(
            db, template, Decimal('10'), Decimal('2.00'), async_test_household.id
        )
        await ValuationService._record_receipt_async(
            db, template, Decimal('20'), Decimal('4.00'), async_test_household.id
        )
        await ValuationService._record_receipt_async(
            db, template, Decimal('10'), Decimal('8.00'), async_test_household.id
        )
        await db.flush()
        await db.refresh(template)

        # AVCO = (10*2 + 20*4 + 10*8) / (10+20+10) = (20+80+80)/40 = 180/40 = 4.50
        assert await _rate(db, async_test_household.id, template) == Decimal('4.50')


@pytest.mark.integration
@pytest.mark.asyncio
class TestSvlRepr:
    async def test_repr_contains_key_info(
        self, real_async_db_session: AsyncSession, async_test_household
    ):
        db = real_async_db_session
        template = ProductTemplate(
            organization_id=async_test_household.id,
            name='ReprTest',
            sku=f'RT-{uuid4().hex[:8]}',
        )
        db.add(template)
        await db.flush()
        await db.refresh(template)

        svl = await ValuationService._record_receipt_async(
            db, template, Decimal('5'), Decimal('3.00'), async_test_household.id
        )
        await db.flush()

        r = repr(svl)
        assert 'StockValuationLayer' in r
        assert str(template.id) in r
        assert '5' in r
        assert '3.00' in r


@pytest.mark.integration
@pytest.mark.asyncio
class TestUnitCostOnManualReceipt:
    """A manual receipt (create/scan) with a unit cost must value the stock
    at that cost, not fabricate a zero-cost SVL layer (which pollutes AVCO)."""

    async def test_apply_quantity_change_with_unit_cost_values_layer(
        self,
        real_async_db_session: AsyncSession,
        async_test_household,
        async_test_storage_location,
    ):
        from sqlalchemy import select

        from app.models.item import Item
        from app.models.stock_valuation_layer import StockValuationLayer
        from app.services.items._stock_quant import apply_quantity_change_async

        db = real_async_db_session
        template = ProductTemplate(
            organization_id=async_test_household.id,
            name='C2Tpl',
            sku=f'C2-{uuid4().hex[:8]}',
        )
        db.add(template)
        await db.flush()  # populate template.id before referencing it
        item = Item(
            organization_id=async_test_household.id,
            storage_location_id=async_test_storage_location.id,
            template_id=template.id,
            name='C2Item',
            quantity=Decimal('0'),
        )
        db.add(item)
        await db.run_sync(anchor_pending_records)
        await db.flush()

        await apply_quantity_change_async(
            db,
            item,
            Decimal('5'),
            old_quantity=Decimal('0'),
            unit_cost=Decimal('12.50'),
        )
        await db.flush()

        svl = await db.scalar(
            select(StockValuationLayer).where(
                StockValuationLayer.product_template_id == template.id
            )
        )
        assert svl is not None, 'expected a valued SVL layer, got none'
        assert svl.unit_cost == Decimal('12.50')
        assert svl.remaining_qty == Decimal('5')

    async def test_apply_quantity_change_without_unit_cost_says_unknown(
        self,
        real_async_db_session: AsyncSession,
        async_test_household,
        async_test_storage_location,
    ):
        # No unit_cost and no rate to fall back on: the layer is posted and
        # marked unknown. The number beside it is 0.00 because a Numeric
        # column has to hold something — the mark is what a reader goes by.
        from sqlalchemy import select

        from app.models.item import Item
        from app.models.stock_valuation_layer import StockValuationLayer
        from app.services.items._stock_quant import apply_quantity_change_async

        db = real_async_db_session
        template = ProductTemplate(
            organization_id=async_test_household.id,
            name='C2Zero',
            sku=f'C2Z-{uuid4().hex[:8]}',
        )
        db.add(template)
        await db.flush()  # populate template.id before referencing it
        item = Item(
            organization_id=async_test_household.id,
            storage_location_id=async_test_storage_location.id,
            template_id=template.id,
            name='C2ZeroItem',
            quantity=Decimal('0'),
        )
        db.add(item)
        await db.run_sync(anchor_pending_records)
        await db.flush()

        await apply_quantity_change_async(
            db, item, Decimal('3'), old_quantity=Decimal('0')
        )
        await db.flush()

        svl = await db.scalar(
            select(StockValuationLayer).where(
                StockValuationLayer.product_template_id == template.id
            )
        )
        assert svl is not None
        assert svl.unit_cost == Decimal('0')
        assert svl.cost_basis == CostBasis.UNKNOWN


@pytest.mark.integration
@pytest.mark.asyncio
class TestCurrentValuationRateIsOrgScoped:
    """The method took ``organization_id`` and ignored it, so it
    returned another organization's AVCO cost."""

    async def test_foreign_template_rate_is_not_returned(
        self, real_async_db_session: AsyncSession, async_test_household
    ):
        from app.models.organization import Organization

        db = real_async_db_session
        other_org = Organization(name=f'Other {uuid4().hex[:8]}')
        db.add(other_org)
        await db.flush()

        template = ProductTemplate(
            organization_id=other_org.id,
            name='Foreign',
            sku=f'F-{uuid4().hex[:8]}',
        )
        db.add(template)
        await db.flush()
        await ValuationService._record_receipt_async(
            db, template, Decimal('10'), Decimal('42.00'), other_org.id
        )
        await db.flush()

        rate = await ValuationService.get_current_valuation_rate_async(
            db, async_test_household.id, template.id
        )

        assert rate is None

    async def test_own_and_global_templates_still_resolve(
        self, real_async_db_session: AsyncSession, async_test_household
    ):
        db = real_async_db_session
        mine = ProductTemplate(
            organization_id=async_test_household.id,
            name='Mine',
            sku=f'M-{uuid4().hex[:8]}',
        )
        shared = ProductTemplate(
            organization_id=None,
            name='Global',
            sku=f'G-{uuid4().hex[:8]}',
        )
        db.add_all([mine, shared])
        await db.flush()
        # Both rates come from this organization's own layers — including the
        # one on the global template, which is the whole point.
        await ValuationService._record_receipt_async(
            db, mine, Decimal('2'), Decimal('7.50'), async_test_household.id
        )
        await ValuationService._record_receipt_async(
            db, shared, Decimal('4'), Decimal('3.25'), async_test_household.id
        )
        await db.flush()

        assert await ValuationService.get_current_valuation_rate_async(
            db, async_test_household.id, mine.id
        ) == Decimal('7.50')
        assert await ValuationService.get_current_valuation_rate_async(
            db, async_test_household.id, shared.id
        ) == Decimal('3.25')


@pytest.mark.integration
@pytest.mark.asyncio
class TestValuationWriteIsOrgScoped:
    """the read paths are org-scoped since /; the write
    paths accepted ``organization_id`` and ignored it, so a receipt or
    delivery could value another organization's template or consume its
    layers."""

    async def _make_org(self, db: AsyncSession):
        from app.models.organization import Organization

        org = Organization(name=f'Other {uuid4().hex[:8]}')
        db.add(org)
        await db.flush()
        return org

    async def _make_template(self, db: AsyncSession, org_id):
        template = ProductTemplate(
            organization_id=org_id,
            name='ScopedWrite',
            sku=f'SW-{uuid4().hex[:8]}',
        )
        db.add(template)
        await db.flush()
        await db.refresh(template)
        return template

    async def test_foreign_template_receipt_creates_no_layer_and_keeps_rate(
        self, real_async_db_session: AsyncSession, async_test_household
    ):
        from sqlalchemy import select

        from app.models.stock_valuation_layer import StockValuationLayer

        db = real_async_db_session
        other_org = await self._make_org(db)
        foreign = await self._make_template(db, other_org.id)
        await ValuationService._record_receipt_async(
            db, foreign, Decimal('1'), Decimal('42.00'), other_org.id
        )
        await db.flush()

        result = await ValuationService.record_receipt_by_id_async(
            db, async_test_household.id, foreign.id, Decimal('10'), Decimal('5.00')
        )
        await db.flush()

        assert result is None
        layers = (
            await db.scalars(
                select(StockValuationLayer).where(
                    StockValuationLayer.product_template_id == foreign.id,
                    StockValuationLayer.organization_id == async_test_household.id,
                )
            )
        ).all()
        assert layers == []
        # And the other organization's own figure is untouched.
        assert await _rate(db, other_org.id, foreign) == Decimal('42.00')

    async def test_foreign_template_delivery_consumes_nothing(
        self, real_async_db_session: AsyncSession, async_test_household
    ):
        from sqlalchemy import select

        from app.models.stock_valuation_layer import StockValuationLayer

        db = real_async_db_session
        other_org = await self._make_org(db)
        foreign = await self._make_template(db, other_org.id)
        # Other org holds 20 units at 5.00.
        await ValuationService._record_receipt_async(
            db, foreign, Decimal('20'), Decimal('5.00'), other_org.id
        )
        await db.flush()

        consumed = await ValuationService.post_delivery_by_id_async(
            db, async_test_household.id, foreign.id, Decimal('5')
        )
        await db.flush()

        assert consumed.consumed_layers == []
        layer = (
            await db.scalars(
                select(StockValuationLayer).where(
                    StockValuationLayer.product_template_id == foreign.id
                )
            )
        ).first()
        assert layer is not None
        assert layer.remaining_qty == Decimal('20')
        assert await _rate(db, other_org.id, foreign) == Decimal('5.00')

    async def test_global_template_receipt_still_valued(
        self, real_async_db_session: AsyncSession, async_test_household
    ):
        db = real_async_db_session
        shared = await self._make_template(db, None)

        svl = await ValuationService.record_receipt_by_id_async(
            db, async_test_household.id, shared.id, Decimal('10'), Decimal('5.00')
        )
        await db.flush()

        assert svl is not None
        assert svl.organization_id == async_test_household.id
        assert await _rate(db, async_test_household.id, shared) == Decimal('5.00')

    async def test_global_template_delivery_consumes_only_own_org_layers(
        self, real_async_db_session: AsyncSession, async_test_household
    ):
        from sqlalchemy import select

        from app.models.stock_valuation_layer import StockValuationLayer

        db = real_async_db_session
        other_org = await self._make_org(db)
        shared = await self._make_template(db, None)

        # Both orgs valued the same global template.
        await ValuationService._record_receipt_async(
            db, shared, Decimal('10'), Decimal('5.00'), async_test_household.id
        )
        await ValuationService._record_receipt_async(
            db, shared, Decimal('10'), Decimal('3.00'), other_org.id
        )
        await db.flush()

        consumed = await ValuationService.post_delivery_by_id_async(
            db, async_test_household.id, shared.id, Decimal('4')
        )
        await db.flush()

        assert len(consumed.consumed_layers) == 1
        assert consumed.consumed_layers[0].organization_id == async_test_household.id
        assert consumed.consumed_layers[0].remaining_qty == Decimal('6')

        layers = (
            await db.scalars(
                select(StockValuationLayer)
                .where(
                    StockValuationLayer.product_template_id == shared.id,
                    StockValuationLayer.direction == 'IN',
                )
                .order_by(StockValuationLayer.unit_cost.asc())
            )
        ).all()
        assert len(layers) == 2
        by_org = {str(layer.organization_id): layer.remaining_qty for layer in layers}
        assert by_org[str(async_test_household.id)] == Decimal('6')
        assert by_org[str(other_org.id)] == Decimal('10')

        # The delivery also posts what it was worth, and that record belongs
        # to the organization that made it — a global template is shared, its
        # cost history is not.
        outgoing = (
            await db.scalars(
                select(StockValuationLayer).where(
                    StockValuationLayer.product_template_id == shared.id,
                    StockValuationLayer.direction == 'OUT',
                )
            )
        ).all()
        assert len(outgoing) == 1
        assert outgoing[0].organization_id == async_test_household.id
        assert outgoing[0].quantity == Decimal('4')
        assert outgoing[0].unit_cost == Decimal('5.00')
        assert outgoing[0].total_value == Decimal('20.00')
        # And it holds nothing anybody can draw on later.
        assert outgoing[0].remaining_qty == Decimal('0')

        # Each organization reads its own layers off the shared template:
        # (6 * 5) / 6 here, and the other organization's 3.00 stays theirs.
        # These two numbers used to be one column on one row.
        assert await _rate(db, async_test_household.id, shared) == Decimal('5.00')
        assert await _rate(db, other_org.id, shared) == Decimal('3.00')

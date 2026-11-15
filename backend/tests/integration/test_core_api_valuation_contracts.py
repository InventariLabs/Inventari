"""
Contract tests for CoreValuationAPI (app.core.public_api.core_api.valuation).

These tests pin down the SHAPE of every public method (async variants).
Valuation methods mutate ProductTemplate.last_purchase_price and
StockValuationLayer records; the contract is "no exception, side
effects visible after commit".
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.public_api import core_api


def _make_valuation_template(db, organization_id):
    """Create a ProductTemplate for valuation tests via sync session."""
    from uuid import uuid4

    from app.models.product_template import ProductTemplate

    template = ProductTemplate(
        organization_id=organization_id,
        name='Valuation Test',
        sku=f'SKU-VAL-{uuid4().hex[:8]}',
    )
    db.add(template)
    db.flush()
    db.refresh(template)
    return template


@pytest.mark.integration
@pytest.mark.asyncio
class TestCoreValuationReceiptContract:
    """`record_receipt_async` accepts and persists data."""

    async def test_record_receipt_async_returns_the_layer_it_opened(
        self, real_async_db_session: AsyncSession, async_test_household
    ):
        def _make_template(db):
            return _make_valuation_template(db, async_test_household.id)

        template = await real_async_db_session.run_sync(_make_template)

        result = await core_api.valuation.record_receipt_async(
            db=real_async_db_session,
            organization_id=async_test_household.id,
            product_template_id=template.id,
            quantity=Decimal('10.0'),
            unit_cost=Decimal('5.50'),
        )
        assert isinstance(result, UUID)

    async def test_record_receipt_async_sets_this_organizations_rate(
        self, real_async_db_session: AsyncSession, async_test_household
    ):
        """The rate is read back through the API, not off the template row.

        It used to be a cached column there, and a global template is one row
        every organization shares — so the figure belonged to whoever wrote
        last.
        """

        def _make_template(db):
            return _make_valuation_template(db, async_test_household.id)

        template = await real_async_db_session.run_sync(_make_template)
        template_id = template.id

        await core_api.valuation.record_receipt_async(
            db=real_async_db_session,
            organization_id=async_test_household.id,
            product_template_id=template_id,
            quantity=Decimal('10.0'),
            unit_cost=Decimal('5.50'),
        )

        assert await core_api.valuation.get_current_rate_async(
            real_async_db_session, async_test_household.id, template_id
        ) == Decimal('5.50')

    async def test_record_receipt_async_with_async_session(
        self, real_async_db_session: AsyncSession, async_test_household
    ):
        def _make_template(db):
            return _make_valuation_template(db, async_test_household.id)

        template = await real_async_db_session.run_sync(_make_template)

        result = await core_api.valuation.record_receipt_async(
            db=real_async_db_session,
            organization_id=async_test_household.id,
            product_template_id=template.id,
            quantity=Decimal('5.0'),
            unit_cost=Decimal('3.00'),
        )
        assert isinstance(result, UUID)


@pytest.mark.integration
@pytest.mark.asyncio
class TestCoreValuationAddValueContract:
    """`add_value_to_layer_async` puts a cost found later on what is still there."""

    async def test_only_the_units_still_on_the_layer_carry_the_value(
        self, real_async_db_session: AsyncSession, async_test_household, async_test_user
    ):
        from app.core.contracts import UserContextDTO
        from app.models.stock_valuation_layer import StockValuationLayer

        template = await real_async_db_session.run_sync(
            lambda db: _make_valuation_template(db, async_test_household.id)
        )
        layer_id = await core_api.valuation.record_receipt_async(
            db=real_async_db_session,
            organization_id=async_test_household.id,
            product_template_id=template.id,
            quantity=Decimal('4'),
            unit_cost=Decimal('2.00'),
        )
        await core_api.valuation.record_delivery_async(
            real_async_db_session, async_test_household.id, template.id, Decimal('1')
        )
        user = UserContextDTO(
            id=async_test_user.id, organization_id=async_test_household.id
        )

        # 4.00 is for the four units received; one has left, so three share 3.00.
        placed = await core_api.valuation.add_value_to_layer_async(
            real_async_db_session,
            async_test_household.id,
            layer_id,
            Decimal('4.00'),
            user=user,
        )

        assert placed == Decimal('3.00')
        layer = await real_async_db_session.get(StockValuationLayer, layer_id)
        assert layer.remaining_qty == Decimal('3')
        assert layer.unit_cost == Decimal('3.0000')

    async def test_a_layer_that_is_empty_takes_nothing(
        self, real_async_db_session: AsyncSession, async_test_household, async_test_user
    ):
        from app.core.contracts import UserContextDTO

        template = await real_async_db_session.run_sync(
            lambda db: _make_valuation_template(db, async_test_household.id)
        )
        layer_id = await core_api.valuation.record_receipt_async(
            db=real_async_db_session,
            organization_id=async_test_household.id,
            product_template_id=template.id,
            quantity=Decimal('2'),
            unit_cost=Decimal('2.00'),
        )
        await core_api.valuation.record_delivery_async(
            real_async_db_session, async_test_household.id, template.id, Decimal('2')
        )

        placed = await core_api.valuation.add_value_to_layer_async(
            real_async_db_session,
            async_test_household.id,
            layer_id,
            Decimal('1.00'),
            user=UserContextDTO(
                id=async_test_user.id, organization_id=async_test_household.id
            ),
        )

        assert placed == Decimal('0')

    async def test_a_layer_takes_a_cost_once_and_remembers_what_it_read_before(
        self, real_async_db_session: AsyncSession, async_test_household, async_test_user
    ):
        from app.core.contracts import UserContextDTO
        from app.models.stock_valuation_layer import StockValuationLayer

        template = await real_async_db_session.run_sync(
            lambda db: _make_valuation_template(db, async_test_household.id)
        )
        layer_id = await core_api.valuation.record_receipt_async(
            db=real_async_db_session,
            organization_id=async_test_household.id,
            product_template_id=template.id,
            quantity=Decimal('2'),
            unit_cost=Decimal('2.00'),
        )
        user = UserContextDTO(
            id=async_test_user.id, organization_id=async_test_household.id
        )

        async def add(amount: str) -> Decimal:
            return await core_api.valuation.add_value_to_layer_async(
                real_async_db_session,
                async_test_household.id,
                layer_id,
                Decimal(amount),
                user=user,
            )

        assert await add('1.00') == Decimal('1.00')
        layer = await real_async_db_session.get(StockValuationLayer, layer_id)
        assert layer.unit_cost == Decimal('2.5000')
        assert layer.unit_cost_before == Decimal('2.0000')
        assert layer.cost_basis_before == layer.cost_basis
        assert layer.revalued_at is not None

        # The cost of a receipt is closed once: a second one is not placed, and
        # what the first one recorded stays what the layer read before it.
        assert await add('1.00') == Decimal('0')
        await real_async_db_session.refresh(layer)
        assert layer.unit_cost == Decimal('2.5000')
        assert layer.unit_cost_before == Decimal('2.0000')

    async def test_a_layer_nobody_priced_has_a_stated_cost_once_it_takes_one(
        self, real_async_db_session: AsyncSession, async_test_household, async_test_user
    ):
        from app.core.contracts import UserContextDTO
        from app.models.stock_valuation_layer import CostBasis, StockValuationLayer

        template = await real_async_db_session.run_sync(
            lambda db: _make_valuation_template(db, async_test_household.id)
        )
        layer_id = await core_api.valuation.record_receipt_async(
            db=real_async_db_session,
            organization_id=async_test_household.id,
            product_template_id=template.id,
            quantity=Decimal('2'),
            unit_cost=None,
        )
        layer = await real_async_db_session.get(StockValuationLayer, layer_id)
        assert layer.cost_basis == CostBasis.UNKNOWN

        await core_api.valuation.add_value_to_layer_async(
            real_async_db_session,
            async_test_household.id,
            layer_id,
            Decimal('1.00'),
            user=UserContextDTO(
                id=async_test_user.id, organization_id=async_test_household.id
            ),
        )

        await real_async_db_session.refresh(layer)
        assert layer.cost_basis == CostBasis.STATED
        assert layer.cost_basis_before == CostBasis.UNKNOWN
        assert layer.unit_cost == Decimal('0.5000')
        assert layer.unit_cost_before == Decimal('0.0000')


@pytest.mark.integration
@pytest.mark.asyncio
class TestCoreValuationUnpricedContract:
    """`record_unpriced_receipt_async` accepts a receipt with no stated price."""

    async def test_record_unpriced_receipt_async_returns_none(
        self, real_async_db_session: AsyncSession, async_test_household
    ):
        def _make_template(db):
            return _make_valuation_template(db, async_test_household.id)

        template = await real_async_db_session.run_sync(_make_template)

        result = await core_api.valuation.record_unpriced_receipt_async(
            db=real_async_db_session,
            organization_id=async_test_household.id,
            product_template_id=template.id,
            quantity=Decimal('5.0'),
        )
        assert result is None


@pytest.mark.integration
@pytest.mark.asyncio
class TestCoreValuationDeliveryContract:
    """`record_delivery_async` consumes the cost layers and says what they cost."""

    async def test_record_delivery_async_returns_what_the_layers_cost(
        self, real_async_db_session: AsyncSession, async_test_household
    ):
        def _make_template(db):
            return _make_valuation_template(db, async_test_household.id)

        template = await real_async_db_session.run_sync(_make_template)

        # First add stock with cost
        await core_api.valuation.record_receipt_async(
            db=real_async_db_session,
            organization_id=async_test_household.id,
            product_template_id=template.id,
            quantity=Decimal('20.0'),
            unit_cost=Decimal('2.00'),
        )
        # Then deliver some
        result = await core_api.valuation.record_delivery_async(
            db=real_async_db_session,
            organization_id=async_test_household.id,
            product_template_id=template.id,
            quantity=Decimal('5.0'),
        )
        # Five units off a layer bought at 2.00. The figure is what a caller
        # pricing the result of the outflow — a production run valuing its
        # output — has to charge; ``None`` is reserved for layers that cannot
        # say what the goods cost.
        assert result == Decimal('10.00')


@pytest.mark.integration
@pytest.mark.asyncio
class TestCoreValuationWriteIsOrgScoped:
    """the public API write path must not touch another
    organization's template or layers."""

    async def test_receipt_for_foreign_template_is_a_noop(
        self, real_async_db_session: AsyncSession, async_test_household
    ):
        from uuid import uuid4

        from sqlalchemy import select

        from app.models.organization import Organization
        from app.models.product_template import ProductTemplate
        from app.models.stock_valuation_layer import StockValuationLayer

        db = real_async_db_session

        def _make_foreign_template(session):
            other_org = Organization(name=f'Foreign {uuid4().hex[:8]}')
            session.add(other_org)
            session.flush()
            foreign = ProductTemplate(
                organization_id=other_org.id,
                name='Foreign',
                sku=f'SKU-FOR-{uuid4().hex[:8]}',
            )
            session.add(foreign)
            session.flush()
            session.refresh(foreign)
            return foreign, other_org.id

        foreign, other_org_id = await db.run_sync(_make_foreign_template)
        # The other organization's own stock, at its own price.
        await core_api.valuation.record_receipt_async(
            db=db,
            organization_id=other_org_id,
            product_template_id=foreign.id,
            quantity=Decimal('1.0'),
            unit_cost=Decimal('42.00'),
        )

        result = await core_api.valuation.record_receipt_async(
            db=db,
            organization_id=async_test_household.id,
            product_template_id=foreign.id,
            quantity=Decimal('10.0'),
            unit_cost=Decimal('5.50'),
        )
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
        # And the owner's figure is untouched.
        assert await core_api.valuation.get_current_rate_async(
            db, other_org_id, foreign.id
        ) == Decimal('42.00')

"""Tests for the PartnerPricelist service.

Service is async; tests use real_async_db_session + async_test_*
fixtures to avoid sync/async mix issues.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.user import User


@pytest.mark.integration
@pytest.mark.asyncio
class TestPartnerPricelistService:
    """CRUD + query contract for PartnerPricelist."""

    async def test_create_async_persists_entry(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
        async_test_storage_location: StorageLocation,
    ) -> None:
        db = real_async_db_session

        template = ProductTemplate(
            organization_id=async_test_household.id,
            name='Pricelist Test',
            sku=f'SKU-PL-{uuid4().hex[:8]}',
        )
        partner = Partner(
            organization_id=async_test_household.id,
            name='Test Supplier',
            type='SUPPLIER',
            created_by=async_test_user.id,
        )
        db.add_all([template, partner])
        await db.flush()

        from app.modules.purchase_orders.pricelist_service import create_async

        entry = await create_async(
            db,
            organization_id=async_test_household.id,
            partner_id=partner.id,
            product_template_id=template.id,
            unit_price=Decimal('12.5000'),
            currency='EUR',
            valid_from=date(2026, 1, 1),
            valid_to=date(2026, 12, 31),
            notes='Q1-Q4 contract',
        )
        await db.commit()

        assert entry.id is not None
        assert entry.unit_price == Decimal('12.5000')
        assert entry.currency == 'EUR'
        assert entry.valid_from == date(2026, 1, 1)
        assert entry.valid_to == date(2026, 12, 31)
        assert entry.notes == 'Q1-Q4 contract'

    async def test_create_async_validates_positive_unit_price(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
    ) -> None:
        from app.modules.purchase_orders.pricelist_service import create_async

        template = ProductTemplate(
            organization_id=async_test_household.id,
            name='Pricelist Validate',
            sku=f'SKU-PV-{uuid4().hex[:8]}',
        )
        partner = Partner(
            organization_id=async_test_household.id,
            name='Validate Supplier',
            type='SUPPLIER',
            created_by=async_test_user.id,
        )
        real_async_db_session.add_all([template, partner])
        await real_async_db_session.flush()

        with pytest.raises(ValueError, match='unit_price'):
            await create_async(
                real_async_db_session,
                organization_id=async_test_household.id,
                partner_id=partner.id,
                product_template_id=template.id,
                unit_price=Decimal('-1'),
                valid_from=date.today(),
            )

    async def test_create_async_validates_valid_to_ge_valid_from(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
    ) -> None:
        from app.modules.purchase_orders.pricelist_service import create_async

        template = ProductTemplate(
            organization_id=async_test_household.id,
            name='Pricelist Validate',
            sku=f'SKU-PV2-{uuid4().hex[:8]}',
        )
        partner = Partner(
            organization_id=async_test_household.id,
            name='Validate Supplier',
            type='SUPPLIER',
            created_by=async_test_user.id,
        )
        real_async_db_session.add_all([template, partner])
        await real_async_db_session.flush()

        with pytest.raises(ValueError, match='valid_to'):
            await create_async(
                real_async_db_session,
                organization_id=async_test_household.id,
                partner_id=partner.id,
                product_template_id=template.id,
                unit_price=Decimal('5'),
                valid_from=date(2026, 6, 1),
                valid_to=date(2026, 1, 1),
            )

    async def test_list_for_partner_async_returns_only_partner_entries(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
    ) -> None:
        db = real_async_db_session

        template = ProductTemplate(
            organization_id=async_test_household.id,
            name='Pricelist List',
            sku=f'SKU-PLL-{uuid4().hex[:8]}',
        )
        partner_a = Partner(
            organization_id=async_test_household.id,
            name='Supplier A',
            type='SUPPLIER',
            created_by=async_test_user.id,
        )
        partner_b = Partner(
            organization_id=async_test_household.id,
            name='Supplier B',
            type='SUPPLIER',
            created_by=async_test_user.id,
        )
        db.add_all([template, partner_a, partner_b])
        await db.flush()

        from app.modules.purchase_orders.pricelist_service import (
            create_async,
            list_for_partner_async,
        )

        await create_async(
            db,
            organization_id=async_test_household.id,
            partner_id=partner_a.id,
            product_template_id=template.id,
            unit_price=Decimal('10'),
            valid_from=date(2026, 1, 1),
        )
        await create_async(
            db,
            organization_id=async_test_household.id,
            partner_id=partner_a.id,
            product_template_id=template.id,
            unit_price=Decimal('8'),
            valid_from=date(2026, 6, 1),
        )
        await create_async(
            db,
            organization_id=async_test_household.id,
            partner_id=partner_b.id,
            product_template_id=template.id,
            unit_price=Decimal('9'),
            valid_from=date(2026, 1, 1),
        )
        await db.commit()

        only_a = await list_for_partner_async(db, async_test_household.id, partner_a.id)
        assert len(only_a) == 2
        assert all(e.partner_id == partner_a.id for e in only_a)
        # Display name comes from the selectin-loaded product_template
        assert all(e.product_name == 'Pricelist List' for e in only_a)

    async def test_list_for_template_async_ordered_by_unit_price(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
    ) -> None:
        db = real_async_db_session

        template = ProductTemplate(
            organization_id=async_test_household.id,
            name='Pricelist Compare',
            sku=f'SKU-PC-{uuid4().hex[:8]}',
        )
        p_cheap = Partner(
            organization_id=async_test_household.id,
            name='Cheap',
            type='SUPPLIER',
            created_by=async_test_user.id,
        )
        p_mid = Partner(
            organization_id=async_test_household.id,
            name='Mid',
            type='SUPPLIER',
            created_by=async_test_user.id,
        )
        p_exp = Partner(
            organization_id=async_test_household.id,
            name='Expensive',
            type='SUPPLIER',
            created_by=async_test_user.id,
        )
        db.add_all([template, p_cheap, p_mid, p_exp])
        await db.flush()

        from app.modules.purchase_orders.pricelist_service import (
            create_async,
            list_for_template_async,
        )

        await create_async(
            db,
            organization_id=async_test_household.id,
            partner_id=p_exp.id,
            product_template_id=template.id,
            unit_price=Decimal('20'),
            valid_from=date(2026, 1, 1),
        )
        await create_async(
            db,
            organization_id=async_test_household.id,
            partner_id=p_cheap.id,
            product_template_id=template.id,
            unit_price=Decimal('5'),
            valid_from=date(2026, 1, 1),
        )
        await create_async(
            db,
            organization_id=async_test_household.id,
            partner_id=p_mid.id,
            product_template_id=template.id,
            unit_price=Decimal('12'),
            valid_from=date(2026, 1, 1),
        )
        await db.commit()

        offers = await list_for_template_async(db, async_test_household.id, template.id)
        prices = [e.unit_price for e in offers]
        assert prices == [Decimal('5'), Decimal('12'), Decimal('20')]

    async def test_get_best_price_async_returns_cheapest_valid(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
    ) -> None:
        db = real_async_db_session

        template = ProductTemplate(
            organization_id=async_test_household.id,
            name='Best Price',
            sku=f'SKU-BP-{uuid4().hex[:8]}',
        )
        p_a = Partner(
            organization_id=async_test_household.id,
            name='A',
            type='SUPPLIER',
            created_by=async_test_user.id,
        )
        p_b = Partner(
            organization_id=async_test_household.id,
            name='B',
            type='SUPPLIER',
            created_by=async_test_user.id,
        )
        db.add_all([template, p_a, p_b])
        await db.flush()

        from app.modules.purchase_orders.pricelist_service import (
            create_async,
            get_best_price_async,
        )

        # Expired entry (should be ignored)
        await create_async(
            db,
            organization_id=async_test_household.id,
            partner_id=p_a.id,
            product_template_id=template.id,
            unit_price=Decimal('1'),
            valid_from=date(2025, 1, 1),
            valid_to=date(2025, 12, 31),
        )
        # Active, more expensive
        await create_async(
            db,
            organization_id=async_test_household.id,
            partner_id=p_b.id,
            product_template_id=template.id,
            unit_price=Decimal('15'),
            valid_from=date(2026, 1, 1),
        )
        # Active, cheaper
        await create_async(
            db,
            organization_id=async_test_household.id,
            partner_id=p_a.id,
            product_template_id=template.id,
            unit_price=Decimal('7'),
            valid_from=date(2026, 1, 1),
        )
        await db.commit()

        best = await get_best_price_async(
            db, async_test_household.id, template.id, on_date=date(2026, 6, 1)
        )
        assert best is not None
        assert best.unit_price == Decimal('7')
        assert best.partner_id == p_a.id

    async def test_get_best_price_async_with_volume_tier(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
    ) -> None:
        db = real_async_db_session

        template = ProductTemplate(
            organization_id=async_test_household.id,
            name='Volume Tier',
            sku=f'SKU-VT-{uuid4().hex[:8]}',
        )
        p = Partner(
            organization_id=async_test_household.id,
            name='Vol',
            type='SUPPLIER',
            created_by=async_test_user.id,
        )
        db.add_all([template, p])
        await db.flush()

        from app.modules.purchase_orders.pricelist_service import (
            create_async,
            get_best_price_async,
        )

        # Small-volume: cheap per-unit
        await create_async(
            db,
            organization_id=async_test_household.id,
            partner_id=p.id,
            product_template_id=template.id,
            unit_price=Decimal('1'),
            min_quantity=Decimal('1'),
            valid_from=date(2026, 1, 1),
        )
        # Bulk discount: requires 100+ units, slightly more per-unit
        await create_async(
            db,
            organization_id=async_test_household.id,
            partner_id=p.id,
            product_template_id=template.id,
            unit_price=Decimal('0.80'),
            min_quantity=Decimal('100'),
            valid_from=date(2026, 1, 1),
        )
        await db.commit()

        small = await get_best_price_async(
            db, async_test_household.id, template.id, quantity=Decimal('10')
        )
        assert small is not None
        assert small.unit_price == Decimal('1')

        bulk = await get_best_price_async(
            db, async_test_household.id, template.id, quantity=Decimal('200')
        )
        assert bulk is not None
        assert bulk.unit_price == Decimal('0.80')

    async def test_get_best_price_async_returns_none_when_no_entries(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
    ) -> None:
        from app.modules.purchase_orders.pricelist_service import get_best_price_async

        assert (
            await get_best_price_async(
                real_async_db_session, async_test_household.id, uuid4()
            )
            is None
        )

    async def test_update_async_modifies_unit_price(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
    ) -> None:
        db = real_async_db_session

        template = ProductTemplate(
            organization_id=async_test_household.id,
            name='Pricelist Update',
            sku=f'SKU-PU-{uuid4().hex[:8]}',
        )
        partner = Partner(
            organization_id=async_test_household.id,
            name='Upd',
            type='SUPPLIER',
            created_by=async_test_user.id,
        )
        db.add_all([template, partner])
        await db.flush()

        from app.modules.purchase_orders.pricelist_service import (
            create_async,
            update_async,
        )

        entry = await create_async(
            db,
            organization_id=async_test_household.id,
            partner_id=partner.id,
            product_template_id=template.id,
            unit_price=Decimal('10'),
            valid_from=date(2026, 1, 1),
        )
        await db.commit()

        updated = await update_async(
            db,
            organization_id=async_test_household.id,
            entry_id=entry.id,
            unit_price=Decimal('15'),
            notes='Updated',
        )
        await db.commit()

        assert updated is not None
        assert updated.unit_price == Decimal('15')
        assert updated.notes == 'Updated'

    async def test_delete_async_removes_entry(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
    ) -> None:
        db = real_async_db_session

        template = ProductTemplate(
            organization_id=async_test_household.id,
            name='Pricelist Delete',
            sku=f'SKU-PD-{uuid4().hex[:8]}',
        )
        partner = Partner(
            organization_id=async_test_household.id,
            name='Del',
            type='SUPPLIER',
            created_by=async_test_user.id,
        )
        db.add_all([template, partner])
        await db.flush()

        from app.modules.purchase_orders.pricelist_service import (
            create_async,
            delete_async,
            get_async,
        )

        entry = await create_async(
            db,
            organization_id=async_test_household.id,
            partner_id=partner.id,
            product_template_id=template.id,
            unit_price=Decimal('10'),
            valid_from=date(2026, 1, 1),
        )
        await db.commit()

        assert await delete_async(db, async_test_household.id, entry.id) is True
        assert await get_async(db, async_test_household.id, entry.id) is None

    async def test_delete_async_returns_false_when_missing(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
    ) -> None:
        from app.modules.purchase_orders.pricelist_service import delete_async

        assert (
            await delete_async(real_async_db_session, async_test_household.id, uuid4())
            is False
        )


@pytest.mark.integration
@pytest.mark.asyncio
class TestPurchaseOrdersAPIPricelist:
    """Public Core API surface for PartnerPricelist."""

    async def test_list_pricelist_for_partner_async_returns_dtos(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
    ) -> None:
        db = real_async_db_session

        template = ProductTemplate(
            organization_id=async_test_household.id,
            name='API Partner List',
            sku=f'SKU-APL-{uuid4().hex[:8]}',
        )
        partner = Partner(
            organization_id=async_test_household.id,
            name='API Supplier',
            type='SUPPLIER',
            created_by=async_test_user.id,
        )
        db.add_all([template, partner])
        await db.flush()

        from app.modules.purchase_orders.pricelist_service import create_async
        from app.modules.purchase_orders.purchase_orders_api import purchase_orders_api

        await create_async(
            db,
            organization_id=async_test_household.id,
            partner_id=partner.id,
            product_template_id=template.id,
            unit_price=Decimal('5'),
            valid_from=date(2026, 1, 1),
        )
        await db.commit()

        dtos = await purchase_orders_api.list_pricelist_for_partner_async(
            db, async_test_household.id, partner.id
        )
        assert len(dtos) == 1
        assert dtos[0].unit_price == Decimal('5')

    async def test_list_supplier_prices_for_template_async(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
    ) -> None:
        db = real_async_db_session

        template = ProductTemplate(
            organization_id=async_test_household.id,
            name='API Template Compare',
            sku=f'SKU-ATC-{uuid4().hex[:8]}',
        )
        p_a = Partner(
            organization_id=async_test_household.id,
            name='A',
            type='SUPPLIER',
            created_by=async_test_user.id,
        )
        p_b = Partner(
            organization_id=async_test_household.id,
            name='B',
            type='SUPPLIER',
            created_by=async_test_user.id,
        )
        db.add_all([template, p_a, p_b])
        await db.flush()

        from app.modules.purchase_orders.pricelist_service import create_async
        from app.modules.purchase_orders.purchase_orders_api import purchase_orders_api

        await create_async(
            db,
            organization_id=async_test_household.id,
            partner_id=p_a.id,
            product_template_id=template.id,
            unit_price=Decimal('20'),
            valid_from=date(2026, 1, 1),
        )
        await create_async(
            db,
            organization_id=async_test_household.id,
            partner_id=p_b.id,
            product_template_id=template.id,
            unit_price=Decimal('10'),
            valid_from=date(2026, 1, 1),
        )
        await db.commit()

        dtos = await purchase_orders_api.list_supplier_prices_for_template_async(
            db, async_test_household.id, template.id
        )
        assert len(dtos) == 2
        assert dtos[0].unit_price == Decimal('10')
        assert dtos[1].unit_price == Decimal('20')

    async def test_get_best_price_for_competing_suppliers(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
    ) -> None:
        db = real_async_db_session

        template = ProductTemplate(
            organization_id=async_test_household.id,
            name='API Best',
            sku=f'SKU-AB-{uuid4().hex[:8]}',
        )
        p_a = Partner(
            organization_id=async_test_household.id,
            name='A',
            type='SUPPLIER',
            created_by=async_test_user.id,
        )
        p_b = Partner(
            organization_id=async_test_household.id,
            name='B',
            type='SUPPLIER',
            created_by=async_test_user.id,
        )
        db.add_all([template, p_a, p_b])
        await db.flush()

        from app.modules.purchase_orders.pricelist_service import (
            create_async,
            get_best_price_async,
        )

        await create_async(
            db,
            organization_id=async_test_household.id,
            partner_id=p_a.id,
            product_template_id=template.id,
            unit_price=Decimal('30'),
            valid_from=date(2026, 1, 1),
        )
        await create_async(
            db,
            organization_id=async_test_household.id,
            partner_id=p_b.id,
            product_template_id=template.id,
            unit_price=Decimal('12'),
            valid_from=date(2026, 1, 1),
        )
        await db.commit()

        best = await get_best_price_async(db, async_test_household.id, template.id)
        assert best is not None
        assert best.unit_price == Decimal('12')
        assert best.partner_id == p_b.id

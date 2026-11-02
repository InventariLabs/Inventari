"""Tests for the ReorderRule service.

Service is async; tests use real_async_db_session + async_test_* fixtures
to avoid sync/async mix issues.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.user import User


@pytest.mark.integration
@pytest.mark.asyncio
class TestReorderService:
    """CRUD contract for ReorderRule."""

    async def test_create_async_persists_rule(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
        async_test_storage_location: StorageLocation,
    ) -> None:
        db = real_async_db_session

        template = await db.run_sync(
            lambda s: ProductTemplate(
                organization_id=async_test_household.id,
                name='Reorder Test',
                sku=f'SKU-RORD-{uuid4().hex[:8]}',
            )
        )
        db.add(template)
        await db.flush()

        from app.modules.purchase_orders.reorder_service import create_async

        rule = await create_async(
            db,
            organization_id=async_test_household.id,
            product_template_id=template.id,
            storage_location_id=async_test_storage_location.id,
            min_quantity=Decimal('5'),
            max_quantity=Decimal('20'),
            safety_stock=Decimal('2'),
        )
        await db.commit()

        assert rule.id is not None
        assert rule.min_quantity == Decimal('5')
        assert rule.max_quantity == Decimal('20')
        assert rule.safety_stock == Decimal('2')

    async def test_create_async_validates_max_ge_min(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_storage_location: StorageLocation,
    ) -> None:
        from app.modules.purchase_orders.reorder_service import create_async

        template = ProductTemplate(
            organization_id=async_test_household.id,
            name='Reorder Validate',
            sku=f'SKU-RV-{uuid4().hex[:8]}',
        )
        real_async_db_session.add(template)
        await real_async_db_session.flush()

        with pytest.raises(ValueError, match='max_quantity'):
            await create_async(
                real_async_db_session,
                organization_id=async_test_household.id,
                product_template_id=template.id,
                storage_location_id=async_test_storage_location.id,
                min_quantity=Decimal('20'),
                max_quantity=Decimal('5'),
            )

    async def test_create_async_validates_non_negative(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_storage_location: StorageLocation,
    ) -> None:
        from app.modules.purchase_orders.reorder_service import create_async

        template = ProductTemplate(
            organization_id=async_test_household.id,
            name='Reorder Validate',
            sku=f'SKU-RV2-{uuid4().hex[:8]}',
        )
        real_async_db_session.add(template)
        await real_async_db_session.flush()

        with pytest.raises(ValueError, match='safety_stock'):
            await create_async(
                real_async_db_session,
                organization_id=async_test_household.id,
                product_template_id=template.id,
                storage_location_id=async_test_storage_location.id,
                min_quantity=Decimal('0'),
                max_quantity=Decimal('10'),
                safety_stock=Decimal('-1'),
            )

    async def test_get_async_returns_rule_or_none(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_storage_location: StorageLocation,
    ) -> None:
        from app.modules.purchase_orders.reorder_service import (
            create_async,
            get_async,
        )

        template = ProductTemplate(
            organization_id=async_test_household.id,
            name='Reorder Get',
            sku=f'SKU-RG-{uuid4().hex[:8]}',
        )
        real_async_db_session.add(template)
        await real_async_db_session.flush()

        rule = await create_async(
            real_async_db_session,
            organization_id=async_test_household.id,
            product_template_id=template.id,
            storage_location_id=async_test_storage_location.id,
            min_quantity=Decimal('5'),
            max_quantity=Decimal('20'),
        )
        await real_async_db_session.commit()

        found = await get_async(real_async_db_session, async_test_household.id, rule.id)
        assert found is not None
        assert found.id == rule.id

        missing = await get_async(
            real_async_db_session, async_test_household.id, uuid4()
        )
        assert missing is None

    async def test_list_for_org_async_filters(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
        async_test_storage_location: StorageLocation,
    ) -> None:
        from app.modules.purchase_orders.reorder_service import (
            create_async,
            list_for_org_async,
        )

        template = ProductTemplate(
            organization_id=async_test_household.id,
            name='Reorder List',
            sku=f'SKU-RL-{uuid4().hex[:8]}',
        )
        real_async_db_session.add(template)
        await real_async_db_session.flush()

        loc_b = StorageLocation(
            organization_id=async_test_household.id,
            created_by=async_test_user.id,
            storage_type_id=async_test_storage_location.storage_type_id,
            name='Loc B',
        )
        real_async_db_session.add(loc_b)
        await real_async_db_session.flush()

        for loc in (async_test_storage_location, loc_b):
            await create_async(
                real_async_db_session,
                organization_id=async_test_household.id,
                product_template_id=template.id,
                storage_location_id=loc.id,
                min_quantity=Decimal('5'),
                max_quantity=Decimal('20'),
            )
        await real_async_db_session.commit()

        all_rules = await list_for_org_async(
            real_async_db_session, async_test_household.id
        )
        assert len(all_rules) == 2

        only_first = await list_for_org_async(
            real_async_db_session,
            async_test_household.id,
            storage_location_id=async_test_storage_location.id,
        )
        assert len(only_first) == 1

    async def test_update_async_modifies_fields(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_storage_location: StorageLocation,
    ) -> None:
        from app.modules.purchase_orders.reorder_service import (
            create_async,
            update_async,
        )

        template = ProductTemplate(
            organization_id=async_test_household.id,
            name='Reorder Update',
            sku=f'SKU-RU-{uuid4().hex[:8]}',
        )
        real_async_db_session.add(template)
        await real_async_db_session.flush()

        rule = await create_async(
            real_async_db_session,
            organization_id=async_test_household.id,
            product_template_id=template.id,
            storage_location_id=async_test_storage_location.id,
            min_quantity=Decimal('5'),
            max_quantity=Decimal('20'),
        )
        await real_async_db_session.commit()

        updated = await update_async(
            real_async_db_session,
            organization_id=async_test_household.id,
            rule_id=rule.id,
            min_quantity=Decimal('10'),
            safety_stock=Decimal('3'),
        )
        await real_async_db_session.commit()

        assert updated is not None
        assert updated.min_quantity == Decimal('10')
        assert updated.safety_stock == Decimal('3')
        assert updated.max_quantity == Decimal('20')  # unchanged

    async def test_delete_async_removes_rule(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_storage_location: StorageLocation,
    ) -> None:
        from app.modules.purchase_orders.reorder_service import (
            create_async,
            delete_async,
            get_async,
        )

        template = ProductTemplate(
            organization_id=async_test_household.id,
            name='Reorder Delete',
            sku=f'SKU-RD-{uuid4().hex[:8]}',
        )
        real_async_db_session.add(template)
        await real_async_db_session.flush()

        rule = await create_async(
            real_async_db_session,
            organization_id=async_test_household.id,
            product_template_id=template.id,
            storage_location_id=async_test_storage_location.id,
            min_quantity=Decimal('5'),
            max_quantity=Decimal('20'),
        )
        await real_async_db_session.commit()

        assert (
            await delete_async(real_async_db_session, async_test_household.id, rule.id)
            is True
        )
        assert (
            await get_async(real_async_db_session, async_test_household.id, rule.id)
            is None
        )

    async def test_delete_async_returns_false_when_missing(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
    ) -> None:
        from app.modules.purchase_orders.reorder_service import delete_async

        assert (
            await delete_async(real_async_db_session, async_test_household.id, uuid4())
            is False
        )

    async def test_create_async_duplicate_raises_domain_error(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_storage_location: StorageLocation,
    ) -> None:
        """When the same (org, product, location) tuple is inserted
        twice, the service must raise a domain-specific error rather
        than a raw ``sqlalchemy.exc.IntegrityError`` (which would
        bubble to the router and surface as HTTP 500 to the UI).

        The router maps ``ReorderRuleAlreadyExistsError`` to HTTP 409
        — same pattern as :class:`ConnectionStillBoundError` in the
        AI Connections API.
        """
        from app.modules.purchase_orders.reorder_service import (
            ReorderRuleAlreadyExistsError,
            create_async,
        )

        template = ProductTemplate(
            organization_id=async_test_household.id,
            name='Reorder Duplicate',
            sku=f'SKU-RDUP-{uuid4().hex[:8]}',
        )
        real_async_db_session.add(template)
        await real_async_db_session.flush()
        template_id = template.id  # cache before any rollback

        await create_async(
            real_async_db_session,
            organization_id=async_test_household.id,
            product_template_id=template_id,
            storage_location_id=async_test_storage_location.id,
            min_quantity=Decimal('5'),
            max_quantity=Decimal('20'),
        )
        await real_async_db_session.commit()

        with pytest.raises(ReorderRuleAlreadyExistsError) as exc_info:
            await create_async(
                real_async_db_session,
                organization_id=async_test_household.id,
                product_template_id=template_id,
                storage_location_id=async_test_storage_location.id,
                min_quantity=Decimal('7'),
                max_quantity=Decimal('25'),
            )
            await real_async_db_session.commit()
        await real_async_db_session.rollback()

        # Error message names the offending tuple — fast debugging.
        # Use the cached template_id rather than re-accessing the
        # attribute, which would lazy-load after the rollback.
        msg = str(exc_info.value)
        assert str(template_id) in msg
        assert 'organization' in msg.lower()
        assert 'product' in msg.lower()
        assert 'location' in msg.lower()

    async def test_unique_constraint_at_db_level(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_storage_location: StorageLocation,
    ) -> None:
        """Defense-in-depth: the unique constraint is enforced by the
        database itself (see migration po_reorder_rules01). The service
        layer translates the raw ``IntegrityError`` into a domain error;
        bypass tests verify the DB-level guard still triggers when
        someone bypasses the service (e.g. raw SQL)."""
        from sqlalchemy import text
        from sqlalchemy.exc import IntegrityError

        template = ProductTemplate(
            organization_id=async_test_household.id,
            name='Reorder Unique DB',
            sku=f'SKU-RUDB-{uuid4().hex[:8]}',
        )
        real_async_db_session.add(template)
        await real_async_db_session.flush()

        await real_async_db_session.execute(
            text(
                'INSERT INTO po_reorder_rules (id, organization_id, '
                'product_template_id, storage_location_id, min_quantity, '
                'max_quantity, safety_stock, created_at, updated_at) '
                'VALUES (gen_random_uuid(), :oid, :tid, :lid, 1, 10, 0, '
                'now(), now())'
            ),
            {
                'oid': str(async_test_household.id),
                'tid': str(template.id),
                'lid': str(async_test_storage_location.id),
            },
        )
        await real_async_db_session.commit()

        with pytest.raises(IntegrityError):
            await real_async_db_session.execute(
                text(
                    'INSERT INTO po_reorder_rules (id, organization_id, '
                    'product_template_id, storage_location_id, min_quantity, '
                    'max_quantity, safety_stock, created_at, updated_at) '
                    'VALUES (gen_random_uuid(), :oid, :tid, :lid, 2, 20, 0, '
                    'now(), now())'
                ),
                {
                    'oid': str(async_test_household.id),
                    'tid': str(template.id),
                    'lid': str(async_test_storage_location.id),
                },
            )
            await real_async_db_session.commit()
        await real_async_db_session.rollback()

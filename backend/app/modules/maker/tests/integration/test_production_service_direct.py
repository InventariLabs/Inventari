"""Direct integration tests for ``production_service``.

The existing ``test_production_*`` tests drive these functions through the
FastAPI ``TestClient``, which runs the async app in a separate blocking-portal
thread. Coverage's tracer does not reliably record statements after the first
``await`` inside that worker thread, so those endpoint tests leave this module
around 29%. These tests call the service functions directly on a real
``AsyncSession`` so the lines are attributed correctly.

Production runs consume raw-material stock and produce finished goods. The
critical paths covered here are BOM explosion, cross-location consumption,
finished-good creation, yield/loss handling, quantity validation and the error
paths (missing template, insufficient stock, invalid quantities, wrong state).
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable, Coroutine
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, cast
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.contracts import UserContextDTO
from app.core.exceptions import EntityNotFoundError
from app.core.testing import ModuleTestHelper, ShelfRow
from app.models.audit_log import AuditLog
from app.models.item import Item
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.user import User
from app.modules.maker import production_service, recipe_service
from app.modules.maker._schemas_production import (
    ProductionOrderCreate,
    ProductionOrderUpdate,
)
from app.modules.maker.exceptions import (
    EmptyBillOfMaterialsError,
    InsufficientStockError,
    ShortageBlockedError,
    ShortageWarningError,
)
from app.modules.maker.models import (
    BoMLine,
    MakerModuleSettings,
    MakerRecipe,
    MakerRecipeCostLine,
    ProductionOrder,
)
from tests.integration._shelf import anchor_pending_records, put_on_shelf


@pytest.fixture
async def prod_org(real_async_db_session: AsyncSession) -> Organization:
    org = Organization(name='Production Ops Org', enabled_modules=['core', 'maker'])
    real_async_db_session.add(org)
    await real_async_db_session.flush()
    return org


@pytest.fixture
async def prod_user(
    real_async_db_session: AsyncSession, prod_org: Organization
) -> User:
    return await ModuleTestHelper.create_user_async(
        real_async_db_session,
        prod_org,
        email='production-ops@example.com',
        role='admin',
    )


@pytest.fixture
async def prod_ctx(prod_user: User) -> UserContextDTO:
    return UserContextDTO(
        id=prod_user.id,
        organization_id=prod_user.organization_id,
        role='admin',
    )


@pytest.fixture
async def prod_storage_type(real_async_db_session: AsyncSession) -> StorageType:
    storage_type = StorageType(
        name=f'Maker Storage {uuid.uuid4().hex[:8]}',
        type_code='MAKER',
        behavior_mode='NONE',
    )
    real_async_db_session.add(storage_type)
    await real_async_db_session.flush()
    return storage_type


# ---------------------------------------------------------------------------
# Async setup helpers (same session, flush-only — no commit).
# ---------------------------------------------------------------------------


async def _template(
    db: AsyncSession, org: Organization, *, name: str, removal_strategy: str = 'FIFO'
) -> ProductTemplate:
    template = ProductTemplate(
        organization_id=org.id,
        name=name,
        removal_strategy=removal_strategy,
    )
    db.add(template)
    await db.flush()
    return template


async def _recipe(
    db: AsyncSession,
    org: Organization,
    *,
    output_template_id: UUID,
    name: str = 'Test Recipe',
    batch_yield_qty: Decimal = Decimal('1'),
    is_default: bool = True,
    reference_price: Decimal | None = None,
) -> MakerRecipe:
    recipe = MakerRecipe(
        organization_id=org.id,
        output_template_id=output_template_id,
        name=name,
        batch_yield_qty=batch_yield_qty,
        is_default=is_default,
        reference_price=reference_price,
    )
    db.add(recipe)
    await db.flush()
    return recipe


async def _bom_line(
    db: AsyncSession,
    org: Organization,
    recipe: MakerRecipe,
    child_template_id: UUID,
    *,
    qty: Decimal = Decimal('1'),
    unit: str = 'kg',
    yield_loss_pct: Decimal = Decimal('0'),
) -> BoMLine:
    line = BoMLine(
        organization_id=org.id,
        recipe_id=recipe.id,
        parent_template_id=recipe.output_template_id,
        child_template_id=child_template_id,
        qty_per_batch=qty,
        unit=unit,
        yield_loss_pct=yield_loss_pct,
    )
    db.add(line)
    await db.flush()
    return line


async def _cost_line(
    db: AsyncSession,
    org: Organization,
    recipe: MakerRecipe,
    *,
    kind: str = 'LABOR',
    label: str = 'Labor',
    amount: Decimal = Decimal('5.00'),
    sort_order: int = 0,
) -> MakerRecipeCostLine:
    cost_line = MakerRecipeCostLine(
        recipe_id=recipe.id,
        organization_id=org.id,
        kind=kind,
        label=label,
        amount=amount,
        sort_order=sort_order,
    )
    db.add(cost_line)
    await db.flush()
    return cost_line


async def _location(
    db: AsyncSession,
    org: Organization,
    user: User,
    storage_type: StorageType,
    *,
    name: str,
) -> StorageLocation:
    location = StorageLocation(
        organization_id=org.id,
        storage_type_id=storage_type.id,
        created_by=user.id,
        name=name,
    )
    db.add(location)
    await db.flush()
    return location


async def _stock(
    db: AsyncSession,
    keeper: User,
    template: ProductTemplate,
    location: StorageLocation,
    *,
    qty: Decimal = Decimal('100'),
    unit_cost: Decimal | None = None,
) -> Item:
    """Put *qty* of *template* on the shelf as one record, the way an entry does.

    *unit_cost* prices the record, and with it the receipt layer a run
    consumes; without it the receipt is posted unpriced.
    """
    return await put_on_shelf(
        db, keeper, template, location.id, qty, purchase_price=unit_cost
    )


async def _item(
    db: AsyncSession,
    org: Organization,
    template: ProductTemplate,
    location: StorageLocation,
    *,
    name: str,
    quantity: Decimal = Decimal('0'),
    created_at: datetime | None = None,
) -> Item:
    item = Item(
        organization_id=org.id,
        storage_location_id=location.id,
        template_id=template.id,
        name=name,
        quantity=quantity,
        created_at=created_at,
    )
    db.add(item)
    await db.run_sync(anchor_pending_records)
    await db.flush()
    return item


async def _draft_order(
    db: AsyncSession,
    org: Organization,
    ctx: UserContextDTO,
    *,
    output_template: ProductTemplate,
    output_location: StorageLocation,
    recipe_id: UUID | None = None,
    planned_qty: Decimal = Decimal('1'),
    # The strategy default is WARN, which would turn a short run into a
    # 422 before the test reaches what it actually drives; the two
    # strategy tests below turn it off on purpose.
    confirm_shortage: bool = True,
) -> ProductionOrder:
    data = ProductionOrderCreate(
        output_template_id=output_template.id,
        recipe_id=recipe_id,
        planned_qty=planned_qty,
        output_location_id=output_location.id,
        confirm_shortage=confirm_shortage,
    )
    return await production_service.create_order(db, org.id, data, ctx)


async def _insert_order(
    db: AsyncSession,
    org: Organization,
    user: User,
    *,
    output_template: ProductTemplate,
    output_location: StorageLocation,
    recipe_id: UUID | None = None,
    status: str = 'DRAFT',
    planned_qty: Decimal = Decimal('1'),
    actual_qty: Decimal | None = None,
    total_cost: Decimal | None = None,
    result_per_unit: Decimal | None = None,
    notes: str | None = None,
    created_at: datetime | None = None,
    completed_at: datetime | None = None,
) -> ProductionOrder:
    order = ProductionOrder(
        organization_id=org.id,
        output_template_id=output_template.id,
        recipe_id=recipe_id,
        status=status,
        planned_qty=planned_qty,
        actual_qty=actual_qty,
        total_cost=total_cost,
        result_per_unit=result_per_unit,
        notes=notes,
        created_by=user.id,
        created_at=created_at,
        completed_at=completed_at,
        output_storage_location_id=output_location.id,
    )
    db.add(order)
    await db.flush()
    return order


async def _get_shelf(
    db: AsyncSession,
    org: Organization,
    template: ProductTemplate,
    location: StorageLocation,
) -> ShelfRow | None:
    result = await db.execute(
        select(ShelfRow).where(
            ShelfRow.organization_id == org.id,
            ShelfRow.product_template_id == template.id,
            ShelfRow.storage_location_id == location.id,
        )
    )
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# get_order / list_lines / list_orders / monthly_result
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestGetOrder:
    @pytest.mark.asyncio
    async def test_get_order_found(
        self,
        real_async_db_session: AsyncSession,
        prod_org: Organization,
        prod_user: User,
        prod_ctx: UserContextDTO,
        prod_storage_type: StorageType,
    ) -> None:
        output = await _template(real_async_db_session, prod_org, name='GetOrder Out')
        location = await _location(
            real_async_db_session,
            prod_org,
            prod_user,
            prod_storage_type,
            name='GetOrder Loc',
        )
        order = await _insert_order(
            real_async_db_session,
            prod_org,
            prod_user,
            output_template=output,
            output_location=location,
        )

        found = await production_service.get_order(
            real_async_db_session, prod_org.id, order.id
        )

        assert found is not None
        assert found.id == order.id

    @pytest.mark.asyncio
    async def test_get_order_not_found(
        self, real_async_db_session: AsyncSession, prod_org: Organization
    ) -> None:
        assert (
            await production_service.get_order(
                real_async_db_session, prod_org.id, uuid.uuid4()
            )
            is None
        )


@pytest.mark.integration
class TestListLines:
    @pytest.mark.asyncio
    async def test_list_lines_empty(
        self,
        real_async_db_session: AsyncSession,
        prod_org: Organization,
        prod_user: User,
        prod_storage_type: StorageType,
    ) -> None:
        output = await _template(real_async_db_session, prod_org, name='NoLines Out')
        location = await _location(
            real_async_db_session,
            prod_org,
            prod_user,
            prod_storage_type,
            name='NoLines Loc',
        )
        order = await _insert_order(
            real_async_db_session,
            prod_org,
            prod_user,
            output_template=output,
            output_location=location,
        )

        assert (
            await production_service.list_lines(
                real_async_db_session, prod_org.id, order.id
            )
            == []
        )

    @pytest.mark.asyncio
    async def test_list_lines_foreign_org_returns_empty(
        self,
        real_async_db_session: AsyncSession,
        prod_org: Organization,
        prod_user: User,
        prod_storage_type: StorageType,
    ) -> None:
        from app.modules.maker.models import ProductionOrderLine

        db = real_async_db_session
        output = await _template(db, prod_org, name='Foreign Out')
        location = await _location(
            db,
            prod_org,
            prod_user,
            prod_storage_type,
            name='Foreign Loc',
        )
        order = await _insert_order(
            db,
            prod_org,
            prod_user,
            output_template=output,
            output_location=location,
        )
        db.add(
            ProductionOrderLine(
                production_order_id=order.id,
                child_template_id=output.id,
                consumed_qty=Decimal('1'),
                unit='pcs',
            )
        )
        await db.flush()

        other_org = Organization(name=f'Other {uuid.uuid4().hex[:8]}')
        db.add(other_org)
        await db.flush()

        # Sanity: the owner sees the line; a foreign org sees nothing.
        own = await production_service.list_lines(db, prod_org.id, order.id)
        assert len(own) == 1
        foreign = await production_service.list_lines(db, other_org.id, order.id)
        assert foreign == []

    @pytest.mark.asyncio
    async def test_list_lines_returns_snapshot(
        self,
        real_async_db_session: AsyncSession,
        prod_org: Organization,
        prod_user: User,
        prod_ctx: UserContextDTO,
        prod_storage_type: StorageType,
    ) -> None:
        ingredient = await _template(real_async_db_session, prod_org, name='LineIng')
        output = await _template(real_async_db_session, prod_org, name='LineOut')
        input_loc = await _location(
            real_async_db_session,
            prod_org,
            prod_user,
            prod_storage_type,
            name='LineIn Loc',
        )
        output_loc = await _location(
            real_async_db_session,
            prod_org,
            prod_user,
            prod_storage_type,
            name='LineOut Loc',
        )
        recipe = await _recipe(
            real_async_db_session, prod_org, output_template_id=output.id
        )
        await _bom_line(
            real_async_db_session, prod_org, recipe, ingredient.id, qty=Decimal('1')
        )
        await _stock(
            real_async_db_session,
            prod_user,
            ingredient,
            input_loc,
            qty=Decimal('10'),
        )
        order = await _draft_order(
            real_async_db_session,
            prod_org,
            prod_ctx,
            output_template=output,
            output_location=output_loc,
        )
        await production_service.complete_production(
            real_async_db_session, prod_org.id, order.id, prod_ctx
        )

        lines = await production_service.list_lines(
            real_async_db_session, prod_org.id, order.id
        )

        assert len(lines) == 1
        assert lines[0].child_template_id == ingredient.id
        assert lines[0].consumed_qty == Decimal('1')
        assert lines[0].source_storage_location_id == input_loc.id


@pytest.mark.integration
class TestListOrders:
    @pytest.mark.asyncio
    async def test_list_orders_filters_sorts_and_paginates(
        self,
        real_async_db_session: AsyncSession,
        prod_org: Organization,
        prod_user: User,
        prod_storage_type: StorageType,
    ) -> None:
        first_out = await _template(real_async_db_session, prod_org, name='First Out')
        second_out = await _template(real_async_db_session, prod_org, name='Second Out')
        location = await _location(
            real_async_db_session,
            prod_org,
            prod_user,
            prod_storage_type,
            name='List Loc',
        )

        first = await _insert_order(
            real_async_db_session,
            prod_org,
            prod_user,
            output_template=first_out,
            output_location=location,
            status='DRAFT',
            total_cost=Decimal('100.00'),
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        second = await _insert_order(
            real_async_db_session,
            prod_org,
            prod_user,
            output_template=second_out,
            output_location=location,
            status='COMPLETED',
            total_cost=Decimal('200.00'),
            created_at=datetime(2026, 2, 1, tzinfo=UTC),
        )
        third = await _insert_order(
            real_async_db_session,
            prod_org,
            prod_user,
            output_template=first_out,
            output_location=location,
            status='CANCELLED',
            total_cost=None,
            created_at=datetime(2026, 3, 1, tzinfo=UTC),
        )

        newest, newest_total = await production_service.list_orders(
            real_async_db_session, prod_org.id, sort='newest'
        )
        assert [o.id for o in newest] == [third.id, second.id, first.id]
        assert newest_total == 3

        oldest, _ = await production_service.list_orders(
            real_async_db_session, prod_org.id, sort='oldest'
        )
        assert [o.id for o in oldest] == [first.id, second.id, third.id]

        cost_desc, _ = await production_service.list_orders(
            real_async_db_session, prod_org.id, sort='cost_desc'
        )
        assert [o.id for o in cost_desc] == [second.id, first.id, third.id]

        drafts, drafts_total = await production_service.list_orders(
            real_async_db_session, prod_org.id, status='DRAFT'
        )
        assert [o.id for o in drafts] == [first.id]
        assert drafts_total == 1

        by_output, by_output_total = await production_service.list_orders(
            real_async_db_session,
            prod_org.id,
            output_template_id=second_out.id,
        )
        assert [o.id for o in by_output] == [second.id]
        assert by_output_total == 1

        from_feb, from_feb_total = await production_service.list_orders(
            real_async_db_session, prod_org.id, date_from=date(2026, 2, 1)
        )
        assert [o.id for o in from_feb] == [third.id, second.id]
        assert from_feb_total == 2

        to_feb, _ = await production_service.list_orders(
            real_async_db_session, prod_org.id, date_to=date(2026, 2, 1)
        )
        assert [o.id for o in to_feb] == [second.id, first.id]


@pytest.mark.integration
class TestMonthlyResult:
    async def _completed_order(
        self,
        db: AsyncSession,
        org: Organization,
        user: User,
        storage_type: StorageType,
        *,
        result_per_unit: Decimal,
        actual_qty: Decimal | None,
        planned_qty: Decimal,
        completed_at: datetime | None = None,
    ) -> ProductionOrder:
        output = await _template(db, org, name=f'Monthly {uuid.uuid4().hex[:8]}')
        location = await _location(
            db, org, user, storage_type, name=f'Monthly Loc {uuid.uuid4().hex[:8]}'
        )
        return await _insert_order(
            db,
            org,
            user,
            output_template=output,
            output_location=location,
            status='COMPLETED',
            planned_qty=planned_qty,
            actual_qty=actual_qty,
            result_per_unit=result_per_unit,
            completed_at=completed_at or datetime.now(tz=UTC),
        )

    @pytest.mark.asyncio
    async def test_monthly_result_buckets_on_the_organisations_calendar(
        self,
        real_async_db_session: AsyncSession,
        prod_org: Organization,
        prod_user: User,
        prod_storage_type: StorageType,
    ) -> None:
        """A run belongs to the month the organization was in, not the server.

        Kiritimati is UTC+14, so 23:00 on the last day of a UTC month is
        already 13:00 on the first day of the next month there. Bucketed on
        the server's clock the run falls into the month that had ended; on
        the organization's, into the one it is living in. The two keys are
        asserted to differ first, so the test cannot pass by coincidence.
        """
        prod_org.timezone = 'Pacific/Kiritimati'
        await real_async_db_session.flush()
        tz = ZoneInfo('Pacific/Kiritimati')

        now_utc = datetime.now(tz=UTC)
        utc_month_start = datetime(now_utc.year, now_utc.month, 1, tzinfo=UTC)
        completed_at = utc_month_start - timedelta(hours=1)

        server_key = f'{completed_at.year:04d}-{completed_at.month:02d}'
        local = completed_at.astimezone(tz)
        org_key = f'{local.year:04d}-{local.month:02d}'
        assert org_key != server_key

        await self._completed_order(
            real_async_db_session,
            prod_org,
            prod_user,
            prod_storage_type,
            result_per_unit=Decimal('5.00'),
            actual_qty=Decimal('2'),
            planned_qty=Decimal('2'),
            completed_at=completed_at,
        )

        rows = await production_service.monthly_result(
            real_async_db_session, prod_org.id, months=3
        )
        by_month = {row['month']: row for row in rows}

        assert by_month[org_key]['orders'] == 1
        assert by_month[org_key]['result'] == Decimal('10.00')
        assert by_month.get(server_key, {'orders': 0})['orders'] == 0

    @pytest.mark.asyncio
    async def test_monthly_result_empty_window_returns_zero_months(
        self, real_async_db_session: AsyncSession, prod_org: Organization
    ) -> None:
        rows = await production_service.monthly_result(
            real_async_db_session, prod_org.id, months=2
        )

        assert len(rows) == 2
        assert all(row['result'] == Decimal('0.00') for row in rows)
        assert all(row['orders'] == 0 for row in rows)

    @pytest.mark.asyncio
    async def test_monthly_result_aggregates_completed_order(
        self,
        real_async_db_session: AsyncSession,
        prod_org: Organization,
        prod_user: User,
        prod_storage_type: StorageType,
    ) -> None:
        await self._completed_order(
            real_async_db_session,
            prod_org,
            prod_user,
            prod_storage_type,
            result_per_unit=Decimal('5.00'),
            actual_qty=Decimal('2'),
            planned_qty=Decimal('2'),
        )

        rows = await production_service.monthly_result(
            real_async_db_session, prod_org.id, months=2
        )

        current_key = f'{date.today().year:04d}-{date.today().month:02d}'
        current = next(row for row in rows if row['month'] == current_key)
        assert current['result'] == Decimal('10.00')
        assert current['orders'] == 1

    @pytest.mark.asyncio
    async def test_monthly_result_falls_back_to_planned_qty(
        self,
        real_async_db_session: AsyncSession,
        prod_org: Organization,
        prod_user: User,
        prod_storage_type: StorageType,
    ) -> None:
        await self._completed_order(
            real_async_db_session,
            prod_org,
            prod_user,
            prod_storage_type,
            result_per_unit=Decimal('2.00'),
            actual_qty=None,
            planned_qty=Decimal('3'),
        )

        rows = await production_service.monthly_result(
            real_async_db_session, prod_org.id, months=1
        )
        assert rows[0]['result'] == Decimal('6.00')
        assert rows[0]['orders'] == 1

    @pytest.mark.asyncio
    async def test_monthly_result_ignores_zero_effective_quantity(
        self,
        real_async_db_session: AsyncSession,
        prod_org: Organization,
        prod_user: User,
        prod_storage_type: StorageType,
    ) -> None:
        await self._completed_order(
            real_async_db_session,
            prod_org,
            prod_user,
            prod_storage_type,
            result_per_unit=Decimal('5.00'),
            actual_qty=Decimal('0'),
            planned_qty=Decimal('0'),
        )

        rows = await production_service.monthly_result(
            real_async_db_session, prod_org.id, months=1
        )
        assert rows[0]['result'] == Decimal('0.00')
        assert rows[0]['orders'] == 1

    @pytest.mark.asyncio
    async def test_monthly_result_crosses_year_boundary(
        self,
        real_async_db_session: AsyncSession,
        prod_org: Organization,
        prod_user: User,
        prod_storage_type: StorageType,
    ) -> None:
        await self._completed_order(
            real_async_db_session,
            prod_org,
            prod_user,
            prod_storage_type,
            result_per_unit=Decimal('1.00'),
            actual_qty=Decimal('1'),
            planned_qty=Decimal('1'),
        )

        rows = await production_service.monthly_result(
            real_async_db_session, prod_org.id, months=12
        )

        assert len(rows) == 12
        assert sum(cast(int, row['orders']) for row in rows) == 1
        assert sum(cast(Decimal, row['result']) for row in rows) == Decimal('1.00')


# ---------------------------------------------------------------------------
# create_order
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestCreateOrder:
    @pytest.mark.asyncio
    async def test_create_order_with_default_recipe(
        self,
        real_async_db_session: AsyncSession,
        prod_org: Organization,
        prod_user: User,
        prod_ctx: UserContextDTO,
        prod_storage_type: StorageType,
    ) -> None:
        output = await _template(real_async_db_session, prod_org, name='Default Out')
        location = await _location(
            real_async_db_session,
            prod_org,
            prod_user,
            prod_storage_type,
            name='Default Loc',
        )
        recipe = await _recipe(
            real_async_db_session, prod_org, output_template_id=output.id
        )

        order = await _draft_order(
            real_async_db_session,
            prod_org,
            prod_ctx,
            output_template=output,
            output_location=location,
            planned_qty=Decimal('2'),
        )

        assert order.status == 'DRAFT'
        assert order.recipe_id == recipe.id
        assert order.planned_qty == Decimal('2')

    @pytest.mark.asyncio
    async def test_create_order_with_explicit_recipe(
        self,
        real_async_db_session: AsyncSession,
        prod_org: Organization,
        prod_user: User,
        prod_ctx: UserContextDTO,
        prod_storage_type: StorageType,
    ) -> None:
        output = await _template(real_async_db_session, prod_org, name='Explicit Out')
        location = await _location(
            real_async_db_session,
            prod_org,
            prod_user,
            prod_storage_type,
            name='Explicit Loc',
        )
        recipe = await _recipe(
            real_async_db_session,
            prod_org,
            output_template_id=output.id,
            is_default=False,
        )

        order = await _draft_order(
            real_async_db_session,
            prod_org,
            prod_ctx,
            output_template=output,
            output_location=location,
            recipe_id=recipe.id,
        )

        assert order.recipe_id == recipe.id

    @pytest.mark.asyncio
    async def test_create_order_recipe_not_found(
        self,
        real_async_db_session: AsyncSession,
        prod_org: Organization,
        prod_user: User,
        prod_ctx: UserContextDTO,
        prod_storage_type: StorageType,
    ) -> None:
        output = await _template(real_async_db_session, prod_org, name='MissingRec Out')
        location = await _location(
            real_async_db_session,
            prod_org,
            prod_user,
            prod_storage_type,
            name='MissingRec Loc',
        )

        with pytest.raises(ValueError, match='not found in this organization'):
            await _draft_order(
                real_async_db_session,
                prod_org,
                prod_ctx,
                output_template=output,
                output_location=location,
                recipe_id=uuid.uuid4(),
            )

    @pytest.mark.asyncio
    async def test_create_order_recipe_mismatch(
        self,
        real_async_db_session: AsyncSession,
        prod_org: Organization,
        prod_user: User,
        prod_ctx: UserContextDTO,
        prod_storage_type: StorageType,
    ) -> None:
        output = await _template(real_async_db_session, prod_org, name='Mismatch Out')
        other_output = await _template(
            real_async_db_session, prod_org, name='Mismatch Other'
        )
        location = await _location(
            real_async_db_session,
            prod_org,
            prod_user,
            prod_storage_type,
            name='Mismatch Loc',
        )
        recipe = await _recipe(
            real_async_db_session, prod_org, output_template_id=other_output.id
        )

        with pytest.raises(ValueError, match='does not belong to this product'):
            await _draft_order(
                real_async_db_session,
                prod_org,
                prod_ctx,
                output_template=output,
                output_location=location,
                recipe_id=recipe.id,
            )

    @pytest.mark.asyncio
    async def test_create_order_no_recipe(
        self,
        real_async_db_session: AsyncSession,
        prod_org: Organization,
        prod_user: User,
        prod_ctx: UserContextDTO,
        prod_storage_type: StorageType,
    ) -> None:
        output = await _template(real_async_db_session, prod_org, name='NoRecipe Out')
        location = await _location(
            real_async_db_session,
            prod_org,
            prod_user,
            prod_storage_type,
            name='NoRecipe Loc',
        )

        with pytest.raises(ValueError, match='create a BOM first'):
            await _draft_order(
                real_async_db_session,
                prod_org,
                prod_ctx,
                output_template=output,
                output_location=location,
            )

    @pytest.mark.asyncio
    async def test_create_order_block_strategy_rejects_on_shortage(
        self,
        real_async_db_session: AsyncSession,
        prod_org: Organization,
        prod_user: User,
        prod_ctx: UserContextDTO,
        prod_storage_type: StorageType,
    ) -> None:
        output = await _template(real_async_db_session, prod_org, name='Block Out')
        ingredient = await _template(real_async_db_session, prod_org, name='Block Ing')
        location = await _location(
            real_async_db_session,
            prod_org,
            prod_user,
            prod_storage_type,
            name='Block Loc',
        )
        recipe = await _recipe(
            real_async_db_session, prod_org, output_template_id=output.id
        )
        await _bom_line(
            real_async_db_session,
            prod_org,
            recipe,
            ingredient.id,
            qty=Decimal('100'),
        )
        real_async_db_session.add(
            MakerModuleSettings(
                organization_id=prod_org.id, create_on_shortage_strategy='BLOCK'
            )
        )
        await real_async_db_session.flush()

        with pytest.raises(ShortageBlockedError):
            await _draft_order(
                real_async_db_session,
                prod_org,
                prod_ctx,
                output_template=output,
                output_location=location,
                confirm_shortage=False,
            )

    @pytest.mark.asyncio
    async def test_create_order_warn_strategy_raises_without_confirm(
        self,
        real_async_db_session: AsyncSession,
        prod_org: Organization,
        prod_user: User,
        prod_ctx: UserContextDTO,
        prod_storage_type: StorageType,
    ) -> None:
        output = await _template(real_async_db_session, prod_org, name='Warn Out')
        ingredient = await _template(real_async_db_session, prod_org, name='Warn Ing')
        location = await _location(
            real_async_db_session,
            prod_org,
            prod_user,
            prod_storage_type,
            name='Warn Loc',
        )
        recipe = await _recipe(
            real_async_db_session, prod_org, output_template_id=output.id
        )
        await _bom_line(
            real_async_db_session,
            prod_org,
            recipe,
            ingredient.id,
            qty=Decimal('100'),
        )
        real_async_db_session.add(
            MakerModuleSettings(
                organization_id=prod_org.id, create_on_shortage_strategy='WARN'
            )
        )
        await real_async_db_session.flush()

        with pytest.raises(ShortageWarningError):
            await _draft_order(
                real_async_db_session,
                prod_org,
                prod_ctx,
                output_template=output,
                output_location=location,
                confirm_shortage=False,
            )

    @pytest.mark.asyncio
    async def test_create_order_warn_strategy_creates_with_confirm(
        self,
        real_async_db_session: AsyncSession,
        prod_org: Organization,
        prod_user: User,
        prod_ctx: UserContextDTO,
        prod_storage_type: StorageType,
    ) -> None:
        output = await _template(real_async_db_session, prod_org, name='Confirm Out')
        ingredient = await _template(
            real_async_db_session, prod_org, name='Confirm Ing'
        )
        location = await _location(
            real_async_db_session,
            prod_org,
            prod_user,
            prod_storage_type,
            name='Confirm Loc',
        )
        recipe = await _recipe(
            real_async_db_session, prod_org, output_template_id=output.id
        )
        await _bom_line(
            real_async_db_session,
            prod_org,
            recipe,
            ingredient.id,
            qty=Decimal('100'),
        )
        real_async_db_session.add(
            MakerModuleSettings(
                organization_id=prod_org.id, create_on_shortage_strategy='WARN'
            )
        )
        await real_async_db_session.flush()

        data = ProductionOrderCreate(
            output_template_id=output.id,
            planned_qty=Decimal('1'),
            output_location_id=location.id,
            confirm_shortage=True,
        )
        order = await production_service.create_order(
            real_async_db_session, prod_org.id, data, prod_ctx
        )

        assert order.status == 'DRAFT'


# ---------------------------------------------------------------------------
# complete_production
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestCompleteProduction:
    @pytest.mark.asyncio
    async def test_complete_success_with_explicit_recipe_and_fixed_costs(
        self,
        real_async_db_session: AsyncSession,
        prod_org: Organization,
        prod_user: User,
        prod_ctx: UserContextDTO,
        prod_storage_type: StorageType,
    ) -> None:
        ingredient = await _template(real_async_db_session, prod_org, name='Sugar')
        output = await _template(real_async_db_session, prod_org, name='Jam')
        input_loc = await _location(
            real_async_db_session,
            prod_org,
            prod_user,
            prod_storage_type,
            name='Jam Ing Loc',
        )
        output_loc = await _location(
            real_async_db_session,
            prod_org,
            prod_user,
            prod_storage_type,
            name='Jam Out Loc',
        )
        recipe = await _recipe(
            real_async_db_session,
            prod_org,
            output_template_id=output.id,
            batch_yield_qty=Decimal('2'),
            reference_price=Decimal('10.00'),
        )
        await _bom_line(
            real_async_db_session,
            prod_org,
            recipe,
            ingredient.id,
            qty=Decimal('1.5'),
        )
        await _cost_line(
            real_async_db_session,
            prod_org,
            recipe,
            kind='LABOR',
            label='Labor',
            amount=Decimal('5.00'),
        )
        await _cost_line(
            real_async_db_session,
            prod_org,
            recipe,
            kind='PACKAGING',
            label='Jars',
            amount=Decimal('2.00'),
            sort_order=1,
        )
        await _stock(
            real_async_db_session,
            prod_user,
            ingredient,
            input_loc,
            qty=Decimal('100'),
            unit_cost=Decimal('2.00'),
        )
        order = await _draft_order(
            real_async_db_session,
            prod_org,
            prod_ctx,
            output_template=output,
            output_location=output_loc,
            recipe_id=recipe.id,
            planned_qty=Decimal('4'),
        )

        completed = await production_service.complete_production(
            real_async_db_session,
            prod_org.id,
            order.id,
            prod_ctx,
            actual_qty=Decimal('3'),
        )

        # Material: batches = 4 / 2 = 2; child qty = 2 * 1.5 = 3.0.
        # Material cost = 3.0 * 2.00 = 6.00.
        # Fixed = 2 batches * (5.00 + 2.00) = 14.00; total = 20.00.
        assert completed.status == 'COMPLETED'
        assert completed.total_cost == Decimal('20.00')
        assert completed.actual_qty == Decimal('3')
        assert completed.overproduced is False
        assert completed.scrap_qty == Decimal('1')
        assert completed.unit_cost_snapshot == Decimal('6.6667')
        assert completed.reference_price_snapshot == Decimal('10.00')
        assert completed.result_per_unit == Decimal('3.33')
        assert completed.result_per_batch == Decimal('6.66')
        assert completed.produced_item_id is not None

        ingredient_shelf = await _get_shelf(
            real_async_db_session, prod_org, ingredient, input_loc
        )
        assert ingredient_shelf is not None
        assert ingredient_shelf.quantity == Decimal('97')
        output_shelf = await _get_shelf(
            real_async_db_session, prod_org, output, output_loc
        )
        assert output_shelf is not None
        assert output_shelf.quantity == Decimal('3')

        lines = await production_service.list_lines(
            real_async_db_session, prod_org.id, order.id
        )
        assert len(lines) == 1
        assert lines[0].consumed_qty == Decimal('3.0')
        assert lines[0].unit_cost_snapshot == Decimal('2.00')
        # What the layers actually gave up, not the average they averaged to.
        assert lines[0].cost_source == 'fifo'
        assert lines[0].source_storage_location_id == input_loc.id

        last = await recipe_service.get_last_unit_costs(
            real_async_db_session, prod_org.id, [recipe.id]
        )
        assert last[recipe.id].uncosted_ingredients == 0

    @pytest.mark.asyncio
    async def test_complete_legacy_order_without_recipe(
        self,
        real_async_db_session: AsyncSession,
        prod_org: Organization,
        prod_user: User,
        prod_ctx: UserContextDTO,
        prod_storage_type: StorageType,
    ) -> None:
        ingredient = await _template(real_async_db_session, prod_org, name='Legacy Ing')
        output = await _template(real_async_db_session, prod_org, name='Legacy Out')
        input_loc = await _location(
            real_async_db_session,
            prod_org,
            prod_user,
            prod_storage_type,
            name='Legacy In Loc',
        )
        output_loc = await _location(
            real_async_db_session,
            prod_org,
            prod_user,
            prod_storage_type,
            name='Legacy Out Loc',
        )
        recipe = await _recipe(
            real_async_db_session, prod_org, output_template_id=output.id
        )
        await _bom_line(
            real_async_db_session, prod_org, recipe, ingredient.id, qty=Decimal('1')
        )
        await _stock(
            real_async_db_session,
            prod_user,
            ingredient,
            input_loc,
            qty=Decimal('100'),
            unit_cost=Decimal('2.00'),
        )
        order = await _insert_order(
            real_async_db_session,
            prod_org,
            prod_user,
            output_template=output,
            output_location=output_loc,
            recipe_id=None,
            planned_qty=Decimal('5'),
        )

        completed = await production_service.complete_production(
            real_async_db_session, prod_org.id, order.id, prod_ctx
        )

        assert completed.status == 'COMPLETED'
        assert completed.total_cost == Decimal('10.00')
        assert completed.actual_qty == Decimal('5')
        assert completed.scrap_qty == Decimal('0')
        assert completed.unit_cost_snapshot is None
        assert completed.reference_price_snapshot is None
        assert completed.result_per_unit is None
        assert completed.result_per_batch is None

        ingredient_shelf = await _get_shelf(
            real_async_db_session, prod_org, ingredient, input_loc
        )
        assert ingredient_shelf is not None
        assert ingredient_shelf.quantity == Decimal('95')

        lines = await production_service.list_lines(
            real_async_db_session, prod_org.id, order.id
        )
        # What the layers actually gave up, not the average they averaged to.
        assert lines[0].cost_source == 'fifo'
        assert lines[0].unit_cost_snapshot == Decimal('2.00')

    @pytest.mark.asyncio
    async def test_complete_with_zero_rate_records_none_cost(
        self,
        real_async_db_session: AsyncSession,
        prod_org: Organization,
        prod_user: User,
        prod_ctx: UserContextDTO,
        prod_storage_type: StorageType,
    ) -> None:
        ingredient = await _template(
            real_async_db_session, prod_org, name='ZeroRate Ing'
        )
        output = await _template(real_async_db_session, prod_org, name='ZeroRate Out')
        input_loc = await _location(
            real_async_db_session,
            prod_org,
            prod_user,
            prod_storage_type,
            name='ZeroRate In',
        )
        output_loc = await _location(
            real_async_db_session,
            prod_org,
            prod_user,
            prod_storage_type,
            name='ZeroRate Out',
        )
        recipe = await _recipe(
            real_async_db_session, prod_org, output_template_id=output.id
        )
        await _bom_line(
            real_async_db_session, prod_org, recipe, ingredient.id, qty=Decimal('1')
        )
        await _stock(
            real_async_db_session,
            prod_user,
            ingredient,
            input_loc,
            qty=Decimal('10'),
        )
        order = await _draft_order(
            real_async_db_session,
            prod_org,
            prod_ctx,
            output_template=output,
            output_location=output_loc,
        )

        completed = await production_service.complete_production(
            real_async_db_session, prod_org.id, order.id, prod_ctx
        )

        assert completed.status == 'COMPLETED'
        assert completed.total_cost == Decimal('0')
        assert completed.unit_cost_snapshot == Decimal('0.0000')
        assert completed.reference_price_snapshot is None
        assert completed.result_per_unit is None
        assert completed.result_per_batch is None

        lines = await production_service.list_lines(
            real_async_db_session, prod_org.id, order.id
        )
        assert lines[0].cost_source == 'none'
        assert lines[0].unit_cost_snapshot is None

        # What the catalog reads. A total of zero assembled from an
        # ingredient nobody priced reached the card as "Unit cost $0.00" —
        # the same sentence a product that is genuinely free to make would
        # get, and the one somebody sets a margin against.
        last = await recipe_service.get_last_unit_costs(
            real_async_db_session, prod_org.id, [recipe.id]
        )
        assert last[recipe.id].unit_cost == Decimal('0.0000')
        assert last[recipe.id].uncosted_ingredients == 1

    @pytest.mark.asyncio
    async def test_complete_zero_actual_qty_raises(
        self,
        real_async_db_session: AsyncSession,
        prod_org: Organization,
        prod_user: User,
        prod_ctx: UserContextDTO,
        prod_storage_type: StorageType,
    ) -> None:
        output = await _template(real_async_db_session, prod_org, name='ZeroQty Out')
        location = await _location(
            real_async_db_session,
            prod_org,
            prod_user,
            prod_storage_type,
            name='ZeroQty Loc',
        )
        await _recipe(real_async_db_session, prod_org, output_template_id=output.id)
        order = await _draft_order(
            real_async_db_session,
            prod_org,
            prod_ctx,
            output_template=output,
            output_location=location,
        )

        with pytest.raises(ValueError, match='greater than zero'):
            await production_service.complete_production(
                real_async_db_session,
                prod_org.id,
                order.id,
                prod_ctx,
                actual_qty=Decimal('0'),
            )

    @pytest.mark.asyncio
    async def test_complete_overproduction_blocked(
        self,
        real_async_db_session: AsyncSession,
        prod_org: Organization,
        prod_user: User,
        prod_ctx: UserContextDTO,
        prod_storage_type: StorageType,
    ) -> None:
        ingredient = await _template(real_async_db_session, prod_org, name='Block Ing')
        output = await _template(real_async_db_session, prod_org, name='Block Out')
        input_loc = await _location(
            real_async_db_session,
            prod_org,
            prod_user,
            prod_storage_type,
            name='Block In',
        )
        output_loc = await _location(
            real_async_db_session,
            prod_org,
            prod_user,
            prod_storage_type,
            name='Block Out',
        )
        recipe = await _recipe(
            real_async_db_session, prod_org, output_template_id=output.id
        )
        await _bom_line(
            real_async_db_session, prod_org, recipe, ingredient.id, qty=Decimal('1')
        )
        await _stock(
            real_async_db_session,
            prod_user,
            ingredient,
            input_loc,
            qty=Decimal('100'),
        )
        real_async_db_session.add(
            MakerModuleSettings(organization_id=prod_org.id, allow_overproduction=False)
        )
        await real_async_db_session.flush()
        order = await _draft_order(
            real_async_db_session,
            prod_org,
            prod_ctx,
            output_template=output,
            output_location=output_loc,
            planned_qty=Decimal('10'),
        )

        with pytest.raises(ValueError, match='Overproduction is disabled'):
            await production_service.complete_production(
                real_async_db_session,
                prod_org.id,
                order.id,
                prod_ctx,
                actual_qty=Decimal('12'),
            )

    @pytest.mark.asyncio
    async def test_complete_overproduction_allowed(
        self,
        real_async_db_session: AsyncSession,
        prod_org: Organization,
        prod_user: User,
        prod_ctx: UserContextDTO,
        prod_storage_type: StorageType,
    ) -> None:
        ingredient = await _template(real_async_db_session, prod_org, name='Over Ing')
        output = await _template(real_async_db_session, prod_org, name='Over Out')
        input_loc = await _location(
            real_async_db_session,
            prod_org,
            prod_user,
            prod_storage_type,
            name='Over In',
        )
        output_loc = await _location(
            real_async_db_session,
            prod_org,
            prod_user,
            prod_storage_type,
            name='Over Out',
        )
        recipe = await _recipe(
            real_async_db_session, prod_org, output_template_id=output.id
        )
        await _bom_line(
            real_async_db_session, prod_org, recipe, ingredient.id, qty=Decimal('1')
        )
        await _stock(
            real_async_db_session,
            prod_user,
            ingredient,
            input_loc,
            qty=Decimal('100'),
            unit_cost=Decimal('1.00'),
        )
        order = await _draft_order(
            real_async_db_session,
            prod_org,
            prod_ctx,
            output_template=output,
            output_location=output_loc,
            planned_qty=Decimal('10'),
        )

        completed = await production_service.complete_production(
            real_async_db_session,
            prod_org.id,
            order.id,
            prod_ctx,
            actual_qty=Decimal('12'),
        )

        assert completed.overproduced is True
        assert completed.scrap_qty == Decimal('-2')
        output_shelf = await _get_shelf(
            real_async_db_session, prod_org, output, output_loc
        )
        assert output_shelf is not None
        assert output_shelf.quantity == Decimal('12')

    @pytest.mark.asyncio
    async def test_complete_order_not_found(
        self,
        real_async_db_session: AsyncSession,
        prod_org: Organization,
        prod_ctx: UserContextDTO,
    ) -> None:
        with pytest.raises(EntityNotFoundError):
            await production_service.complete_production(
                real_async_db_session, prod_org.id, uuid.uuid4(), prod_ctx
            )

    @pytest.mark.asyncio
    async def test_complete_wrong_status_raises(
        self,
        real_async_db_session: AsyncSession,
        prod_org: Organization,
        prod_user: User,
        prod_ctx: UserContextDTO,
        prod_storage_type: StorageType,
    ) -> None:
        output = await _template(real_async_db_session, prod_org, name='Status Out')
        location = await _location(
            real_async_db_session,
            prod_org,
            prod_user,
            prod_storage_type,
            name='Status Loc',
        )
        await _recipe(real_async_db_session, prod_org, output_template_id=output.id)
        order = await _insert_order(
            real_async_db_session,
            prod_org,
            prod_user,
            output_template=output,
            output_location=location,
            status='CANCELLED',
        )

        with pytest.raises(ValueError, match='only a draft can be completed'):
            await production_service.complete_production(
                real_async_db_session, prod_org.id, order.id, prod_ctx
            )

    @pytest.mark.asyncio
    async def test_complete_empty_bom_with_recipe(
        self,
        real_async_db_session: AsyncSession,
        prod_org: Organization,
        prod_user: User,
        prod_ctx: UserContextDTO,
        prod_storage_type: StorageType,
    ) -> None:
        output = await _template(real_async_db_session, prod_org, name='EmptyBom Out')
        location = await _location(
            real_async_db_session,
            prod_org,
            prod_user,
            prod_storage_type,
            name='EmptyBom Loc',
        )
        recipe = await _recipe(
            real_async_db_session, prod_org, output_template_id=output.id
        )
        order = await _draft_order(
            real_async_db_session,
            prod_org,
            prod_ctx,
            output_template=output,
            output_location=location,
            recipe_id=recipe.id,
        )

        with pytest.raises(EmptyBillOfMaterialsError):
            await production_service.complete_production(
                real_async_db_session, prod_org.id, order.id, prod_ctx
            )

    @pytest.mark.asyncio
    async def test_complete_empty_bom_legacy_order(
        self,
        real_async_db_session: AsyncSession,
        prod_org: Organization,
        prod_user: User,
        prod_ctx: UserContextDTO,
        prod_storage_type: StorageType,
    ) -> None:
        output = await _template(real_async_db_session, prod_org, name='LegacyBom Out')
        location = await _location(
            real_async_db_session,
            prod_org,
            prod_user,
            prod_storage_type,
            name='LegacyBom Loc',
        )
        order = await _insert_order(
            real_async_db_session,
            prod_org,
            prod_user,
            output_template=output,
            output_location=location,
            recipe_id=None,
            planned_qty=Decimal('3'),
        )

        with pytest.raises(EmptyBillOfMaterialsError):
            await production_service.complete_production(
                real_async_db_session, prod_org.id, order.id, prod_ctx
            )

    @pytest.mark.asyncio
    async def test_complete_insufficient_stock_precheck(
        self,
        real_async_db_session: AsyncSession,
        prod_org: Organization,
        prod_user: User,
        prod_ctx: UserContextDTO,
        prod_storage_type: StorageType,
    ) -> None:
        ingredient = await _template(real_async_db_session, prod_org, name='Short Ing')
        output = await _template(real_async_db_session, prod_org, name='Short Out')
        input_loc = await _location(
            real_async_db_session,
            prod_org,
            prod_user,
            prod_storage_type,
            name='Short In',
        )
        output_loc = await _location(
            real_async_db_session,
            prod_org,
            prod_user,
            prod_storage_type,
            name='Short Out',
        )
        recipe = await _recipe(
            real_async_db_session, prod_org, output_template_id=output.id
        )
        await _bom_line(
            real_async_db_session,
            prod_org,
            recipe,
            ingredient.id,
            qty=Decimal('5'),
        )
        await _stock(
            real_async_db_session,
            prod_user,
            ingredient,
            input_loc,
            qty=Decimal('3'),
        )
        order = await _draft_order(
            real_async_db_session,
            prod_org,
            prod_ctx,
            output_template=output,
            output_location=output_loc,
        )

        with pytest.raises(InsufficientStockError):
            await production_service.complete_production(
                real_async_db_session, prod_org.id, order.id, prod_ctx
            )

        refreshed = await production_service.get_order(
            real_async_db_session, prod_org.id, order.id
        )
        assert refreshed is not None
        assert refreshed.status == 'DRAFT'

    @pytest.mark.asyncio
    async def test_complete_legacy_insufficient_stock_raises_value_error(
        self,
        real_async_db_session: AsyncSession,
        prod_org: Organization,
        prod_user: User,
        prod_ctx: UserContextDTO,
        prod_storage_type: StorageType,
    ) -> None:
        ingredient = await _template(
            real_async_db_session, prod_org, name='LegacyShort Ing'
        )
        output = await _template(
            real_async_db_session, prod_org, name='LegacyShort Out'
        )
        input_loc = await _location(
            real_async_db_session,
            prod_org,
            prod_user,
            prod_storage_type,
            name='LegacyShort In',
        )
        output_loc = await _location(
            real_async_db_session,
            prod_org,
            prod_user,
            prod_storage_type,
            name='LegacyShort Out',
        )
        recipe = await _recipe(
            real_async_db_session, prod_org, output_template_id=output.id
        )
        await _bom_line(
            real_async_db_session,
            prod_org,
            recipe,
            ingredient.id,
            qty=Decimal('5'),
        )
        await _stock(
            real_async_db_session,
            prod_user,
            ingredient,
            input_loc,
            qty=Decimal('3'),
        )
        order = await _insert_order(
            real_async_db_session,
            prod_org,
            prod_user,
            output_template=output,
            output_location=output_loc,
            recipe_id=None,
            planned_qty=Decimal('1'),
        )

        with pytest.raises(ValueError, match='Insufficient stock for template'):
            await production_service.complete_production(
                real_async_db_session, prod_org.id, order.id, prod_ctx
            )


# ---------------------------------------------------------------------------
# cancel_order
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestCancelOrder:
    @pytest.mark.asyncio
    async def test_cancel_success_with_reason(
        self,
        real_async_db_session: AsyncSession,
        prod_org: Organization,
        prod_user: User,
        prod_ctx: UserContextDTO,
        prod_storage_type: StorageType,
    ) -> None:
        output = await _template(real_async_db_session, prod_org, name='Cancel Out')
        location = await _location(
            real_async_db_session,
            prod_org,
            prod_user,
            prod_storage_type,
            name='Cancel Loc',
        )
        await _recipe(real_async_db_session, prod_org, output_template_id=output.id)
        order = await _draft_order(
            real_async_db_session,
            prod_org,
            prod_ctx,
            output_template=output,
            output_location=location,
        )

        cancelled = await production_service.cancel_order(
            real_async_db_session,
            prod_org.id,
            order.id,
            prod_ctx,
            reason='Customer pulled the order',
        )

        assert cancelled.status == 'CANCELLED'
        assert cancelled.completed_at is not None
        assert cancelled.completed_by == prod_user.id
        assert cancelled.cancel_reason == 'Customer pulled the order'

        audit = (
            await real_async_db_session.scalars(
                select(AuditLog).where(
                    AuditLog.organization_id == prod_org.id,
                    AuditLog.target_type == 'maker_production_order',
                    AuditLog.target_id == order.id,
                )
            )
        ).all()
        # The order now also leaves a CREATE entry; the cancel is the entry
        # whose snapshot says DRAFT -> CANCELLED.
        cancels = [
            e for e in audit if (e.snapshot or {}).get('new_status') == 'CANCELLED'
        ]
        assert len(cancels) == 1
        assert cancels[0].reason == 'Customer pulled the order'
        assert cancels[0].snapshot == {
            'old_status': 'DRAFT',
            'new_status': 'CANCELLED',
        }

    @pytest.mark.asyncio
    async def test_cancel_success_without_reason(
        self,
        real_async_db_session: AsyncSession,
        prod_org: Organization,
        prod_user: User,
        prod_ctx: UserContextDTO,
        prod_storage_type: StorageType,
    ) -> None:
        output = await _template(real_async_db_session, prod_org, name='NoReason Out')
        location = await _location(
            real_async_db_session,
            prod_org,
            prod_user,
            prod_storage_type,
            name='NoReason Loc',
        )
        await _recipe(real_async_db_session, prod_org, output_template_id=output.id)
        order = await _draft_order(
            real_async_db_session,
            prod_org,
            prod_ctx,
            output_template=output,
            output_location=location,
        )

        cancelled = await production_service.cancel_order(
            real_async_db_session, prod_org.id, order.id, prod_ctx
        )

        assert cancelled.status == 'CANCELLED'
        assert cancelled.cancel_reason is None

    @pytest.mark.asyncio
    async def test_cancel_not_found(
        self,
        real_async_db_session: AsyncSession,
        prod_org: Organization,
        prod_ctx: UserContextDTO,
    ) -> None:
        with pytest.raises(EntityNotFoundError):
            await production_service.cancel_order(
                real_async_db_session, prod_org.id, uuid.uuid4(), prod_ctx
            )

    @pytest.mark.asyncio
    async def test_cancel_non_draft_rejected(
        self,
        real_async_db_session: AsyncSession,
        prod_org: Organization,
        prod_user: User,
        prod_ctx: UserContextDTO,
        prod_storage_type: StorageType,
    ) -> None:
        output = await _template(real_async_db_session, prod_org, name='Done Out')
        location = await _location(
            real_async_db_session,
            prod_org,
            prod_user,
            prod_storage_type,
            name='Done Loc',
        )
        await _recipe(real_async_db_session, prod_org, output_template_id=output.id)
        order = await _draft_order(
            real_async_db_session,
            prod_org,
            prod_ctx,
            output_template=output,
            output_location=location,
        )
        await production_service.cancel_order(
            real_async_db_session, prod_org.id, order.id, prod_ctx
        )

        with pytest.raises(ValueError, match='only a draft can be cancelled'):
            await production_service.cancel_order(
                real_async_db_session, prod_org.id, order.id, prod_ctx
            )


# ---------------------------------------------------------------------------
# update_order
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestUpdateOrder:
    @pytest.mark.asyncio
    async def test_update_success_sets_fields(
        self,
        real_async_db_session: AsyncSession,
        prod_org: Organization,
        prod_user: User,
        prod_ctx: UserContextDTO,
        prod_storage_type: StorageType,
    ) -> None:
        output = await _template(real_async_db_session, prod_org, name='Update Out')
        location = await _location(
            real_async_db_session,
            prod_org,
            prod_user,
            prod_storage_type,
            name='Update Loc',
        )
        await _recipe(real_async_db_session, prod_org, output_template_id=output.id)
        order = await _draft_order(
            real_async_db_session,
            prod_org,
            prod_ctx,
            output_template=output,
            output_location=location,
        )

        updated = await production_service.update_order(
            real_async_db_session,
            prod_org.id,
            order.id,
            ProductionOrderUpdate(
                planned_qty=Decimal('7'),
                production_date=date(2026, 8, 1),
                notes='updated',
            ),
            prod_ctx,
        )

        assert updated.planned_qty == Decimal('7')
        assert updated.production_date == date(2026, 8, 1)
        assert updated.notes == 'updated'

    @pytest.mark.asyncio
    async def test_update_with_all_none_keeps_fields(
        self,
        real_async_db_session: AsyncSession,
        prod_org: Organization,
        prod_user: User,
        prod_ctx: UserContextDTO,
        prod_storage_type: StorageType,
    ) -> None:
        output = await _template(real_async_db_session, prod_org, name='Keep Out')
        location = await _location(
            real_async_db_session,
            prod_org,
            prod_user,
            prod_storage_type,
            name='Keep Loc',
        )
        await _recipe(real_async_db_session, prod_org, output_template_id=output.id)
        order = await _draft_order(
            real_async_db_session,
            prod_org,
            prod_ctx,
            output_template=output,
            output_location=location,
            planned_qty=Decimal('4'),
        )

        updated = await production_service.update_order(
            real_async_db_session,
            prod_org.id,
            order.id,
            ProductionOrderUpdate(),
            prod_ctx,
        )

        assert updated.planned_qty == Decimal('4')
        assert updated.notes is None

    @pytest.mark.asyncio
    async def test_update_not_found(
        self,
        real_async_db_session: AsyncSession,
        prod_org: Organization,
        prod_ctx: UserContextDTO,
    ) -> None:
        with pytest.raises(EntityNotFoundError):
            await production_service.update_order(
                real_async_db_session,
                prod_org.id,
                uuid.uuid4(),
                ProductionOrderUpdate(planned_qty=Decimal('1')),
                prod_ctx,
            )

    @pytest.mark.asyncio
    async def test_update_non_draft_rejected(
        self,
        real_async_db_session: AsyncSession,
        prod_org: Organization,
        prod_user: User,
        prod_ctx: UserContextDTO,
        prod_storage_type: StorageType,
    ) -> None:
        output = await _template(real_async_db_session, prod_org, name='Frozen Out')
        location = await _location(
            real_async_db_session,
            prod_org,
            prod_user,
            prod_storage_type,
            name='Frozen Loc',
        )
        await _recipe(real_async_db_session, prod_org, output_template_id=output.id)
        order = await _draft_order(
            real_async_db_session,
            prod_org,
            prod_ctx,
            output_template=output,
            output_location=location,
        )
        await production_service.cancel_order(
            real_async_db_session, prod_org.id, order.id, prod_ctx
        )

        with pytest.raises(ValueError, match='only a draft can be edited'):
            await production_service.update_order(
                real_async_db_session,
                prod_org.id,
                order.id,
                ProductionOrderUpdate(planned_qty=Decimal('1')),
                prod_ctx,
            )

    @pytest.mark.asyncio
    async def test_an_edit_reaches_the_log_with_what_moved(
        self,
        real_async_db_session: AsyncSession,
        prod_org: Organization,
        prod_user: User,
        prod_ctx: UserContextDTO,
        prod_storage_type: StorageType,
    ) -> None:
        """A planned run changed size and nobody could say who changed it."""
        output = await _template(real_async_db_session, prod_org, name='Log Out')
        location = await _location(
            real_async_db_session,
            prod_org,
            prod_user,
            prod_storage_type,
            name='Log Loc',
        )
        await _recipe(real_async_db_session, prod_org, output_template_id=output.id)
        order = await _draft_order(
            real_async_db_session,
            prod_org,
            prod_ctx,
            output_template=output,
            output_location=location,
            planned_qty=Decimal('4'),
        )

        await production_service.update_order(
            real_async_db_session,
            prod_org.id,
            order.id,
            ProductionOrderUpdate(planned_qty=Decimal('9'), notes=order.notes),
            prod_ctx,
        )

        updates = await _order_entries(
            real_async_db_session, prod_org, order.id, 'UPDATE'
        )
        assert len(updates) == 1
        assert updates[0].user_id == prod_user.id
        assert updates[0].snapshot == {
            'name': order.number,
            'before': {'planned_qty': '4.000'},
            'after': {'planned_qty': '9.000'},
        }

    @pytest.mark.asyncio
    async def test_an_edit_that_moves_nothing_writes_nothing(
        self,
        real_async_db_session: AsyncSession,
        prod_org: Organization,
        prod_user: User,
        prod_ctx: UserContextDTO,
        prod_storage_type: StorageType,
    ) -> None:
        output = await _template(real_async_db_session, prod_org, name='Still Out')
        location = await _location(
            real_async_db_session,
            prod_org,
            prod_user,
            prod_storage_type,
            name='Still Loc',
        )
        await _recipe(real_async_db_session, prod_org, output_template_id=output.id)
        order = await _draft_order(
            real_async_db_session,
            prod_org,
            prod_ctx,
            output_template=output,
            output_location=location,
            planned_qty=Decimal('4'),
        )

        await production_service.update_order(
            real_async_db_session,
            prod_org.id,
            order.id,
            ProductionOrderUpdate(planned_qty=Decimal('4')),
            prod_ctx,
        )

        assert (
            await _order_entries(real_async_db_session, prod_org, order.id, 'UPDATE')
            == []
        )

    @pytest.mark.asyncio
    async def test_the_same_edit_saved_twice_at_once_writes_one_entry(
        self,
        real_async_db_session: AsyncSession,
        prod_org: Organization,
        prod_user: User,
        prod_ctx: UserContextDTO,
        prod_storage_type: StorageType,
    ) -> None:
        """Two saves of the same note meet: the second finds it already
        written, and an entry from what it read before the first committed
        would journal a change that never happened."""
        output = await _template(real_async_db_session, prod_org, name='Twice Out')
        location = await _location(
            real_async_db_session,
            prod_org,
            prod_user,
            prod_storage_type,
            name='Twice Loc',
        )
        await _recipe(real_async_db_session, prod_org, output_template_id=output.id)
        order = await _draft_order(
            real_async_db_session,
            prod_org,
            prod_ctx,
            output_template=output,
            output_location=location,
        )
        await real_async_db_session.commit()
        maker = async_sessionmaker(
            bind=real_async_db_session.bind, expire_on_commit=False
        )
        edit = ProductionOrderUpdate(notes='Saved twice')

        async with maker() as first, maker() as second:
            await production_service.update_order(
                first, prod_org.id, order.id, edit, prod_ctx
            )
            first_pid = int(await first.scalar(text('SELECT pg_backend_pid()')))
            second_pid = int(await second.scalar(text('SELECT pg_backend_pid()')))
            racer = asyncio.create_task(
                production_service.update_order(
                    second, prod_org.id, order.id, edit, prod_ctx
                )
            )
            try:
                await _wait_until_parked(
                    racer, racer_pid=second_pid, holder_pid=first_pid, maker=maker
                )
            except BaseException:
                await first.rollback()
                await asyncio.gather(racer, return_exceptions=True)
                raise
            await first.commit()
            await racer
            await second.commit()

        updates = await _order_entries(
            real_async_db_session, prod_org, order.id, 'UPDATE'
        )
        assert [entry.snapshot for entry in updates] == [
            {
                'name': order.number,
                'before': {'notes': None},
                'after': {'notes': 'Saved twice'},
            }
        ]


async def _wait_until_parked(
    racer: asyncio.Task[Any],
    *,
    racer_pid: int,
    holder_pid: int,
    maker: async_sessionmaker[AsyncSession],
) -> None:
    """Return once the *racer*'s backend waits on a lock the *holder*'s holds.

    Both backends are named by the caller before the racer starts, and the
    lock table is asked about them: any other backend queued on any other
    lock, in this database or a neighbour's, does not stand in for the racer.
    A racer that raised is answered by its own exception as soon as it has.
    """
    deadline = asyncio.get_running_loop().time() + 15
    async with maker() as probe:
        while not racer.done():
            waiting = await probe.scalar(
                text('SELECT :holder = ANY(pg_blocking_pids(:racer))'),
                {'holder': holder_pid, 'racer': racer_pid},
            )
            if waiting:
                return
            if asyncio.get_running_loop().time() > deadline:
                raise AssertionError('the second save never parked on the first')
            await asyncio.sleep(0.02)
    racer.result()
    raise AssertionError('the second save finished without parking on the first')


class TestTheParkedProbeWatchesItsOwnRacer:
    """A racer that ends ends the wait; a stranger's queueing is not a racer's."""

    @staticmethod
    async def _watch(
        db: AsyncSession,
        racer_work: Callable[[AsyncSession], Coroutine[Any, Any, None]],
    ) -> None:
        maker = async_sessionmaker(bind=db.bind, expire_on_commit=False)
        take = text('SELECT pg_advisory_xact_lock(7)')
        async with maker() as holder, maker() as stranger, maker() as racing:
            pids = [
                int(await s.scalar(text('SELECT pg_backend_pid()')))
                for s in (holder, stranger, racing)
            ]
            await holder.execute(take)
            queued = asyncio.create_task(stranger.execute(take))
            racer = asyncio.create_task(racer_work(racing))
            try:
                await _wait_until_parked(
                    racer, racer_pid=pids[2], holder_pid=pids[0], maker=maker
                )
            finally:
                racer.cancel()
                await holder.rollback()
                await asyncio.gather(racer, queued, return_exceptions=True)

    @pytest.mark.asyncio
    async def test_a_racer_that_fails_reports_its_own_failure(
        self, real_async_db_session: AsyncSession
    ) -> None:
        async def _breaks(_session: AsyncSession) -> None:
            raise LookupError('the save broke')

        with pytest.raises(LookupError, match='the save broke'):
            await self._watch(real_async_db_session, _breaks)

    @pytest.mark.asyncio
    async def test_a_racer_that_never_waits_is_said_to_have_finished(
        self, real_async_db_session: AsyncSession
    ) -> None:
        async def _free(_session: AsyncSession) -> None:
            return None

        with pytest.raises(AssertionError, match='finished without parking'):
            await self._watch(real_async_db_session, _free)


async def _order_entries(
    db: AsyncSession, org: Organization, order_id: UUID, action: str
) -> list[AuditLog]:
    return list(
        (
            await db.scalars(
                select(AuditLog).where(
                    AuditLog.organization_id == org.id,
                    AuditLog.target_type == 'maker_production_order',
                    AuditLog.target_id == order_id,
                    AuditLog.action == action,
                )
            )
        ).all()
    )


# ---------------------------------------------------------------------------
# duplicate_order
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestDuplicateOrder:
    @pytest.mark.asyncio
    async def test_duplicate_with_notes(
        self,
        real_async_db_session: AsyncSession,
        prod_org: Organization,
        prod_user: User,
        prod_ctx: UserContextDTO,
        prod_storage_type: StorageType,
    ) -> None:
        output = await _template(real_async_db_session, prod_org, name='Dup Out')
        location = await _location(
            real_async_db_session,
            prod_org,
            prod_user,
            prod_storage_type,
            name='Dup Loc',
        )
        await _recipe(real_async_db_session, prod_org, output_template_id=output.id)
        order = await _draft_order(
            real_async_db_session,
            prod_org,
            prod_ctx,
            output_template=output,
            output_location=location,
            planned_qty=Decimal('6'),
        )
        await production_service.update_order(
            real_async_db_session,
            prod_org.id,
            order.id,
            ProductionOrderUpdate(notes='original'),
            prod_ctx,
        )

        duplicate = await production_service.duplicate_order(
            real_async_db_session, prod_org.id, order.id, prod_ctx
        )

        assert duplicate.status == 'DRAFT'
        assert duplicate.notes == '[duplicate] original'
        assert duplicate.planned_qty == Decimal('6')
        assert duplicate.output_template_id == output.id
        assert duplicate.output_storage_location_id == location.id
        assert duplicate.produced_item_id is None

    @pytest.mark.asyncio
    async def test_duplicate_without_notes(
        self,
        real_async_db_session: AsyncSession,
        prod_org: Organization,
        prod_user: User,
        prod_ctx: UserContextDTO,
        prod_storage_type: StorageType,
    ) -> None:
        output = await _template(real_async_db_session, prod_org, name='DupNoNote Out')
        location = await _location(
            real_async_db_session,
            prod_org,
            prod_user,
            prod_storage_type,
            name='DupNoNote Loc',
        )
        await _recipe(real_async_db_session, prod_org, output_template_id=output.id)
        order = await _draft_order(
            real_async_db_session,
            prod_org,
            prod_ctx,
            output_template=output,
            output_location=location,
        )

        duplicate = await production_service.duplicate_order(
            real_async_db_session, prod_org.id, order.id, prod_ctx
        )

        assert duplicate.notes == '[duplicate]'
        # The copy is an order opened like any other, and says where from.
        created = await _order_entries(
            real_async_db_session, prod_org, duplicate.id, 'CREATE'
        )
        assert len(created) == 1
        assert created[0].user_id == prod_user.id
        assert created[0].snapshot == {
            'name': duplicate.number,
            'status': 'DRAFT',
            'output': output.name,
            'planned_qty': '1.000',
            'copied_from': order.number,
        }

    @pytest.mark.asyncio
    async def test_the_opening_entry_keeps_the_exact_digits_of_the_quantity(
        self,
        real_async_db_session: AsyncSession,
        prod_org: Organization,
        prod_user: User,
        prod_ctx: UserContextDTO,
        prod_storage_type: StorageType,
    ) -> None:
        """A quantity is written down as the digits the column keeps — a text,
        not the float that would print ``0.1`` for a value it only
        approximates — for the order and for its copy alike."""
        output = await _template(real_async_db_session, prod_org, name='Exact Out')
        location = await _location(
            real_async_db_session,
            prod_org,
            prod_user,
            prod_storage_type,
            name='Exact Loc',
        )
        await _recipe(real_async_db_session, prod_org, output_template_id=output.id)
        order = await _draft_order(
            real_async_db_session,
            prod_org,
            prod_ctx,
            output_template=output,
            output_location=location,
            planned_qty=Decimal('2.5'),
        )
        duplicate = await production_service.duplicate_order(
            real_async_db_session, prod_org.id, order.id, prod_ctx
        )

        for opened in (order, duplicate):
            (entry,) = await _order_entries(
                real_async_db_session, prod_org, opened.id, 'CREATE'
            )
            assert entry.snapshot is not None
            assert entry.snapshot['planned_qty'] == '2.500'

    @pytest.mark.asyncio
    async def test_a_quantity_resaved_with_other_digits_writes_nothing(
        self,
        real_async_db_session: AsyncSession,
        prod_org: Organization,
        prod_user: User,
        prod_ctx: UserContextDTO,
        prod_storage_type: StorageType,
    ) -> None:
        """``4`` posted over a stored ``4.000`` is one quantity, not a change."""
        output = await _template(real_async_db_session, prod_org, name='Digits Out')
        location = await _location(
            real_async_db_session,
            prod_org,
            prod_user,
            prod_storage_type,
            name='Digits Loc',
        )
        await _recipe(real_async_db_session, prod_org, output_template_id=output.id)
        order = await _draft_order(
            real_async_db_session,
            prod_org,
            prod_ctx,
            output_template=output,
            output_location=location,
            planned_qty=Decimal('4.000'),
        )

        await production_service.update_order(
            real_async_db_session,
            prod_org.id,
            order.id,
            ProductionOrderUpdate(planned_qty=Decimal('4')),
            prod_ctx,
        )

        assert (
            await _order_entries(real_async_db_session, prod_org, order.id, 'UPDATE')
            == []
        )

    @pytest.mark.asyncio
    async def test_duplicate_not_found(
        self,
        real_async_db_session: AsyncSession,
        prod_org: Organization,
        prod_ctx: UserContextDTO,
    ) -> None:
        with pytest.raises(EntityNotFoundError):
            await production_service.duplicate_order(
                real_async_db_session, prod_org.id, uuid.uuid4(), prod_ctx
            )


@pytest.mark.integration
class TestExplodeQueryCount:
    """multi-level explosion must batch per level, not query per line.

    The number of statements grows with depth, not with the number of
    sibling lines: expanding a 2-level BOM with 8 leaf lines costs the
    same as one with 4.
    """

    @pytest.mark.asyncio
    async def test_query_count_grows_with_depth_not_line_count(
        self,
        real_async_db_session: AsyncSession,
        prod_org: Organization,
    ) -> None:
        from sqlalchemy import event

        from app.modules.maker import bom_service

        async def _seed_two_level_bom(leaf_count: int, name: str) -> UUID:
            """Root recipe: N-1 leaves + 1 sub-assembly; sub has 2 leaves."""
            root_tpl = await _template(real_async_db_session, prod_org, name=name)
            sub_tpl = await _template(
                real_async_db_session, prod_org, name=f'{name} Sub'
            )
            leaves = [
                await _template(
                    real_async_db_session, prod_org, name=f'{name} Leaf {i}'
                )
                for i in range(leaf_count)
            ]
            root_recipe = await _recipe(
                real_async_db_session,
                prod_org,
                output_template_id=root_tpl.id,
            )
            sub_recipe = await _recipe(
                real_async_db_session,
                prod_org,
                output_template_id=sub_tpl.id,
            )
            await _bom_line(
                real_async_db_session,
                prod_org,
                root_recipe,
                sub_tpl.id,
            )
            for leaf in leaves[:-1]:
                await _bom_line(
                    real_async_db_session,
                    prod_org,
                    root_recipe,
                    leaf.id,
                )
            for leaf in leaves:
                await _bom_line(
                    real_async_db_session,
                    prod_org,
                    sub_recipe,
                    leaf.id,
                )
            await real_async_db_session.flush()
            return root_tpl.id

        async def _explode_and_count(root_template_id: UUID) -> int:
            bind = real_async_db_session.get_bind()
            counter = {'count': 0}

            def _on_execute(*_args: object, **_kwargs: object) -> None:
                counter['count'] += 1

            event.listen(bind, 'before_cursor_execute', _on_execute)
            try:
                await bom_service.explode(
                    real_async_db_session, prod_org.id, root_template_id, Decimal('1')
                )
            finally:
                event.remove(bind, 'before_cursor_execute', _on_execute)
            return counter['count']

        small_root = await _seed_two_level_bom(4, 'Small')
        large_root = await _seed_two_level_bom(8, 'Large')

        small_queries = await _explode_and_count(small_root)
        large_queries = await _explode_and_count(large_root)

        assert small_queries == large_queries, (
            f'query count must not grow with sibling lines: '
            f'{small_queries} (4 lines) vs {large_queries} (8 lines)'
        )
        # Constant per level: root recipe lookup + lazy ``lines`` load, one
        # batched recipe fetch (+ its batched ``lines``) per level, plus the
        # model's own selectin loads (``output_template``, ``cost_lines``).
        # Two levels must stay well under a per-line cost.
        assert large_queries <= 10, f'expected ≤10 queries, got {large_queries}'


@pytest.mark.integration
class TestAvailabilityQueryCount:
    """availability and shortage checks batch template and stock
    reads — query count stays flat as the ingredient count grows."""

    @pytest.mark.asyncio
    async def test_query_count_stays_flat_as_ingredients_grow(
        self,
        real_async_db_session: AsyncSession,
        prod_org: Organization,
        prod_user: User,
        prod_storage_type: StorageType,
    ) -> None:
        from sqlalchemy import event

        from app.modules.maker import availability_service

        db = real_async_db_session

        async def _seed_recipe_with_ingredients(
            ingredient_count: int, name: str
        ) -> UUID:
            output = await _template(db, prod_org, name=name)
            location = await _location(
                db, prod_org, prod_user, prod_storage_type, name=f'{name} Loc'
            )
            recipe = await _recipe(db, prod_org, output_template_id=output.id)
            for i in range(ingredient_count):
                ingredient = await _template(db, prod_org, name=f'{name} Ing {i}')
                await _bom_line(db, prod_org, recipe, ingredient.id)
                await _stock(db, prod_user, ingredient, location, qty=Decimal('100'))
            await db.flush()
            return recipe.id

        async def _run_and_count(coro: Coroutine[Any, Any, Any]) -> int:
            bind = db.get_bind()
            counter = {'count': 0}

            def _on_execute(*_args: object, **_kwargs: object) -> None:
                counter['count'] += 1

            event.listen(bind, 'before_cursor_execute', _on_execute)
            try:
                await coro
            finally:
                event.remove(bind, 'before_cursor_execute', _on_execute)
            return counter['count']

        small_recipe = await _seed_recipe_with_ingredients(4, 'AvailSmall')
        large_recipe = await _seed_recipe_with_ingredients(8, 'AvailLarge')

        small_avail = await _run_and_count(
            availability_service.compute_availability(db, prod_org.id, small_recipe)
        )
        large_avail = await _run_and_count(
            availability_service.compute_availability(db, prod_org.id, large_recipe)
        )
        assert small_avail == large_avail, (
            f'compute_availability query count must not grow with '
            f'ingredients: {small_avail} (4) vs {large_avail} (8)'
        )

        small_shortage = await _run_and_count(
            availability_service.compute_shortage_list(
                db, prod_org.id, small_recipe, Decimal('1')
            )
        )
        large_shortage = await _run_and_count(
            availability_service.compute_shortage_list(
                db, prod_org.id, large_recipe, Decimal('1')
            )
        )
        assert small_shortage == large_shortage, (
            f'compute_shortage_list query count must not grow with '
            f'ingredients: {small_shortage} (4) vs {large_shortage} (8)'
        )

"""Turning a module on or off has to be true for the next request, not the next restart.

Two caches answered "is this module on" and neither of them was told when
the answer changed:

* the stock bridge kept a process-local dict of "does this organisation use
  WMS stock", cleared only by a CLI command. Four workers meant four
  answers, and every one of them survived the toggle until the process
  died -- so enabling a warehouse module left stock silently untracked on
  whichever worker had already answered "no". The bridge no longer asks
  (every organisation keeps the register); the question lives
  on where the screens decide whether to read the cost ledger, and it has to
  be answered as fresh there.
* "is module X enabled" existed twice under one name, once reading the
  column and once through a sixty-second cache, so for a minute after a
  toggle the answer depended on which of the two an endpoint happened to
  call.

The switch itself is also made in three places -- the toggle, a profile
switch and onboarding -- and only the first of them invalidated anything.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import cache as cache_module
from app.core.public_api import core_api
from app.core.testing import ModuleTestHelper
from app.models.item import Item
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.stock_move import StockMove
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from tests.integration._fake_redis import FakeRedis
from tests.integration._shelf import anchor_pending_records

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

#: Declares consumes_stock_quant, so enabling it puts the register on screen.
_WMS_MODULE = 'warehouse'


class _Warehouse:
    def __init__(self) -> None:
        self.org: Organization
        self.location: StorageLocation
        self.user: object


async def _warehouse(db: AsyncSession, *, modules: list[str]) -> _Warehouse:
    fixture = _Warehouse()
    org = Organization(
        name=f'Switching {uuid.uuid4().hex[:6]}',
        enabled_modules=modules,
    )
    db.add(org)
    await db.flush()
    fixture.org = org
    fixture.user = await ModuleTestHelper.create_user_async(
        db, org, email=f'switch_{uuid.uuid4().hex[:8]}@test.com', role='admin'
    )
    storage_type = StorageType(
        name='Shelf', type_code=f'SHELF_{uuid.uuid4().hex[:6]}', behavior_mode='NONE'
    )
    db.add(storage_type)
    await db.flush()
    fixture.location = StorageLocation(
        name='Aisle 1',
        organization_id=org.id,
        storage_type_id=storage_type.id,
        created_by=fixture.user.id,
    )
    db.add(fixture.location)
    await db.commit()
    return fixture


async def _stock_a_product(db: AsyncSession, shed: _Warehouse) -> ProductTemplate:
    """Put something on the shelf the way the app does, bridge and all."""
    template = ProductTemplate(
        organization_id=shed.org.id,
        name=f'Product {uuid.uuid4().hex[:6]}',
        sku=f'P-{uuid.uuid4().hex[:8]}',
    )
    db.add(template)
    await db.flush()
    item = Item(
        name=template.name,
        organization_id=shed.org.id,
        storage_location_id=shed.location.id,
        template_id=template.id,
        quantity=Decimal('0'),
    )
    db.add(item)
    await db.run_sync(anchor_pending_records)
    await db.flush()

    from app.services.items._stock_quant import apply_quantity_change_async

    # At a stated cost, so the ledger actually answers for this stock: what
    # this test switches is the module, and a ledger holding only unknown
    # 0.00 layers is not one the value reader may choose
    # (``org_uses_valuation_layers_async``).
    await apply_quantity_change_async(db, item, Decimal('5'), unit_cost=Decimal('2.00'))
    await db.commit()
    return template


async def _moves_for(db: AsyncSession, template: ProductTemplate) -> int:
    """How many movements the register holds for *template*."""
    return int(
        await db.scalar(
            select(func.count())
            .select_from(StockMove)
            .where(StockMove.product_template_id == template.id)
        )
        or 0
    )


async def _set_modules(db: AsyncSession, shed: _Warehouse, modules: list[str]) -> None:
    shed.org.enabled_modules = modules
    db.add(shed.org)
    await db.commit()


class TestTheSwitchIsSeenWhereItStillCounts:
    async def test_the_bridge_writes_whichever_way_the_switch_stands(
        self, real_async_db_session: AsyncSession
    ) -> None:
        """Off and on alike: the register is kept for every organization."""
        db = real_async_db_session
        shed = await _warehouse(db, modules=['core', 'items', 'locations'])

        first = await _stock_a_product(db, shed)
        await _set_modules(db, shed, ['core', 'items', 'locations', _WMS_MODULE])
        second = await _stock_a_product(db, shed)
        await _set_modules(db, shed, ['core', 'items', 'locations'])
        third = await _stock_a_product(db, shed)

        assert [await _moves_for(db, t) for t in (first, second, third)] == [1, 1, 1]

    async def test_the_value_reader_notices_the_switch_at_once(
        self, real_async_db_session: AsyncSession
    ) -> None:
        """The damaging direction: a figure read from the wrong ledger."""
        from app.services.analytics._common import org_uses_valuation_layers_async

        db = real_async_db_session
        shed = await _warehouse(db, modules=['core', 'items', 'locations'])
        await _stock_a_product(db, shed)
        assert await org_uses_valuation_layers_async(db, shed.org.id) is False

        await _set_modules(db, shed, ['core', 'items', 'locations', _WMS_MODULE])
        assert await org_uses_valuation_layers_async(db, shed.org.id) is True

        await _set_modules(db, shed, ['core', 'items', 'locations'])
        assert await org_uses_valuation_layers_async(db, shed.org.id) is False


class TestBothAnswersAgree:
    @pytest.fixture(autouse=True)
    def _with_a_cache(self):
        """A live cache client, or the question below answers itself."""
        original = cache_module._redis
        cache_module._redis = FakeRedis()  # type: ignore[assignment]
        yield
        cache_module._redis = original

    async def test_the_two_entry_points_say_the_same_thing_after_a_switch(
        self, real_async_db_session: AsyncSession
    ) -> None:
        from app.core.modules import is_module_enabled_async as via_core_modules

        db = real_async_db_session
        shed = await _warehouse(db, modules=['core', 'items', 'locations', _WMS_MODULE])

        # Ask once while it is on, which is what fills a cache.
        assert await via_core_modules(db, shed.org.id, _WMS_MODULE) is True

        await _set_modules(db, shed, ['core', 'items', 'locations'])

        assert await via_core_modules(db, shed.org.id, _WMS_MODULE) is False
        assert (
            await core_api.organizations.is_module_enabled_async(
                db, shed.org.id, _WMS_MODULE
            )
            is False
        )

    async def test_they_agree_the_other_way_round_too(
        self, real_async_db_session: AsyncSession
    ) -> None:
        from app.core.modules import is_module_enabled_async as via_core_modules

        db = real_async_db_session
        shed = await _warehouse(db, modules=['core', 'items', 'locations'])

        assert await via_core_modules(db, shed.org.id, _WMS_MODULE) is False

        await _set_modules(db, shed, ['core', 'items', 'locations', _WMS_MODULE])

        assert await via_core_modules(db, shed.org.id, _WMS_MODULE) is True
        assert (
            await core_api.organizations.is_module_enabled_async(
                db, shed.org.id, _WMS_MODULE
            )
            is True
        )

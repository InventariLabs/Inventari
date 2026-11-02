"""A unit of another organization is not this organization's unit.

``CoreUomsAPI.get_async`` and ``validate_quantity_precision_async`` were
addressed by a unit id alone, so whichever module passed the id decided
which tenant's unit it was: a unit one organization defined for itself could
be read by another, and its rounding applied to that other organization's
stock. Both now require the caller's organization and see only its own units
plus the system catalogue (``organization_id IS NULL``).

The pair measured here: org B's own unit does not exist for org A — neither
in a read answer nor as a precision reference — while org A's own unit and a
global system unit both do. The controls keep the refusal from being "the
method refuses everything": B's own call still reads and accepts its unit,
and A's own unit still answers.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ServiceRejectionError
from app.core.public_api import core_api
from app.models.organization import Organization
from app.models.uom import Uom, UomCategory


async def _unit(
    db: AsyncSession,
    name: str,
    symbol: str,
    rounding: str,
    organization_id: uuid.UUID | None,
) -> Uom:
    category = UomCategory(name=f'{name} {uuid.uuid4().hex[:6]}')
    db.add(category)
    await db.flush()
    uom = Uom(
        category_id=category.id,
        name=name,
        symbol=symbol,
        rounding=Decimal(rounding),
        organization_id=organization_id,
    )
    db.add(uom)
    await db.flush()
    return uom


@pytest.fixture
async def org_a(real_async_db_session: AsyncSession) -> Organization:
    org = Organization(name='Unit Org A', enabled_modules=['core'])
    real_async_db_session.add(org)
    await real_async_db_session.flush()
    return org


@pytest.fixture
async def org_b(real_async_db_session: AsyncSession) -> Organization:
    org = Organization(name='Unit Org B', enabled_modules=['core'])
    real_async_db_session.add(org)
    await real_async_db_session.flush()
    return org


@pytest.fixture
async def own_unit(real_async_db_session: AsyncSession, org_a: Organization) -> Uom:
    return await _unit(real_async_db_session, 'Half crate', 'halfA', '0.5', org_a.id)


@pytest.fixture
async def foreign_unit(real_async_db_session: AsyncSession, org_b: Organization) -> Uom:
    return await _unit(real_async_db_session, 'Half crate', 'halfB', '0.5', org_b.id)


@pytest.fixture
async def global_unit(real_async_db_session: AsyncSession) -> Uom:
    return await _unit(real_async_db_session, 'Pieces', 'pcsorg', '1', None)


@pytest.mark.integration
@pytest.mark.asyncio
class TestGetAsyncSeesOnlyOwnAndGlobal:
    async def test_own_unit_is_returned(
        self,
        real_async_db_session: AsyncSession,
        org_a: Organization,
        own_unit: Uom,
    ) -> None:
        found = await core_api.uoms.get_async(
            real_async_db_session, own_unit.id, org_a.id
        )
        assert found is not None
        assert found.id == own_unit.id

    async def test_another_orgs_unit_reads_as_absent(
        self,
        real_async_db_session: AsyncSession,
        org_a: Organization,
        foreign_unit: Uom,
    ) -> None:
        assert (
            await core_api.uoms.get_async(
                real_async_db_session, foreign_unit.id, org_a.id
            )
            is None
        )

    async def test_another_orgs_unit_is_still_its_own_orgs_unit(
        self,
        real_async_db_session: AsyncSession,
        org_b: Organization,
        foreign_unit: Uom,
    ) -> None:
        """The control: the read is scoped, not broken."""
        found = await core_api.uoms.get_async(
            real_async_db_session, foreign_unit.id, org_b.id
        )
        assert found is not None
        assert found.id == foreign_unit.id

    async def test_global_unit_is_returned_for_every_org(
        self,
        real_async_db_session: AsyncSession,
        org_a: Organization,
        global_unit: Uom,
    ) -> None:
        found = await core_api.uoms.get_async(
            real_async_db_session, global_unit.id, org_a.id
        )
        assert found is not None
        assert found.id == global_unit.id


@pytest.mark.integration
@pytest.mark.asyncio
class TestValidateRefusesWhatTheOrgCannotSee:
    async def test_a_foreign_unit_is_refused(
        self,
        real_async_db_session: AsyncSession,
        org_a: Organization,
        foreign_unit: Uom,
    ) -> None:
        """2.5 is a whole number of the halves B counts in — for B, not for A."""
        with pytest.raises(ServiceRejectionError) as refusal:
            await core_api.uoms.validate_quantity_precision_async(
                real_async_db_session, foreign_unit.id, Decimal('2.5'), org_a.id
            )
        assert refusal.value.key == 'uom_not_found'

    async def test_the_foreign_units_own_org_still_accepts_it(
        self,
        real_async_db_session: AsyncSession,
        org_b: Organization,
        foreign_unit: Uom,
    ) -> None:
        """The control: the same call, the same unit, the owning org."""
        await core_api.uoms.validate_quantity_precision_async(
            real_async_db_session, foreign_unit.id, Decimal('2.5'), org_b.id
        )

    async def test_a_global_unit_still_speaks_for_every_org(
        self,
        real_async_db_session: AsyncSession,
        org_a: Organization,
        global_unit: Uom,
    ) -> None:
        """The control: scoping hides other tenants, not the system catalogue."""
        with pytest.raises(ServiceRejectionError) as refusal:
            await core_api.uoms.validate_quantity_precision_async(
                real_async_db_session, global_unit.id, Decimal('2.5'), org_a.id
            )
        assert refusal.value.key == 'uom_quantity_requires_whole_number'

    async def test_the_orgs_own_unit_still_accepts_what_it_can_hold(
        self,
        real_async_db_session: AsyncSession,
        org_a: Organization,
        own_unit: Uom,
    ) -> None:
        await core_api.uoms.validate_quantity_precision_async(
            real_async_db_session, own_unit.id, Decimal('2.5'), org_a.id
        )

"""What a new organization is switched on with, for every profile there is.

Onboarding asks what kind of place this is and then *added* the answer to a
list the organization already held from the ORM's column default — eight
modules, hand-written, never subtracted from. The result of choosing a profile
was therefore always a union, and the eight-module default won every contest
because it went first.

Measured on a clean organization: choosing `food_home` produced
`[core, items, locations, categories, shopping_lists, stock_takes, stats,
documents, recipes, nutrition, vision]`. The last three came from the profile.
`documents` — a register with numbering, accounting periods and approval
thresholds — came from the default, and `food_home.default_modules` neither
lists it nor is meant to.

One test per profile rather than two named ones, because the rule is the rule:
the profile's list plus what nobody opts into, and nothing else.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserContextDTO
from app.core.module_safety import ALWAYS_ON_MODULES
from app.core.product_profiles import PRODUCT_PROFILES
from app.models.organization import Organization
from app.models.user import User
from app.services.onboarding_service import apply_onboarding_profile_async

pytestmark = pytest.mark.integration


async def _onboarder(session: AsyncSession, org: Organization) -> UserContextDTO:
    """A real user row for an onboarding call: profiles that declare
    starting locations create them with a creator, and ``created_by`` is
    NOT NULL."""
    user = User(
        email=f'user_{uuid.uuid4().hex[:8]}@example.com',
        hashed_password='x',
        full_name='Onboarder',
        organization_id=org.id,
        role='admin',
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return UserContextDTO(id=user.id, organization_id=org.id, role='admin')


@pytest.mark.asyncio
@pytest.mark.parametrize('profile_id', sorted(PRODUCT_PROFILES))
async def test_a_fresh_organization_gets_exactly_its_profile(
    real_async_db_session: AsyncSession, profile_id: str
) -> None:
    org = Organization(name=f'Fresh {uuid.uuid4().hex[:8]}')
    real_async_db_session.add(org)
    await real_async_db_session.flush()

    result = await apply_onboarding_profile_async(
        real_async_db_session,
        org,
        profile_id,
        user=await _onboarder(real_async_db_session, org),
    )

    expected = set(PRODUCT_PROFILES[profile_id].default_modules) | ALWAYS_ON_MODULES
    assert set(result.enabled_modules) == expected

    # A profile's declared starting locations exist after
    # onboarding, for every profile that declares any.
    from sqlalchemy import select

    from app.models.storage_location import StorageLocation

    rows = (
        (
            await real_async_db_session.execute(
                select(StorageLocation.name).where(
                    StorageLocation.organization_id == org.id
                )
            )
        )
        .scalars()
        .all()
    )
    declared = {loc.name for loc in PRODUCT_PROFILES[profile_id].default_locations}
    assert declared <= set(rows)


@pytest.mark.asyncio
async def test_a_household_does_not_get_the_document_register(
    real_async_db_session: AsyncSession,
) -> None:
    """The measured case, kept by name because it is what a person noticed."""
    org = Organization(name=f'Household {uuid.uuid4().hex[:8]}')
    real_async_db_session.add(org)
    await real_async_db_session.flush()

    result = await apply_onboarding_profile_async(
        real_async_db_session,
        org,
        'food_home',
        user=await _onboarder(real_async_db_session, org),
    )

    assert 'warehouse' not in result.enabled_modules
    assert 'recipes' in result.enabled_modules


@pytest.mark.asyncio
async def test_before_onboarding_an_organization_has_only_what_is_not_a_choice(
    real_async_db_session: AsyncSession,
) -> None:
    """The column default, which is what an account that never onboards keeps.

    An organization is created at registration and `onboarding_completed` is
    set by the profile step, so this is a real state a person can sit in. It
    used to be eight hand-written names; it is now the always-on set, which is
    a usable inventory — items, locations, categories — and no opinion about
    anything else.

    Flushed, because the column default lands on INSERT: the registration path
    commits the row, which is the state this is about.
    """
    org = Organization(name=f'Never onboarded {uuid.uuid4().hex[:8]}')
    real_async_db_session.add(org)
    await real_async_db_session.flush()

    assert set(org.enabled_modules or []) == ALWAYS_ON_MODULES


# Every profile as it comes, and the business profile with equipment
# tracking unticked on the second step — a small warehouse that tracks no IT
# assets. The equipment module is what brought that profile's shared
# "Main Warehouse"; without it the organization was left with the quarantine
# shelf alone, and the product form offered nowhere else to put stock.
_FIRST_PRODUCT_CASES = [(profile_id, None) for profile_id in sorted(PRODUCT_PROFILES)]
_FIRST_PRODUCT_CASES.append(
    (
        'equipment_wms',
        [
            name
            for name in PRODUCT_PROFILES['equipment_wms'].default_modules
            if name != 'equipment'
        ],
    )
)


@pytest.mark.asyncio
@pytest.mark.parametrize(('profile_id', 'modules'), _FIRST_PRODUCT_CASES)
async def test_a_fresh_organization_has_somewhere_to_put_its_first_product(
    real_async_db_session: AsyncSession,
    profile_id: str,
    modules: list[str] | None,
) -> None:
    """The first product needs a place, and setting one up is not step one.

    Whatever the reader picked, onboarding ends with at least one ordinary
    location — internal, owned by no module, not the quarantine shelf.
    """
    from sqlalchemy import select

    from app.core.product_profiles import QUARANTINE_LOCATION_CODE
    from app.models.storage_location import LocationUsage, StorageLocation

    org = Organization(name=f'First product {uuid.uuid4().hex[:8]}')
    real_async_db_session.add(org)
    await real_async_db_session.flush()

    await apply_onboarding_profile_async(
        real_async_db_session,
        org,
        profile_id,
        user=await _onboarder(real_async_db_session, org),
        modules=modules,
    )

    rows = (
        (
            await real_async_db_session.execute(
                select(StorageLocation).where(
                    StorageLocation.organization_id == org.id,
                    StorageLocation.usage == LocationUsage.INTERNAL,
                    StorageLocation.context_tag.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    ordinary = [
        row.name
        for row in rows
        if ((row.settings or {}).get('seed') or {}).get('code')
        != QUARANTINE_LOCATION_CODE
    ]
    assert ordinary, f'{profile_id} left no ordinary location for a first product'

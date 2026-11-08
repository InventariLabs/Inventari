"""Integration tests for the onboarding profile application flow.

Verifies that apply_onboarding_profile_async enables the modules
declared in the chosen ProductProfile.default_modules — specifically
the promise that 'recipes' is enabled for the
food_home profile (it was described but missing from default_modules).
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import cache as cache_module
from app.core.contracts import UserContextDTO
from app.models.organization import Organization
from app.services.onboarding_service import apply_onboarding_profile_async
from tests.integration._fake_redis import FakeRedis

pytestmark = pytest.mark.integration


@pytest.fixture
def fake_redis() -> FakeRedis:
    """In-memory Redis replacement for cache tests."""
    return FakeRedis()


@pytest.fixture(autouse=True)
def _reset_cache_redis():
    """Restore cache module to unconfigured state around each test."""
    original = cache_module._redis
    yield
    cache_module._redis = original


async def _onboarder(session: AsyncSession, org: Organization) -> UserContextDTO:
    """A real user row for an onboarding call: profiles that declare
    starting locations create them with a creator, and ``created_by`` is
    NOT NULL."""
    from app.core.contracts import UserContextDTO
    from app.models.user import User

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
class TestOnboardingProfileApplication:
    """apply_onboarding_profile_async — profile → enabled_modules."""

    async def test_food_home_enables_recipes(
        self,
        real_async_db_session: AsyncSession,
    ):
        """food_home profile must enable 'recipes'.

        The profile description says 'Includes recipes and shopping lists'.
        Before the fix, recipes was NOT in default_modules — the biggest
        FE module (77 files) was invisible after onboarding.
        """
        org = Organization(
            name=f'Test Org {uuid.uuid4().hex[:8]}',
            enabled_modules=['core'],
        )
        real_async_db_session.add(org)
        await real_async_db_session.flush()

        result = await apply_onboarding_profile_async(
            real_async_db_session,
            org,
            'food_home',
            user=await _onboarder(real_async_db_session, org),
        )

        # Core assertions: recipes + shopping_lists
        # promised by the profile description must be enabled.
        assert 'recipes' in result.enabled_modules
        assert 'shopping_lists' in result.enabled_modules

    async def test_onboarding_runs_the_modules_own_enable_hook(
        self,
        real_async_db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """``on_enable`` says it runs whenever the module is enabled, and
        onboarding — the way every new organization gets its modules — ran
        only ``system_on_enable``. A module from outside that seeds its
        defaults in ``on_enable`` (or ``define_module(seed=)``) left every
        onboarded organization without them."""
        from app.core.module_registry import module_registry

        seen: list[uuid.UUID] = []
        module = module_registry.get('stock_takes')
        assert module is not None
        monkeypatch.setattr(
            module,
            'on_enable',
            lambda organization_id, context: seen.append(organization_id),
        )

        org = Organization(
            name=f'Test Org {uuid.uuid4().hex[:8]}',
            enabled_modules=['core'],
        )
        real_async_db_session.add(org)
        await real_async_db_session.flush()

        await apply_onboarding_profile_async(
            real_async_db_session,
            org,
            'clean_core',
            user=await _onboarder(real_async_db_session, org),
        )

        assert seen == [org.id]

    async def test_service_leaves_the_cache_for_the_caller_to_clear_after_commit(
        self,
        fake_redis: FakeRedis,
        real_async_db_session: AsyncSession,
    ):
        """The service only flushes; the router clears the caches once the
        commit has landed. Cleared here, a read before that commit would
        re-cache the old committed set for the full TTL.
        """
        cache_module._redis = fake_redis  # type: ignore[assignment]

        org = Organization(
            name=f'Test Org {uuid.uuid4().hex[:8]}',
            enabled_modules=['core'],
        )
        real_async_db_session.add(org)
        await real_async_db_session.flush()

        cache_key = f'org:{org.id}:modules'

        async def _stale_modules() -> list[str]:
            return list(org.enabled_modules)

        await cache_module.cache_get_or_set(cache_key, ttl=300, factory=_stale_modules)
        assert await fake_redis.get(cache_key) is not None

        await apply_onboarding_profile_async(
            real_async_db_session, org, 'equipment_wms'
        )

        assert await fake_redis.get(cache_key) is not None

    async def test_equipment_wms_seeds_default_locations_on_onboarding(
        self,
        real_async_db_session: AsyncSession,
    ):
        """Onboarding must seed the module's declared
        default storage locations through the framework ``system_on_enable``
        hook — the same machinery that seeds equipment categories on both
        enable paths. Before the fix, the class-level ``on_enable`` seed was
        skipped by onboarding, so a fresh org had no locations and the first
        asset save failed with "Location is required"."""
        from sqlalchemy import select

        from app.core.contracts import UserContextDTO
        from app.models.storage_location import StorageLocation
        from app.models.user import User

        org = Organization(
            name=f'Test Org {uuid.uuid4().hex[:8]}',
            enabled_modules=['core'],
        )
        real_async_db_session.add(org)
        await real_async_db_session.flush()

        user = User(
            email=f'user_{uuid.uuid4().hex[:8]}@example.com',
            hashed_password='x',
            full_name='Onboarder',
            organization_id=org.id,
            role='admin',
            is_active=True,
        )
        real_async_db_session.add(user)
        await real_async_db_session.flush()

        await apply_onboarding_profile_async(
            real_async_db_session,
            org,
            'equipment_wms',
            user=UserContextDTO(id=user.id, organization_id=org.id, role='admin'),
        )

        rows = (
            (
                await real_async_db_session.execute(
                    select(StorageLocation).where(
                        StorageLocation.organization_id == org.id,
                        StorageLocation.context_tag == 'equipment',
                    )
                )
            )
            .scalars()
            .all()
        )
        assert {r.name for r in rows} == {'Server Room', 'IT Storage'}

    async def test_food_home_seeds_its_declared_locations_on_onboarding(
        self,
        real_async_db_session: AsyncSession,
    ):
        """The home profile declares a Fridge, Shelf A and
        a Freezer, and the declaration used to stay dead — the first thing
        someone wanting to take stock of their fridge saw was "create a
        storage". Onboarding now seeds what the profile declares, the way
        equipment seeds its own through ``system_on_enable``."""
        from sqlalchemy import select

        from app.core.contracts import UserContextDTO
        from app.models.storage_location import StorageLocation
        from app.models.user import User

        org = Organization(
            name=f'Test Org {uuid.uuid4().hex[:8]}',
            enabled_modules=['core'],
        )
        real_async_db_session.add(org)
        await real_async_db_session.flush()

        user = User(
            email=f'user_{uuid.uuid4().hex[:8]}@example.com',
            hashed_password='x',
            full_name='Onboarder',
            organization_id=org.id,
            role='admin',
            is_active=True,
        )
        real_async_db_session.add(user)
        await real_async_db_session.flush()

        await apply_onboarding_profile_async(
            real_async_db_session,
            org,
            'food_home',
            user=UserContextDTO(id=user.id, organization_id=org.id, role='admin'),
        )

        # Core-seeded locations carry no context tag; the virtual ones the
        # seeder guarantees sit on the same tag, so this is a superset read.
        rows = (
            (
                await real_async_db_session.execute(
                    select(StorageLocation).where(
                        StorageLocation.organization_id == org.id,
                        StorageLocation.context_tag.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        assert {r.name for r in rows} >= {
            'Fridge',
            'Shelf A',
            'Freezer',
        }

    async def test_unknown_profile_raises_value_error(
        self,
        real_async_db_session: AsyncSession,
    ):
        """Unknown profile IDs raise ValueError, not a silent no-op."""
        org = Organization(
            name=f'Test Org {uuid.uuid4().hex[:8]}',
            enabled_modules=['core'],
        )
        real_async_db_session.add(org)
        await real_async_db_session.flush()

        with pytest.raises(ValueError, match='Unknown profile'):
            await apply_onboarding_profile_async(
                real_async_db_session, org, 'nonexistent_profile'
            )

    async def test_virtual_module_enabled_without_registry_entry(
        self,
        real_async_db_session: AsyncSession,
    ):
        """Virtual modules (e.g. 'partners') have no ``BaseModule``
        and were silently dropped by the registry lookup. They must still be
        appended to ``enabled_modules`` so the feature is usable right after
        onboarding, without a manual toggle in Settings."""
        from app.core.product_profiles import ProductProfile

        profile = ProductProfile(
            id='test_virtual',
            name='Test Virtual',
            description='Has a virtual module.',
            default_modules=['core', 'partners'],
            seed_profile='clean_core',
        )
        org = Organization(
            name=f'Test Org {uuid.uuid4().hex[:8]}',
            enabled_modules=['core'],
        )
        real_async_db_session.add(org)
        await real_async_db_session.flush()

        result = await apply_onboarding_profile_async(
            real_async_db_session, org, 'test_virtual', profile=profile
        )

        assert 'partners' in result.enabled_modules

    async def test_document_preset_applied_during_onboarding(
        self,
        real_async_db_session: AsyncSession,
    ):
        """When a profile declares ``document_preset``, onboarding
        must apply it to the org's DocumentProfile after enabling the
        warehouse module. ``value_tracking_enabled`` lives on DocumentProfile
        (not ``module_config`` — documents declares no settings schema), so
        this is the only path to turn value tracking on for a fresh org."""
        from app.core.product_profiles import ProductProfile
        from app.modules.warehouse.document_profile_service import (
            get_profile as get_document_profile,
        )

        profile = ProductProfile(
            id='test_preset',
            name='Test Preset',
            description='Has a document preset.',
            default_modules=['core', 'warehouse'],
            seed_profile='clean_core',
            document_preset='Full Value',
        )
        org = Organization(
            name=f'Test Org {uuid.uuid4().hex[:8]}',
            enabled_modules=['core'],
        )
        real_async_db_session.add(org)
        await real_async_db_session.flush()

        await apply_onboarding_profile_async(
            real_async_db_session, org, 'test_preset', profile=profile
        )

        doc_profile = await get_document_profile(real_async_db_session, org.id)
        assert doc_profile is not None
        assert doc_profile.value_tracking_enabled is True
        assert doc_profile.name == 'Full Value'

    async def test_equipment_wms_pins_no_tax_rate_for_a_polish_org(
        self,
        real_async_db_session: AsyncSession,
    ):
        """A Polish organization taking the real ``equipment_wms`` profile
        must not find a tax rate waiting on its document profile. That
        profile applies the ``Full Value`` preset, which used to carry the
        UK basic rate (20%) — a silent 20% on every document a Polish
        company would ever raise. A preset is a way of working, not a
        country: the rate is either the organization's own or none at all."""
        from app.modules.warehouse.document_profile_service import (
            get_profile as get_document_profile,
        )

        org = Organization(
            name=f'Test Org {uuid.uuid4().hex[:8]}',
            enabled_modules=['core'],
            country='PL',
        )
        real_async_db_session.add(org)
        await real_async_db_session.flush()

        await apply_onboarding_profile_async(
            real_async_db_session, org, 'equipment_wms'
        )

        doc_profile = await get_document_profile(real_async_db_session, org.id)
        assert doc_profile is not None
        assert doc_profile.name == 'Full Value'
        assert doc_profile.value_tracking_enabled is True
        assert doc_profile.default_tax_rate is None

    @pytest.mark.parametrize(
        ('country', 'preset'),
        [('PL', 'PL Magazyn'), ('DE', 'DE Lager'), ('GB', 'UK Warehouse')],
    )
    async def test_accepted_country_preset_keeps_the_profiles_value_tracking(
        self,
        real_async_db_session: AsyncSession,
        country: str,
        preset: str,
    ):
        """The founder who accepts the offer gets the country's paperwork
        (``DE Lager`` turns value tracking off) without losing the value
        tracking, nor the simple-rate tax handling that lets the country's
        standard rate reach the first document."""
        from app.modules.warehouse.document_profile_service import (
            get_profile as get_document_profile,
        )

        org = Organization(
            name=f'Test Org {uuid.uuid4().hex[:8]}',
            enabled_modules=['core'],
        )
        real_async_db_session.add(org)
        await real_async_db_session.flush()

        await apply_onboarding_profile_async(
            real_async_db_session,
            org,
            'equipment_wms',
            country=country,
            use_country_preset=True,
        )

        doc_profile = await get_document_profile(real_async_db_session, org.id)
        assert doc_profile is not None
        assert doc_profile.name == preset
        assert doc_profile.value_tracking_enabled is True
        assert doc_profile.tax_handling == 'SIMPLE_RATE'
        assert doc_profile.default_tax_rate is None

    async def test_declined_country_preset_leaves_the_profiles_preset(
        self,
        real_async_db_session: AsyncSession,
    ):
        from app.modules.warehouse.document_profile_service import (
            get_profile as get_document_profile,
        )

        org = Organization(
            name=f'Test Org {uuid.uuid4().hex[:8]}',
            enabled_modules=['core'],
        )
        real_async_db_session.add(org)
        await real_async_db_session.flush()

        await apply_onboarding_profile_async(
            real_async_db_session, org, 'equipment_wms', country='DE'
        )

        doc_profile = await get_document_profile(real_async_db_session, org.id)
        assert doc_profile is not None
        assert doc_profile.name == 'Full Value'

    async def test_country_preset_of_a_country_without_one_is_ignored(
        self,
        real_async_db_session: AsyncSession,
    ):
        from app.modules.warehouse.document_profile_service import (
            get_profile as get_document_profile,
        )

        org = Organization(
            name=f'Test Org {uuid.uuid4().hex[:8]}',
            enabled_modules=['core'],
        )
        real_async_db_session.add(org)
        await real_async_db_session.flush()

        await apply_onboarding_profile_async(
            real_async_db_session,
            org,
            'equipment_wms',
            country='JP',
            use_country_preset=True,
        )

        doc_profile = await get_document_profile(real_async_db_session, org.id)
        assert doc_profile is not None
        assert doc_profile.name == 'Full Value'

    async def test_the_profile_decides_rather_than_adds(
        self,
        real_async_db_session: AsyncSession,
    ):
        """What the organization had before onboarding does not survive it.

        This assertion used to say the opposite — "modules already enabled
        before onboarding are not dropped" — and that premise is the defect:
        onboarding added the profile to whatever was there, so the answer to
        "what kind of place is this?" was always a union. On a fresh
        organization "whatever was there" was an eight-module ORM default, and
        a household choosing Food & Home was handed the document register its
        profile does not list.

        Onboarding runs once, on an organization that has answered nothing.
        """
        org = Organization(
            name=f'Test Org {uuid.uuid4().hex[:8]}',
            enabled_modules=['core', 'warehouse'],
        )
        real_async_db_session.add(org)
        await real_async_db_session.flush()

        result = await apply_onboarding_profile_async(
            real_async_db_session,
            org,
            'food_home',
            user=await _onboarder(real_async_db_session, org),
        )

        assert 'recipes' in result.enabled_modules
        assert 'warehouse' not in result.enabled_modules

    async def test_equipment_wms_applies_module_config(
        self,
        real_async_db_session: AsyncSession,
    ):
        """equipment_wms must persist its
        declared module_config into the ``module:equipment`` settings
        namespace during onboarding (end-to-end, real registry)."""
        from app.core.public_api import core_api

        org = Organization(
            name=f'Test Org {uuid.uuid4().hex[:8]}',
            enabled_modules=['core'],
        )
        real_async_db_session.add(org)
        await real_async_db_session.flush()

        result = await apply_onboarding_profile_async(
            real_async_db_session, org, 'equipment_wms'
        )

        assert 'equipment' in result.enabled_modules
        settings = await core_api.settings.get_async(
            real_async_db_session, org.id, 'equipment'
        )
        assert settings is not None
        assert settings['warranty_warning_days'] == 60
        assert settings['maintenance_warning_days'] == 14

        # The stats presets are named explicitly on this profile: a warehouse
        # with procurement history is exactly who the value figure is for.
        stats_settings = await core_api.settings.get_async(
            real_async_db_session, org.id, 'stats'
        )
        assert stats_settings is not None
        assert stats_settings['enable_analytics'] is True
        assert stats_settings['show_inventory_value'] is True

    async def test_the_wizard_journals_the_module_settings_it_wrote(
        self,
        real_async_db_session: AsyncSession,
    ):
        """The settings a profile establishes earn the same entry a manual
        settings edit does — the wizard rewrote them and named none."""
        from app.models.audit_log import AuditLog

        org = Organization(
            name=f'Test Org {uuid.uuid4().hex[:8]}',
            enabled_modules=['core'],
        )
        real_async_db_session.add(org)
        await real_async_db_session.flush()

        await apply_onboarding_profile_async(
            real_async_db_session, org, 'equipment_wms'
        )

        rows = (
            await real_async_db_session.scalars(
                select(AuditLog).where(
                    AuditLog.organization_id == org.id,
                    AuditLog.target_type == 'module',
                )
            )
        ).all()
        named = {row.snapshot['name']: row.snapshot for row in rows}
        assert 'equipment' in named, (
            f'the wizard wrote module:equipment settings unjournaled: {rows}'
        )
        assert named['equipment']['subject'] == 'profile:equipment_wms'
        assert named['equipment']['after']['warranty_warning_days'] == 60
        # The profile's stats presets spell the schema defaults a fresh
        # namespace already answers with (analytics on, value on), so that
        # write moved nothing — and the journal records changes, not
        # keystrokes. Two namespaces declared, one entry.
        assert 'stats' not in named

    async def test_food_home_applies_stats_module_config(
        self,
        real_async_db_session: AsyncSession,
    ):
        """Onboarding on the home profile persists the stats
        presets — a profile change alters the behaviour the org runs with
        (analytics off, no inventory-value signal), not only the palette."""
        from app.core.public_api import core_api

        org = Organization(
            name=f'Test Org {uuid.uuid4().hex[:8]}',
            enabled_modules=['core'],
        )
        real_async_db_session.add(org)
        await real_async_db_session.flush()

        result = await apply_onboarding_profile_async(
            real_async_db_session,
            org,
            'food_home',
            user=await _onboarder(real_async_db_session, org),
        )

        assert 'stats' in result.enabled_modules
        stats_settings = await core_api.settings.get_async(
            real_async_db_session, org.id, 'stats'
        )
        assert stats_settings is not None
        assert stats_settings['enable_analytics'] is False
        assert stats_settings['show_inventory_value'] is False

    async def test_equipment_wms_enables_procurement_and_value_tracking(
        self,
        real_async_db_session: AsyncSession,
    ):
        """The Equipment & WMS pack must enable the
        procurement stack (documents, partners, purchase_orders, approvals) so
        a fresh user can run the PO → receipt → stock and approval-threshold
        golden paths without manual Settings configuration. Value
        tracking must be ON via the declared document_preset."""
        from app.modules.warehouse.document_profile_service import (
            get_profile as get_document_profile,
        )

        org = Organization(
            name=f'Test Org {uuid.uuid4().hex[:8]}',
            enabled_modules=['core'],
        )
        real_async_db_session.add(org)
        await real_async_db_session.flush()

        result = await apply_onboarding_profile_async(
            real_async_db_session, org, 'equipment_wms'
        )

        # Procurement stack enabled.
        for module in (
            'warehouse',
            'partners',
            'purchase_orders',
            'approvals',
        ):
            assert module in result.enabled_modules, (
                f'equipment_wms must enable {module!r} for the WMS golden path'
            )

        # Value tracking ON (audit: was False — fresh user saw no amounts).
        doc_profile = await get_document_profile(real_async_db_session, org.id)
        assert doc_profile is not None
        assert doc_profile.value_tracking_enabled is True


@pytest.mark.asyncio
class TestOnboardingSelection:
    """The second onboarding step: what the reader ticked and unticked.

    A profile is a starting point, not a verdict. The reader can drop what
    their kind of place does not need — an equipment register, a document
    trail — and pick up what no profile enables, which is how 'maker',
    'api_keys' and 'webhooks' become reachable without a trip to Settings.

    Unticking is safe here and nowhere else: onboarding runs on an empty
    organization, so there is no data to strand and no disable hook owed.
    """

    @staticmethod
    async def _fresh_org(db: AsyncSession) -> Organization:
        org = Organization(
            name=f'Test Org {uuid.uuid4().hex[:8]}',
            enabled_modules=['core'],
        )
        db.add(org)
        await db.flush()
        return org

    async def test_no_selection_still_means_the_whole_preset(
        self,
        real_async_db_session: AsyncSession,
    ):
        """Skipping the step, or an older client that does not send one, must
        land exactly where onboarding landed before it existed."""
        org = await self._fresh_org(real_async_db_session)

        result = await apply_onboarding_profile_async(
            real_async_db_session,
            org,
            'food_home',
            modules=None,
            user=await _onboarder(real_async_db_session, org),
        )

        assert 'recipes' in result.enabled_modules
        assert 'nutrition' in result.enabled_modules

    async def test_what_the_reader_unticked_is_not_enabled(
        self,
        real_async_db_session: AsyncSession,
    ):
        """Equipment & WMS bundles an asset register with a document trail
        and a sign-off chain. Someone running a warehouse of ordinary goods
        needs neither, and should not have to go and switch them off after
        the fact."""
        org = await self._fresh_org(real_async_db_session)

        result = await apply_onboarding_profile_async(
            real_async_db_session,
            org,
            'equipment_wms',
            modules=['equipment', 'stock_takes'],
        )

        assert 'equipment' in result.enabled_modules
        assert 'warehouse' not in result.enabled_modules
        assert 'approvals' not in result.enabled_modules

    async def test_the_seven_pinned_modules_survive_an_empty_selection(
        self,
        real_async_db_session: AsyncSession,
    ):
        """Unticking everything is a legitimate answer; shipping an
        organization with no inventory at all is not."""
        from app.core.module_safety import ALWAYS_ON_MODULES

        org = await self._fresh_org(real_async_db_session)

        result = await apply_onboarding_profile_async(
            real_async_db_session,
            org,
            'clean_core',
            modules=[],
            user=await _onboarder(real_async_db_session, org),
        )

        assert ALWAYS_ON_MODULES <= set(result.enabled_modules)

    async def test_a_module_outside_the_offer_is_refused(
        self,
        real_async_db_session: AsyncSession,
    ):
        """The offer is the contract. Without this a client could enable any
        module by naming it — including a premium one nobody unlocked, and
        the document register Food & Home exists to keep out."""
        from app.core.exceptions import ValidationException

        org = await self._fresh_org(real_async_db_session)

        with pytest.raises(ValidationException):
            await apply_onboarding_profile_async(
                real_async_db_session,
                org,
                'food_home',
                modules=['recipes', 'warehouse'],
            )


@pytest.mark.asyncio
class TestOnboardingKeepsManualToggles:
    """A module the admin switched on before answering the profile question
    survives the answer.

    Onboarding used to overwrite ``enabled_modules`` with the profile's
    chosen set, so a module enabled through POST /modules/toggle before
    'Get started' was dropped without its disable hook and without a word.
    The toggle path records the explicit choice on the organization while
    onboarding stands open; onboarding keeps it.
    """

    @staticmethod
    async def _fresh_org(db: AsyncSession) -> Organization:
        org = Organization(
            name=f'Test Org {uuid.uuid4().hex[:8]}',
            enabled_modules=['core'],
        )
        db.add(org)
        await db.flush()
        return org

    async def test_a_module_toggled_on_before_onboarding_survives_it(
        self,
        real_async_db_session: AsyncSession,
    ):
        """The toggle path recorded 'warehouse'; Food & Home does not offer
        it. The admin's explicit choice is kept, not dropped — and the
        record is consumed, because onboarding runs once. Fails on dev,
        where the chosen set overwrites the list and only the log mourns."""
        org = await self._fresh_org(real_async_db_session)
        org.pre_onboarding_manual_modules = ['warehouse']

        result = await apply_onboarding_profile_async(
            real_async_db_session,
            org,
            'food_home',
            user=await _onboarder(real_async_db_session, org),
        )

        assert 'warehouse' in result.enabled_modules
        assert result.pre_onboarding_manual_modules is None

    async def test_a_manual_toggle_switched_back_off_stays_off(
        self,
        real_async_db_session: AsyncSession,
    ):
        """The admin who toggles a module on and then off before onboarding
        has answered; nothing of the exchange survives, and the profile's
        set stands alone."""
        org = await self._fresh_org(real_async_db_session)
        org.pre_onboarding_manual_modules = []

        result = await apply_onboarding_profile_async(
            real_async_db_session,
            org,
            'food_home',
            user=await _onboarder(real_async_db_session, org),
        )

        assert 'warehouse' not in result.enabled_modules

    async def test_no_manual_toggles_end_exactly_on_the_profiles_set(
        self,
        real_async_db_session: AsyncSession,
    ):
        """An organization that toggled nothing lands on exactly the
        profile's chosen set — the 'Food & Home receives the document
        register' regression must not return through the keeping."""
        from app.core.product_profiles import get_profile
        from app.services.onboarding_service import _chosen_modules

        org = await self._fresh_org(real_async_db_session)

        result = await apply_onboarding_profile_async(
            real_async_db_session,
            org,
            'food_home',
            user=await _onboarder(real_async_db_session, org),
        )

        expected = _chosen_modules(get_profile('food_home'), None)
        assert set(result.enabled_modules) == set(expected)
        assert 'warehouse' not in result.enabled_modules


@pytest.mark.asyncio
class TestTheCountryAnswersWhereTheProfileDoesNot:
    """Onboarding composes the document profile from two sources: the work
    profile provides the shape, the organization's country provides the law.

    The composition is a resolution at read time, not a write: the preset
    pins no rate and no tax-id requirement (its ``None`` means "no
    opinion"), so a country change later moves with the organization
    instead of freezing the value the day it was onboarded — the same shape
    ``default_currency`` already has against the organization currency.
    """

    async def test_the_preset_leaves_the_numbers_to_the_country(
        self,
        real_async_db_session: AsyncSession,
    ) -> None:
        """Fails on dev: the profile carries no country wiring at all, so
        the resolved rate is None and the resolved requirement is the
        preset's pinned False."""
        from decimal import Decimal

        from app.modules.warehouse.document_profile_service import (
            get_profile,
            resolve_document_tax_rate,
            resolve_partner_tax_id_required,
        )

        org = Organization(
            name=f'Test Org {uuid.uuid4().hex[:8]}',
            enabled_modules=['core'],
            country='PL',
        )
        real_async_db_session.add(org)
        await real_async_db_session.flush()

        await apply_onboarding_profile_async(
            real_async_db_session,
            org,
            'equipment_wms',
            user=await _onboarder(real_async_db_session, org),
        )

        profile = await get_profile(real_async_db_session, org.id)
        assert profile is not None

        # The profile states no opinion on either legal axis ...
        assert profile.default_tax_rate is None
        assert profile.require_partner_tax_id is None
        # ... and the country answers both.
        assert await resolve_document_tax_rate(
            real_async_db_session, org.id, profile
        ) == Decimal('23.00')
        assert (
            await resolve_partner_tax_id_required(
                real_async_db_session, org.id, profile
            )
            is True
        )

    @pytest.mark.parametrize(
        ('country', 'rate'), [('PL', '23.00'), ('DE', '19.00'), ('GB', '20.00')]
    )
    async def test_the_country_given_at_onboarding_decides_the_rate(
        self,
        country: str,
        rate: str,
        real_async_db_session: AsyncSession,
    ) -> None:
        """An organization registered with no country, onboarded with one,
        applies that country's rate and partner rule without a visit to
        Settings. Fails without the fix: ``country`` is not a parameter, and
        the organization keeps no country and so no rate."""
        from decimal import Decimal

        from app.modules.warehouse.document_profile_service import (
            get_profile,
            resolve_document_tax_rate,
            resolve_partner_tax_id_required,
        )

        org = Organization(
            name=f'Test Org {uuid.uuid4().hex[:8]}', enabled_modules=['core']
        )
        real_async_db_session.add(org)
        await real_async_db_session.flush()
        assert org.country is None

        await apply_onboarding_profile_async(
            real_async_db_session,
            org,
            'equipment_wms',
            user=await _onboarder(real_async_db_session, org),
            country=country,
        )

        assert org.country == country
        profile = await get_profile(real_async_db_session, org.id)
        assert profile is not None
        assert await resolve_document_tax_rate(
            real_async_db_session, org.id, profile
        ) == Decimal(rate)
        assert await resolve_partner_tax_id_required(
            real_async_db_session, org.id, profile
        ) is (country == 'PL')


@pytest.mark.asyncio
class TestOnboardingNamesTheOrganization:
    """The founder's own name for the organization is the one it keeps."""

    async def _fresh_org(self, session: AsyncSession) -> Organization:
        org = Organization(name="Jan Kowalski's Organization", enabled_modules=['core'])
        session.add(org)
        await session.flush()
        return org

    async def test_the_given_name_replaces_the_derived_one(
        self, real_async_db_session: AsyncSession
    ):
        org = await self._fresh_org(real_async_db_session)

        result = await apply_onboarding_profile_async(
            real_async_db_session,
            org,
            'food_home',
            user=await _onboarder(real_async_db_session, org),
            organization_name='Kowalski Bakery',
        )

        assert result.name == 'Kowalski Bakery'

    async def test_without_a_name_the_derived_one_stands(
        self, real_async_db_session: AsyncSession
    ):
        org = await self._fresh_org(real_async_db_session)

        result = await apply_onboarding_profile_async(
            real_async_db_session,
            org,
            'food_home',
            user=await _onboarder(real_async_db_session, org),
        )

        assert result.name == "Jan Kowalski's Organization"

"""
Lock-before-change smoke tests for the seed_profiles system.

These tests lock the CURRENT seed data behavior so that any accidental
regression is immediately visible.

Current behavior (after the storage types were made neutral):
- seed_neutral_storage_types (base) creates: SHELF, STORAGE_ROOM, SYSTEM.
- seed_food_storage_types creates: FREEZER, FRIDGE, PANTRY, MEDICINE_CABINET.
 Both are owned by an organization since, so the storage-type tests
  take ``async_test_household`` — the fixture that seeds them for one.
- Combined: FREEZER, FRIDGE, PANTRY, MEDICINE_CABINET, SHELF, STORAGE_ROOM, SYSTEM.
- FREEZER → FREEZING, FRIDGE → EXPIRY, PANTRY → EXPIRY.
- Each system storage type has is_system=True.
- Each relevant type has the expected categories seeded.
- All seed functions are idempotent (running twice doesn't create duplicates).
- Storage types' `context_schema` contains ONLY neutral base
  keys (no `freeze_date`, `expiry_date`, `brand`, `production_date`).
  Vertical-specific fields live on Category.field_definitions.
"""

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.category import Category
from app.models.storage_type import StorageType
from app.seed_profiles._food_home_categories import seed_food_categories
from app.seed_profiles._food_home_storage_types import seed_food_storage_types
from app.seed_profiles.base import seed_neutral_storage_types


@pytest.mark.integration
@pytest.mark.asyncio
class TestSeedData:
    """Lock current seed data shape."""

    async def test_seed_creates_system_storage_types(
        self, real_async_db_session: AsyncSession, async_test_household
    ):
        """Lock: seed creates the expected system storage types.

        The db_session fixture already seeds all storage types, so we just
        verify the expected rows exist.
        """
        system_types = (
            await real_async_db_session.scalars(
                select(StorageType).where(StorageType.is_system.is_(True))
            )
        ).all()
        type_codes = {st.type_code for st in system_types}

        expected = {
            'FREEZER',
            'FRIDGE',
            'PANTRY',
            'MEDICINE_CABINET',
            'SHELF',
            'STORAGE_ROOM',
            'SYSTEM',
        }
        assert expected.issubset(type_codes), (
            f'Missing system storage types: {expected - type_codes}'
        )

    async def test_seed_storage_types_have_expected_behavior_modes(
        self, real_async_db_session: AsyncSession, async_test_household
    ):
        """Lock: FREEZER→FREEZING, FRIDGE→EXPIRY, PANTRY→EXPIRY, SHELF→STOCK, SYSTEM→NONE."""
        expected_modes = {
            'FREEZER': 'FREEZING',
            'FRIDGE': 'EXPIRY',
            'PANTRY': 'EXPIRY',
            'MEDICINE_CABINET': 'EXPIRY',
            'SHELF': 'STOCK',
            'STORAGE_ROOM': 'STOCK',
            'SYSTEM': 'NONE',
        }

        for type_code, expected_mode in expected_modes.items():
            st = (
                await real_async_db_session.scalars(
                    select(StorageType).where(StorageType.type_code == type_code)
                )
            ).first()
            assert st is not None, f'Missing storage type: {type_code}'
            assert st.behavior_mode == expected_mode, (
                f'{type_code}: expected behavior_mode={expected_mode!r}, '
                f'got {st.behavior_mode!r}'
            )

    async def test_seed_storage_types_are_all_system(
        self, real_async_db_session: AsyncSession, async_test_household
    ):
        """Lock: all seed storage types have is_system=True."""
        system_codes = {
            'FREEZER',
            'FRIDGE',
            'PANTRY',
            'MEDICINE_CABINET',
            'SHELF',
            'STORAGE_ROOM',
            'SYSTEM',
        }

        for code in system_codes:
            st = (
                await real_async_db_session.scalars(
                    select(StorageType).where(StorageType.type_code == code)
                )
            ).first()
            assert st is not None, f'Missing: {code}'
            assert st.is_system is True, f'{code} should have is_system=True'

    async def test_seed_creates_categories_for_freezer(
        self, real_async_db_session: AsyncSession
    ):
        """Lock: seed creates categories grouped as 'FREEZER'.

        The group used to arrive in a read-only column, so the screen filed
        those rows under a group its own form could not show, let alone
        rename. It is a label the organisation owns now.
        """
        freezer_categories = (
            await real_async_db_session.scalars(
                select(Category).where(Category.group_label == 'FREEZER')
            )
        ).all()

        assert len(freezer_categories) > 0, 'No FREEZER categories in seed data'

        category_codes = {c.code for c in freezer_categories}
        expected_codes = {'pork', 'beef', 'poultry'}
        assert expected_codes.issubset(category_codes), (
            f'Missing FREEZER categories: {expected_codes - category_codes}'
        )

    async def test_seed_creates_categories_for_fridge(
        self, real_async_db_session: AsyncSession
    ):
        """Lock: seed creates categories grouped as 'FRIDGE'.

        The group used to arrive in a read-only column, so the screen filed
        those rows under a group its own form could not show, let alone
        rename. It is a label the organisation owns now.
        """
        fridge_categories = (
            await real_async_db_session.scalars(
                select(Category).where(Category.group_label == 'FRIDGE')
            )
        ).all()

        assert len(fridge_categories) > 0, 'No FRIDGE categories in seed data'

    async def test_seed_creates_categories_for_pantry(
        self, real_async_db_session: AsyncSession
    ):
        """Lock: seed creates categories grouped as 'PANTRY'.

        The group used to arrive in a read-only column, so the screen filed
        those rows under a group its own form could not show, let alone
        rename. It is a label the organisation owns now.
        """
        pantry_categories = (
            await real_async_db_session.scalars(
                select(Category).where(Category.group_label == 'PANTRY')
            )
        ).all()

        assert len(pantry_categories) > 0, 'No PANTRY categories in seed data'

    async def test_seed_keeps_bulk_packaging_out_of_the_convertible_set(
        self, real_async_db_session: AsyncSession
    ):
        """Bulk packaging is a label, not a share of the piece's dimension.

        ``pack``, ``can``, ``bottle``, ``box`` and ``bag`` used to sit beside
        ``pcs`` in the Unit category at factor 1.0, so "100 pack → 100 pcs"
        came back as a successful conversion — stated with total confidence,
        though no unit table can know how many pieces a pack holds. That
        ratio belongs to the product (Odoo's ``product.packaging``, which
        this app does not model yet). Until it does, each packaging unit
        forms its own single-unit category, so the category rule — the one
        gate every conversion path reads — refuses pack↔pcs instead of
        quietly equating it.
        """
        from decimal import Decimal

        from app.models.uom import Uom, UomCategory
        from app.services.uom_service import convert_quantity

        unit_category = await real_async_db_session.scalar(
            select(UomCategory).where(UomCategory.name == 'Unit')
        )
        assert unit_category is not None
        unit_uoms = (
            await real_async_db_session.scalars(
                select(Uom).where(Uom.category_id == unit_category.id)
            )
        ).all()
        # Counted pieces stay the whole Unit category, still never divided.
        assert {u.symbol for u in unit_uoms} == {'pcs'}
        for unit in unit_uoms:
            assert unit.rounding == 1.0, f'{unit.name} rounds to {unit.rounding}'

        packaging: dict[str, Uom] = {}
        for symbol in ('pack', 'can', 'bottle', 'box', 'bag'):
            uom = await real_async_db_session.scalar(
                select(Uom).where(Uom.symbol == symbol, Uom.organization_id.is_(None))
            )
            assert uom is not None, f'{symbol} missing from the seed'
            category = await real_async_db_session.scalar(
                select(UomCategory).where(UomCategory.id == uom.category_id)
            )
            assert category is not None
            assert category.name not in ('Unit', 'Weight', 'Volume', 'Length'), (
                f'{symbol} still shares a category with convertible units'
            )
            siblings = (
                await real_async_db_session.scalars(
                    select(Uom).where(Uom.category_id == category.id)
                )
            ).all()
            assert len(siblings) == 1, f'{category.name} holds a foreign unit'
            assert uom.is_reference is True
            assert uom.rounding == 1.0
            packaging[symbol] = uom

        pcs = next(u for u in unit_uoms if u.symbol == 'pcs')
        converted, ok = convert_quantity(Decimal('100'), packaging['pack'], pcs)
        assert ok is False, 'pack must refuse to become pieces'
        assert converted == Decimal('100')
        back, ok = convert_quantity(Decimal('50'), pcs, packaging['box'])
        assert ok is False, 'pieces must refuse to become boxes'
        assert back == Decimal('50')

    async def test_seed_puts_the_length_reference_on_the_unit_scaled_to_one(
        self, real_async_db_session: AsyncSession
    ):
        """The reference unit is the one whose factor is 1.0, by definition.

        Length stated its factors in centimetres and flagged Meter. Every
        conversion is a ratio so nothing computed wrongly, but the catalogue
        described itself incorrectly — and it was the only category where the
        flag and the scale disagreed.
        """
        from app.models.uom import Uom, UomCategory

        length = (
            await real_async_db_session.scalars(
                select(Uom)
                .join(UomCategory, UomCategory.id == Uom.category_id)
                .where(UomCategory.name == 'Length')
            )
        ).all()

        references = [u for u in length if u.is_reference]
        assert len(references) == 1
        assert references[0].factor == 1.0

    async def test_seed_storage_types_is_idempotent(
        self, real_async_db_session: AsyncSession, async_test_household
    ):
        """Lock: running storage type seeders twice doesn't create duplicates."""
        org_id = async_test_household.id
        before_count = await real_async_db_session.scalar(
            select(func.count(StorageType.id)).where(StorageType.is_system.is_(True))
        )

        await real_async_db_session.run_sync(
            lambda s: seed_neutral_storage_types(s, organization_id=org_id)
        )
        await real_async_db_session.run_sync(
            lambda s: seed_food_storage_types(s, organization_id=org_id)
        )

        after_count = await real_async_db_session.scalar(
            select(func.count(StorageType.id)).where(StorageType.is_system.is_(True))
        )

        assert after_count == before_count, (
            f'storage type seeders are not idempotent: '
            f'before={before_count}, after={after_count}'
        )

    async def test_seed_categories_is_idempotent(
        self, real_async_db_session: AsyncSession
    ):
        """Lock: running seed_food_categories twice doesn't create duplicates."""
        before_count = await real_async_db_session.scalar(
            select(func.count(Category.id))
        )

        await real_async_db_session.run_sync(lambda s: seed_food_categories(s))

        after_count = await real_async_db_session.scalar(
            select(func.count(Category.id))
        )

        assert after_count == before_count, (
            f'seed_food_categories is not idempotent: '
            f'before={before_count}, after={after_count}'
        )

    async def test_seed_freezer_context_schema_is_neutral(
        self, real_async_db_session: AsyncSession, async_test_household
    ):
        """FREEZER storage type context_schema contains only neutral keys.

        freeze_date moves to category field_definitions. Storage
        context_schema must be vertical-agnostic — same keys as FRIDGE/PANTRY.
        """
        freezer = (
            await real_async_db_session.scalars(
                select(StorageType).where(StorageType.type_code == 'FREEZER')
            )
        ).first()

        assert freezer is not None
        forbidden = {'freeze_date', 'expiry_date', 'production_date', 'brand'}
        actual = set(freezer.context_schema or [])
        assert actual.isdisjoint(forbidden), (
            f'FREEZER context_schema has food-biased keys: '
            f'{actual & forbidden} (full: {actual})'
        )

    async def test_seed_fridge_context_schema_is_neutral(
        self, real_async_db_session: AsyncSession, async_test_household
    ):
        """FRIDGE storage type context_schema contains only neutral keys.

        expiry_date stays as an Item column (Core, 3-vertical test passes),
        but it is no longer a storage toggle — verticals come from category.
        """
        fridge = (
            await real_async_db_session.scalars(
                select(StorageType).where(StorageType.type_code == 'FRIDGE')
            )
        ).first()

        assert fridge is not None
        forbidden = {'freeze_date', 'expiry_date', 'production_date', 'brand'}
        actual = set(fridge.context_schema or [])
        assert actual.isdisjoint(forbidden), (
            f'FRIDGE context_schema has food-biased keys: '
            f'{actual & forbidden} (full: {actual})'
        )

    async def test_seed_pantry_context_schema_is_neutral(
        self, real_async_db_session: AsyncSession, async_test_household
    ):
        """PANTRY storage type context_schema contains only neutral keys."""
        pantry = (
            await real_async_db_session.scalars(
                select(StorageType).where(StorageType.type_code == 'PANTRY')
            )
        ).first()

        assert pantry is not None
        forbidden = {'freeze_date', 'expiry_date', 'production_date', 'brand'}
        actual = set(pantry.context_schema or [])
        assert actual.isdisjoint(forbidden), (
            f'PANTRY context_schema has food-biased keys: '
            f'{actual & forbidden} (full: {actual})'
        )

    async def test_seed_medicine_cabinet_context_schema_is_neutral(
        self, real_async_db_session: AsyncSession, async_test_household
    ):
        """MEDICINE_CABINET context_schema contains only neutral keys."""
        cabinet = (
            await real_async_db_session.scalars(
                select(StorageType).where(StorageType.type_code == 'MEDICINE_CABINET')
            )
        ).first()

        assert cabinet is not None
        forbidden = {'freeze_date', 'expiry_date', 'production_date', 'brand'}
        actual = set(cabinet.context_schema or [])
        assert actual.isdisjoint(forbidden), (
            f'MEDICINE_CABINET context_schema has food-biased keys: '
            f'{actual & forbidden} (full: {actual})'
        )

    async def test_seed_all_food_storage_types_share_neutral_schema(
        self, real_async_db_session: AsyncSession, async_test_household
    ):
        """All food storage types have identical neutral context_schema.

        This is the strongest 'storage is vertical-agnostic' invariant:
        FREEZER, FRIDGE, PANTRY, MEDICINE_CABINET must all expose the same
        set of toggles. Vertical behaviour comes from Category.field_definitions
        on the assigned item, not from the storage type.
        """
        codes = ['FREEZER', 'FRIDGE', 'PANTRY', 'MEDICINE_CABINET']
        schemas: dict[str, set[str]] = {}
        for code in codes:
            st = (
                await real_async_db_session.scalars(
                    select(StorageType).where(StorageType.type_code == code)
                )
            ).first()
            assert st is not None, f'Missing storage type: {code}'
            schemas[code] = set(st.context_schema or [])

        first = next(iter(schemas.values()))
        for code, schema in schemas.items():
            assert schema == first, (
                f'{code} context_schema differs from others: '
                f'{schema} vs {first} ({schemas})'
            )

    # ── freeze_date moved from storage to category ──────────────────────────

    async def test_seed_user_frozen_categories_have_freeze_date(
        self, real_async_db_session: AsyncSession
    ):
        """Categories the user typically freezes at home get freeze_date.

        freeze_date moves from FREEZER storage's context_schema to
        category field_definitions for items the user actually freezes.
        """
        user_frozen_codes = {'pork', 'beef', 'poultry', 'fish', 'seafood'}
        for code in user_frozen_codes:
            cat = (
                await real_async_db_session.scalars(
                    select(Category).where(Category.code == code)
                )
            ).first()
            assert cat is not None, f'Missing category: {code}'
            keys = {fd.get('key') for fd in (cat.field_definitions or [])}
            assert 'freeze_date' in keys, (
                f'{code} should have freeze_date in field_definitions '
                f'(user-frozen category), got keys: {keys}'
            )

    async def test_seed_pre_frozen_categories_lack_freeze_date(
        self, real_async_db_session: AsyncSession
    ):
        """Pre-frozen categories (ice cream, frozen meals, …) must NOT have freeze_date.

        These items are already frozen at production; tracking freeze_date
        on the user's side would be redundant noise.
        """
        pre_frozen_codes = {
            'frozen_meals',
            'frozen_vegetables',
            'frozen_fruits',
            'ice_cream',
            'frozen_pizza',
        }
        for code in pre_frozen_codes:
            cat = (
                await real_async_db_session.scalars(
                    select(Category).where(Category.code == code)
                )
            ).first()
            assert cat is not None, f'Missing category: {code}'
            keys = {fd.get('key') for fd in (cat.field_definitions or [])}
            assert 'freeze_date' not in keys, (
                f'{code} should NOT have freeze_date (pre-frozen category), '
                f'got keys: {keys}'
            )

    async def test_seed_fridge_and_pantry_categories_lack_freeze_date(
        self, real_async_db_session: AsyncSession
    ):
        """Fridge/pantry items never get freeze_date."""
        non_freezer_codes = {
            'dairy',
            'cheese',
            'deli',
            'eggs',
            'fresh_vegetables',
            'fresh_fruits',
            'drinks',
            'sauces',
            'fresh_meat',
            'fresh_meals',
            'dry_products',
            'pasta',
            'rice_grains',
            'canned_goods',
            'spices_herbs',
            'oils_vinegars',
            'flours_sugars',
            'snacks',
            'sweets',
            'beverages',
            'tea_coffee',
            'cans_jars',
        }
        for code in non_freezer_codes:
            cat = (
                await real_async_db_session.scalars(
                    select(Category).where(Category.code == code)
                )
            ).first()
            assert cat is not None, f'Missing category: {code}'
            keys = {fd.get('key') for fd in (cat.field_definitions or [])}
            assert 'freeze_date' not in keys, (
                f'{code} (non-freezer category) should NOT have freeze_date, '
                f'got keys: {keys}'
            )

    async def test_seed_freeze_date_field_definition_has_correct_type(
        self, real_async_db_session: AsyncSession
    ):
        """freeze_date on a category must be a date field, visible, optional."""
        pork = (
            await real_async_db_session.scalars(
                select(Category).where(Category.code == 'pork')
            )
        ).first()
        assert pork is not None
        freeze_def = next(
            (
                fd
                for fd in (pork.field_definitions or [])
                if fd.get('key') == 'freeze_date'
            ),
            None,
        )
        assert freeze_def is not None, 'pork missing freeze_date'
        assert freeze_def.get('type') == 'date', (
            f"freeze_date type must be 'date', got {freeze_def.get('type')!r}"
        )
        # Contract: vertical fields are optional, not required —
        # the user can leave freeze_date blank if irrelevant.
        assert freeze_def.get('required', False) is False, (
            'freeze_date must not be required (vertical fields are optional)'
        )


@pytest.mark.integration
@pytest.mark.asyncio
class TestNeutralSeedHasNoUsKitchenUnits:
    """The neutral base seed must not carry one vertical's kitchen measures.

    ``seed_uom`` lives in the profile described as "neutral, vertical-agnostic
    defaults", yet it seeded cup/pint/quart/gallon/fl-oz — so a workspace in
    the neutral mode picked its default unit between pieces, kilograms and
    teacups. Those five units belong to the food profile's seed; existing
    installations keep their rows (``uoms`` has no owner column and is
    referenced by items, so nothing is deleted anywhere).
    """

    _US_KITCHEN = {'Cup (US)', 'Pint (US)', 'Quart (US)', 'Gallon (US)', 'Fluid Ounce'}

    async def test_base_seed_omits_us_kitchen_units(
        self, real_async_db_session: AsyncSession
    ):
        from sqlalchemy import text

        from app.models.uom import Uom
        from app.seed_profiles.base import seed_uom

        await real_async_db_session.execute(
            text('TRUNCATE uoms, uom_categories CASCADE')
        )
        await real_async_db_session.commit()

        await real_async_db_session.run_sync(lambda s: seed_uom(s))

        names = {
            u.name for u in (await real_async_db_session.scalars(select(Uom))).all()
        }
        assert names.isdisjoint(self._US_KITCHEN), (
            f'neutral seed still creates kitchen units: {names & self._US_KITCHEN}'
        )
        # The neutral catalogue itself must stay intact.
        assert {'Gram', 'Kilogram', 'Milliliter', 'Liter', 'Piece'} <= names

    async def test_food_profile_seed_includes_us_kitchen_units(
        self, real_async_db_session: AsyncSession, async_test_household
    ):
        from sqlalchemy import text

        from app.models.uom import Uom
        from app.seed_profiles.food_home import seed_food_home

        await real_async_db_session.execute(
            text('TRUNCATE uoms, uom_categories CASCADE')
        )
        await real_async_db_session.commit()

        await real_async_db_session.run_sync(
            lambda s: seed_food_home(s, organization_id=async_test_household.id)
        )

        names = {
            u.name for u in (await real_async_db_session.scalars(select(Uom))).all()
        }
        assert self._US_KITCHEN <= names, (
            f'food profile lost its kitchen units: {self._US_KITCHEN - names}'
        )

"""Tests for Tier 2 CoreAPI extensions on items + product_templates.

Covers the operational extensions added to replace the
recipes-module escape hatches:

- ``core_api.items.list_by_expiry_async`` — FEFO picking order
- ``core_api.items.list_with_template_async`` — batch by template_id
- ``core_api.items.find_by_barcode_async`` — barcode lookup with eager loads
- ``core_api.product_templates.search_fuzzy_async`` — ILIKE fuzzy match
- ``core_api.product_templates.get_with_uom_async`` — template + weight_uom

Contract:
- Org-scoped (data from other orgs never leaks).
- Read-only (no commit/add/delete).
- Returns typed DTOs.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.public_api import core_api
from app.models.item import Item
from app.models.product_template import ProductTemplate
from tests.integration._shelf import anchor_pending_records

pytestmark = pytest.mark.integration


async def _make_template(
    db: AsyncSession,
    org_id,
    *,
    name: str = 'Tpl',
    barcode: str | None = None,
    sku: str | None = None,
    weight_value: Decimal | None = None,
    weight_uom_id=None,
) -> ProductTemplate:
    tpl = ProductTemplate(
        organization_id=org_id,
        name=name,
        barcode=barcode,
        sku=sku,
        weight_value=weight_value,
        weight_uom_id=weight_uom_id,
    )
    db.add(tpl)
    await db.flush()
    await db.refresh(tpl)
    return tpl


async def _make_item(
    db: AsyncSession,
    org_id,
    storage_id,
    *,
    name: str = 'Item',
    quantity: Decimal = Decimal('5'),
    expiry_date: date | None = None,
    template_id=None,
    barcode: str | None = None,
    is_deleted: bool = False,
) -> Item:
    item = Item(
        organization_id=org_id,
        storage_location_id=storage_id,
        name=name,
        quantity=quantity,
        expiry_date=expiry_date,
        template_id=template_id,
        barcode=barcode,
        is_deleted=is_deleted,
    )
    db.add(item)
    await db.run_sync(anchor_pending_records)
    await db.flush()
    return item


@pytest.mark.asyncio
class TestCoreItemsListByExpiry:
    """`core_api.items.list_by_expiry_async`."""

    async def test_empty_org_returns_empty(
        self, real_async_db_session: AsyncSession, async_test_storage_location
    ):
        db = real_async_db_session
        result = await core_api.items.list_by_expiry_async(
            db, async_test_storage_location.organization_id
        )
        assert result == []

    async def test_orders_by_expiry_asc(
        self, real_async_db_session: AsyncSession, async_test_storage_location
    ):
        """Earliest expiry comes first (FEFO)."""
        db = real_async_db_session
        org_id = async_test_storage_location.organization_id
        loc_id = async_test_storage_location.id
        today = date.today()
        await _make_item(
            db, org_id, loc_id, name='Later', expiry_date=today + timedelta(days=30)
        )
        await _make_item(
            db, org_id, loc_id, name='Sooner', expiry_date=today + timedelta(days=2)
        )
        await _make_item(
            db, org_id, loc_id, name='Middle', expiry_date=today + timedelta(days=10)
        )
        await db.commit()

        result = await core_api.items.list_by_expiry_async(db, org_id)
        names = [item.name for item in result]
        assert names == ['Sooner', 'Middle', 'Later']

    async def test_desc_order_reverses(
        self, real_async_db_session: AsyncSession, async_test_storage_location
    ):
        db = real_async_db_session
        org_id = async_test_storage_location.organization_id
        loc_id = async_test_storage_location.id
        today = date.today()
        await _make_item(
            db, org_id, loc_id, name='Later', expiry_date=today + timedelta(days=30)
        )
        await _make_item(
            db, org_id, loc_id, name='Sooner', expiry_date=today + timedelta(days=2)
        )
        await db.commit()

        result = await core_api.items.list_by_expiry_async(db, org_id, order='desc')
        assert [item.name for item in result] == ['Later', 'Sooner']

    async def test_filters_by_template(
        self, real_async_db_session: AsyncSession, async_test_storage_location
    ):
        db = real_async_db_session
        org_id = async_test_storage_location.organization_id
        loc_id = async_test_storage_location.id
        tpl_a = await _make_template(db, org_id, name='A')
        tpl_b = await _make_template(db, org_id, name='B')
        today = date.today()
        await _make_item(
            db,
            org_id,
            loc_id,
            name='A1',
            expiry_date=today,
            template_id=tpl_a.id,
        )
        await _make_item(
            db,
            org_id,
            loc_id,
            name='B1',
            expiry_date=today,
            template_id=tpl_b.id,
        )
        await db.commit()

        result = await core_api.items.list_by_expiry_async(
            db, org_id, template_ids=[tpl_a.id]
        )
        assert [item.name for item in result] == ['A1']

    async def test_excludes_deleted_and_zero_qty(
        self, real_async_db_session: AsyncSession, async_test_storage_location
    ):
        db = real_async_db_session
        org_id = async_test_storage_location.organization_id
        loc_id = async_test_storage_location.id
        today = date.today()
        await _make_item(
            db,
            org_id,
            loc_id,
            name='Active',
            expiry_date=today,
            quantity=Decimal('3'),
        )
        await _make_item(
            db,
            org_id,
            loc_id,
            name='Deleted',
            expiry_date=today,
            quantity=Decimal('3'),
            is_deleted=True,
        )
        await _make_item(
            db,
            org_id,
            loc_id,
            name='Empty',
            expiry_date=today,
            quantity=Decimal('0'),
        )
        await db.commit()

        result = await core_api.items.list_by_expiry_async(db, org_id)
        assert [item.name for item in result] == ['Active']

    async def test_org_scoping(
        self, real_async_db_session: AsyncSession, async_test_storage_location
    ):
        """Items from another org are never visible."""
        db = real_async_db_session
        org_a = async_test_storage_location.organization_id
        today = date.today()
        await _make_item(
            db, org_a, async_test_storage_location.id, name='A', expiry_date=today
        )
        await db.commit()

        result = await core_api.items.list_by_expiry_async(db, uuid4())
        assert result == []


@pytest.mark.asyncio
class TestCoreItemsListWithTemplate:
    """`core_api.items.list_with_template_async`."""

    async def test_returns_grouped_dict(
        self, real_async_db_session: AsyncSession, async_test_storage_location
    ):
        db = real_async_db_session
        org_id = async_test_storage_location.organization_id
        loc_id = async_test_storage_location.id
        tpl_a = await _make_template(db, org_id, name='A')
        tpl_b = await _make_template(db, org_id, name='B')
        await _make_item(db, org_id, loc_id, name='A1', template_id=tpl_a.id)
        await _make_item(db, org_id, loc_id, name='A2', template_id=tpl_a.id)
        await _make_item(db, org_id, loc_id, name='B1', template_id=tpl_b.id)
        await db.commit()

        result = await core_api.items.list_with_template_async(
            db, org_id, [tpl_a.id, tpl_b.id]
        )
        assert set(result.keys()) == {tpl_a.id, tpl_b.id}
        assert {i.name for i in result[tpl_a.id]} == {'A1', 'A2'}
        assert {i.name for i in result[tpl_b.id]} == {'B1'}

    async def test_empty_template_ids_returns_empty(
        self, real_async_db_session: AsyncSession, async_test_storage_location
    ):
        db = real_async_db_session
        result = await core_api.items.list_with_template_async(
            db, async_test_storage_location.organization_id, []
        )
        assert result == {}

    async def test_unknown_template_returns_empty_list(
        self, real_async_db_session: AsyncSession, async_test_storage_location
    ):
        db = real_async_db_session
        result = await core_api.items.list_with_template_async(
            db, async_test_storage_location.organization_id, [uuid4()]
        )
        assert result == {result.popitem()[0]: []} or result == {}


@pytest.mark.asyncio
class TestCoreItemsFindByBarcode:
    """`core_api.items.find_by_barcode_async`."""

    async def test_found(
        self, real_async_db_session: AsyncSession, async_test_storage_location
    ):
        db = real_async_db_session
        org_id = async_test_storage_location.organization_id
        loc_id = async_test_storage_location.id
        await _make_item(
            db, org_id, loc_id, name='Tagged', barcode='ABC123', quantity=Decimal('2')
        )
        await db.commit()

        result = await core_api.items.find_by_barcode_async(db, org_id, 'ABC123')
        assert result is not None
        assert result.name == 'Tagged'
        assert result.barcode == 'ABC123'

    async def test_not_found_returns_none(
        self, real_async_db_session: AsyncSession, async_test_storage_location
    ):
        db = real_async_db_session
        result = await core_api.items.find_by_barcode_async(
            db, async_test_storage_location.organization_id, 'NOPE'
        )
        assert result is None

    async def test_org_scoping(
        self, real_async_db_session: AsyncSession, async_test_storage_location
    ):
        """Barcode from another org is not visible."""
        db = real_async_db_session
        await _make_item(
            db,
            async_test_storage_location.organization_id,
            async_test_storage_location.id,
            name='X',
            barcode='XYZ',
        )
        await db.commit()

        result = await core_api.items.find_by_barcode_async(db, uuid4(), 'XYZ')
        assert result is None

    async def test_zero_quantity_excluded_by_default(
        self, real_async_db_session: AsyncSession, async_test_storage_location
    ):
        """Depleted stock returns None unless quantity_positive=False."""
        db = real_async_db_session
        org_id = async_test_storage_location.organization_id
        loc_id = async_test_storage_location.id
        await _make_item(
            db,
            org_id,
            loc_id,
            name='Depleted',
            barcode='EMPTY',
            quantity=Decimal('0'),
        )
        await db.commit()

        assert await core_api.items.find_by_barcode_async(db, org_id, 'EMPTY') is None
        assert (
            await core_api.items.find_by_barcode_async(
                db, org_id, 'EMPTY', quantity_positive=False
            )
            is not None
        )


@pytest.mark.asyncio
class TestCoreProductTemplatesSearchFuzzy:
    """`core_api.product_templates.search_fuzzy_async`."""

    async def test_empty_query_returns_empty(
        self, real_async_db_session: AsyncSession, async_test_storage_location
    ):
        db = real_async_db_session
        result = await core_api.product_templates.search_fuzzy_async(
            db, async_test_storage_location.organization_id, '   '
        )
        assert result == []

    async def test_ilike_match(
        self, real_async_db_session: AsyncSession, async_test_storage_location
    ):
        db = real_async_db_session
        org_id = async_test_storage_location.organization_id
        await _make_template(db, org_id, name='Onion White')
        await _make_template(db, org_id, name='Tomato Cherry')
        await _make_template(db, org_id, name='Garlic Peeled')
        await db.commit()

        result = await core_api.product_templates.search_fuzzy_async(
            db, org_id, 'onion'
        )
        names = [t.name for t in result]
        assert 'Onion White' in names
        assert 'Tomato Cherry' not in names

    async def test_includes_global_templates(
        self, real_async_db_session: AsyncSession, async_test_storage_location
    ):
        """Templates with organization_id=NULL are visible to all orgs."""
        db = real_async_db_session
        org_id = async_test_storage_location.organization_id
        global_tpl = await _make_template(db, None, name='Salt Global')
        org_tpl = await _make_template(db, org_id, name='Salt Brand X')
        await db.commit()

        result = await core_api.product_templates.search_fuzzy_async(db, org_id, 'salt')
        names = [t.name for t in result]
        assert 'Salt Global' in names
        assert 'Salt Brand X' in names
        assert global_tpl.id in [t.id for t in result]
        assert org_tpl.id in [t.id for t in result]

    async def test_org_scoping(
        self, real_async_db_session: AsyncSession, async_test_storage_location
    ):
        """Other org's templates are not visible."""
        db = real_async_db_session
        from app.models.organization import Organization

        other_org = Organization(name='Other Org')
        db.add(other_org)
        await db.flush()
        await _make_template(db, other_org.id, name='Secret Recipe')
        await db.commit()

        result = await core_api.product_templates.search_fuzzy_async(
            db, async_test_storage_location.organization_id, 'secret'
        )
        assert result == []

    async def test_phrase_that_matches_nothing_is_retried_word_by_word(
        self,
        real_async_db_session: AsyncSession,
        async_test_storage_location,
    ):
        """Typing the recipe's wording must still offer the catalogue's."""
        db = real_async_db_session
        org_id = async_test_storage_location.organization_id
        await _make_template(db, org_id, name='Ciecierzyca w puszce')
        await _make_template(db, org_id, name='Fasola biala w puszce')
        await db.commit()

        result = await core_api.product_templates.search_fuzzy_async(
            db, org_id, 'Ciecierzyca z puszki'
        )
        assert [t.name for t in result] == ['Ciecierzyca w puszce']

    async def test_the_word_wise_pass_still_requires_every_word(
        self,
        real_async_db_session: AsyncSession,
        async_test_storage_location,
    ):
        db = real_async_db_session
        org_id = async_test_storage_location.organization_id
        await _make_template(db, org_id, name='Mleko UHT 3.2%')
        await db.commit()

        assert (
            await core_api.product_templates.search_fuzzy_async(
                db, org_id, 'mleko kokosowe'
            )
            == []
        )

    async def test_diacritics_do_not_stop_the_fallback(
        self,
        real_async_db_session: AsyncSession,
        async_test_storage_location,
    ):
        db = real_async_db_session
        org_id = async_test_storage_location.organization_id
        await _make_template(db, org_id, name='Maka pszenna typ 550')
        await db.commit()

        result = await core_api.product_templates.search_fuzzy_async(
            db, org_id, 'Mąka pszenna'
        )
        assert [t.name for t in result] == ['Maka pszenna typ 550']

    async def test_a_substring_hit_keeps_its_order_untouched(
        self,
        real_async_db_session: AsyncSession,
        async_test_storage_location,
    ):
        """The fallback runs only when the plain search finds nothing."""
        db = real_async_db_session
        org_id = async_test_storage_location.organization_id
        await _make_template(db, org_id, name='Cukier bialy 1kg')
        await _make_template(db, org_id, name='Cukier waniliowy')
        await db.commit()

        result = await core_api.product_templates.search_fuzzy_async(
            db, org_id, 'cukier'
        )
        assert [t.name for t in result] == ['Cukier bialy 1kg', 'Cukier waniliowy']


@pytest.mark.asyncio
class TestCoreProductTemplatesSearchFuzzyMany:
    """`core_api.product_templates.search_fuzzy_many_async`."""

    async def test_empty_queries_return_empty(
        self, real_async_db_session: AsyncSession, async_test_storage_location
    ):
        db = real_async_db_session
        result = await core_api.product_templates.search_fuzzy_many_async(
            db, async_test_storage_location.organization_id, ['', '  ']
        )
        assert result == {}

    async def test_candidates_carry_their_names(
        self, real_async_db_session: AsyncSession, async_test_storage_location
    ):
        """Ranking happens in the caller, so the caller needs the names."""
        db = real_async_db_session
        org_id = async_test_storage_location.organization_id
        tpl = await _make_template(db, org_id, name='Ciecierzyca w puszce')
        await _make_template(db, org_id, name='Fasola biala w puszce')
        await db.commit()

        result = await core_api.product_templates.search_fuzzy_many_async(
            db, org_id, ['ciec']
        )
        assert [(c.id, c.name) for c in result['ciec']] == [
            (tpl.id, 'Ciecierzyca w puszce')
        ]

    async def test_stem_fragment_narrows_without_dropping_the_match(
        self, real_async_db_session: AsyncSession, async_test_storage_location
    ):
        """A stem, not the whole phrase — "z puszki" must not exclude "w puszce"."""
        db = real_async_db_session
        org_id = async_test_storage_location.organization_id
        await _make_template(db, org_id, name='Ciecierzyca w puszce')
        await db.commit()

        result = await core_api.product_templates.search_fuzzy_many_async(
            db, org_id, ['ciec', 'ciecierzyca z puszki']
        )
        assert [c.name for c in result['ciec']] == ['Ciecierzyca w puszce']
        assert result['ciecierzyca z puszki'] == []

    async def test_diacritics_match_in_both_directions(
        self, real_async_db_session: AsyncSession, async_test_storage_location
    ):
        db = real_async_db_session
        org_id = async_test_storage_location.organization_id
        await _make_template(db, org_id, name='Masło Extra 82%')
        await _make_template(db, org_id, name='Maslo orzechowe')
        await db.commit()

        result = await core_api.product_templates.search_fuzzy_many_async(
            db, org_id, ['masł', 'masl']
        )
        assert sorted(c.name for c in result['masł']) == [
            'Maslo orzechowe',
            'Masło Extra 82%',
        ]
        assert sorted(c.name for c in result['masl']) == [
            'Maslo orzechowe',
            'Masło Extra 82%',
        ]

    async def test_ascii_fragment_finds_an_accented_name(
        self, real_async_db_session: AsyncSession, async_test_storage_location
    ):
        """The caller folds its fragment to ASCII ("ryz"); the stored name
        keeps its letters ("Ryż 1 kg"), and the database comparison alone
        never joined the two."""
        db = real_async_db_session
        org_id = async_test_storage_location.organization_id
        await _make_template(db, org_id, name='Ryż 1 kg')
        await _make_template(db, org_id, name='Śmietana 18%')
        await db.commit()

        result = await core_api.product_templates.search_fuzzy_many_async(
            db, org_id, ['ryz', 'smie']
        )
        assert [c.name for c in result['ryz']] == ['Ryż 1 kg']
        assert [c.name for c in result['smie']] == ['Śmietana 18%']

    @pytest.mark.parametrize(
        'name',
        ['Weißbrot', 'Œufs', 'Молоко', 'Phở', 'Ryż', 'Maslo'],
    )
    async def test_a_name_finds_itself_whatever_its_script(
        self, real_async_db_session: AsyncSession, async_test_storage_location, name
    ):
        """Folds beyond a single Latin letter (ß, œ, Cyrillic, Vietnamese)
        are found by the raw spelling, as they always were. One fragment per
        call: fragments of one call widen each other's SQL."""
        db = real_async_db_session
        org_id = async_test_storage_location.organization_id
        await _make_template(db, org_id, name=name)
        await db.commit()

        result = await core_api.product_templates.search_fuzzy_many_async(
            db, org_id, [name.lower()]
        )
        assert [c.name for c in result[name.lower()]] == [name]

    async def test_org_scoping(
        self, real_async_db_session: AsyncSession, async_test_storage_location
    ):
        db = real_async_db_session
        from app.models.organization import Organization

        other_org = Organization(name='Other Org Batch')
        db.add(other_org)
        await db.flush()
        await _make_template(db, other_org.id, name='Secret Batch Recipe')
        await db.commit()

        result = await core_api.product_templates.search_fuzzy_many_async(
            db, async_test_storage_location.organization_id, ['secr']
        )
        assert result == {'secr': []}


@pytest.mark.asyncio
class TestCoreProductTemplatesGetWithUom:
    """`core_api.product_templates.get_with_uom_async`."""

    async def test_returns_none_for_missing(
        self, real_async_db_session: AsyncSession, async_test_storage_location
    ):
        db = real_async_db_session
        result = await core_api.product_templates.get_with_uom_async(
            db, async_test_storage_location.organization_id, uuid4()
        )
        assert result is None

    async def test_returns_dto(
        self, real_async_db_session: AsyncSession, async_test_storage_location
    ):
        db = real_async_db_session
        org_id = async_test_storage_location.organization_id
        tpl = await _make_template(
            db, org_id, name='Spice', weight_value=Decimal('100')
        )
        await db.commit()

        result = await core_api.product_templates.get_with_uom_async(db, org_id, tpl.id)
        assert result is not None
        assert result.id == tpl.id
        assert result.name == 'Spice'

    async def test_global_template_visible(
        self, real_async_db_session: AsyncSession, async_test_storage_location
    ):
        """Global templates (organization_id IS NULL) are visible to any org."""
        db = real_async_db_session
        org_id = async_test_storage_location.organization_id
        tpl = await _make_template(db, None, name='Global Spice')
        await db.commit()

        result = await core_api.product_templates.get_with_uom_async(db, org_id, tpl.id)
        assert result is not None
        assert result.name == 'Global Spice'

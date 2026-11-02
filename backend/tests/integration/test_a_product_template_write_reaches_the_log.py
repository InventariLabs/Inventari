"""A product template is a definition every record is written against.

Change the unit of measure on one and every quantity stored for its products
means something else; change the barcode and a scanner starts finding a
different thing. The rule names the catalogue among the four kinds of act the
journal holds, and this was the one catalogue table nothing recorded at all.

The second half is who writes the entry. An equipment model *is* a product
template -- the same row in the same table, reached from a second screen --
and the equipment module used to log it under a word of its own. So the same
act was in the journal when equipment did it, absent when the products screen
did it, and named two different things in the filter. The entry is written in
the core now, once, for whoever wrote the row.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.public_api import core_api
from app.models.audit_log import AuditLog

pytestmark = pytest.mark.integration


async def _entries(db, org_id) -> list[AuditLog]:
    rows = await db.scalars(
        select(AuditLog)
        .where(
            AuditLog.organization_id == org_id,
            AuditLog.target_type == 'product_template',
        )
        .order_by(AuditLog.created_at.asc())
    )
    return list(rows.all())


async def _template(db, org_id, user_id, **overrides):
    payload = {'name': 'Pilsner malt', 'brand': 'Weyermann'}
    payload.update(overrides)
    return await core_api.product_templates.create_async(
        db, org_id, user_id=user_id, **payload
    )


class TestTheCatalogueIsWrittenDown:
    async def test_creating_one_names_it(
        self, real_async_db_session, async_test_user, async_test_household
    ):
        db, org = real_async_db_session, async_test_household
        tpl = await _template(db, org.id, async_test_user.id)

        (entry,) = await _entries(db, org.id)
        assert entry.action == 'CREATE'
        assert entry.target_id == tpl.id
        assert entry.user_id == async_test_user.id
        assert entry.snapshot is not None
        assert entry.snapshot['name'] == 'Pilsner malt'
        assert entry.snapshot['brand'] == 'Weyermann'

    async def test_an_edit_says_only_what_moved(
        self, real_async_db_session, async_test_user, async_test_household
    ):
        db, org = real_async_db_session, async_test_household
        tpl = await _template(db, org.id, async_test_user.id)

        await core_api.product_templates.update_async(
            db, tpl.id, org.id, brand='Best Malz', user_id=async_test_user.id
        )

        _created, edited = await _entries(db, org.id)
        assert edited.action == 'UPDATE'
        assert edited.snapshot is not None
        assert edited.snapshot['before'] == {'brand': 'Weyermann'}
        assert edited.snapshot['after'] == {'brand': 'Best Malz'}

    async def test_a_submit_that_changed_nothing_writes_nothing(
        self, real_async_db_session, async_test_user, async_test_household
    ):
        """The form posts its whole state, and that is not a change."""
        db, org = real_async_db_session, async_test_household
        tpl = await _template(db, org.id, async_test_user.id)

        await core_api.product_templates.update_async(
            db,
            tpl.id,
            org.id,
            name='Pilsner malt',
            brand='Weyermann',
            user_id=async_test_user.id,
        )

        assert len(await _entries(db, org.id)) == 1

    async def test_deleting_one_keeps_the_definition(
        self, real_async_db_session, async_test_user, async_test_household
    ):
        db, org = real_async_db_session, async_test_household
        tpl = await _template(db, org.id, async_test_user.id)

        await core_api.product_templates.delete_async(
            db, tpl.id, org.id, async_test_user.id
        )

        _created, removed = await _entries(db, org.id)
        assert removed.action == 'HARD_DELETE'
        assert removed.snapshot is not None
        assert removed.snapshot['name'] == 'Pilsner malt'


class TestOneRowOneWord:
    async def test_both_screens_write_the_same_kind_of_entry(
        self, real_async_db_session, async_test_user, async_test_household
    ):
        """The products screen and the equipment screen, on one template.

        Reached two ways, the row must read one way -- otherwise the filter
        offers two words for one act and neither of them finds both.
        """
        from app.modules.equipment.model_service import update_equipment_model

        db, org = real_async_db_session, async_test_household
        tpl = await _template(
            db, org.id, async_test_user.id, meta_data={'equipment': {'ports': 4}}
        )

        await core_api.product_templates.update_async(
            db, tpl.id, org.id, brand='Dell', user_id=async_test_user.id
        )
        await update_equipment_model(
            db,
            org.id,
            tpl.id,
            equipment_meta={'ports': 8},
            user_id=async_test_user.id,
        )

        _created, from_products, from_equipment = await _entries(db, org.id)
        assert from_products.target_type == from_equipment.target_type
        assert from_products.target_id == from_equipment.target_id == tpl.id
        assert (from_equipment.snapshot or {})['after'] == {
            'meta_data': {'equipment': {'ports': 8}}
        }


class TestAStubIsStillATemplate:
    async def test_a_stub_created_from_a_scan_says_it_is_one(
        self, real_async_db_session, async_test_user, async_test_household
    ):
        """Quick entry makes a template with almost nothing in it.

        It is still a definition items get written against, and the flag is
        what tells a reader it arrived from a barcode rather than a person
        filling in a form.
        """
        db, org = real_async_db_session, async_test_household
        await core_api.product_templates.create_stub_async(
            db, org.id, 'Unknown 5900000000000', '5900000000000', async_test_user.id
        )

        (entry,) = await _entries(db, org.id)
        assert entry.snapshot is not None
        assert entry.snapshot['stub'] is True
        assert entry.snapshot['barcode'] == '5900000000000'


class TestNobodyToName:
    async def test_a_write_with_no_user_still_records(
        self, real_async_db_session, async_test_household
    ):
        """Seeding and imports have no person behind them; the row still goes in."""
        db, org = real_async_db_session, async_test_household
        await core_api.product_templates.create_async(db, org.id, name='Seeded')

        (entry,) = await _entries(db, org.id)
        assert entry.user_id is None
        assert entry.snapshot is not None
        assert entry.snapshot['name'] == 'Seeded'


class TestTheUnitIsNamedNotNumbered:
    """A reference the writer can name is written down with its name.

    The journal row used to read `Unit: 16282d80` — the label translated,
    the value eight characters of a uuid the reader cannot pronounce. The
    unit is chosen from a catalogue of words, so the entry owes the same
    word the product screen prints, read while the row is still in hand.
    """

    async def _uom(self, db):
        from decimal import Decimal

        from app.models.uom import Uom, UomCategory

        category = UomCategory(organization_id=None, name='Test Volume')
        db.add(category)
        await db.flush()
        uom = Uom(
            organization_id=None,
            category_id=category.id,
            name='Test Unit Literal',
            symbol='tul',
            factor=Decimal('1'),
        )
        db.add(uom)
        await db.flush()
        return uom

    async def test_creating_one_names_the_unit(
        self, real_async_db_session, async_test_user, async_test_household
    ):
        from app.services._product_template_writes import (
            create_product_template_async,
        )

        db, org = real_async_db_session, async_test_household
        uom = await self._uom(db)

        tpl = await create_product_template_async(
            db,
            org.id,
            name='Pilsner malt',
            uom_id=uom.id,
            user_id=async_test_user.id,
        )

        (entry,) = await _entries(db, org.id)
        snapshot = entry.snapshot
        assert snapshot is not None
        assert snapshot['uom_id'] == str(uom.id)
        # The symbol, not the catalogue name: `tul` is the word the product
        # screen and the shelf label print, the same rule the item writer's
        # reference naming applies.
        assert snapshot['uom_name'] == 'tul'
        assert tpl.uom_id == uom.id

    async def test_a_stub_names_the_unit_too(
        self, real_async_db_session, async_test_user, async_test_household
    ):
        """Quick entry from a scan takes the default piece unit — named as well."""
        db, org = real_async_db_session, async_test_household

        await core_api.product_templates.create_stub_async(
            db, org.id, 'Unknown 5900000000001', '5900000000001', async_test_user.id
        )

        (entry,) = await _entries(db, org.id)
        snapshot = entry.snapshot
        assert snapshot is not None
        assert snapshot['stub'] is True
        assert snapshot['uom_id'] is not None
        assert snapshot['uom_name'] == 'pcs'

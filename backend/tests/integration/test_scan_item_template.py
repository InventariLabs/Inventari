"""Items created by a scan resolve a product template, like every other item.

There were two creation paths and only one of them resolved a template, so an
item added by scanning a label or a barcode silently ended up without
`template_id` — no unit weight, no stock threshold, and every
template-driven suggestion bailing out early on `if not template`.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserContextDTO
from app.models.label_pool import LabelPool
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.uom import Uom, UomCategory
from app.schemas.label_pool import LabelAssignRequest
from app.services.items import assign_label_or_barcode

pytestmark = pytest.mark.integration


def _user_dto(user) -> UserContextDTO:
    return UserContextDTO(
        id=user.id,
        organization_id=user.organization_id,
        role=user.role,
        email=user.email,
    )


async def _storage(db: AsyncSession, org_id, user_id) -> StorageLocation:
    location = StorageLocation(
        organization_id=org_id,
        created_by=user_id,
        name=f'Receiving-{uuid.uuid4().hex[:6]}',
    )
    db.add(location)
    await db.flush()
    return location


async def _label(db: AsyncSession, org_id, user_id) -> LabelPool:
    label = LabelPool(
        short_code=f'LBL-{uuid.uuid4().hex[:6].upper()}',
        organization_id=org_id,
        created_by=user_id,
    )
    db.add(label)
    await db.flush()
    return label


@pytest.mark.asyncio
class TestScanResolvesTemplate:
    async def test_a_scan_that_names_no_unit_lands_in_pieces(
        self, real_async_db_session: AsyncSession, async_test_user
    ):
        """A scanned product answers "a quantity of *what*" like every other
        create path: no unit on the request means pieces, not a unitless row.

        The form defaults it, POST /items defaults it, the importer defaults
        it — the scan built its Item directly and was the one door a unitless
        record could still walk through.

        This is the test that pins the backfill in ``create_item_async``: the
        template is minted before the default unit is known, so only the
        step that copies the record's unit onto a freshly minted template
        gives it one. Without that step the assertion on the template fails."""
        db = real_async_db_session
        org_id = async_test_user.organization_id
        location = await _storage(db, org_id, async_test_user.id)
        label = await _label(db, org_id, async_test_user.id)

        item = await assign_label_or_barcode(
            db,
            label.short_code,
            LabelAssignRequest(
                location_id=location.id,
                name='Scanned without a unit',
                quantity=1,
            ),
            _user_dto(async_test_user),
        )

        assert item.uom_id is not None
        uom = await db.get(Uom, item.uom_id)
        assert uom is not None and uom.symbol == 'pcs'

        # The template minted by this scan inherits the unit its first
        # record landed with — a unitless template is where BoM
        # convertibility checks go to die.
        template = await db.get(ProductTemplate, item.template_id)
        assert template is not None
        assert template.uom_id == item.uom_id

    async def test_a_scan_that_names_a_unit_leaves_it_on_the_template(
        self, real_async_db_session: AsyncSession, async_test_user
    ):
        """The scan that carries a unit leaves it on the catalogue row too,
        not only on its own record: the template reads one unit, the one
        the first scan named.

        An end-to-end check of the outcome, not a pin on one step: the unit
        reaches the template twice — the template is minted wearing it, and
        the backfill (pinned by the no-unit test above) would write it
        anyway — so removing either step alone leaves this test green. It
        fails only when neither puts the unit there."""
        db = real_async_db_session
        org_id = async_test_user.organization_id
        location = await _storage(db, org_id, async_test_user.id)
        label = await _label(db, org_id, async_test_user.id)
        category = UomCategory(organization_id=org_id, name='Mass')
        db.add(category)
        await db.flush()
        kg = Uom(
            organization_id=org_id,
            name='Kilogram',
            symbol='kg',
            category_id=category.id,
            factor=1.0,
            is_reference=True,
        )
        db.add(kg)
        await db.flush()

        item = await assign_label_or_barcode(
            db,
            label.short_code,
            LabelAssignRequest(
                location_id=location.id,
                name='Scanned in kilograms',
                quantity=2,
                uom_id=kg.id,
            ),
            _user_dto(async_test_user),
        )

        assert item.uom_id == kg.id
        template = await db.get(ProductTemplate, item.template_id)
        assert template is not None
        assert template.uom_id == kg.id

    async def test_item_created_from_a_label_scan_gets_a_template(
        self, real_async_db_session: AsyncSession, async_test_user
    ):
        db = real_async_db_session
        org_id = async_test_user.organization_id
        location = await _storage(db, org_id, async_test_user.id)
        label = await _label(db, org_id, async_test_user.id)

        item = await assign_label_or_barcode(
            db,
            label.short_code,
            LabelAssignRequest(
                location_id=location.id,
                name='Scanned product',
                quantity=1,
            ),
            _user_dto(async_test_user),
        )

        assert item.template_id is not None

    async def test_a_barcode_scan_reuses_the_template_that_barcode_already_has(
        self, real_async_db_session: AsyncSession, async_test_user
    ):
        """Two items of the same product must share one template, not fork."""
        db = real_async_db_session
        org_id = async_test_user.organization_id
        location = await _storage(db, org_id, async_test_user.id)
        barcode = '5901234123457'

        existing = ProductTemplate(
            organization_id=org_id, name='Known product', barcode=barcode
        )
        db.add(existing)
        await db.flush()

        item = await assign_label_or_barcode(
            db,
            barcode,
            LabelAssignRequest(
                location_id=location.id,
                name='Known product',
                quantity=1,
            ),
            _user_dto(async_test_user),
        )

        assert item.template_id == existing.id

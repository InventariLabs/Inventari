"""A code that already has a carrier does not get a second one.

Records created before the code moved to the template keep it on the row —
that is the state of every existing installation. Scanning such a code and
changing the name on the form minted a *new* template carrying it: from
then on the scan resolved the new product and the older record, holding the
same code, dropped out of the scan's answer entirely.

The rule is the one the manual form already answers to: a code in use by a
live record of a different product is refused, by name, before anything is
minted for it. A record of the *same* product is not a conflict — that is
the code moving to where it belongs.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.item import Item
from app.models.product_template import ProductTemplate
from app.models.storage_location import LocationUsage, StorageLocation
from app.schemas.label_pool import LabelAssignRequest
from app.services.items.scan_service import assign_label_or_barcode
from tests.integration._shelf import anchor_pending_records

pytestmark = pytest.mark.integration


def _barcode() -> str:
    return f'76{uuid.uuid4().int % 10**11:011d}'


async def _location(db: AsyncSession, org_id, user_id, name: str) -> StorageLocation:
    location = StorageLocation(
        organization_id=org_id,
        created_by=user_id,
        name=name,
        usage=LocationUsage.INTERNAL,
    )
    db.add(location)
    await db.flush()
    return location


async def _legacy_carrier(db: AsyncSession, org_id, location, barcode: str) -> Item:
    """A record from before the move: the code sits on the row itself."""
    template = ProductTemplate(organization_id=org_id, name='Kawa mielona')
    db.add(template)
    await db.flush()
    item = Item(
        organization_id=org_id,
        storage_location_id=location.id,
        name='Kawa mielona',
        quantity=Decimal('2'),
        barcode=barcode,
        template_id=template.id,
    )
    db.add(item)
    await db.run_sync(anchor_pending_records)
    await db.flush()
    return item


@pytest.mark.asyncio
class TestTheCodeKeepsOneCarrier:
    async def test_a_scan_under_another_name_does_not_mint_a_second_carrier(
        self, real_async_db_session: AsyncSession, async_test_user
    ) -> None:
        db = real_async_db_session
        org_id = async_test_user.organization_id
        barcode = _barcode()
        shelf = await _location(db, org_id, async_test_user.id, 'Main Warehouse')
        cellar = await _location(db, org_id, async_test_user.id, 'Cellar')
        await _legacy_carrier(db, org_id, shelf, barcode)
        await db.commit()

        with pytest.raises(ValueError, match=barcode):
            await assign_label_or_barcode(
                db,
                barcode,
                LabelAssignRequest(
                    location_id=cellar.id,
                    name='Zupełnie inny produkt',
                    quantity=1,
                ),
                async_test_user,
            )
        await db.rollback()

        carriers = (
            await db.scalars(
                select(ProductTemplate).where(
                    ProductTemplate.organization_id == org_id,
                    ProductTemplate.barcode == barcode,
                )
            )
        ).all()
        assert carriers == [], 'no template may be minted carrying a taken code'

    async def test_the_same_product_in_another_place_still_goes_through(
        self, real_async_db_session: AsyncSession, async_test_user
    ) -> None:
        """The code moving onto its own product's template is the point of
        the move, not a conflict — the second location must still work."""
        db = real_async_db_session
        org_id = async_test_user.organization_id
        barcode = _barcode()
        shelf = await _location(db, org_id, async_test_user.id, 'Main Warehouse')
        cellar = await _location(db, org_id, async_test_user.id, 'Cellar')
        carrier = await _legacy_carrier(db, org_id, shelf, barcode)
        await db.commit()

        item = await assign_label_or_barcode(
            db,
            barcode,
            LabelAssignRequest(location_id=cellar.id, name='Kawa mielona', quantity=1),
            async_test_user,
        )
        await db.commit()

        assert item.template_id == carrier.template_id
        assert item.barcode is None, 'the code lives on the product now'

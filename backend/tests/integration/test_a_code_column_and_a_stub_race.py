"""A sheet's code column may hold barcodes; two stubs may want one code.

The app calls a product's barcode "Product code", so a pasted sheet headed
`code` is read as the SKU and may carry EANs all the same — its rows must
find the product, not land as "not in the catalogue". And a quick entry that
loses the race for a new barcode answers the refusal a later request gets,
not a 500.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ServiceRejectionError
from app.modules.warehouse._import_line_builder import _resolve_template
from app.services._product_template_writes import (
    create_product_template_async,
    create_stub_template_async,
)


@pytest.mark.integration
@pytest.mark.asyncio
class TestACodeColumnAndAStubRace:
    async def test_a_sku_cell_holding_a_barcode_finds_the_product(
        self, real_async_db_session: AsyncSession, async_test_user
    ):
        db = real_async_db_session
        org_id = async_test_user.organization_id
        card = await create_product_template_async(
            db, org_id, 'Plum butter', barcode='2000000009018'
        )

        by_code_column = await _resolve_template(
            db, org_id, barcode=None, sku='2000000009018', name=''
        )
        by_barcode_column = await _resolve_template(
            db, org_id, barcode='2000000009018', sku=None, name=''
        )

        assert by_code_column[0] == card.id
        assert by_barcode_column[0] == card.id

    async def test_a_code_nobody_holds_still_finds_nothing(
        self, real_async_db_session: AsyncSession, async_test_user
    ):
        found = await _resolve_template(
            real_async_db_session,
            async_test_user.organization_id,
            barcode=None,
            sku='2000000000015',
            name='',
        )

        assert found[0] is None

    async def test_a_stub_that_loses_the_race_for_a_code_is_refused_not_500ed(
        self, real_async_db_session: AsyncSession, async_test_user, monkeypatch
    ):
        """The first look is made blind to the card that already stands, so
        the race is deterministic rather than a matter of timing."""
        db = real_async_db_session
        org_id = async_test_user.organization_id
        await create_stub_template_async(db, org_id, 'First', '2000000000015')

        async def blind(*args, **kwargs):
            return None

        monkeypatch.setattr(db, 'scalar', blind)

        with pytest.raises(ServiceRejectionError) as refused:
            await create_stub_template_async(db, org_id, 'Second', '2000000000015')

        assert refused.value.key == 'barcode_already_exists'
        monkeypatch.undo()
        # The savepoint left the transaction usable.
        await create_stub_template_async(db, org_id, 'Third', '2000000000022')

"""Integration tests for UoM system in item creation/update/response."""

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.uom import Uom
from app.schemas.item import ItemCreate, ItemUpdate
from app.services.items import (
    create_item,
    update_item,
)


async def _get_storage(db: AsyncSession, org_id, user_id) -> StorageLocation:
    result = await db.scalars(
        select(StorageType).where(StorageType.type_code == 'PANTRY')
    )
    st = result.first()
    assert st is not None, 'PANTRY storage type not seeded'
    storage = StorageLocation(
        name='UoM Integration Test Storage',
        organization_id=org_id,
        storage_type_id=st.id,
        created_by=user_id,
    )
    db.add(storage)
    await db.commit()
    await db.refresh(storage)
    return storage


@pytest.mark.integration
class TestUomItemIntegration:
    @pytest.mark.asyncio
    async def test_create_item_with_uom_id_saves_correctly(
        self, real_async_db_session: AsyncSession, async_test_user
    ):
        """Creating an item with uom_id should persist the relationship."""
        kg = (
            await real_async_db_session.scalars(select(Uom).where(Uom.symbol == 'kg'))
        ).first()
        assert kg is not None, 'kg UoM not seeded'

        storage = await _get_storage(
            real_async_db_session, async_test_user.organization_id, async_test_user.id
        )

        item_in = ItemCreate(
            name='Mąka pełnoziarnista',
            location_id=storage.id,
            quantity=Decimal('2.5'),
            uom_id=kg.id,
        )

        item = await create_item(real_async_db_session, item_in, async_test_user)

        assert item.uom_id == kg.id

    @pytest.mark.asyncio
    async def test_update_item_uom_id(
        self, real_async_db_session: AsyncSession, async_test_user
    ):
        """An empty record keeps its card's unit; one holding stock may not move.

        This used to assert only the first half, on a record holding a
        kilogram — so it asserted that "1 kg" could silently become "1 g".
        """
        kg = (
            await real_async_db_session.scalars(select(Uom).where(Uom.symbol == 'kg'))
        ).first()
        g = (
            await real_async_db_session.scalars(select(Uom).where(Uom.symbol == 'g'))
        ).first()
        assert kg and g

        storage = await _get_storage(
            real_async_db_session, async_test_user.organization_id, async_test_user.id
        )

        # An empty record: nothing on the shelf, but the unit is still the
        # catalogue's to name — the change is refused until it is confirmed,
        # and confirming it writes the choice into the record's history.
        item_in = ItemCreate(
            name='Ryż brązowy',
            location_id=storage.id,
            quantity=Decimal('0'),
            uom_id=kg.id,
        )
        item = await create_item(real_async_db_session, item_in, async_test_user)
        assert item.uom_id == kg.id

        with pytest.raises(ValueError, match='kept in'):
            await update_item(
                real_async_db_session, item, ItemUpdate(uom_id=g.id), async_test_user
            )

        # Confirmed, the record still keeps its card's unit: a quantity named
        # in grams is restated in kilograms, and this edit named none.
        item = await update_item(
            real_async_db_session,
            item,
            ItemUpdate(uom_id=g.id, unit_confirmed_over_template=True),
            async_test_user,
        )
        assert (item.uom_id, item.quantity) == (kg.id, Decimal('0'))

        # And once it holds something, the unit under that number is fixed.
        stocked_in = ItemCreate(
            name='Ryż brązowy (worek)',
            location_id=storage.id,
            quantity=Decimal('1'),
            uom_id=kg.id,
        )
        stocked = await create_item(real_async_db_session, stocked_in, async_test_user)
        with pytest.raises(ValueError, match='kg'):
            await update_item(
                real_async_db_session, stocked, ItemUpdate(uom_id=g.id), async_test_user
            )

    @pytest.mark.asyncio
    async def test_uom_id_without_unit_string(
        self, real_async_db_session: AsyncSession, async_test_user
    ):
        """Creating item with only uom_id (no unit string) should work."""
        pcs = (
            await real_async_db_session.scalars(select(Uom).where(Uom.symbol == 'pcs'))
        ).first()
        assert pcs is not None

        storage = await _get_storage(
            real_async_db_session, async_test_user.organization_id, async_test_user.id
        )

        item_in = ItemCreate(
            name='Jogurt naturalny',
            location_id=storage.id,
            quantity=Decimal('4'),
            uom_id=pcs.id,
        )

        item = await create_item(real_async_db_session, item_in, async_test_user)
        assert item.uom_id == pcs.id

    @pytest.mark.asyncio
    async def test_create_with_uom_id_only(
        self, real_async_db_session: AsyncSession, async_test_user
    ):
        """Creating an item with only uom_id (no unit string) should persist correctly."""
        ml_uom = (
            await real_async_db_session.scalars(select(Uom).where(Uom.symbol == 'ml'))
        ).first()
        assert ml_uom is not None, 'ml UoM not seeded'

        storage = await _get_storage(
            real_async_db_session, async_test_user.organization_id, async_test_user.id
        )

        item_in = ItemCreate(
            name='Majonez dekoracyjny',
            location_id=storage.id,
            quantity=Decimal('318.109'),
            uom_id=ml_uom.id,
        )

        item = await create_item(real_async_db_session, item_in, async_test_user)

        assert item.uom_id == ml_uom.id

    @pytest.mark.asyncio
    async def test_update_uom_id(
        self, real_async_db_session: AsyncSession, async_test_user
    ):
        """A unit that does not convert into the card's is refused, confirmed or not.

        Kilograms to litres is not a conversion without a density, and the
        record is kept in its card's unit — so even an empty record cannot be
        moved to litres while its card is kept in kilograms.
        """
        kg = (
            await real_async_db_session.scalars(select(Uom).where(Uom.symbol == 'kg'))
        ).first()
        l_uom = (
            await real_async_db_session.scalars(select(Uom).where(Uom.symbol == 'l'))
        ).first()
        assert kg and l_uom

        storage = await _get_storage(
            real_async_db_session, async_test_user.organization_id, async_test_user.id
        )

        item_in = ItemCreate(
            name='Olej rzepakowy',
            location_id=storage.id,
            quantity=Decimal('0'),
            uom_id=kg.id,
        )
        item = await create_item(real_async_db_session, item_in, async_test_user)

        # A unit the catalogue does not keep is a deliberate choice: refused
        # unnamed, recorded when confirmed.
        with pytest.raises(ValueError, match='kept in'):
            await update_item(
                real_async_db_session,
                item,
                ItemUpdate(uom_id=l_uom.id),
                async_test_user,
            )

        update_in = ItemUpdate(uom_id=l_uom.id, unit_confirmed_over_template=True)
        with pytest.raises(ValueError, match='cannot be converted'):
            await update_item(real_async_db_session, item, update_in, async_test_user)

        assert item.uom_id == kg.id

    @pytest.mark.asyncio
    async def test_item_api_response_includes_uom(
        self, real_async_db_session: AsyncSession, async_test_user
    ):
        """Response schema should serialize uom relationship into UomInfo."""
        l_uom = (
            await real_async_db_session.scalars(select(Uom).where(Uom.symbol == 'l'))
        ).first()
        assert l_uom is not None

        storage = await _get_storage(
            real_async_db_session, async_test_user.organization_id, async_test_user.id
        )

        item_in = ItemCreate(
            name='Mleko UHT',
            location_id=storage.id,
            quantity=Decimal('2'),
            uom_id=l_uom.id,
        )
        item = await create_item(real_async_db_session, item_in, async_test_user)

        # Eagerly load uom relationship for serialization test
        await real_async_db_session.refresh(item, ['uom'])

        from app.schemas.item import Item as ItemSchema

        schema = ItemSchema.model_validate(item)
        assert schema.uom is not None
        assert schema.uom.symbol == 'l'
        assert schema.uom.category_name == 'Volume'
        assert schema.uom.rounding == l_uom.rounding

    async def test_the_embedded_uom_carries_the_step_it_is_counted_in(
        self, real_async_db_session: AsyncSession, async_test_user
    ):
        """Precision belongs to the unit, and only the unit knows it.

        Quantity is stored in ``numeric(10,3)``, so a piece serializes as
        "1.000" and every screen printing it said a piece divides into
        thousandths. The reader of that string has no way to know better
        unless the unit travels with its own step.
        """
        pcs = (
            await real_async_db_session.scalars(select(Uom).where(Uom.symbol == 'pcs'))
        ).first()
        gram = (
            await real_async_db_session.scalars(select(Uom).where(Uom.symbol == 'g'))
        ).first()
        assert pcs is not None and gram is not None

        storage = await _get_storage(
            real_async_db_session, async_test_user.organization_id, async_test_user.id
        )
        from app.schemas.item import Item as ItemSchema

        for uom, expected in ((pcs, Decimal('1')), (gram, Decimal('0.001'))):
            item = await create_item(
                real_async_db_session,
                ItemCreate(
                    name=f'Counted in {uom.symbol}',
                    location_id=storage.id,
                    quantity=Decimal('1'),
                    uom_id=uom.id,
                ),
                async_test_user,
            )
            await real_async_db_session.refresh(item, ['uom'])

            schema = ItemSchema.model_validate(item)
            assert schema.uom is not None
            assert schema.uom.rounding == expected

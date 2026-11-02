"""Integration tests for uom_service (read-only UoM queries and quantity validation)."""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ServiceRejectionError
from app.services.uom_service import (
    get_uom_async,
    get_uom_by_symbol_async,
    to_canonical_measure_async,
    validate_quantity_precision_async,
)


@pytest.mark.integration
@pytest.mark.asyncio
class TestGetUomBySymbol:
    """Tests for get_uom_by_symbol_async()."""

    async def test_existing_symbol_returns_uom(
        self, real_async_db_session: AsyncSession
    ):
        result = await get_uom_by_symbol_async(real_async_db_session, 'pcs')
        assert result is not None
        assert result.symbol == 'pcs'
        assert result.rounding == 1.0

    async def test_nonexistent_symbol_returns_none(
        self, real_async_db_session: AsyncSession
    ):
        result = await get_uom_by_symbol_async(
            real_async_db_session, 'nonexistent_symbol'
        )
        assert result is None

    async def test_system_uom_returned_with_organization_id(
        self, real_async_db_session: AsyncSession
    ):
        fake_org_id = uuid.uuid4()
        result = await get_uom_by_symbol_async(
            real_async_db_session, 'pcs', organization_id=fake_org_id
        )
        assert result is not None
        assert result.symbol == 'pcs'
        assert result.organization_id is None


@pytest.mark.integration
@pytest.mark.asyncio
class TestGetUom:
    """Tests for get_uom_async()."""

    async def test_valid_id_returns_uom(self, real_async_db_session: AsyncSession):
        pcs = await get_uom_by_symbol_async(real_async_db_session, 'pcs')
        assert pcs is not None
        result = await get_uom_async(real_async_db_session, pcs.id)
        assert result is not None
        assert result.id == pcs.id

    async def test_random_uuid_returns_none(self, real_async_db_session: AsyncSession):
        result = await get_uom_async(real_async_db_session, uuid.uuid4())
        assert result is None


@pytest.mark.integration
@pytest.mark.asyncio
class TestValidateQuantityPrecision:
    """Tests for validate_quantity_precision_async()."""

    async def test_none_uom_id_does_nothing(self, real_async_db_session: AsyncSession):
        await validate_quantity_precision_async(
            real_async_db_session, None, Decimal('3.14')
        )

    async def test_random_uom_id_does_nothing(
        self, real_async_db_session: AsyncSession
    ):
        await validate_quantity_precision_async(
            real_async_db_session, uuid.uuid4(), Decimal('3.14')
        )

    async def test_integer_uom_whole_number_accepted(
        self, real_async_db_session: AsyncSession
    ):
        pcs = await get_uom_by_symbol_async(real_async_db_session, 'pcs')
        assert pcs is not None
        await validate_quantity_precision_async(
            real_async_db_session, pcs.id, Decimal('5')
        )

    async def test_integer_uom_decimal_raises(
        self, real_async_db_session: AsyncSession
    ):
        """The refusal carries its catalogue key — it reaches a reader.

        Checked by key rather than by sentence: the wording lives in the
        catalogue and is asserted there, while this pins the routing (a
        plain ``ValueError`` would answer 400 in English in a Polish
        session). ``ServiceRejectionError`` subclasses ``ValueError``, so
        routers that catch the plain type keep working.
        """
        pcs = await get_uom_by_symbol_async(real_async_db_session, 'pcs')
        assert pcs is not None
        with pytest.raises(ServiceRejectionError) as refusal:
            await validate_quantity_precision_async(
                real_async_db_session, pcs.id, Decimal('5.5')
            )
        assert refusal.value.key == 'uom_quantity_requires_whole_number'

    async def test_decimal_uom_valid_decimal_accepted(
        self, real_async_db_session: AsyncSession
    ):
        kg = await get_uom_by_symbol_async(real_async_db_session, 'kg')
        assert kg is not None
        await validate_quantity_precision_async(
            real_async_db_session, kg.id, Decimal('1.234')
        )

    async def test_decimal_uom_too_many_places_raises(
        self, real_async_db_session: AsyncSession
    ):
        kg = await get_uom_by_symbol_async(real_async_db_session, 'kg')
        assert kg is not None
        with pytest.raises(ServiceRejectionError) as refusal:
            await validate_quantity_precision_async(
                real_async_db_session, kg.id, Decimal('1.1234')
            )
        assert refusal.value.key == 'uom_quantity_too_many_decimal_places'


@pytest.mark.integration
@pytest.mark.asyncio
class TestToCanonicalMeasure:
    """Tests for to_canonical_measure_async() — the one doorway for mass/volume."""

    async def test_ounce_answers_in_grams_from_the_catalogue(
        self, real_async_db_session: AsyncSession
    ):
        """The seeded factor decides: 1 oz = 28.3495 g, not a private table's 28.35."""
        oz = await get_uom_by_symbol_async(real_async_db_session, 'oz')
        assert oz is not None
        measure = await to_canonical_measure_async(
            real_async_db_session, Decimal('1'), oz
        )
        assert measure is not None
        amount, symbol = measure
        assert symbol == 'g'
        assert amount == Decimal('28.3495')

    async def test_kilogram_answers_in_grams(self, real_async_db_session: AsyncSession):
        kg = await get_uom_by_symbol_async(real_async_db_session, 'kg')
        assert kg is not None
        measure = await to_canonical_measure_async(
            real_async_db_session, Decimal('2.5'), kg
        )
        assert measure is not None
        amount, symbol = measure
        assert symbol == 'g'
        assert amount == Decimal('2500')

    async def test_liter_answers_in_ml(self, real_async_db_session: AsyncSession):
        liter = await get_uom_by_symbol_async(real_async_db_session, 'l')
        assert liter is not None
        measure = await to_canonical_measure_async(
            real_async_db_session, Decimal('1.5'), liter
        )
        assert measure is not None
        amount, symbol = measure
        assert symbol == 'ml'
        assert amount == Decimal('1500')

    async def test_counted_unit_answers_in_itself(
        self, real_async_db_session: AsyncSession
    ):
        """A count has no physical measure — the answer names the unit itself."""
        pcs = await get_uom_by_symbol_async(real_async_db_session, 'pcs')
        assert pcs is not None
        measure = await to_canonical_measure_async(
            real_async_db_session, Decimal('7'), pcs
        )
        assert measure is not None
        amount, symbol = measure
        assert symbol == 'pcs'
        assert amount == Decimal('7')

    async def test_none_uom_returns_none(self, real_async_db_session: AsyncSession):
        assert (
            await to_canonical_measure_async(real_async_db_session, Decimal('5'), None)
            is None
        )

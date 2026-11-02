"""A unit's conversion factor is exact, and so is what it converts.

``factor`` and ``rounding`` were ``double precision``. The Python path
recovered most of the damage — ``Decimal(str(x))`` on a float gives back the
short decimal it was written as — but SQL had no such rescue: ``numeric ×
double`` is ``double``, so every aggregate multiplying a stored quantity by a
factor left exact arithmetic the moment it touched the unit table. A
coefficient is a definition, not a measurement; there is no reason for it to
be the one number in the chain that is approximate.

The result of a conversion is rounded here as well. It used to be handed to
Postgres at full precision and rounded on the way into a ``numeric(12,3)``
column — the right answer, arrived at by nobody's decision, and invisible to
the code that had just computed it.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration


class TestTheUnitTableHoldsExactNumbers:
    async def test_factor_and_rounding_are_not_floating_point(
        self, real_async_db_session: AsyncSession
    ) -> None:
        rows = await real_async_db_session.execute(
            text(
                'SELECT column_name, data_type FROM information_schema.columns '
                "WHERE table_name = 'uoms' AND column_name IN ('factor', 'rounding')"
            )
        )
        types = dict(rows.all())
        assert types == {'factor': 'numeric', 'rounding': 'numeric'}, types


class TestAConvertedQuantityIsRoundedWhereItIsComputed:
    async def test_a_third_of_a_kilo_in_grams_comes_back_rounded(
        self, real_async_db_session: AsyncSession
    ) -> None:
        """1000 g of something kept in kilograms, divided three ways.

        The stock columns hold three decimals. The conversion used to hand
        Postgres the full quotient and let the column decide — the right
        answer, arrived at by nobody's decision and invisible to the code
        that had just computed it, which then compared its own number
        against the stored one and found them different.
        """
        from app.models.product_template import ProductTemplate
        from app.services.uom_service import to_stock_uom_async

        db = real_async_db_session
        gram = await db.scalar(
            text('SELECT id FROM uoms WHERE symbol = :s').bindparams(s='g')
        )
        kilo = await db.scalar(
            text('SELECT id FROM uoms WHERE symbol = :s').bindparams(s='kg')
        )
        assert gram and kilo
        template = ProductTemplate(name='Bulk rice', uom_id=kilo)
        db.add(template)
        await db.flush()

        converted = await to_stock_uom_async(
            db,
            template.organization_id,
            template.id,
            Decimal('1000') / Decimal('3'),
            gram,
        )
        assert converted == Decimal('0.333')
        assert converted.as_tuple().exponent == -3

    async def test_a_conversion_that_needs_no_rounding_is_untouched(
        self, real_async_db_session: AsyncSession
    ) -> None:
        """The control: 500 g is half a kilo, exactly, and stays so."""
        from app.models.product_template import ProductTemplate
        from app.services.uom_service import to_stock_uom_async

        db = real_async_db_session
        gram = await db.scalar(
            text('SELECT id FROM uoms WHERE symbol = :s').bindparams(s='g')
        )
        kilo = await db.scalar(
            text('SELECT id FROM uoms WHERE symbol = :s').bindparams(s='kg')
        )
        template = ProductTemplate(name='Packed rice', uom_id=kilo)
        db.add(template)
        await db.flush()

        converted = await to_stock_uom_async(
            db, template.organization_id, template.id, Decimal('500'), gram
        )
        assert converted == Decimal('0.5')

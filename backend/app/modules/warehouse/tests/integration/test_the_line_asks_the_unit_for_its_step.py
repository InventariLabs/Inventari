"""A correction and a return ask the unit what it counts in.

``build_document_line`` — the door every line from the document form comes
through — calls ``validate_quantity_precision_async``. These two services
build their lines by hand, so they asked nobody: a correction delta of 1.5
on a line counted in pieces was saved, confirmed and executed, and half a
piece reached the quant, the movement ledger and the valuation. The stock
take then counts whole pieces and reports a 0.5 discrepancy nobody can
explain.

Both directions are measured here: the fraction a piece cannot hold is
refused, and the fraction a kilogram can hold goes through.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ServiceRejectionError
from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.uom import Uom, UomCategory
from app.models.user import User
from app.modules.warehouse.document_correction_service import create_correction
from app.modules.warehouse.document_return_service import create_return
from app.modules.warehouse.models import Document, DocumentLine, DocumentStatus


@pytest.fixture
async def step_org(real_async_db_session: AsyncSession) -> Organization:
    org = Organization(name='Unit Step Org', enabled_modules=['core', 'warehouse'])
    real_async_db_session.add(org)
    await real_async_db_session.flush()
    return org


@pytest.fixture
async def step_user(
    real_async_db_session: AsyncSession, step_org: Organization
) -> User:
    return await ModuleTestHelper.create_user_async(
        real_async_db_session, step_org, email='unit-step@example.com', role='admin'
    )


async def _unit(db: AsyncSession, name: str, symbol: str, rounding: str) -> Uom:
    category = UomCategory(name=f'{name} {uuid.uuid4().hex[:6]}')
    db.add(category)
    await db.flush()
    uom = Uom(
        category_id=category.id,
        name=name,
        symbol=symbol,
        rounding=Decimal(rounding),
    )
    db.add(uom)
    await db.flush()
    return uom


async def _completed_receipt(
    db: AsyncSession, org: Organization, user: User, uom: Uom, quantity: str
) -> Document:
    doc = Document(
        organization_id=org.id,
        type='IN',
        number=f'IN-{uuid.uuid4().hex[:8]}',
        status=DocumentStatus.COMPLETED.value,
        created_by=user.id,
    )
    doc.lines.append(
        DocumentLine(
            name='Maka pszenna typ 550',
            quantity=Decimal(quantity),
            expected_quantity=Decimal(quantity),
            done_quantity=Decimal(quantity),
            uom_id=uom.id,
            line_number=1,
        )
    )
    db.add(doc)
    await db.flush()
    return doc


@pytest.mark.integration
class TestTheCorrectionAsksTheUnit:
    @pytest.mark.asyncio
    async def test_half_a_piece_is_refused(
        self,
        real_async_db_session: AsyncSession,
        step_org: Organization,
        step_user: User,
    ) -> None:
        pcs = await _unit(real_async_db_session, 'Pieces', 'pcs', '1')
        original = await _completed_receipt(
            real_async_db_session, step_org, step_user, pcs, '3'
        )

        with pytest.raises(ServiceRejectionError) as exc:
            await create_correction(
                real_async_db_session,
                original.id,
                [{'original_line_number': 1, 'quantity_delta': Decimal('1.5')}],
                step_org.id,
                step_user.id,
            )
        assert exc.value.key == 'uom_quantity_requires_whole_number'

    @pytest.mark.asyncio
    async def test_a_negative_delta_of_whole_pieces_still_goes_through(
        self,
        real_async_db_session: AsyncSession,
        step_org: Organization,
        step_user: User,
    ) -> None:
        """A delta is signed by design; the gate measures its magnitude.

        The precision gate refuses a negative quantity outright, so passing
        the delta through unchanged would have turned every correction
        downwards into a refusal.
        """
        pcs = await _unit(real_async_db_session, 'Pieces', 'pcs', '1')
        original = await _completed_receipt(
            real_async_db_session, step_org, step_user, pcs, '3'
        )

        correction = await create_correction(
            real_async_db_session,
            original.id,
            [{'original_line_number': 1, 'quantity_delta': Decimal('-2')}],
            step_org.id,
            step_user.id,
        )
        assert correction.lines[0].quantity == Decimal('-2')

    @pytest.mark.asyncio
    async def test_a_quarter_of_a_kilogram_goes_through(
        self,
        real_async_db_session: AsyncSession,
        step_org: Organization,
        step_user: User,
    ) -> None:
        kg = await _unit(real_async_db_session, 'Kilogram', 'kg', '0.001')
        original = await _completed_receipt(
            real_async_db_session, step_org, step_user, kg, '3'
        )

        correction = await create_correction(
            real_async_db_session,
            original.id,
            [{'original_line_number': 1, 'quantity_delta': Decimal('0.25')}],
            step_org.id,
            step_user.id,
            # A surplus correction; the caller holds the over-receipt
            # permission the ramp would ask of a person.
            may_exceed_over_receipt=True,
        )
        assert correction.lines[0].quantity == Decimal('0.25')


@pytest.mark.integration
class TestTheReturnAsksTheUnit:
    @pytest.mark.asyncio
    async def test_half_a_piece_is_refused(
        self,
        real_async_db_session: AsyncSession,
        step_org: Organization,
        step_user: User,
    ) -> None:
        pcs = await _unit(real_async_db_session, 'Pieces', 'pcs', '1')
        original = await _completed_receipt(
            real_async_db_session, step_org, step_user, pcs, '3'
        )

        with pytest.raises(ServiceRejectionError) as exc:
            await create_return(
                real_async_db_session,
                original.id,
                [{'original_line_number': 1, 'return_quantity': Decimal('1.5')}],
                step_org.id,
                step_user.id,
            )
        assert exc.value.key == 'uom_quantity_requires_whole_number'

    @pytest.mark.asyncio
    async def test_a_quarter_of_a_kilogram_goes_through(
        self,
        real_async_db_session: AsyncSession,
        step_org: Organization,
        step_user: User,
    ) -> None:
        kg = await _unit(real_async_db_session, 'Kilogram', 'kg', '0.001')
        original = await _completed_receipt(
            real_async_db_session, step_org, step_user, kg, '3'
        )

        returned = await create_return(
            real_async_db_session,
            original.id,
            [{'original_line_number': 1, 'return_quantity': Decimal('0.25')}],
            step_org.id,
            step_user.id,
        )
        assert returned.lines[0].quantity == Decimal('0.25')

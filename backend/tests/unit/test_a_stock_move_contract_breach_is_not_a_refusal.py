"""A stock move built wrongly is a caller's mistake, never a sentence for a reader.

``stock_moves_service`` guarded its arguments with plain ``ValueError``, which
the 400 handler shows to the reader as written. No request supplies these
values (the ledger filter's direction is pattern-checked at the door, the
quantities come from postings that have already validated them), so the guards
raise ``ContractViolationError``: a 500 with the traceback in the log.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ContractViolationError
from app.services import stock_moves_service
from app.services.stock_moves_service import _direction_condition


def test_an_unknown_direction_is_a_contract_breach() -> None:
    with pytest.raises(ContractViolationError, match='Unknown direction'):
        _direction_condition('SIDEWAYS')


@pytest.mark.asyncio
@pytest.mark.parametrize('write', ['create_async', 'record_async'])
async def test_a_move_without_a_location_is_a_contract_breach(write: str) -> None:
    with pytest.raises(ContractViolationError, match='at least one of'):
        await getattr(stock_moves_service, write)(
            MagicMock(spec=AsyncSession),
            organization_id=uuid4(),
            product_template_id=uuid4(),
            quantity=Decimal(1),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize('write', ['create_async', 'record_async'])
@pytest.mark.parametrize('quantity', [Decimal(0), Decimal(-1), None])
async def test_a_move_of_no_quantity_is_a_contract_breach(
    write: str, quantity: Decimal | None
) -> None:
    with pytest.raises(ContractViolationError, match='quantity must be'):
        await getattr(stock_moves_service, write)(
            MagicMock(spec=AsyncSession),
            organization_id=uuid4(),
            product_template_id=uuid4(),
            quantity=quantity,
            to_location_id=uuid4(),
        )

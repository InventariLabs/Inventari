"""The trace sheet names its Source in words, as the screen does.

The stock ledger's screen says "Production" for a run and "Document" for a
receipt. The sheet handed to an inspector says the same words rather than the
ledger's keys, ``maker_production`` and ``document``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from app.core.contracts import LotTraceDTO, LotTraceEntryDTO, LotTraceLotDTO
from app.services.lot_trace_service import trace_to_export_frame

WORDS = {
    'document': 'Document',
    'item': 'By hand',
    'adjustment': 'Stock take',
    'maker_production': 'Production',
    'recipe_picking': 'Cooking',
    'item_history': 'Historical record',
    'opening_balance': 'Opening balance',
    'location_relocation': 'Moved with location',
}


def _frame(reference_type: str | None):
    entry = LotTraceEntryDTO(
        direction='in',
        reference_type=reference_type,
        moved_at=datetime(2026, 11, 1, tzinfo=UTC),
        quantity=Decimal('1'),
    )
    lot = LotTraceLotDTO(lot_id=uuid4(), lot_name='L-1', received=[entry])
    trace = LotTraceDTO(lot_id=lot.lot_id, lots=[lot])
    return trace_to_export_frame(trace, UTC)


@pytest.mark.parametrize(('reference_type', 'word'), sorted(WORDS.items()))
def test_a_known_source_prints_the_screens_word(reference_type: str, word: str) -> None:
    assert _frame(reference_type)['Source'][0] == word


def test_a_source_nobody_named_prints_as_the_ledger_wrote_it() -> None:
    """A module's own reference type is not guessed at or blanked."""
    assert _frame('some_module_act')['Source'][0] == 'some_module_act'

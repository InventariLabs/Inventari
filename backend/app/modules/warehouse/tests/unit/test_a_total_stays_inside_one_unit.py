"""A printed quantity total means something only inside one unit.

Found reviewing the PDF localisation work: a PZ receipt of 123 pieces and
2.5 kilograms printed "125,5" under Zamówiono — a sum of pieces and
kilograms that means nothing to the person signing the receipt. The totals
row prints one total per unit when the document carries more than one, and
the single sum when every line shares a unit.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest

from app.models.uom import Uom
from app.modules.warehouse.document_pdf_service import _svc, build_pdf_context
from app.modules.warehouse.models import Document, DocumentLine


def _line(number: int, symbol: str | None, expected: str, done: str) -> DocumentLine:
    line = DocumentLine(
        name=f'Line {number}',
        quantity=Decimal(expected),
        expected_quantity=Decimal(expected),
        done_quantity=Decimal(done),
        line_number=number,
    )
    if symbol is not None:
        line.uom = Uom(name=symbol, symbol=symbol)
    return line


def _render(*lines: DocumentLine) -> str:
    """The pl_pz printout of a confirmed receipt made of ``lines``."""
    doc = Document(
        organization_id=UUID('00000000-0000-0000-0000-000000000001'),
        type='IN',
        number='IN/2026/001',
        status='CONFIRMED',
    )
    doc.lines.extend(lines)
    context = build_pdf_context(doc, None, lang='pl')
    return _svc.render_filesystem_template('pl_pz.html', context)


@pytest.mark.unit
class TestATotalStaysInsideOneUnit:
    def test_a_mixed_unit_receipt_prints_one_total_per_unit(self) -> None:
        """The case the fix is for — prints "125,5" without it."""
        html = _render(
            _line(1, 'pcs', '123', '123'),
            _line(2, 'kg', '2.5', '0'),
        )

        assert '125,5' not in html, 'pieces and kilograms were added up'
        assert '123&nbsp;szt.' in html
        assert '2,5&nbsp;kg' in html
        assert '0&nbsp;kg' in html

    def test_a_one_unit_receipt_keeps_its_single_sum(self) -> None:
        """A guard, not a red-before test: the single sum printed before the
        fix too, and must keep printing — the fix only takes away the sum
        that crosses units.
        """
        html = _render(
            _line(1, 'pcs', '100', '25'),
            _line(2, 'pcs', '25', '0'),
        )

        assert '>125<' in html

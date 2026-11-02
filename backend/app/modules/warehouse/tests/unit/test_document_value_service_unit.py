from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from app.modules.warehouse.document_value_service import (
    compute_document_totals,
    compute_line_gross,
    compute_line_tax,
    compute_line_value,
    compute_line_values,
    recompute_document_values,
)


def _make_line(
    *,
    expected_quantity: Decimal = Decimal('10'),
    unit_price: Decimal | None = None,
    tax_rate: Decimal | None = None,
) -> MagicMock:
    line = MagicMock()
    line.expected_quantity = expected_quantity
    line.unit_price = unit_price
    line.tax_rate = tax_rate
    line.line_value = None
    line.line_tax = None
    line.line_gross = None
    return line


def _make_doc(lines: list[MagicMock]) -> MagicMock:
    doc = MagicMock()
    doc.lines = lines
    doc.total_net = None
    doc.total_tax = None
    doc.total_gross = None
    return doc


@pytest.mark.unit
class TestComputeLineValue:
    def test_returns_none_when_no_unit_price(self) -> None:
        line = _make_line(expected_quantity=Decimal('10'), unit_price=None)
        assert compute_line_value(line) is None

    def test_multiplies_quantity_by_price(self) -> None:
        line = _make_line(expected_quantity=Decimal('10'), unit_price=Decimal('5.50'))
        assert compute_line_value(line) == Decimal('55.00')

    def test_quantizes_to_two_places(self) -> None:
        line = _make_line(expected_quantity=Decimal('3'), unit_price=Decimal('1.333'))
        assert compute_line_value(line) == Decimal('4.00')

    def test_zero_quantity(self) -> None:
        line = _make_line(expected_quantity=Decimal('0'), unit_price=Decimal('10.00'))
        assert compute_line_value(line) == Decimal('0.00')

    def test_fractional_quantity(self) -> None:
        line = _make_line(expected_quantity=Decimal('2.5'), unit_price=Decimal('4.00'))
        assert compute_line_value(line) == Decimal('10.00')


@pytest.mark.unit
class TestComputeLineTax:
    def test_returns_none_when_value_is_none(self) -> None:
        assert compute_line_tax(None, Decimal('23')) is None

    def test_returns_none_when_rate_is_none(self) -> None:
        assert compute_line_tax(Decimal('100'), None) is None

    def test_calculates_tax(self) -> None:
        assert compute_line_tax(Decimal('100.00'), Decimal('23')) == Decimal('23.00')

    def test_quantizes_tax(self) -> None:
        assert compute_line_tax(Decimal('100.00'), Decimal('8.5')) == Decimal('8.50')

    def test_zero_rate(self) -> None:
        assert compute_line_tax(Decimal('100.00'), Decimal('0')) == Decimal('0.00')


@pytest.mark.unit
class TestComputeLineGross:
    def test_returns_none_when_value_is_none(self) -> None:
        assert compute_line_gross(None, Decimal('23')) is None

    def test_falls_back_to_the_net_when_there_is_no_tax(self) -> None:
        assert compute_line_gross(Decimal('100'), None) == Decimal('100')

    def test_adds_value_and_tax(self) -> None:
        assert compute_line_gross(Decimal('100.00'), Decimal('23.00')) == Decimal(
            '123.00'
        )

    def test_quantizes_gross(self) -> None:
        assert compute_line_gross(Decimal('100.00'), Decimal('8.55')) == Decimal(
            '108.55'
        )


@pytest.mark.unit
class TestComputeLineValues:
    def test_sets_all_three_fields(self) -> None:
        line = _make_line(
            expected_quantity=Decimal('10'),
            unit_price=Decimal('5.00'),
            tax_rate=Decimal('23'),
        )
        compute_line_values(line)
        assert line.line_value == Decimal('50.00')
        assert line.line_tax == Decimal('11.50')
        assert line.line_gross == Decimal('61.50')

    def test_sets_none_when_no_price(self) -> None:
        line = _make_line(
            expected_quantity=Decimal('10'),
            unit_price=None,
            tax_rate=Decimal('23'),
        )
        compute_line_values(line)
        assert line.line_value is None
        assert line.line_tax is None
        assert line.line_gross is None

    def test_gross_equals_net_when_no_rate(self) -> None:
        line = _make_line(
            expected_quantity=Decimal('10'),
            unit_price=Decimal('5.00'),
            tax_rate=None,
        )
        compute_line_values(line)
        assert line.line_value == Decimal('50.00')
        assert line.line_tax is None
        assert line.line_gross == Decimal('50.00')


@pytest.mark.unit
class TestComputeDocumentTotals:
    def test_sets_none_when_no_lines_have_values(self) -> None:
        line1 = _make_line(unit_price=None)
        line1.line_value = None
        line1.line_tax = None
        line1.line_gross = None
        doc = _make_doc([line1])
        compute_document_totals(doc)
        assert doc.total_net is None
        assert doc.total_tax is None
        assert doc.total_gross is None

    def test_sums_values_across_lines(self) -> None:
        line1 = _make_line()
        line1.line_value = Decimal('100.00')
        line1.line_tax = Decimal('23.00')
        line1.line_gross = Decimal('123.00')
        line2 = _make_line()
        line2.line_value = Decimal('50.00')
        line2.line_tax = Decimal('11.50')
        line2.line_gross = Decimal('61.50')
        doc = _make_doc([line1, line2])
        compute_document_totals(doc)
        assert doc.total_net == Decimal('150.00')
        assert doc.total_tax == Decimal('34.50')
        assert doc.total_gross == Decimal('184.50')

    def test_handles_mixed_none_and_value_lines(self) -> None:
        line1 = _make_line()
        line1.line_value = Decimal('100.00')
        line1.line_tax = Decimal('23.00')
        line1.line_gross = Decimal('123.00')
        line2 = _make_line(unit_price=None)
        line2.line_value = None
        line2.line_tax = None
        line2.line_gross = None
        doc = _make_doc([line1, line2])
        compute_document_totals(doc)
        assert doc.total_net == Decimal('100.00')
        assert doc.total_tax == Decimal('23.00')
        assert doc.total_gross == Decimal('123.00')

    def test_untaxed_document_totals_gross_at_its_net(self) -> None:
        """Priced lines, no tax rate anywhere — the shape the list reads."""
        line1 = _make_line(
            expected_quantity=Decimal('10'),
            unit_price=Decimal('5.00'),
            tax_rate=None,
        )
        line2 = _make_line(
            expected_quantity=Decimal('4'),
            unit_price=Decimal('2.25'),
            tax_rate=None,
        )
        doc = _make_doc([line1, line2])
        recompute_document_values(doc)
        assert doc.total_net == Decimal('59.00')
        assert doc.total_tax == Decimal('0.00')
        assert doc.total_gross == Decimal('59.00')

    def test_empty_lines_list(self) -> None:
        doc = _make_doc([])
        compute_document_totals(doc)
        assert doc.total_net is None


@pytest.mark.unit
class TestRecomputeDocumentValues:
    def test_recomputes_all_lines_and_totals(self) -> None:
        line1 = _make_line(
            expected_quantity=Decimal('10'),
            unit_price=Decimal('5.00'),
            tax_rate=Decimal('23'),
        )
        line2 = _make_line(
            expected_quantity=Decimal('20'),
            unit_price=Decimal('2.50'),
            tax_rate=Decimal('8'),
        )
        doc = _make_doc([line1, line2])
        recompute_document_values(doc)
        assert line1.line_value == Decimal('50.00')
        assert line2.line_value == Decimal('50.00')
        assert doc.total_net == Decimal('100.00')

from decimal import Decimal

from app.core.money import quantise

from .document_types import is_scrap
from .models import Document, DocumentLine

# ``None`` here means "not known", not "zero": a line without a price has no
# value at all — which is why these keep their own nullable shape instead of
# calling ``money.line_amounts``, where a missing input counts as zero. The
# rounding is the shared one. A missing *tax rate* is the one thing that is
# not unknown: it means no tax is charged, so the gross falls back to the net
# (see ``compute_line_gross``) while the tax itself stays unstated.


def valued_quantity(line: DocumentLine, *, executed: bool) -> Decimal:
    """What the line's value is computed from.

    While the document is a plan its value is what it plans; once it is
    executed its value is what it did. Both readings existed in the code
    already — the landed-cost allocation makes the same distinction, for the
    same reason — but the value on the document itself only ever used the
    plan, and nothing recomputed it at completion. A delivery of sixty
    against an order of a hundred stayed in the register at the value of a
    hundred, and the figure the approval threshold reads with it.
    """
    return line.done_quantity if executed else line.expected_quantity


def compute_line_value(line: DocumentLine, *, executed: bool = False) -> Decimal | None:
    if line.unit_price is None:
        return None
    return quantise(valued_quantity(line, executed=executed) * line.unit_price)


def compute_line_tax(
    line_value: Decimal | None, tax_rate: Decimal | None
) -> Decimal | None:
    if line_value is None or tax_rate is None:
        return None
    return quantise(line_value * tax_rate / Decimal('100'))


def compute_line_gross(
    line_value: Decimal | None, line_tax: Decimal | None
) -> Decimal | None:
    """What the line costs in total — which, untaxed, is what it costs net.

    A profile without ``tax_handling=SIMPLE_RATE`` leaves every ``tax_rate``
    empty, so a whole document arrives here with ``line_tax`` at ``None``.
    That is "no tax is charged", not "the gross is unknown" — and reading it
    as unknown left the register showing 0.00 next to a document worth
    thirty-five thousand, because the list prices documents by their gross.
    """
    if line_value is None:
        return None
    if line_tax is None:
        return line_value
    return quantise(line_value + line_tax)


def compute_line_values(line: DocumentLine, *, executed: bool = False) -> None:
    line_value = compute_line_value(line, executed=executed)
    line_tax = compute_line_tax(line_value, line.tax_rate)
    line_gross = compute_line_gross(line_value, line_tax)
    line.line_value = line_value
    line.line_tax = line_tax
    line.line_gross = line_gross


def compute_document_totals(doc: Document) -> None:
    total_net = Decimal('0.00')
    total_tax = Decimal('0.00')
    total_gross = Decimal('0.00')
    has_values = False

    for line in doc.lines:
        if line.line_value is not None:
            has_values = True
            total_net += line.line_value
        if line.line_tax is not None:
            total_tax += line.line_tax
        if line.line_gross is not None:
            total_gross += line.line_gross

    if has_values:
        doc.total_net = quantise(total_net)
        doc.total_tax = quantise(total_tax)
        doc.total_gross = quantise(total_gross)
    else:
        doc.total_net = None
        doc.total_tax = None
        doc.total_gross = None


def recompute_document_values(doc: Document, *, executed: bool = False) -> None:
    for line in doc.lines:
        if executed and is_scrap(doc.type) and line.done_quantity:
            # A write-off is worth what the cost layers it drew were worth —
            # written by the executor, not derived from a price on the line.
            continue
        compute_line_values(line, executed=executed)
    compute_document_totals(doc)

"""PDF/HTML render-context builder for Purchase Orders.

Extracted from ``_router_po.py`` to keep that file under the 400-LOC lint
limit. This is the SINGLE context builder for both output paths — the HTML
preview endpoint and ``generate_po_pdf`` render the same template with the
same context, so a placeholder that works in one works in both (
follow-up: the two builders used to drift apart, e.g. ``tax_pct`` existed
only in the PDF and ``po_title`` only in the preview).

PDF helpers go through ``core_api.pdf`` — no direct
``app.services`` imports in module code.
"""

from __future__ import annotations

from typing import Any

from app.core.datetimes import format_date_for
from app.core.money import ZERO, amounts_by_rate, line_amounts
from app.core.print_identity import IssuerContext, print_date_rows
from app.core.public_api import core_api

from .po_pdf_service import get_po_labels


class AmountNotKnown:
    """An amount no line price lets anyone state, as a template meets it.

    It prints its words, under ``{{ total_net }}`` and under the
    ``format_decimal`` every layout runs an amount through, so a layout says
    what the screens say without a change, a copy already saved included.

    An organization's template may also calculate with a total it was only
    ever tested on with prices. Anything calculated from this stays not known,
    and no comparison holds, which is why it is not ``None`` or a plain string:
    those stop the whole print with a ``TypeError`` at the first ``+`` or ``>``.
    Floating-point formatting has no words to offer and prints ``nan``.
    """

    def __init__(self, words: str) -> None:
        self._words = words

    def __str__(self) -> str:
        return self._words

    def __bool__(self) -> bool:
        return False

    def __float__(self) -> float:
        return float('nan')

    def _stays_not_known(self, *_: object) -> AmountNotKnown:
        return self

    def _does_not_hold(self, _other: object) -> bool:
        return False

    __add__ = __radd__ = __sub__ = __rsub__ = _stays_not_known
    __mul__ = __rmul__ = __truediv__ = __rtruediv__ = _stays_not_known
    __mod__ = __rmod__ = __floordiv__ = __rfloordiv__ = _stays_not_known
    __pow__ = __rpow__ = __round__ = __abs__ = __neg__ = _stays_not_known
    __lt__ = __le__ = __gt__ = __ge__ = _does_not_hold


#: A line without a price prints the dash its unit price already prints, as the
#: order's lines do on screen; the column is too narrow for the sentence.
_NO_LINE_AMOUNT = AmountNotKnown('—')


def _line_row(line: Any) -> dict[str, Any]:
    row: dict[str, Any] = {'line': line, 'tax_pct': line.tax_rate}
    if line.unit_price is None:
        return {
            **row,
            'net': _NO_LINE_AMOUNT,
            'tax': _NO_LINE_AMOUNT,
            'gross': _NO_LINE_AMOUNT,
        }
    # Unrounded on purpose: the template rounds once, at the total.
    amounts = line_amounts(
        line.quantity_ordered, line.unit_price, line.tax_rate, places=None
    )
    return {**row, 'net': amounts.net, 'tax': amounts.tax, 'gross': amounts.gross}


def _totals(rows: list[dict[str, Any]], labels: dict[str, str]) -> dict[str, Any]:
    """The order's totals and its amounts per rate.

    One line without a price leaves the order without any of them, the way the
    order's schema and its approval rule read it: what the priced lines add up
    to is not what the order is worth.
    """
    if any(row['net'] is _NO_LINE_AMOUNT for row in rows):
        not_known = AmountNotKnown(labels['no_price_yet'])
        return {
            'total_net': not_known,
            'total_tax': not_known,
            'total_gross': not_known,
            'tax_by_rate': [],
        }
    return {
        'total_net': sum((row['net'] for row in rows), ZERO),
        'total_tax': sum((row['tax'] for row in rows), ZERO),
        'total_gross': sum((row['gross'] for row in rows), ZERO),
        # A reduced rate on some lines and the standard one on others: the
        # amounts per rate, rounded once per rate like the totals.
        'tax_by_rate': amounts_by_rate(
            (row['tax_pct'], row['net'], row['tax']) for row in rows
        ),
    }


def build_po_context(
    po: Any, lang: str, issuer: IssuerContext | None = None
) -> dict[str, Any]:
    """Return the template render context for a Purchase Order.

    ``issuer`` supplies the letterhead the shared header prints. When
    it is absent — the HTML preview, which renders without reading the
    organization's logo from storage — the identity falls back to what the
    order itself knows, so the preview shows the same block minus the image
    rather than an empty one.
    """
    labels = get_po_labels(lang)
    partner = po.partner
    partner_ctx = {
        'name': partner.name if partner else None,
        'tax_id': getattr(partner, 'tax_id', None),
        'address': core_api.pdf.format_partner_address(
            getattr(partner, 'address', None) if partner else None, lang
        ),
    }
    lines_data = [_line_row(line) for line in po.lines]
    status_map = core_api.pdf.get_doc_status_map(lang)
    issuer = issuer or IssuerContext.from_organization(po.organization, lang)
    country = getattr(po.organization, 'country', None)
    return {
        'po': po,
        'partner': partner_ctx,
        'issuer': issuer,
        'labels': labels,
        'lang': lang,
        # The shared header — the same names every print family reads.
        'print_title': labels['document'],
        'print_subtitle': None,
        'print_number': po.number,
        'print_status': status_map.get(po.status, po.status),
        'print_dates': print_date_rows(
            [
                (labels['created'], po.created_at),
                (labels['date'], po.scheduled_date),
            ],
            lang,
            country,
        ),
        # The two dates the info block prints outside the shared header, in
        # the document's own language — the template used the Polish-shaped
        # filter whatever language the order was printed in.
        'scheduled_date_text': format_date_for(
            lang, po.scheduled_date or po.created_at, country=country
        ),
        'created_at_text': format_date_for(lang, po.created_at, country=country),
        'lines': lines_data,
        **_totals(lines_data, labels),
        # Same geometry as the warehouse-document families: this one
        # printed the size the documented measurement had already rejected,
        # because it kept its own copy of the rule.
        **core_api.pdf.printed_codes(po.number),
        'doc_status_map': status_map,
        # The advertised {{po_title}} placeholder — localized, not an English
        # literal: ``labels['document']`` already carries the title in five
        # languages ( follow-up).
        'po_title': labels['document'],
        'currency': po.currency or '',
        'organization_name': po.organization.name if po.organization else '',
    }

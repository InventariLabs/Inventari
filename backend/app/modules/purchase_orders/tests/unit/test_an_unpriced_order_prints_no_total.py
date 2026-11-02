"""An order whose total nobody can state does not print one.

The screens say "No price yet" for such an order, and the approval rule refuses
to call it below any limit. The printout summed a missing price as zero, so the
paper sent to a supplier said 0.00, or a partial sum, about the same order.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import pytest

from app.core.public_api import core_api
from app.modules.purchase_orders._po_render_context import build_po_context
from app.modules.purchase_orders.po_pdf_service import _svc, generate_po_pdf

pytestmark = pytest.mark.unit

#: The words the order's card and list use (``noPriceYet``), language by language.
NO_PRICE_YET = {
    'en': 'No price yet',
    'pl': 'Jeszcze bez ceny',
    'de': 'Noch kein Preis',
    'fr': 'Pas encore de prix',
    'es': 'Aún sin precio',
}


def _line(price: str | None, rate: str = '23') -> SimpleNamespace:
    return SimpleNamespace(
        name='Flour',
        product_template=None,
        uom=None,
        quantity_ordered=Decimal('10'),
        quantity_received=Decimal('0'),
        unit_price=None if price is None else Decimal(price),
        tax_rate=Decimal(rate),
        line_number=1,
        notes=None,
    )


def _order(*prices: str | None) -> Any:
    return SimpleNamespace(
        id=uuid4(),
        number='PO/2026/0011',
        currency='EUR',
        status='DRAFT',
        created_at=datetime(2026, 10, 27, 9, 0),
        scheduled_date=None,
        notes=None,
        organization=SimpleNamespace(name='Bakery GmbH'),
        partner=SimpleNamespace(name='Mill', tax_id=None, address=None),
        lines=[_line(price) for price in prices],
    )


async def _printed(po: Any, lang: str) -> str:
    with patch.object(_svc, 'render_to_pdf', return_value=b'%PDF') as render:
        await generate_po_pdf(po, lang=lang)
    html: str = render.call_args[0][0]
    return html


class TestTheBuiltInLayout:
    @pytest.mark.parametrize(('lang', 'words'), NO_PRICE_YET.items())
    async def test_says_what_the_screens_say_in_every_language(
        self, lang: str, words: str
    ) -> None:
        html = await _printed(_order(None), lang)

        # Net, tax and gross: all three are unknown, none is a zero.
        assert html.count(words) == 3
        assert '0.00' not in html
        assert '0,00' not in html

    async def test_a_partly_priced_order_prints_no_partial_sum(self) -> None:
        html = await _printed(_order('2.50', None), 'en')

        # The priced line keeps its own amounts, and its gross appears only on
        # that line: the footer used to repeat it as the order's total.
        assert '25.00' in html
        assert html.count('30.75') == 1
        assert html.count('No price yet') == 3

    async def test_a_partly_priced_order_keeps_no_table_of_rates(self) -> None:
        po = _order('2.50', None)
        po.lines[0].tax_rate = Decimal('7')

        assert build_po_context(po, 'en')['tax_by_rate'] == []
        assert '<table class="tax-by-rate">' not in await _printed(po, 'en')

    async def test_a_fully_priced_order_is_unchanged(self) -> None:
        po = _order('10.00')

        context = build_po_context(po, 'en')

        assert context['total_net'] == Decimal('100.00')
        assert context['total_tax'] == Decimal('23.00')
        assert context['total_gross'] == Decimal('123.00')
        assert context['lines'][0]['net'] == Decimal('100.00')
        html = await _printed(po, 'en')
        assert '123.00' in html
        assert 'No price yet' not in html

    def test_an_order_priced_at_zero_is_a_total_of_zero(self) -> None:
        assert build_po_context(_order('0'), 'en')['total_gross'] == Decimal('0')


class TestAnOrganizationsOwnTemplate:
    """The sandboxed engine an organization's template runs in, and what it meets."""

    @staticmethod
    def _render(body: str, *prices: str | None) -> str:
        context = build_po_context(_order(*prices), 'en')
        return core_api.pdf.render_html(body, context).strip()

    @pytest.mark.parametrize('placeholder', ['total_net', 'total_tax', 'total_gross'])
    def test_a_placeholder_prints_the_words(self, placeholder: str) -> None:
        assert self._render(f'{{{{{placeholder}}}}}', None) == 'No price yet'
        assert (
            self._render(f'{{{{{placeholder}|format_decimal}}}}', None)
            == 'No price yet'
        )

    @pytest.mark.parametrize(
        ('expression', 'printed'),
        [
            ('{{ total_gross + 10 }}', 'No price yet'),
            ('{{ 10 + total_gross }}', 'No price yet'),
            ('{{ total_net * 1.23 }}', 'No price yet'),
            ('{{ total_net / 2 }}', 'No price yet'),
            ('{{ total_net - total_tax }}', 'No price yet'),
            ('{{ total_net % 2 }}', 'No price yet'),
            ('{{ total_net // 2 }}', 'No price yet'),
            ('{{ total_net ** 2 }}', 'No price yet'),
            ('{{ -total_net }}', 'No price yet'),
            ('{{ total_gross|round(2) }}', 'No price yet'),
            ('{{ total_gross|abs }}', 'No price yet'),
            ('{% if total_gross > 1000 %}big{% else %}small{% endif %}', 'small'),
            ('{% if total_gross <= 1000 %}small{% else %}big{% endif %}', 'big'),
            ('{% if total_gross %}some{% else %}none{% endif %}', 'none'),
            ("{{ lines|sum(attribute='net') }}", '—'),
            ('{% for row in lines %}{{ row.net }}{% endfor %}', '—'),
            ('{% for row in lines %}{{ row.gross|format_decimal }}{% endfor %}', '—'),
        ],
    )
    def test_a_calculation_on_it_does_not_stop_the_print(
        self, expression: str, printed: str
    ) -> None:
        assert self._render(expression, None) == printed

    def test_the_usual_money_format_does_not_stop_the_print(self) -> None:
        assert self._render("{{ '%.2f'|format(total_gross) }}", None) == 'nan'

    def test_a_known_total_stays_a_number_to_calculate_with(self) -> None:
        assert self._render('{{ total_gross + 1 }}', '10.00') == '124.00'

    def test_a_seeded_copy_of_the_layout_prints_the_words(self) -> None:
        path = _svc.templates_dir / 'po_standard.html'
        html = core_api.pdf.render_html(
            path.read_text(encoding='utf-8'),
            build_po_context(_order(None), 'en'),
            templates_dir=_svc.templates_dir,
        )

        assert html.count('No price yet') == 3
        assert '0.00' not in html

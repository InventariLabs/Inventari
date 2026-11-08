from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.core.public_api import core_api
from app.modules.purchase_orders._po_render_context import build_po_context
from app.modules.purchase_orders._router_templates import PO_PLACEHOLDERS
from app.modules.purchase_orders.po_pdf_service import _svc, generate_po_pdf


@pytest.mark.unit
class TestGeneratePoPdf:
    @pytest.mark.asyncio
    async def test_generates_pdf_with_filesystem_template(self) -> None:
        po = MagicMock()
        po.id = uuid4()
        po.number = 'PO/2025/0001'
        po.partner = MagicMock()
        po.partner.name = 'Supplier A'
        po.partner.tax_id = '123'
        po.partner.address = None
        po.lines = []
        with patch('app.modules.purchase_orders.po_pdf_service._svc') as mock_svc:
            mock_svc.get_labels.return_value = {
                'document': 'Purchase Order',
                'created': 'Created',
                'date': 'Date',
            }
            mock_svc.try_db_template = AsyncMock(return_value=None)
            mock_svc.render_filesystem_template = MagicMock(
                return_value='<html></html>'
            )
            mock_svc.render_to_pdf = MagicMock(return_value=b'%PDF-1.4')
            result = await generate_po_pdf(po, lang='en')
        assert result == b'%PDF-1.4'
        mock_svc.render_to_pdf.assert_called_once()

    @pytest.mark.asyncio
    async def test_uses_db_template_when_available(self) -> None:
        po = MagicMock()
        po.id = uuid4()
        po.number = 'PO/2025/0002'
        po.partner = None
        po.lines = []
        db = MagicMock()
        # The paper the organization prints on is read through the session
        # (a two-column select, awaited) — the mock answers it like a row.
        db.execute = AsyncMock(
            return_value=SimpleNamespace(
                first=lambda: SimpleNamespace(print_page_size=None, country='PL')
            )
        )
        org_id = uuid4()
        with patch('app.modules.purchase_orders.po_pdf_service._svc') as mock_svc:
            mock_svc.get_labels.return_value = {
                'document': 'PO',
                'created': 'Created',
                'date': 'Date',
            }
            mock_svc.render_to_pdf = MagicMock(return_value=b'%PDF-DB')
            # Queried directly on the AsyncSession now — no db.run_sync detour
            # parking a greenlet to reach a sync twin.
            mock_svc.try_db_template = AsyncMock(
                return_value='<html>DB template</html>'
            )
            result = await generate_po_pdf(po, lang='pl', db=db, org_id=org_id)
        assert result == b'%PDF-DB'
        mock_svc.try_db_template.assert_awaited_once()
        db.run_sync.assert_not_called()

    @pytest.mark.asyncio
    async def test_computes_line_totals(self) -> None:
        po = MagicMock()
        po.id = uuid4()
        po.number = 'PO/2025/0003'
        po.partner = MagicMock()
        po.partner.name = 'Supplier'
        po.partner.tax_id = None
        po.partner.address = None
        line = MagicMock()
        line.unit_price = Decimal('100')
        line.tax_rate = Decimal('23')
        line.quantity_ordered = Decimal('10')
        po.lines = [line]
        with patch('app.modules.purchase_orders.po_pdf_service._svc') as mock_svc:
            mock_svc.get_labels.return_value = {
                'document': 'Purchase Order',
                'created': 'Created',
                'date': 'Date',
            }
            mock_svc.try_db_template = AsyncMock(return_value=None)
            mock_svc.render_filesystem_template = MagicMock(
                return_value='<html></html>'
            )
            mock_svc.render_to_pdf = MagicMock(return_value=b'%PDF')
            result = await generate_po_pdf(po, lang='en')
        assert result == b'%PDF'
        call_args = mock_svc.render_filesystem_template.call_args
        ctx = call_args[1] if call_args[1] else call_args[0][1]
        assert ctx['total_net'] == Decimal('1000')
        assert ctx['total_tax'] == Decimal('230')
        assert ctx['total_gross'] == Decimal('1230')

    @pytest.mark.asyncio
    async def test_context_carries_currency_and_organization_name(self) -> None:
        po = MagicMock()
        po.id = uuid4()
        po.number = 'PO/2025/0006'
        po.currency = 'PLN'
        po.organization = MagicMock()
        po.organization.name = 'Acme Sp. z o.o.'
        po.partner = MagicMock()
        po.partner.name = 'Supplier'
        po.partner.tax_id = None
        po.partner.address = None
        po.lines = []
        with patch('app.modules.purchase_orders.po_pdf_service._svc') as mock_svc:
            mock_svc.get_labels.return_value = {
                'document': 'Purchase Order',
                'created': 'Created',
                'date': 'Date',
            }
            mock_svc.try_db_template = AsyncMock(return_value=None)
            mock_svc.render_filesystem_template = MagicMock(
                return_value='<html></html>'
            )
            mock_svc.render_to_pdf = MagicMock(return_value=b'%PDF')
            await generate_po_pdf(po, lang='en')
        call_args = mock_svc.render_filesystem_template.call_args
        ctx = call_args[1] if call_args[1] else call_args[0][1]
        assert ctx['currency'] == 'PLN'
        assert ctx['organization_name'] == 'Acme Sp. z o.o.'

    @pytest.mark.parametrize(
        ('country', 'written'), [('GB', '3 Apr 2025'), ('US', 'Apr 3, 2025')]
    )
    def test_english_dates_follow_the_organization_country(
        self, country: str, written: str
    ) -> None:
        from datetime import datetime

        from app.modules.purchase_orders._po_render_context import build_po_context

        po = MagicMock()
        po.number = 'PO/2025/0007'
        po.status = 'draft'
        po.currency = 'GBP'
        po.created_at = datetime(2025, 4, 3, 9, 0)
        po.scheduled_date = None
        po.organization = MagicMock()
        po.organization.country = country
        po.organization.address = None
        po.partner = None
        po.lines = []
        ctx = build_po_context(po, 'en')
        assert ctx['created_at_text'] == written

    @pytest.mark.asyncio
    async def test_rendered_template_contains_organization_and_currency(self) -> None:
        """The HTML (not just the context) carries the org name and currency.

        ``render_to_pdf`` is mocked so WeasyPrint never runs; the filesystem
        template is rendered for real, and the value must survive the render.
        """
        po = SimpleNamespace(
            id=uuid4(),
            number='PO/2025/0007',
            currency='PLN',
            status='DRAFT',
            scheduled_date=None,
            created_at=datetime(2026, 1, 1),
            notes=None,
            partner=SimpleNamespace(name='Supplier A', tax_id=None, address=None),
            organization=SimpleNamespace(name='Acme Sp. z o.o.'),
            lines=[],
        )
        with patch.object(_svc, 'render_to_pdf', return_value=b'%PDF') as mock_render:
            # SimpleNamespace stands in for the ORM row — the service only reads
            # a handful of attributes, so the full model type is unnecessary here.
            result = await generate_po_pdf(po, lang='en')  # type: ignore[arg-type]

        assert result == b'%PDF'
        html = mock_render.call_args[0][0]
        assert 'Acme Sp. z o.o.' in html
        assert 'PLN' in html

    @pytest.mark.asyncio
    async def test_passes_no_db_when_not_provided(self) -> None:
        po = MagicMock()
        po.id = uuid4()
        po.number = 'PO/2025/0004'
        po.partner = MagicMock()
        po.partner.name = None
        po.partner.tax_id = None
        po.partner.address = None
        po.lines = []
        with patch('app.modules.purchase_orders.po_pdf_service._svc') as mock_svc:
            mock_svc.get_labels.return_value = {
                'document': 'Purchase Order',
                'created': 'Created',
                'date': 'Date',
            }
            mock_svc.try_db_template = AsyncMock(return_value=None)
            mock_svc.render_filesystem_template = MagicMock(
                return_value='<html></html>'
            )
            mock_svc.render_to_pdf = MagicMock(return_value=b'%PDF')
            await generate_po_pdf(po, lang='en')
        mock_svc.try_db_template.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_polish_labels_used(self) -> None:
        po = MagicMock()
        po.id = uuid4()
        po.number = 'PO/2025/0005'
        po.partner = MagicMock()
        po.partner.name = 'Dostawca'
        po.partner.tax_id = None
        po.partner.address = None
        po.lines = []
        with patch('app.modules.purchase_orders.po_pdf_service._svc') as mock_svc:
            mock_svc.get_labels.return_value = {
                'document': 'Zamówienie',
                'created': 'Created',
                'date': 'Date',
            }
            mock_svc.try_db_template = AsyncMock(return_value=None)
            mock_svc.render_filesystem_template = MagicMock(
                return_value='<html></html>'
            )
            mock_svc.render_to_pdf = MagicMock(return_value=b'%PDF')
            await generate_po_pdf(po, lang='pl')
        mock_svc.get_labels.assert_called_with('pl')

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ('lang', 'expected'),
        [
            ('de', 'Bestellung'),
            ('fr', 'Commande fournisseur'),
            ('es', 'Pedido de compra'),
        ],
    )
    async def test_german_french_spanish_labels_used(
        self, lang: str, expected: str
    ) -> None:
        po = MagicMock()
        po.id = uuid4()
        po.number = 'PO/2025/0006'
        po.partner = MagicMock()
        po.partner.name = 'Lieferant'
        po.partner.tax_id = None
        po.partner.address = None
        po.lines = []
        with patch('app.modules.purchase_orders.po_pdf_service._svc') as mock_svc:
            mock_svc.get_labels.return_value = {
                'document': expected,
                'created': 'Created',
                'date': 'Date',
            }
            mock_svc.try_db_template = AsyncMock(return_value=None)
            mock_svc.render_filesystem_template = MagicMock(
                return_value='<html></html>'
            )
            mock_svc.render_to_pdf = MagicMock(return_value=b'%PDF')
            await generate_po_pdf(po, lang=lang)
        mock_svc.get_labels.assert_called_with(lang)

    def test_build_po_context_carries_labels_and_status_map(self) -> None:
        """HTML preview context has labels + status map like the PDF context."""
        po = SimpleNamespace(
            id=uuid4(),
            number='PO/2025/0008',
            currency='PLN',
            status='DRAFT',
            created_at=datetime(2026, 8, 23, 9, 0),
            scheduled_date=None,
            organization=SimpleNamespace(name='Acme Sp. z o.o.'),
            partner=SimpleNamespace(name='Supplier A', tax_id=None, address=None),
            lines=[],
        )
        context = build_po_context(po, lang='pl')
        assert context['labels']['document'] == 'Zamówienie zakupowe'
        assert context['labels']['partner'] == 'Dostawca'
        assert context['doc_status_map']['DRAFT'] == 'Projekt'
        # follow-up: po_title is the localized label, not an English
        # literal — and tax_pct rides every line so the template's VAT column
        # prints the line rate instead of 0.00%.
        assert context['po_title'] == 'Zamówienie zakupowe'

    def test_build_po_context_lines_carry_tax_pct(self) -> None:
        """The VAT column needs tax_pct per line — it used to render 0.00%."""
        po = SimpleNamespace(
            id=uuid4(),
            number='PO/2025/0009',
            currency='PLN',
            status='DRAFT',
            created_at=datetime(2026, 8, 23, 9, 0),
            scheduled_date=None,
            organization=SimpleNamespace(name='Acme Sp. z o.o.'),
            partner=SimpleNamespace(name='Supplier A', tax_id=None, address=None),
            lines=[
                SimpleNamespace(
                    quantity_ordered=Decimal('10'),
                    unit_price=Decimal('5'),
                    tax_rate=Decimal('23'),
                )
            ],
        )
        context = build_po_context(po, lang='en')
        assert context['lines'][0]['tax_pct'] == Decimal('23')
        assert context['total_tax'] == Decimal('11.5')


@pytest.mark.unit
class TestThePrintedOrderSumsTaxByRate:
    """Food at a reduced rate next to goods at the standard one."""

    @staticmethod
    def _order() -> SimpleNamespace:
        def line(name: str, price: str, rate: str) -> SimpleNamespace:
            return SimpleNamespace(
                name=name,
                product_template=None,
                product_template_id=None,
                uom=None,
                quantity_ordered=Decimal('10'),
                quantity_received=Decimal('0'),
                unit_price=Decimal(price),
                tax_rate=Decimal(rate),
                line_number=1,
                notes=None,
            )

        return SimpleNamespace(
            id=uuid4(),
            number='PO/2026/0010',
            currency='EUR',
            status='DRAFT',
            created_at=datetime(2026, 10, 27, 9, 0),
            scheduled_date=None,
            notes=None,
            organization=SimpleNamespace(name='Bakery GmbH'),
            partner=SimpleNamespace(name='Mill', tax_id=None, address=None),
            lines=[line('Flour', '2.50', '7'), line('Detergent', '10.00', '19')],
        )

    def test_the_context_carries_one_row_per_rate(self) -> None:
        rows = build_po_context(self._order(), lang='en')['tax_by_rate']
        assert [(r.rate, r.tax, r.gross) for r in rows] == [
            (Decimal('19.00'), Decimal('19.00'), Decimal('119.00')),
            (Decimal('7.00'), Decimal('1.75'), Decimal('26.75')),
        ]

    @pytest.mark.asyncio
    async def test_the_printout_carries_the_table(self) -> None:
        """Fails without the fix: the order printed its totals only."""
        with patch.object(_svc, 'render_to_pdf', return_value=b'%PDF') as mock_render:
            await generate_po_pdf(self._order(), lang='en')  # type: ignore[arg-type]
        html = mock_render.call_args[0][0]
        assert '<table class="tax-by-rate">' in html
        assert '1.75' in html


@pytest.mark.unit
class TestEveryAdvertisedPlaceholderPrints:
    """The catalogue the editor shows and the render context are one contract.

    A custom layout is written against the placeholder list, so a key the list
    advertises and the context does not set prints nothing — the layout its
    author built looks broken while the built-in one works.
    """

    @staticmethod
    def _order() -> SimpleNamespace:
        return SimpleNamespace(
            id=uuid4(),
            number='PO/2026/0011',
            currency='PLN',
            status='DRAFT',
            created_at=datetime(2026, 10, 27, 9, 0),
            scheduled_date=datetime(2026, 10, 28, 9, 0),
            notes=None,
            organization=SimpleNamespace(
                name='Acme Sp. z o.o.',
                tax_id='PL1234567890',
                address={
                    'street': 'Main 1',
                    'city': 'Warsaw',
                    'postal_code': '00-001',
                },
                country='PL',
            ),
            partner=SimpleNamespace(
                name='Supplier A',
                tax_id='PL9876543210',
                address={
                    'street': 'Side 2',
                    'city': 'Kraków',
                    'postal_code': '30-001',
                },
            ),
            lines=[
                SimpleNamespace(
                    name='Widget',
                    product_template=None,
                    uom=None,
                    quantity_ordered=Decimal('2'),
                    quantity_received=Decimal('0'),
                    unit_price=Decimal('5'),
                    tax_rate=Decimal('23'),
                    line_number=1,
                    notes=None,
                )
            ],
        )

    def test_each_advertised_key_renders_a_value(self) -> None:
        context = build_po_context(self._order(), lang='en')
        empty: list[str] = []
        for placeholder in PO_PLACEHOLDERS:
            html = core_api.pdf.render_html(f'<p>{placeholder.key}</p>', context)
            if not html.removeprefix('<p>').removesuffix('</p>'):
                empty.append(placeholder.key)
        assert empty == [], f'advertised placeholders printed nothing: {empty}'

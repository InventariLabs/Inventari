"""The stock-on-a-date report as a printed sheet.

The screen answers the question; this is what goes into a binder, so it
carries the three facts a filed printout has to carry — the date it is
about, the date it was made, and whose warehouse it is. It draws the header
every other printout draws, which is why that header now stands without a
barcode: a report identifies a date, not a record.
"""

from __future__ import annotations

from typing import Any

from app.core.async_utils import run_sync_in_thread
from app.core.contracts import StockAsOfReportDTO
from app.core.datetimes import format_date_for
from app.core.pdf_base_service import PdfServiceBase
from app.core.print_identity import PRINT_TEMPLATES_DIR, build_issuer_context
from app.core.print_page_size import apply_page_size, page_size_of


class StockReportPdfService(PdfServiceBase):
    """The core's own print family: reports, not documents."""

    templates_dir = PRINT_TEMPLATES_DIR
    module_name = 'core'

    labels_en = {
        'title': 'Stock on hand',
        'product': 'Product',
        'quantity': 'Quantity',
        'value': 'Value',
        'total': 'Total',
        'as_of': 'As of',
        'generated': 'Printed',
        'complete_from': 'The movement ledger starts on',
        'no_value_source': 'no cost history, so no value is stated',
        'excluded': 'Rows left out for a foreign currency',
        'unpriced': 'Products with no cost history, left out of the total',
        'nothing': 'Nothing was on the shelf on this date.',
    }
    labels_pl = {
        'title': 'Stan magazynowy',
        'product': 'Produkt',
        'quantity': 'Ilość',
        'value': 'Wartość',
        'total': 'Razem',
        'as_of': 'Stan na',
        'generated': 'Wydruk',
        'complete_from': 'Rejestr ruchów zaczyna się',
        'no_value_source': 'brak historii kosztów, więc bez wartości',
        'excluded': 'Wiersze pominięte z powodu obcej waluty',
        'unpriced': 'Produkty bez historii kosztów, poza sumą',
        'nothing': 'Na ten dzień nic nie stało na półce.',
    }
    labels_de = {
        'title': 'Lagerbestand',
        'product': 'Produkt',
        'quantity': 'Menge',
        'value': 'Wert',
        'total': 'Summe',
        'as_of': 'Stand',
        'generated': 'Gedruckt',
        'complete_from': 'Das Bewegungsjournal beginnt am',
        'no_value_source': 'keine Kostenhistorie, daher ohne Wert',
        'excluded': 'Wegen Fremdwährung ausgelassene Zeilen',
        'unpriced': 'Produkte ohne Kostenhistorie, nicht in der Summe',
        'nothing': 'An diesem Tag lag nichts im Lager.',
    }
    labels_fr = {
        'title': 'État du stock',
        'product': 'Produit',
        'quantity': 'Quantité',
        'value': 'Valeur',
        'total': 'Total',
        'as_of': 'Au',
        'generated': 'Imprimé le',
        'complete_from': 'Le journal des mouvements commence le',
        'no_value_source': "pas d'historique des coûts, donc sans valeur",
        'excluded': 'Lignes écartées pour cause de devise étrangère',
        'unpriced': 'Produits sans historique des coûts, hors du total',
        'nothing': "Rien n'était en stock à cette date.",
    }
    labels_es = {
        'title': 'Existencias',
        'product': 'Producto',
        'quantity': 'Cantidad',
        'value': 'Valor',
        'total': 'Total',
        'as_of': 'A fecha de',
        'generated': 'Impreso',
        'complete_from': 'El libro de movimientos empieza el',
        'no_value_source': 'sin historial de costes, por eso sin valor',
        'excluded': 'Filas excluidas por moneda extranjera',
        'unpriced': 'Productos sin historial de costes, fuera del total',
        'nothing': 'En esa fecha no había nada en las estanterías.',
    }


_svc = StockReportPdfService()


async def generate_stock_as_of_pdf(
    report: StockAsOfReportDTO,
    organization: Any,
    lang: str = 'en',
    *,
    show_value: bool = True,
) -> bytes:
    """Render one report. No barcode: the sheet identifies a date."""
    labels = _svc.get_labels(lang)
    issuer = await build_issuer_context(organization, lang)
    country = getattr(organization, 'country', None)

    context: dict[str, Any] = {
        'issuer': issuer,
        'labels': labels,
        'print_title': labels['title'],
        # The number a reader would quote is the date the report is about.
        'print_number': format_date_for(lang, report.as_of, country=country),
        # Both rows stay even on the same day: "as of today" and "printed
        # today" are different statements (print_date_rows would merge them).
        'print_dates': [
            {
                'label': labels['as_of'],
                'value': format_date_for(lang, report.as_of, country=country),
            },
            {
                'label': labels['generated'],
                'value': format_date_for(lang, report.generated_at, country=country),
            },
        ],
        'rows': report.items,
        # A file is the screen in the reader's hands: what the organization's
        # profile withholds there, this sheet must not state here.
        'show_value': show_value,
        'total_value': report.total_value,
        'currency': report.currency,
        'complete_from': report.complete_from,
        # The ledger's boundary is read beside the report's dates, so it is
        # spelled the way the report's language spells a date — the template
        # used the Polish-shaped filter whatever language the report was for.
        'complete_from_text': format_date_for(
            lang, report.complete_from, country=country
        ),
        'value_source': report.value_source,
        'excluded_currency_rows': report.excluded_currency_rows,
        # A printed report is filed and read months later, so the caveat
        # matters more here than on the screen, not less.
        'unpriced_rows': sum(1 for row in report.items if row.value is None)
        if report.value_source is not None
        else 0,
    }
    html = _svc.render_filesystem_template('stock_as_of.html', context)
    # The paper the organization prints on — stated after the body, so
    # whatever a template said about page size loses to it.
    page = apply_page_size(html, page_size_of(organization))
    # WeasyPrint is synchronous and CPU-bound: on the event loop a big sheet
    # holds every other request on this worker for the whole render.
    return await run_sync_in_thread(lambda: _svc.render_to_pdf(page))


def rows_to_export_frame(report: StockAsOfReportDTO, *, show_value: bool = True) -> Any:
    """The report as a table a spreadsheet can open.

    *show_value* follows the organization's switch, so the spreadsheet does
    not state the worth the profile hides on the screen it was exported from.
    """
    import pandas as pd

    columns = ['Product', 'Quantity', 'Unit']
    if show_value:
        columns.append('Value')
    if not report.items:
        return pd.DataFrame(columns=columns)
    records = []
    for row in report.items:
        record: dict[str, Any] = {
            'Product': row.product_name,
            'Quantity': float(row.quantity),
            'Unit': row.uom_symbol,
        }
        if show_value:
            record['Value'] = float(row.value) if row.value is not None else None
        records.append(record)
    return pd.DataFrame(records, columns=columns)

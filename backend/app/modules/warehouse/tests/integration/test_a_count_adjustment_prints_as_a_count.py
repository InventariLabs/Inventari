"""The document a stock count's differences post as does not read as a receipt.

It carries a title in the reader's language, not the stored type code; no
machine key where a reference goes; and none of the receipt's counterparty
box or supplier and driver signatures, since a count has neither.
"""

import pytest

from app.modules.warehouse.document_pdf_service import render_document_html
from app.modules.warehouse.models import Document, DocumentProfile

pytestmark = pytest.mark.integration

_RECEIPT_ONLY = {
    'en': ('Carrier / Driver', 'Received by', 'Supplier'),
    'pl': ('Dostawca / Kierowca', 'Towar przyjął', 'Dostawca', 'Przyjął'),
    'de': ('Fahrer / Spediteur', 'Empfangen von', 'Lieferant'),
    'fr': ('Transporteur / Chauffeur', 'Reçu par', 'Fournisseur'),
    'es': ('Transportista / Conductor', 'Recibido por', 'Proveedor'),
    'pt': ('Transportadora / Motorista', 'Recebido por', 'Fornecedor'),
}
_TITLES = {
    'en': 'Stock Count Adjustment',
    'pl': 'Korekta różnic inwentaryzacyjnych',
    'de': 'Bestandskorrektur nach Inventur',
    'fr': 'Ajustement d&#39;inventaire',
    'es': 'Ajuste de inventario',
    'pt': 'Ajuste de inventário',
}


def _adjustment(doc: Document) -> Document:
    doc.type = 'ADJUSTMENT'
    doc.external_reference = 'stock_take:6f1c2b0e-0000-4000-8000-000000000001'
    doc.partner = None
    return doc


class TestACountAdjustmentPrintsAsACount:
    @pytest.mark.parametrize('layout', ['standard', 'pl_pz'])
    @pytest.mark.parametrize('lang', list(_TITLES))
    def test_title_reference_and_signatures(
        self, layout: str, lang: str, doc_draft_pz: Document
    ) -> None:
        profile = DocumentProfile(name='Plain')
        profile.print_template = layout

        html = render_document_html(_adjustment(doc_draft_pz), profile, lang=lang)

        # The Polish form is written in Polish whatever the reader's language.
        assert _TITLES['pl' if layout == 'pl_pz' else lang] in html
        assert 'ADJUSTMENT' not in html
        assert 'stock_take:' not in html
        for receipt_only in _RECEIPT_ONLY['pl' if layout == 'pl_pz' else lang]:
            assert receipt_only not in html, receipt_only

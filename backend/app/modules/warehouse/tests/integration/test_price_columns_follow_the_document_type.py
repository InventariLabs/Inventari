"""The printout draws price columns for the documents that carry a price.

Price and VAT belong on receipts and issues — goods coming in or going out,
internally or across the counter. A transfer moves the same goods to another
shelf without changing what they are worth, a scrap writes them off and a
correction records a difference: none of the three asks for a price, and the
form offers one to nobody. The printout drew its price and tax columns
whenever the profile tracked value, whatever the document was.

What a document stores is not part of this: values already written stay where
they are, and the register lists them as before.
"""

import pytest

from app.modules.warehouse.document_pdf_service import build_pdf_context
from app.modules.warehouse.models import Document, DocumentProfile, TaxHandling

pytestmark = pytest.mark.integration


def _value_tracking_profile() -> DocumentProfile:
    """A profile that tracks value and charges a rate — the one whose
    printout used to draw price columns for every document type."""
    profile = DocumentProfile(name='Full value')
    profile.value_tracking_enabled = True
    profile.tax_handling = TaxHandling.SIMPLE_RATE.value
    profile.default_tax_rate = None
    return profile


class TestThePrintoutFollowsTheDocumentType:
    def test_a_receipt_prints_its_price_columns(self, doc_draft_pz: Document) -> None:
        context = build_pdf_context(doc_draft_pz, _value_tracking_profile(), lang='en')

        assert context['show_value_columns'] is True
        assert context['show_tax_column'] is True

    def test_a_transfer_prints_no_price_columns(self, doc_draft_pz: Document) -> None:
        """The same document, written as the move it would become. Its
        lines carry no price — a move asks for none — so there is nothing
        to print, and the column headings would ask a question the form
        never let anybody answer."""
        doc_draft_pz.type = 'INT'

        context = build_pdf_context(doc_draft_pz, _value_tracking_profile(), lang='en')

        assert context['show_value_columns'] is False
        assert context['show_tax_column'] is False

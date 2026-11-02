"""A printout of goods at two rates states the amounts per rate.

Food at a reduced rate and other goods at the standard one share a
receipt; the totals alone do not say how much tax was charged at which
rate, which is what the reader of the sheet checks against the supplier's
invoice. One rate needs no table: its row would repeat the totals.
"""

import re
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.models.product_template import ProductTemplate
from app.modules.warehouse.document_pdf_service import (
    build_pdf_context,
    render_document_html,
)
from app.modules.warehouse.document_value_service import recompute_document_values
from app.modules.warehouse.models import (
    Document,
    DocumentLine,
    DocumentProfile,
    TaxHandling,
)

pytestmark = pytest.mark.integration


def _profile(layout: str) -> DocumentProfile:
    profile = DocumentProfile(name='Full value')
    profile.value_tracking_enabled = True
    profile.tax_handling = TaxHandling.PER_LINE_RATE.value
    profile.print_template = layout
    return profile


def _two_rates(db_session: Session, doc: Document, bread: ProductTemplate) -> None:
    doc.lines[0].unit_price = Decimal('10.00')
    doc.lines[0].tax_rate = Decimal('19.00')
    doc.lines.append(
        DocumentLine(
            product_template_id=bread.id,
            quantity=Decimal('10'),
            expected_quantity=Decimal('10'),
            done_quantity=Decimal('0'),
            unit_price=Decimal('2.50'),
            tax_rate=Decimal('7.00'),
            line_number=2,
        )
    )
    recompute_document_values(doc)
    db_session.commit()
    db_session.refresh(doc)


class TestThePrintoutSumsTaxByRate:
    def test_the_context_carries_one_row_per_rate(
        self,
        db_session: Session,
        doc_draft_pz: Document,
        doc_template_with_uom: ProductTemplate,
    ) -> None:
        _two_rates(db_session, doc_draft_pz, doc_template_with_uom)

        rows = build_pdf_context(doc_draft_pz, _profile('standard'))['tax_by_rate']

        assert [(r.rate, r.net, r.tax, r.gross) for r in rows] == [
            (Decimal('19.00'), Decimal('50.00'), Decimal('9.50'), Decimal('59.50')),
            (Decimal('7.00'), Decimal('25.00'), Decimal('1.75'), Decimal('26.75')),
        ]

    @pytest.mark.parametrize('layout', ['standard', 'pl_pz'])
    def test_both_layouts_print_the_table(
        self,
        layout: str,
        db_session: Session,
        doc_draft_pz: Document,
        doc_template_with_uom: ProductTemplate,
    ) -> None:
        """Fails without the fix: neither layout printed the amounts per rate."""
        _two_rates(db_session, doc_draft_pz, doc_template_with_uom)

        html = render_document_html(doc_draft_pz, _profile(layout), lang='en')

        # The class names are in the stylesheet either way; the table is not.
        assert re.search(r'<table class="(tax|vat)-by-rate"', html)
        # The tax per rate is printed nowhere else on the sheet.
        assert re.search(r'(?<!\d)9[.,]50', html)
        assert re.search(r'(?<!\d)1[.,]75', html)

    def test_one_rate_prints_no_table(
        self, db_session: Session, doc_draft_pz: Document
    ) -> None:
        doc_draft_pz.lines[0].unit_price = Decimal('10.00')
        doc_draft_pz.lines[0].tax_rate = Decimal('19.00')
        recompute_document_values(doc_draft_pz)
        db_session.commit()

        html = render_document_html(doc_draft_pz, _profile('standard'), lang='en')

        assert '<table class="tax-by-rate"' not in html

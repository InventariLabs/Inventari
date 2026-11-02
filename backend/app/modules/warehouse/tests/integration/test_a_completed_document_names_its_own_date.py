"""A document that is done does not print its date as a plan.

The register files a document under the day it is *for* (``scheduled_date``),
and the printout labelled that same day "Scheduled" — also on a receipt that
had been posted weeks ago, beside a header that stamps the day it was typed
in. The day is the document's own date once the document is done; only an
open one is still a plan.
"""

from datetime import date

import pytest
from sqlalchemy.orm import Session

from app.core.datetimes import format_date_for
from app.modules.warehouse.document_pdf_service import render_document_html
from app.modules.warehouse.models import Document

pytestmark = pytest.mark.integration


class TestACompletedDocumentNamesItsOwnDate:
    @pytest.mark.parametrize(
        ('layout', 'plan', 'own'),
        [
            ('standard', 'Scheduled:', 'Document date:'),
            ('pl_pz', 'Planowana data', 'Data dokumentu'),
        ],
    )
    def test_the_label_follows_whether_the_document_is_done(
        self,
        layout: str,
        plan: str,
        own: str,
        db_session: Session,
        doc_draft_pz: Document,
    ) -> None:
        from app.modules.warehouse.models import DocumentProfile

        profile = DocumentProfile(name='Plain')
        profile.print_template = layout
        doc_draft_pz.scheduled_date = date(2026, 9, 28)
        db_session.commit()

        open_html = render_document_html(doc_draft_pz, profile, lang='en')
        assert plan in open_html
        assert own not in open_html

        doc_draft_pz.status = 'COMPLETED'
        db_session.commit()

        done_html = render_document_html(doc_draft_pz, profile, lang='en')
        assert own in done_html
        assert plan not in done_html
        assert '2026-09-28' in done_html

    def test_the_header_stamps_the_document_date_not_the_day_it_was_typed_in(
        self,
        db_session: Session,
        doc_draft_pz: Document,
    ) -> None:
        from app.modules.warehouse.document_pdf_service import build_pdf_context
        from app.modules.warehouse.models import DocumentProfile

        doc_draft_pz.scheduled_date = date(2026, 9, 28)
        doc_draft_pz.status = 'COMPLETED'
        db_session.commit()

        context = build_pdf_context(
            doc_draft_pz, DocumentProfile(name='Plain'), lang='en'
        )

        first = context['print_dates'][0]
        assert first['label'] == 'Document date'
        assert first['value'] == format_date_for('en', date(2026, 9, 28))

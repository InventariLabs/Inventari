"""A stored layout the sandbox cannot render prints through the built-in one.

A body saved before layouts were checked can fail to parse. Every printout
that renders a stored layout — a document, a packing slip, a pick list — falls
back to the built-in layout instead of answering with an error.
"""

import pytest
from sqlalchemy.orm import Session

from app.modules.warehouse.document_pdf_service import (
    generate_packing_slip_pdf_async,
    generate_pdf,
    generate_pick_list_pdf_async,
    print_packages,
    render_document_html,
)
from app.modules.warehouse.models import Document, DocumentProfile

pytestmark = pytest.mark.integration

_BROKEN = '<p>{{ broken </p>'


class TestAStoredLayoutThatDoesNotRenderStillPrints:
    def test_a_document_prints_through_the_profile_family(
        self, db_session: Session, doc_draft_pz: Document
    ) -> None:
        profile = DocumentProfile(name='Plain')
        profile.print_template = 'standard'

        html = render_document_html(
            doc_draft_pz, profile, lang='en', user_template_html=_BROKEN
        )

        assert doc_draft_pz.number in html
        assert 'broken' not in html
        assert generate_pdf(
            doc_draft_pz, profile, lang='en', user_template_html=_BROKEN
        ).startswith(b'%PDF')

    async def test_a_pick_list_prints_through_the_built_in_one(
        self, doc_draft_pz: Document
    ) -> None:
        pdf = await generate_pick_list_pdf_async(
            [doc_draft_pz], [], template_html=_BROKEN, lang='en'
        )

        assert pdf.startswith(b'%PDF')

    async def test_a_packing_slip_prints_through_the_built_in_one(
        self, doc_draft_pz: Document
    ) -> None:
        pdf = await generate_packing_slip_pdf_async(
            doc_draft_pz,
            None,
            print_packages(doc_draft_pz, [], total=0),
            template_html=_BROKEN,
            lang='en',
        )

        assert pdf.startswith(b'%PDF')

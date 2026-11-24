"""A stored layout the sandbox cannot render prints through the built-in one.

A body saved before layouts were checked can fail to parse, or fail when it
runs. Every warehouse printout that renders a stored layout — a document, the
merged file over several documents, a packing slip, a pick list — prints the
built-in layout then, as if no layout had been stored, instead of answering
with an error for the whole print.
"""

import io
from types import SimpleNamespace

import pytest
from pypdf import PdfReader

from app.core.print_identity import build_issuer_context
from app.modules.warehouse.document_pdf_service import (
    generate_merged_pdf_async,
    generate_packing_slip_pdf_async,
    generate_pdf,
    generate_pick_list_pdf_async,
    print_packages,
    render_document_html,
)
from app.modules.warehouse.models import Document, DocumentProfile

pytestmark = pytest.mark.integration

_BROKEN = '<p>{{ broken </p>'


def _page_text(pdf: bytes) -> str:
    reader = PdfReader(io.BytesIO(pdf))
    return '\n'.join(page.extract_text() for page in reader.pages)


class TestAStoredLayoutThatDoesNotRenderStillPrints:
    def test_a_document_prints_through_the_profile_family(
        self, doc_draft_pz: Document
    ) -> None:
        profile = DocumentProfile(name='Plain')
        profile.print_template = 'standard'

        html = render_document_html(
            doc_draft_pz, profile, lang='en', user_template_html=_BROKEN
        )
        pdf = generate_pdf(doc_draft_pz, profile, lang='en', user_template_html=_BROKEN)

        assert doc_draft_pz.number in html
        assert 'broken' not in html
        assert doc_draft_pz.number in _page_text(pdf)

    async def test_the_merged_file_prints_through_the_profile_family(
        self, doc_draft_pz: Document
    ) -> None:
        profile = DocumentProfile(name='Plain')
        profile.print_template = 'standard'

        pdf = await generate_merged_pdf_async(
            [(doc_draft_pz, _BROKEN)], profile, lang='en'
        )

        assert doc_draft_pz.number in _page_text(pdf)

    async def test_a_pick_list_prints_through_the_built_in_one(
        self, doc_draft_pz: Document
    ) -> None:
        pdf = await generate_pick_list_pdf_async(
            [doc_draft_pz], [], template_html=_BROKEN, lang='en'
        )

        assert 'Pick List' in _page_text(pdf)

    async def test_a_packing_slip_prints_through_the_built_in_one(
        self, doc_draft_pz: Document
    ) -> None:
        line = doc_draft_pz.lines[0]
        package = SimpleNamespace(
            number=1,
            weight_kg=None,
            lines=[SimpleNamespace(document_line_id=line.id, quantity=line.quantity)],
        )

        pdf = await generate_packing_slip_pdf_async(
            doc_draft_pz,
            None,
            print_packages(doc_draft_pz, [package], total=1),
            template_html=_BROKEN,
            lang='en',
        )

        text = _page_text(pdf)
        assert doc_draft_pz.number in text
        assert 'Package 1 of 1' in text


class TestTheFallbackPrintsTheIssuerInTheLanguageOfTheLayoutThatPrints:
    """A Polish organization's fallback WZ says Polska, as with no stored layout."""

    _ORGANIZATION = SimpleNamespace(
        name='Piekarnia',
        tax_id='PL5260001246',
        address={'street': 'Prosta 1', 'city': 'Warszawa', 'postal_code': '00-001'},
        country='PL',
        logo_url=None,
    )

    def _profile(self) -> DocumentProfile:
        profile = DocumentProfile(name='Auto')
        profile.print_template = 'auto'
        return profile

    async def test_a_document(self, doc_draft_pz: Document) -> None:
        issuer = await build_issuer_context(self._ORGANIZATION, 'en')

        html = render_document_html(
            doc_draft_pz,
            self._profile(),
            lang='en',
            issuer=issuer,
            user_template_html=_BROKEN,
            country='PL',
        )

        assert 'Polska' in html
        assert 'Poland' not in html

    async def test_the_merged_file(self, doc_draft_pz: Document) -> None:
        pdf = await generate_merged_pdf_async(
            [(doc_draft_pz, _BROKEN)],
            self._profile(),
            lang='en',
            organization=self._ORGANIZATION,
        )

        text = _page_text(pdf)
        assert 'Polska' in text
        assert 'Poland' not in text

"""A printed write-off says why, and what it cost.

The document page shows a scrap's reason and the value its cost layers took,
and the register books that value — but the printout carried the line
quantities only, under the raw type code as its title. The office binder held
a sheet that answered neither question the write-off was made to answer.
"""

from __future__ import annotations

import re
from decimal import Decimal
from uuid import UUID

import pytest

from app.modules.warehouse.document_pdf_service import _svc, build_pdf_context
from app.modules.warehouse.models import Document

_TAG = re.compile(r'<[^>]+>')
_STYLE = re.compile(r'<style.*?</style>', re.DOTALL)


def _scrap(**fields: object) -> Document:
    values: dict[str, object] = {
        'organization_id': UUID('00000000-0000-0000-0000-000000000001'),
        'type': 'SCRAP',
        'number': 'ZL/2026/001',
        'status': 'COMPLETED',
        'reason_code': 'EXPIRED',
        'total_net': Decimal('25.00'),
        'currency': 'PLN',
        **fields,
    }
    return Document(**values)


def _text(layout: str, doc: Document, lang: str) -> str:
    """The printed words of ``layout``, whitespace collapsed."""
    html = _svc.render_filesystem_template(
        f'{layout}.html', build_pdf_context(doc, None, lang=lang)
    )
    return ' '.join(_TAG.sub(' ', _STYLE.sub('', html)).split())


@pytest.mark.unit
class TestTheScrapPrintout:
    def test_the_standard_sheet_prints_the_reason_and_the_cost(self) -> None:
        text = _text('standard', _scrap(), 'en')

        assert 'Reason for scrapping: Expired' in text
        assert 'Cost of the write-off 25.00 PLN' in text

    def test_the_polish_sheet_prints_them_in_polish(self) -> None:
        text = _text('pl_pz', _scrap(), 'pl')

        assert 'Powód złomowania: Przeterminowanie' in text
        assert 'KOSZT ODPISU: 25,00 PLN' in text

    @pytest.mark.parametrize('layout', ['standard', 'pl_pz'])
    def test_other_prints_the_note_that_says_what_it_was(self, layout: str) -> None:
        text = _text(
            layout,
            _scrap(reason_code='OTHER', notes='Dropped by the forklift'),
            'pl',
        )

        assert 'Powód złomowania: Inny' in text
        assert 'Dropped by the forklift' in text

    @pytest.mark.parametrize('layout', ['standard', 'pl_pz'])
    def test_a_scrap_with_no_value_prints_no_cost(self, layout: str) -> None:
        """A profile that tracks no value stores none: no line is better
        than a cost of zero the cost layers never said."""
        text = _text(layout, _scrap(total_net=None), 'pl')

        assert 'Koszt odpisu'.lower() not in text.lower()

    @pytest.mark.parametrize('lang', ['en', 'pl', 'de', 'fr', 'es'])
    def test_the_title_names_the_document_not_the_type_code(self, lang: str) -> None:
        context = build_pdf_context(_scrap(), None, lang=lang)

        assert context['print_title'] != 'SCRAP'

    def test_another_type_prints_no_scrap_lines(self) -> None:
        receipt = _scrap(type='IN', reason_code=None)

        text = _text('standard', receipt, 'en')

        assert 'Reason for scrapping' not in text
        assert 'Cost of the write-off' not in text

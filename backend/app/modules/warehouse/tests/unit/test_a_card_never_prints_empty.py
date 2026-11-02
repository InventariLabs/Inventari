"""A printed card is never a heading over an empty box.

The document-details card of the standard sheet and the warehouse cards of
the pl_pz family printed their frame and heading unconditionally while every
row inside was conditional. A document carrying none of the values printed a
bordered box with only a title, next to a party card that showed a dash.
Each card now prints at least one row, or the dash.
"""

from __future__ import annotations

import re
from uuid import UUID

import pytest

from app.modules.warehouse.document_pdf_service import _svc, build_pdf_context
from app.modules.warehouse.models import Document

_CARD = re.compile(r'<div class="(?:info-block|party-box)">(.*?)\n</div>', re.DOTALL)
_ROW = re.compile(r'class="(?:info-row|party-name|party-detail)"|>—</div>')

_TYPES = ('IN', 'OUT', 'INTERNAL_IN', 'INTERNAL_OUT', 'INT', 'CORRECTION')


def _cards(template: str, doc_type: str, **fields: str) -> list[str]:
    doc = Document(
        organization_id=UUID('00000000-0000-0000-0000-000000000001'),
        type=doc_type,
        number='DOC/2026/001',
        status='DRAFT',
        **fields,
    )
    context = build_pdf_context(doc, None, lang='en')
    return _CARD.findall(_svc.render_filesystem_template(template, context))


@pytest.mark.unit
class TestACardNeverPrintsEmpty:
    @pytest.mark.parametrize('template', ['standard.html', 'pl_pz.html'])
    @pytest.mark.parametrize('doc_type', _TYPES)
    def test_a_document_without_details_prints_no_bare_card(
        self, template: str, doc_type: str
    ) -> None:
        """Fails on the bare heading: zero rows inside a printed card."""
        cards = _cards(template, doc_type)

        assert cards, 'the sheet printed no cards at all'
        for card in cards:
            assert len(_ROW.findall(card)) >= 1, f'a card with no rows: {card!r}'

    def test_a_reference_is_a_row_not_the_dash(self) -> None:
        """A guard: a card with a value prints that value, not the dash."""
        cards = _cards('standard.html', 'IN', external_reference='REF-42')

        details = next(c for c in cards if 'REF-42' in c)
        assert len(re.findall(r'class="info-row"', details)) == 1
        assert '>—</div>' not in details

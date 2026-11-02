from __future__ import annotations

import re
from uuid import UUID

import pytest
from jinja2 import Environment, select_autoescape

from app.i18n import MAINTAINED_LANGUAGES
from app.modules.purchase_orders import po_pdf_service
from app.modules.warehouse import _pdf_labels
from app.modules.warehouse.document_pdf_service import _svc, build_pdf_context
from app.modules.warehouse.models import Document
from app.services.pdf_utils import register_pdf_filters

_LANGS = ('en', 'pl', 'de', 'fr', 'es')
# Words that really are spelt like the English one in that language.
_SAME_WORD_IN_ENGLISH = {('de', 'name'), ('fr', 'CORRECTION')}
# Printed words spelt the same as the English one in that language.
_GENUINE_COGNATES = {
    'pl': {'Status'},
    'de': {'Status', 'Name:'},
    'fr': {'Correction'},
    'es': set(),
}
_ADDRESS = 'Main Road 5, Springfield, 1111'


def _render(source: str, lang: str, **context: object) -> str:
    env = Environment(autoescape=select_autoescape(['html']))
    register_pdf_filters(env)
    return env.from_string(source).render(lang=lang, **context)


@pytest.mark.unit
class TestNumbersFollowTheDocumentLanguage:
    @pytest.mark.parametrize(
        ('lang', 'expected'),
        [
            ('en', '12.00'),
            ('pl', '12,00'),
            ('de', '12,00'),
            ('fr', '12,00'),
            ('es', '12,00'),
        ],
    )
    async def test_amount(self, lang: str, expected: str) -> None:
        assert _render('{{ 12 | format_decimal }}', lang) == expected

    async def test_quantity_and_percentage(self) -> None:
        assert _render('{{ "1.5" | format_qty }}', 'pl') == '1,5'
        assert _render('{{ "1.5" | format_qty }}', 'en') == '1.5'
        assert _render('{{ "7.5" | format_pct }}', 'de') == '7,50%'


@pytest.mark.unit
class TestUnitsFollowTheDocumentLanguage:
    @pytest.mark.parametrize(
        ('lang', 'expected'),
        [('en', 'pcs.'), ('pl', 'szt.'), ('de', 'Stk.'), ('es', 'uds.')],
    )
    async def test_piece(self, lang: str, expected: str) -> None:
        assert _render('{{ "pcs" | unit_label }}', lang) == expected

    async def test_unknown_symbol_is_kept(self) -> None:
        assert _render('{{ "crate-x" | unit_label }}', 'pl') == 'crate-x'


@pytest.mark.unit
class TestLabelSetsAreComplete:
    @pytest.mark.parametrize('lang', _LANGS)
    async def test_document_labels_have_every_english_key(self, lang: str) -> None:
        english = set(_pdf_labels._LABELS_EN)
        labels = getattr(_pdf_labels, f'_LABELS_{lang.upper()}')
        assert english - set(labels) == set()

    @pytest.mark.parametrize('lang', _LANGS)
    async def test_purchase_order_labels_have_every_english_key(
        self, lang: str
    ) -> None:
        english = set(po_pdf_service._LABELS_EN)
        labels = getattr(po_pdf_service, f'_LABELS_{lang.upper()}')
        assert english - set(labels) == set()

    @pytest.mark.parametrize('lang', ('pl', 'de', 'fr', 'es'))
    async def test_fixed_texts_are_not_english(self, lang: str) -> None:
        labels = getattr(_pdf_labels, f'_LABELS_{lang.upper()}')
        for key in ('footer', 'financial_impact', 'notes', 'name', 'address'):
            if (lang, key) in _SAME_WORD_IN_ENGLISH:
                continue
            assert labels[key] != _pdf_labels._LABELS_EN[key], key
        po_labels = getattr(po_pdf_service, f'_LABELS_{lang.upper()}')
        assert po_labels['footer'] != po_pdf_service._LABELS_EN['footer']


@pytest.mark.unit
class TestTypeTitlesAreTranslated:
    """The print subtitle comes from these tables, so an English entry would
    print English under a translated title."""

    @pytest.mark.parametrize('lang', ('pl', 'de', 'fr', 'es'))
    async def test_no_title_falls_back_to_english(self, lang: str) -> None:
        english = _pdf_labels._DEFAULT_TYPE_TITLES_EN
        titles = getattr(_pdf_labels, f'_DEFAULT_TYPE_TITLES_{lang.upper()}')
        assert set(english) - set(titles) == set()
        same = {t for t in english if titles[t] == english[t]}
        assert same == {t for t in same if (lang, t) in _SAME_WORD_IN_ENGLISH}


_TAG = re.compile(r'<[^>]+>')
_STYLE = re.compile(r'<style.*?</style>', re.DOTALL)
# Values the document carries itself, so they read the same in every language.
_PARTNER = {
    'name': 'Acme Trading',
    'code': 'ACM-1',
    'tax_id': 'XX123',
    'address': {'street': 'Main Road 5', 'city': 'Springfield', 'postal_code': '1111'},
}


def _words(doc_type: str, lang: str) -> set[str]:
    """Every text run the standard sheet prints, as a set."""
    doc = Document(
        organization_id=UUID('00000000-0000-0000-0000-000000000001'),
        type=doc_type,
        number='DOC/2026/001',
        status='DRAFT',
        partner_snapshot=_PARTNER,
    )
    html = _svc.render_filesystem_template(
        'standard.html', build_pdf_context(doc, None, lang=lang)
    )
    text = _TAG.sub('\n', _STYLE.sub('', html))
    # The page margin boxes (the footer) live in the stylesheet, not the body.
    text += '\n'.join(re.findall(r'content: "([^"]+)"', html))
    return {run.strip() for run in text.splitlines() if re.search(r'[^\W\d_]', run)}


@pytest.mark.unit
class TestStandardSheetPrintsInTheDocumentLanguage:
    """Renders the sheet itself, so a template literal, a missing label key
    or a wrong language pick is caught wherever it hides — not only in the
    dictionaries above. A run of text that is the same as on the English
    sheet is either something the document carries or an English fallback."""

    @pytest.mark.parametrize('lang', [x for x in MAINTAINED_LANGUAGES if x != 'en'])
    @pytest.mark.parametrize('doc_type', ('IN', 'OUT', 'INT', 'CORRECTION', 'SCRAP'))
    def test_no_run_of_text_is_left_in_english(self, lang: str, doc_type: str) -> None:
        carried = {
            _PARTNER['name'],
            _PARTNER['code'],
            _PARTNER['tax_id'],
            _ADDRESS,
            'DOC/2026/001',
        }
        shared = _words(doc_type, 'en') & _words(doc_type, lang)

        assert shared - carried - _GENUINE_COGNATES[lang] == set()


@pytest.mark.unit
class TestFooterStaysInsideTheColumn:
    @pytest.mark.parametrize(
        'path',
        [
            'warehouse/templates/standard.html',
            'warehouse/templates/pl_pz.html',
            'purchase_orders/templates/po_standard.html',
        ],
    )
    async def test_footer_is_inset_and_centred(self, path: str) -> None:
        from pathlib import Path

        source = (Path(po_pdf_service.__file__).parents[1] / path).read_text()
        block = source.split('@bottom-center', 1)[1].split('\n      }', 1)[0]
        assert 'padding: 0 4mm' in block
        assert 'text-align: center' in block

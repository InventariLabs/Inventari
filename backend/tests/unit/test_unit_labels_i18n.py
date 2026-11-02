"""The words a server-composed refusal uses for a unit.

The frontend keeps the labels a reader picks from in ``units.*`` of every
locale's ``common.json``; the backend composes whole sentences of its own (a
toast on the scan screen, a 400 body, an email) and cannot reach a browser
bundle, so it mirrors those labels in ``app.i18n._units``. These tests pin
the mirror's shape and the fallback that keeps a unit outside it readable.
"""

from app.i18n import MAINTAINED_LANGUAGES, UNIT_LABELS
from app.i18n.service import get_current_lang, get_unit_label, set_current_lang

#: The symbols the frontend's ``units`` block carries — the catalogue's whole
#: job is to mirror it, so the set is pinned here rather than discovered.
CATALOGUED_SYMBOLS = frozenset(
    {
        'pcs',
        'kg',
        'g',
        'l',
        'ml',
        'pack',
        'can',
        'bottle',
        'box',
        'bag',
        'oz',
        'lb',
        'mg',
        'cup',
        'fl oz',
        'm',
        'cm',
    }
)


class TestTheUnitLabelCatalogue:
    def test_every_language_carries_the_same_symbols(self) -> None:
        for lang in MAINTAINED_LANGUAGES:
            assert set(UNIT_LABELS[lang]) == CATALOGUED_SYMBOLS, lang

    def test_every_label_is_a_word(self) -> None:
        for lang in MAINTAINED_LANGUAGES:
            for symbol, label in UNIT_LABELS[lang].items():
                assert label.strip(), (lang, symbol)

    def test_a_piece_reads_as_the_word_the_reader_picked(self) -> None:
        """The measured refusal: the screen said "szt.", not "pcs"."""
        assert get_unit_label('pcs', 'pl') == 'szt.'
        assert get_unit_label('pcs', 'de') == 'Stk.'
        assert get_unit_label('pcs', 'es') == 'uds.'

    def test_a_symbol_the_catalogue_does_not_carry_stays_that_symbol(self) -> None:
        """An organization's own unit keeps its symbol.

        A label nobody wrote would be worse than the symbol the data holds —
        the reader at least sees the unit their own catalogue named.
        """
        assert get_unit_label('crate', 'pl') == 'crate'
        assert get_unit_label('pallet', 'en') == 'pallet'

    def test_the_session_language_is_the_default(self) -> None:
        set_current_lang('pl')
        try:
            assert get_current_lang() == 'pl'
            assert get_unit_label('box') == 'pudełko'
        finally:
            set_current_lang(None)

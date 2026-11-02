"""The probe drew the label, so it can say whether the model read it.

The connection test used to answer one question — does the answer parse into
``VisionExtractResult`` — and report it as "the connection works". A model
returning a well-formed ``{"name": "Milk"}`` for a carton labelled OAT DRINK
passed exactly like one that read the picture, and the difference surfaced on
the user's first product.

The verdict deliberately does not change: a well-formed answer is still a
pass. What changes is that the payload now carries what the model read, so a
person choosing a model can see what the verdict cannot express.
"""

from __future__ import annotations

import pytest

from app.modules.vision._probe import read_back
from app.modules.vision.schemas import VisionExtractResult

pytestmark = pytest.mark.unit


def _answer(**fields: str | None) -> VisionExtractResult:
    return VisionExtractResult(**fields)


class TestReadBack:
    def test_a_model_that_read_the_label_matches_every_field(self) -> None:
        report = read_back(
            _answer(
                name='OAT DRINK',
                brand='Barista Edition',
                weight='1 L',
                expiry_date='2027-01-31',
            )
        )

        # Three scored fields: the label establishes no maker, so brand —
        # still welcome in the answer — is nobody's to miss.
        assert report['matched'] == report['of'] == 3
        assert all(entry['matches'] for entry in report['fields'].values())
        assert 'brand' not in report['fields']

    def test_a_superior_name_reading_is_not_a_miss(self) -> None:
        """The measured case: the model read the name line and the variant
        under it, saw no maker anywhere on the label, and said so. Every
        scored field passes."""
        report = read_back(
            _answer(
                name='OAT DRINK Barista Edition',
                brand=None,
                weight='1 L',
                expiry_date='2027-01-31',
            )
        )

        assert report['matched'] == report['of'] == 3

    def test_a_well_formed_guess_is_distinguishable_from_a_reading(self) -> None:
        """The shape is right and the values are from the ceiling."""
        report = read_back(
            _answer(
                name='Milk',
                brand=None,
                weight=None,
                expiry_date=None,
            )
        )

        assert report['matched'] == 0
        assert report['fields']['name'] == {
            'expected': 'OAT DRINK',
            'read': 'Milk',
            'matches': False,
        }

    def test_the_report_names_both_sides_of_every_field(self) -> None:
        """A reader has to see what was expected, not just that it differed."""
        report = read_back(_answer(name='Oat drink'))

        for field, entry in report['fields'].items():
            assert set(entry) == {'expected', 'read', 'matches'}, field
            assert entry['expected']


class TestEquivalentSpellingsAreNotMisreadings:
    @pytest.mark.parametrize(
        'read',
        ['OAT DRINK', 'Oat Drink', 'oat drink', '  OAT  DRINK '],
    )
    def test_case_and_spacing_belong_to_the_model(self, read: str) -> None:
        assert read_back(_answer(name=read))['fields']['name']['matches']

    @pytest.mark.parametrize(
        'read',
        ['2027-01-31', '31.01.2027', '31/01/2027', '31 January 2027'],
    )
    def test_a_date_is_the_day_it_names(self, read: str) -> None:
        assert read_back(_answer(expiry_date=read))['fields']['expiry_date']['matches']

    @pytest.mark.parametrize('read', ['1 L', '1L', '1.0 l', '1000 ml', '1 litre'])
    def test_one_litre_however_it_is_written(self, read: str) -> None:
        assert read_back(_answer(weight=read))['fields']['weight']['matches']

    def test_containment_of_the_expected_words_is_the_same_answer(self) -> None:
        """The corpus scorer's convention: a reading that carries the
        expected name inside it — the variant under the same heading —
        names the product."""
        assert read_back(_answer(name='OAT DRINK Barista Edition'))['fields']['name'][
            'matches'
        ]

    def test_a_different_name_is_still_a_difference(self) -> None:
        assert not read_back(_answer(name='Soy Milk'))['fields']['name']['matches']

    def test_a_different_day_is_still_a_difference(self) -> None:
        """The tolerance is for spelling, not for being wrong."""
        assert not read_back(_answer(expiry_date='2027-02-01'))['fields'][
            'expiry_date'
        ]['matches']

    def test_a_different_volume_is_still_a_difference(self) -> None:
        assert not read_back(_answer(weight='500 ml'))['fields']['weight']['matches']

    def test_an_unparseable_quantity_falls_back_to_the_words(self) -> None:
        """No number to compare — then the text has to match as text."""
        assert not read_back(_answer(weight='one litre'))['fields']['weight']['matches']


class TestTheNameIsWholeAndAFullerReadingStillCounts:
    """The name comparison, pinned from both sides.

    The comparison has two directions and nothing held either of them:
    flipping ``_contains_text`` to one-sided containment left the suite
    green. A name that arrives fuller than the label — the variant line
    riding under the heading — is a reading; anything shorter than the name
    is a fragment, and the header word alone, two letters and one letter all
    have to miss. The shortening direction was dropped on purpose: it
    accepted 'OAT' — the header, exactly as wide as the corpus scorer's
    three-character floor — as having read the name.
    """

    def test_a_reading_that_carries_the_variant_line_still_matches(self) -> None:
        """The measured case: 'OAT DRINK Barista Edition' for 'OAT DRINK'.

        Read the line and the variant under it, and nothing about that
        answer is a miss — the whole reason the comparison stopped being an
        equality in the first place.
        """
        report = read_back(
            _answer(
                name='OAT DRINK Barista Edition',
                weight='1 L',
                expiry_date='2027-01-31',
            )
        )

        assert report['matched'] == report['of'] == 3

    @pytest.mark.parametrize('read', ['OAT', 'oa', 'k'])
    def test_a_fragment_of_the_name_is_not_a_reading(self, read: str) -> None:
        """The header word, two letters, one letter — the screen used to
        report a model that answered like this as having read everything."""
        report = read_back(_answer(name=read))

        assert report['fields']['name']['matches'] is False
        assert report['matched'] == 0
        assert report['of'] == 3

    def test_a_word_of_the_name_alone_is_not_the_name(self) -> None:
        """'drink' is in 'OAT DRINK', and it is still half the name.

        The corpus scorer accepts a shortening that carries a word of the
        accepted name; the probe does not, because the accepted name here is
        the whole line and a read stopping mid-line is the failure mode this
        screen exists to show."""
        assert not read_back(_answer(name='drink'))['fields']['name']['matches']

    @pytest.mark.parametrize('read', ['Oat—Drink', 'OAT® DRINK'])
    def test_typography_is_not_a_misreading(self, read: str) -> None:
        """An em dash or a trademark sign is how the label was printed —
        the words underneath are the same words."""
        assert read_back(_answer(name=read))['fields']['name']['matches']


class TestTheWeightFieldSaysWhatIsNotAWeight:
    """A measured prompt is a decision, and a decision needs a guard.

    The exclusions in ``VisionExtractResult.weight`` were not written for
    readability — each names a value that a model actually returned as a net
    weight while reading these photographs. They read like padding to anyone
    who was not there, which is exactly why shortening them back is an easy
    thing to do by accident.
    """

    def test_it_tells_the_model_that_silence_is_allowed(self) -> None:
        from app.modules.vision.schemas import VisionExtractResult

        description = VisionExtractResult.model_fields['weight'].description or ''

        assert 'null' in description.lower()

    def test_it_names_the_three_things_that_are_not_a_net_weight(self) -> None:
        from app.modules.vision.schemas import VisionExtractResult

        description = (
            VisionExtractResult.model_fields['weight'].description or ''
        ).lower()

        # A nutrition figure, a promotional flash, a count of pieces.
        assert 'serving' in description
        assert 'free' in description
        assert 'count' in description

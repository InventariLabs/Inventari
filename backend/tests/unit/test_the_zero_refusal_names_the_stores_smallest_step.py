"""The sentence that refuses a quantity rounding to zero names the smallest
amount the column keeps. That amount is ``QUANTITY_STEP``; a sentence that
repeats it as a literal keeps answering ``0.001`` after the scale changes."""

from decimal import Decimal

import pytest

from app.i18n import SUPPORTED_LANGUAGES
from app.i18n.service import get_error_message

KEY = 'shopping_list_item_quantity_rounds_to_zero'
SMALLEST = '0,00007'  # a step no sentence could have pasted


@pytest.mark.parametrize('lang', sorted(SUPPORTED_LANGUAGES))
def test_the_sentence_carries_the_step_it_is_given(lang: str) -> None:
    sentence = get_error_message(
        KEY, lang, quantity=Decimal('0.00001'), smallest=SMALLEST
    )

    assert SMALLEST in sentence
    assert '{' not in sentence

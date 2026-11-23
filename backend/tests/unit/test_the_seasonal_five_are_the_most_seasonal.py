"""The seasonal patterns card shows the five most seasonal products, ranked.

The products reach the analysis in the order the database grouped them, which
is no order at all. The list is ranked before it is cut: the highest
seasonality score first, a product whose season has no off-season to measure
against (no score) last, and a tie in the order of the names.
"""

from datetime import date
from decimal import Decimal

from app.modules.stats._purchase_analysis import analyze_seasonality


def _bought(*months: int) -> dict:
    return {
        'purchases': [date(2026, month, 1 + n) for n, month in enumerate(months)],
        'total_quantity': Decimal('10'),
        'total_price': Decimal('120'),
    }


# Three purchases in March make March the peak; the rest are the off-season.
ONE_OFF = _bought(3, 3, 3, 5)  # score -0.67
TWO_OFF = _bought(3, 3, 3, 5, 7)  # score -0.33
THREE_OFF = _bought(3, 3, 3, 3, 5, 7, 8)  # score -0.25
NO_OFF_SEASON = _bought(3, 3, 3, 5, 5)  # May is a peak too: no score


def test_the_card_ranks_by_score_then_name_before_it_cuts_at_five() -> None:
    seasonal = analyze_seasonality(
        {
            'zucchini': ONE_OFF,
            'Apricots': NO_OFF_SEASON,
            'melon': TWO_OFF,
            'Banana': TWO_OFF,
            'Cherries': THREE_OFF,
            'apples': ONE_OFF,
        }
    )

    assert [p['name'] for p in seasonal] == [
        'Cherries',
        'Banana',
        'melon',
        'apples',
        'zucchini',
    ]
    assert [p['seasonality_score'] for p in seasonal] == [
        -0.25,
        -0.33,
        -0.33,
        -0.67,
        -0.67,
    ]


def test_a_product_with_no_score_still_ranks_below_those_with_one() -> None:
    seasonal = analyze_seasonality({'Apricots': NO_OFF_SEASON, 'Banana': ONE_OFF})

    assert [p['name'] for p in seasonal] == ['Banana', 'Apricots']

"""A product with nothing bought at its peak is not a seasonal product.

Seasonality is read off purchase dates, so records whose quantity summed to
zero — a server on the books at 0, a line written down to nothing — still
showed up under "Seasonal products" with "Peak quantity: 0": a season of
buying nothing. The list cuts them.
"""

from datetime import date
from decimal import Decimal

from app.modules.stats._purchase_analysis import analyze_seasonality

# Five purchases, three of them in March: enough for the analysis to call a
# peak month.
DATES = [
    date(2026, 3, 2),
    date(2026, 3, 9),
    date(2026, 3, 16),
    date(2026, 5, 4),
    date(2026, 7, 6),
]


def _bought(quantity: str) -> dict:
    return {
        'purchases': DATES,
        'total_quantity': Decimal(quantity),
        'total_price': Decimal('100'),
    }


def test_a_product_bought_at_zero_is_left_off_the_seasonal_list() -> None:
    seasonal = analyze_seasonality(
        {'Dell PowerEdge R750': _bought('0'), 'Rice Cakes': _bought('10')}
    )

    assert [p['name'] for p in seasonal] == ['Rice Cakes']
    assert seasonal[0]['peak_quantity'] == 6.0

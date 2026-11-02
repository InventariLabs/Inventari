"""A shelf's fill is the sum of each product's quantity over its own limit.

The owner's example is the one the planner used to get wrong: rice limited
to 40 and plums to 50 kg on one shelf, 20 rice and 25 kg plums standing
there. Each product alone is half full; the shelf is full. Asked one
product at a time, the planner kept sending goods to it.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from app.modules.warehouse._shelf_fill import shelf_fill

RICE = uuid4()
PLUMS = uuid4()
LOOSE = uuid4()


def test_a_mixed_shelf_is_full_when_the_shares_add_up_to_one() -> None:
    fill = shelf_fill(
        {RICE: Decimal('20'), PLUMS: Decimal('25')},
        {RICE: Decimal('40'), PLUMS: Decimal('50')},
    )
    assert fill.fill == Decimal('1')
    assert fill.percent == 100
    assert fill.status == 'nearly_full'
    assert {s.product_template_id: s.share for s in fill.shares} == {
        RICE: Decimal('0.5'),
        PLUMS: Decimal('0.5'),
    }
    assert not fill.fits(RICE, Decimal('1'))


def test_the_room_is_what_is_left_of_the_sum_in_the_products_unit() -> None:
    """20/40 rice and 20/50 plums: 90% taken, 10% of 50 kg is 5 kg."""
    fill = shelf_fill(
        {RICE: Decimal('20'), PLUMS: Decimal('20')},
        {RICE: Decimal('40'), PLUMS: Decimal('50')},
    )
    assert fill.fits(PLUMS, Decimal('5'))
    assert not fill.fits(PLUMS, Decimal('5.001'))
    assert fill.fits(RICE, Decimal('4'))
    assert not fill.fits(RICE, Decimal('4.001'))


def test_a_single_product_shelf_compares_stock_with_its_limit() -> None:
    """Thirds do not round their way over the limit: 2 of 3 plus 1 fits."""
    fill = shelf_fill({RICE: Decimal('2')}, {RICE: Decimal('3')})
    assert fill.fits(RICE, Decimal('1'))
    assert not fill.fits(RICE, Decimal('1.001'))
    assert fill.status == 'ok'
    assert fill.percent == 67


def test_a_product_without_a_limit_adds_no_share_and_is_unmeasured() -> None:
    fill = shelf_fill(
        {RICE: Decimal('20'), LOOSE: Decimal('300')},
        {RICE: Decimal('40')},
    )
    assert fill.fill == Decimal('0.5')
    assert fill.unmeasured is True
    loose = next(s for s in fill.shares if s.product_template_id == LOOSE)
    assert loose.share is None
    assert loose.max_quantity is None
    # The unlimited product always fits; it has no limit to break.
    assert fill.fits(LOOSE, Decimal('1000'))


def test_statuses() -> None:
    assert shelf_fill({}, {}).status == 'empty'
    assert shelf_fill({}, {RICE: Decimal('40')}).status == 'empty'
    assert shelf_fill({LOOSE: Decimal('3')}, {}).status == 'no_limit'
    assert shelf_fill({LOOSE: Decimal('3')}, {}).fill is None
    assert shelf_fill({RICE: Decimal('33')}, {RICE: Decimal('40')}).status == 'ok'
    assert (
        shelf_fill({RICE: Decimal('34')}, {RICE: Decimal('40')}).status == 'nearly_full'
    )
    assert shelf_fill({RICE: Decimal('41')}, {RICE: Decimal('40')}).status == 'over'


def test_an_empty_shelf_with_no_limit_fits_anything() -> None:
    fill = shelf_fill({}, {})
    assert fill.fits(RICE, Decimal('10'))
    assert fill.percent is None

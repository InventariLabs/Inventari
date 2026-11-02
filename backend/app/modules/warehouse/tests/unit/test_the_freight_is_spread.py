"""One freight invoice, spread over the goods it arrived with.

Without it the shelf is worth what the supplier invoiced and nothing else,
so every margin taken off that number is short by the cost of getting the
goods there.

Pure arithmetic, no database: the rules worth pinning are what happens when
the basis of the split is missing, and where the odd penny goes.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

from app.modules.warehouse.extra_costs_service import allocate
from app.modules.warehouse.models import ExtraCostAllocation


class _Line:
    """The three fields the allocation reads."""

    def __init__(
        self,
        quantity: str,
        unit_price: str | None = None,
        template_id: UUID | None = None,
    ) -> None:
        self.id = uuid4()
        self.expected_quantity = Decimal(quantity)
        self.done_quantity = Decimal(quantity)
        self.unit_price = Decimal(unit_price) if unit_price is not None else None
        self.product_template_id = template_id
        self.status = 'DONE'


class TestTheHundredAtTenBecomeTwelve:
    def test_freight_lands_in_the_unit_cost(self) -> None:
        line = _Line('100', '10.00')

        shares, _method = allocate(Decimal('200.00'), [line], ExtraCostAllocation.VALUE)

        # 100 at 10.00 plus 200.00 of freight is 12.00 a piece.
        assert shares[line.id] == Decimal('200.00')
        assert line.unit_price is not None
        unit_cost = line.unit_price + shares[line.id] / line.done_quantity
        assert unit_cost == Decimal('12.00')


class TestTheSplitFollowsTheBasisItWasGiven:
    def test_by_value_the_dearer_line_carries_more(self) -> None:
        cheap = _Line('10', '1.00')
        dear = _Line('10', '9.00')

        shares, method = allocate(
            Decimal('100.00'), [cheap, dear], ExtraCostAllocation.VALUE
        )

        assert method == ExtraCostAllocation.VALUE
        assert shares[cheap.id] == Decimal('10.00')
        assert shares[dear.id] == Decimal('90.00')

    def test_by_quantity_the_bigger_line_carries_more(self) -> None:
        few = _Line('1', '9.00')
        many = _Line('9', '1.00')

        shares, _method = allocate(
            Decimal('100.00'), [few, many], ExtraCostAllocation.QUANTITY
        )

        assert shares[few.id] == Decimal('10.00')
        assert shares[many.id] == Decimal('90.00')

    def test_by_weight_it_follows_what_the_haulier_bills_for(self) -> None:
        feathers = uuid4()
        lead = uuid4()
        light = _Line('10', '5.00', feathers)
        heavy = _Line('10', '5.00', lead)

        shares, method = allocate(
            Decimal('100.00'),
            [light, heavy],
            ExtraCostAllocation.WEIGHT,
            {feathers: Decimal('0.1'), lead: Decimal('0.9')},
        )

        assert method == ExtraCostAllocation.WEIGHT
        assert shares[light.id] == Decimal('10.00')
        assert shares[heavy.id] == Decimal('90.00')


class TestASplitNeedsSomethingToSplitBy:
    def test_value_allocation_on_a_delivery_nobody_priced_falls_back(self) -> None:
        first = _Line('3')
        second = _Line('7')

        shares, method = allocate(
            Decimal('100.00'), [first, second], ExtraCostAllocation.VALUE
        )

        # A share of a total of zero is a division by zero, not a cost. It
        # falls back to quantity and says which method it actually used
        # (an unpriced line keeps an unknown cost basis).
        assert method == ExtraCostAllocation.QUANTITY
        assert shares[first.id] == Decimal('30.00')
        assert shares[second.id] == Decimal('70.00')

    def test_weight_allocation_without_weights_falls_back_too(self) -> None:
        first = _Line('1', '5.00', uuid4())
        second = _Line('3', '5.00', uuid4())

        shares, method = allocate(
            Decimal('40.00'), [first, second], ExtraCostAllocation.WEIGHT, {}
        )

        assert method == ExtraCostAllocation.QUANTITY
        assert shares[second.id] == Decimal('30.00')


class TestTheOddPennyGoesSomewhere:
    def test_the_shares_add_up_to_the_invoice_to_the_cent(self) -> None:
        lines = [_Line('1', '1.00') for _ in range(3)]

        shares, _method = allocate(Decimal('10.00'), lines, ExtraCostAllocation.VALUE)

        # 10.00 over three equal lines is 3.33 three times and a penny left
        # over. A penny that quietly disappears is a penny missing from the
        # value of the stock.
        assert sum(shares.values()) == Decimal('10.00')
        assert sorted(shares.values()) == [
            Decimal('3.33'),
            Decimal('3.33'),
            Decimal('3.34'),
        ]

    def test_the_remainder_lands_on_the_last_line(self) -> None:
        """Where Odoo and ERPNext both put it.

        Which line carries the odd penny is convention, not arithmetic, and
        a warehouse that priced the same delivery in the system it came from
        should not have to account for a one-cent difference.
        """
        lines = [_Line('1', '1.00') for _ in range(3)]

        shares, _method = allocate(Decimal('10.00'), lines, ExtraCostAllocation.VALUE)

        assert [shares[line.id] for line in lines] == [
            Decimal('3.33'),
            Decimal('3.33'),
            Decimal('3.34'),
        ]

    def test_several_pennies_of_remainder_land_whole(self) -> None:
        """Six shares of 1.00 each round up, so the last line gives two back.

        The remainder is the sum of every line's rounding, not one penny, and
        the rule has to hold when it is bigger than a penny.
        """
        lines = [_Line('1', '1.00') for _ in range(6)]

        shares, _method = allocate(Decimal('1.00'), lines, ExtraCostAllocation.VALUE)

        assert sum(shares.values()) == Decimal('1.00')
        assert shares[lines[-1].id] == Decimal('0.15')
        assert [shares[line.id] for line in lines[:-1]] == [Decimal('0.17')] * 5


class TestNothingToSpreadOver:
    def test_an_empty_delivery_divides_by_nothing(self) -> None:
        shares, _method = allocate(Decimal('100.00'), [], ExtraCostAllocation.VALUE)

        assert shares == {}

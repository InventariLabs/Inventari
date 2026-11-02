"""Analytics rounds money the way the rest of the application does.

Python's ``round`` is banker's rounding on a binary float: it sends a half to
the nearest even digit, and it does not see a half where the binary
representation is a hair under one. So 2.675 came back as 2.67 and 0.125 as
0.12, while every invoice, document line and cost layer in this codebase
rounds half away from zero.

Two different answers to "what is this worth", depending on which screen
asked — and the analytics one is the screen a person compares against the
register.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.analytics._common import rounded

pytestmark = pytest.mark.unit


class TestAHalfGoesAwayFromZero:
    def test_a_half_cent_rounds_up(self) -> None:
        assert rounded(Decimal('2.675')) == 2.68
        assert rounded(Decimal('0.125')) == 0.13

    def test_it_does_not_depend_on_the_digit_before(self) -> None:
        """Banker's rounding sends 0.125 down and 0.135 up; ours sends both up."""
        assert rounded(Decimal('0.125')) == 0.13
        assert rounded(Decimal('0.135')) == 0.14

    def test_a_float_that_came_from_elsewhere_is_still_handled(self) -> None:
        """Not everything upstream is a Decimal yet, and none of it may crash."""
        assert rounded(2.5, 0) == 3.0
        assert rounded(None) == 0.0

    def test_three_places_for_quantities(self) -> None:
        """Drift is measured in stock units, which have three decimals."""
        assert rounded(Decimal('1.0005'), 3) == 1.001

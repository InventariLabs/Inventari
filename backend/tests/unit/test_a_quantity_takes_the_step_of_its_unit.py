"""A computed quantity is rounded to the step its unit is counted in.

Before this, every consumer of a conversion rounded to a hard three decimal
places, so a unit counted in whole pieces accepted 0.667 of one and a unit
counted in halves accepted 0.334 of one. ``Uom.rounding`` has carried the
right answer all along; these are the two ways of asking it.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID, uuid4

from app.services.uom_service import (
    quantity_step,
    quantize_to_uom,
    round_up_to_uom,
)


@dataclass
class _FakeUom:
    """Minimal UoM stand-in — the step helpers read ``rounding`` only."""

    id: UUID
    category_id: UUID
    factor: Decimal
    rounding: Decimal


def _uom(rounding: str) -> _FakeUom:
    return _FakeUom(
        id=uuid4(),
        category_id=uuid4(),
        factor=Decimal('1'),
        rounding=Decimal(rounding),
    )


class TestQuantityStep:
    """What step a unit is counted in."""

    def test_the_units_own_rounding_is_the_step(self) -> None:
        assert quantity_step(_uom('0.5')) == Decimal('0.5')
        assert quantity_step(_uom('1')) == Decimal('1')

    def test_the_column_scale_is_the_floor(self) -> None:
        # numeric(12,3) keeps three places; a unit naming six would have the
        # rest rounded away by Postgres, silently.
        assert quantity_step(_uom('0.000001')) == Decimal('0.001')

    def test_no_unit_falls_back_to_the_column_scale(self) -> None:
        assert quantity_step(None) == Decimal('0.001')

    def test_the_step_survives_the_columns_trailing_zeros(self) -> None:
        # ``rounding`` is numeric(12,6), so the database hands back 1.000000.
        assert quantity_step(_uom('1.000000')) == Decimal('1')


class TestAMeasurementTakesTheNearestStep:
    """What was scanned or moved reads to the nearest step."""

    def test_a_whole_unit_does_not_accept_a_fraction(self) -> None:
        assert quantize_to_uom(Decimal('2.4'), _uom('1')) == Decimal('2')
        assert quantize_to_uom(Decimal('2.6'), _uom('1')) == Decimal('3')

    def test_a_half_unit_quantizes_to_halves(self) -> None:
        assert quantize_to_uom(Decimal('2.3'), _uom('0.5')) == Decimal('2.5')
        assert quantize_to_uom(Decimal('2.1'), _uom('0.5')) == Decimal('2.0')

    def test_a_gram_keeps_three_places(self) -> None:
        assert quantize_to_uom(Decimal('1.23456'), _uom('0.001')) == Decimal('1.235')


class TestARequirementTakesTheNextStepUp:
    """What must be bought or picked never rounds down to nothing."""

    def test_part_of_a_whole_unit_is_a_whole_unit(self) -> None:
        # The regression this exists for: a third of an egg told the shopping
        # list to buy none.
        assert round_up_to_uom(Decimal('0.333'), _uom('1')) == Decimal('1')

    def test_part_of_a_half_unit_is_a_half_unit(self) -> None:
        assert round_up_to_uom(Decimal('2.1'), _uom('0.5')) == Decimal('2.5')

    def test_an_exact_multiple_is_left_alone(self) -> None:
        assert round_up_to_uom(Decimal('3'), _uom('1')) == Decimal('3')
        assert round_up_to_uom(Decimal('2.5'), _uom('0.5')) == Decimal('2.5')

    def test_nothing_needed_stays_nothing(self) -> None:
        assert round_up_to_uom(Decimal('0'), _uom('1')) == Decimal('0')

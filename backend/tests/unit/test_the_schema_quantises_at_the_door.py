"""A quantity is cut to the store's precision by the schema, not by Postgres.

``quantize_quantity`` was covered where it lives, and nowhere where it is
used: no test asked whether ``ItemCreate`` and ``ItemUpdate`` actually run
it. Unhooking the validator left the helper's own tests green, and the
column then rounded the extra places itself — silently, and banker's-style,
so 1.0005 landed as 1.000 while the client had been told 1.001.

These go through the schemas, because "the schema quantises" is the claim.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

from app.schemas.item import ItemCreate, ItemQuantityUpdate, ItemUpdate

pytestmark = pytest.mark.unit


class TestTheDoorQuantises:
    def test_a_create_rounds_the_fourth_place_half_up(self) -> None:
        item = ItemCreate(
            name='Rye flour',
            quantity=Decimal('1.0005'),
            location_id=uuid4(),
        )
        # Half away from zero, not to even: the column would have made this
        # 1.000 and said nothing.
        assert item.quantity == Decimal('1.001')

    def test_an_update_rounds_the_fourth_place_half_up(self) -> None:
        item = ItemUpdate(quantity=Decimal('2.99949'))
        assert item.quantity == Decimal('2.999')

    def test_a_quantity_update_rounds_the_fourth_place_half_up(self) -> None:
        assert ItemQuantityUpdate(quantity=Decimal('0.0005')).quantity == Decimal(
            '0.001'
        )

    def test_a_json_number_takes_the_same_door(self) -> None:
        """A client sending a JSON number gets the same three places.

        The value arrives as a float, so the before-validator has to make a
        Decimal of it before the after-validator can cut it — a payload, not
        a Decimal handed in by Python, is what a request actually carries.
        """
        item = ItemCreate.model_validate(
            {
                'name': 'Rye flour',
                'quantity': 1.0005,
                'location_id': str(uuid4()),
            }
        )
        assert item.quantity == Decimal('1.001')

    def test_a_quantity_already_at_the_step_is_left_alone(self) -> None:
        item = ItemCreate(
            name='Rye flour',
            quantity=Decimal('12.500'),
            location_id=uuid4(),
        )
        assert item.quantity == Decimal('12.500')


class TestTheNamedQuantityTravelsBeside:
    """The store keeps three places; the unit's gate reads what was named."""

    def test_a_create_keeps_the_fourth_place_for_the_gate(self) -> None:
        item = ItemCreate.model_validate(
            {
                'name': 'Rye flour',
                'quantity': 1.1234,
                'location_id': str(uuid4()),
            }
        )
        assert item.quantity == Decimal('1.123')
        assert item.quantity_as_named == Decimal('1.1234')

    def test_an_update_and_a_quantity_update_keep_it_too(self) -> None:
        assert ItemUpdate(quantity=Decimal('2.99949')).quantity_as_named == Decimal(
            '2.99949'
        )
        assert ItemQuantityUpdate(quantity=0.0005).quantity_as_named == Decimal(
            '0.0005'
        )

    def test_an_update_without_a_quantity_names_none(self) -> None:
        assert ItemUpdate(name='Rye').quantity_as_named is None

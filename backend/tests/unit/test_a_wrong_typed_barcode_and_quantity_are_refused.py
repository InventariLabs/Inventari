"""A value of the wrong JSON type is refused by the schema, never crashes it.

The before-validators on ``barcode`` and ``sku`` and the quantity quantizer
get raw request values. A number where a string belongs, or a quantity wider
than the decimal context, must come out as a ``ValidationError`` (a 422 on
the route), not an ``AttributeError`` or ``InvalidOperation`` (a 500).
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.item import ItemCreate
from app.schemas.product_template import ProductTemplateCreate
from app.schemas.validators import quantize_quantity


@pytest.mark.parametrize('schema', [ItemCreate, ProductTemplateCreate])
@pytest.mark.parametrize('field', ['barcode', 'sku'])
def test_a_number_in_a_text_field_is_a_validation_error(
    schema: type, field: str
) -> None:
    with pytest.raises(ValidationError) as caught:
        schema(**{'name': 'Widget', 'quantity': 1, field: 12345})

    assert (field,) in [error['loc'] for error in caught.value.errors()]


def test_a_quantity_wider_than_the_decimal_context_is_left_for_its_bound() -> None:
    wide = Decimal('1' * 40)

    assert quantize_quantity(wide) == wide
    assert quantize_quantity(Decimal('1.0005')) == Decimal('1.001')

"""The capacity row names the unit its limit is counted in.

The limit speaks the product's stock unit — the same sentence the write
path already obeys — but the response used to carry the number without the
unit, and "holds up to 10" reads the same for ten packages as for ten
kilograms. The router resolves the template's unit symbol beside the
product's name; a template without a unit answers None and the screen
shows the no-unit marker instead of inventing one.
"""

from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.modules.warehouse._router_capacity import _out_with_names
from app.modules.warehouse.models import PutawayCapacity

pytestmark = pytest.mark.unit


def _entry() -> PutawayCapacity:
    return cast(
        PutawayCapacity,
        SimpleNamespace(
            id=uuid4(),
            organization_id=uuid4(),
            location_id=uuid4(),
            product_template_id=uuid4(),
            max_quantity=Decimal('10'),
        ),
    )


def _patched_facades(template: Any, uom: Any) -> tuple[Any, Any, Any]:
    core = AsyncMock()
    core.locations.get_async = AsyncMock(return_value=SimpleNamespace(name='Fridge A'))
    core.product_templates.get_async = AsyncMock(return_value=template)
    core.uoms.get_async = AsyncMock(return_value=uom)
    po = AsyncMock()
    po.list_reorder_rules_async = AsyncMock(return_value=[])
    return (
        patch('app.modules.warehouse._router_capacity.core_api', core),
        patch(
            'app.modules.warehouse._router_capacity.order_side_async',
            AsyncMock(return_value=po),
        ),
        core,
    )


async def test_the_template_unit_rides_along_with_the_name() -> None:
    """The guard on the resolver: remove it from the router and this test is
    the one that reddens, because the symbol stops arriving."""
    template = SimpleNamespace(name='Flour', uom_id=uuid4())
    uom = SimpleNamespace(symbol='kg')
    core_patch, po_patch, _core = _patched_facades(template, uom)
    with core_patch, po_patch:
        dto = await _out_with_names(AsyncMock(), uuid4(), _entry())

    assert dto.product_template_name == 'Flour'
    assert dto.product_unit_symbol == 'kg'


async def test_a_template_without_a_unit_answers_none() -> None:
    """The other half, and only that half: what happens when the product has
    no unit at all.

    It pins the DTO's ``uom_id=None`` default *and* the branch that skips
    the lookup — a resolver that called the UOM API with a missing id would
    trip the ``assert_not_called``. It does not guard the resolver itself:
    deleting it leaves this test green, and
    ``test_the_template_unit_rides_along_with_the_name`` is the one that
    catches that.
    """
    template = SimpleNamespace(name='Mystery', uom_id=None)
    core_patch, po_patch, core = _patched_facades(template, None)
    with core_patch, po_patch:
        dto = await _out_with_names(AsyncMock(), uuid4(), _entry())

    assert dto.product_template_name == 'Mystery'
    assert dto.product_unit_symbol is None
    core.uoms.get_async.assert_not_called()

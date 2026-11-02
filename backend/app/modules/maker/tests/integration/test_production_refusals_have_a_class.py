"""The production refusals raise the 422 class, not ``AppException`` itself.

The bodies are pinned over HTTP next to the routes that answer them. This pins
the type, which a response cannot show: a handler or a test catching
``UnprocessableException`` has to see all four refusals.
"""

from __future__ import annotations

from typing import Any, cast
from uuid import uuid4

import pytest

from app.core.exceptions import UnprocessableException
from app.modules.maker._router_production import (
    _empty_bom_refusal,
    _shortage_refusal,
)
from app.modules.maker.exceptions import (
    EmptyBillOfMaterialsError,
    InsufficientStockError,
    ShortageBlockedError,
    ShortageError,
    ShortageWarningError,
)


@pytest.mark.parametrize(
    ('error', 'raised'),
    [
        ('shortage_blocked', ShortageBlockedError([])),
        ('shortage_warning', ShortageWarningError([])),
        ('insufficient_stock', InsufficientStockError([])),
    ],
)
def test_a_shortage_is_answered_by_the_422_class(
    error: str, raised: ShortageError
) -> None:
    refusal = _shortage_refusal(error, raised)

    assert isinstance(refusal, UnprocessableException)
    assert refusal.status_code == 422
    detail = cast(dict[str, Any], refusal.detail)
    assert detail['code'] == error
    assert detail['error'] == error
    assert detail['shortages'] == []


def test_an_empty_formula_is_answered_by_the_422_class() -> None:
    raised = EmptyBillOfMaterialsError(uuid4(), 'Bread')

    refusal = _empty_bom_refusal(raised)

    assert isinstance(refusal, UnprocessableException)
    assert refusal.status_code == 422
    detail = cast(dict[str, Any], refusal.detail)
    assert detail['code'] == 'empty_bom'
    assert detail['recipe_name'] == 'Bread'

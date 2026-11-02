"""The warehouse loads, and runs, without the purchase orders module.

The two modules used to import each other: the warehouse weighed receipts
against the order, read replenishment, reorder rules and pricelists from the
orders module, and the orders module required the warehouse. The over-order
guard is now a pre-post check the orders module registers, the replenishment
routes are the orders module's own, and what is left (a price hint, a shelf's
reorder ceiling, an order's currency, the count on completion) is asked of
the orders module on the call, only while it is there (``_order_side``).
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from .test_the_warehouse_loads_without_approvals import _module_level_imports

_WAREHOUSE = Path(__file__).resolve().parents[2]


@pytest.mark.unit
def test_no_warehouse_file_imports_purchase_orders_when_it_is_imported() -> None:
    offenders = sorted(
        str(path.relative_to(_WAREHOUSE))
        for path in _WAREHOUSE.rglob('*.py')
        if 'tests' not in path.relative_to(_WAREHOUSE).parts
        and 'migrations' not in path.relative_to(_WAREHOUSE).parts
        and any(
            name == 'app.modules.purchase_orders'
            or name.startswith('app.modules.purchase_orders.')
            for name in _module_level_imports(
                ast.parse(path.read_text(encoding='utf-8'))
            )
        )
    )

    assert offenders == []


@pytest.mark.unit
def test_only_the_order_side_reaches_for_the_orders_module_at_all() -> None:
    """One door, so the degradation lives in one place."""
    callers = sorted(
        str(path.relative_to(_WAREHOUSE))
        for path in _WAREHOUSE.rglob('*.py')
        if 'tests' not in path.relative_to(_WAREHOUSE).parts
        and 'migrations' not in path.relative_to(_WAREHOUSE).parts
        and path.name != '_order_side.py'
        and 'from app.modules.purchase_orders' in path.read_text(encoding='utf-8')
    )

    assert callers == []


@pytest.mark.unit
def test_the_manifest_declares_the_orders_module_optional() -> None:
    manifest = json.loads((_WAREHOUSE / 'manifest.json').read_text(encoding='utf-8'))

    assert 'purchase_orders' in manifest['optional_requires']
    assert 'purchase_orders' not in manifest['requires']

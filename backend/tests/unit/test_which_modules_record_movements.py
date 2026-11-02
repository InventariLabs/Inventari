"""The interface's list of stock-recording modules mirrors the manifests.

The movement ledger's navigation entry is offered only to organizations with
a module that reads the register. Every organization writes movements now,
but a household without such a module was promised no visible change, so the
entry stays where it was.

The frontend cannot read a manifest, so it carries that list by hand in
``frontend/src/modules/inventory/module.ts`` (``requiresModules``). A mirror
nobody checks drifts, so this is the check: the day a module declares
``consumes_stock_quant``, this test fails and names the file to update.
"""

from __future__ import annotations

import pytest

#: What ``requiresModules`` says on the ledger's nav entry.
NAV_ENTRY_MODULES = {'warehouse', 'maker', 'purchase_orders', 'stock_takes'}


@pytest.mark.unit
def test_the_nav_entry_lists_every_module_that_records_movements() -> None:
    from app.core.module_registry import module_registry

    recording = {
        module.metadata.name
        for module in module_registry.get_all()
        if module.metadata.consumes_stock_quant
    }

    assert recording == NAV_ENTRY_MODULES, (
        'The modules that record stock movements changed. Update '
        "`requiresModules` on the '/inventory/moves' entry in "
        'frontend/src/modules/inventory/module.ts, then this constant.'
    )

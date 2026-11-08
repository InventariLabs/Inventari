"""A pick-order strategy name belongs to the module that registered it.

The registry was one flat namespace keyed by name alone, so a second module
registering a name another had taken replaced it in silence — the default
walk included — and the organization that had chosen it walked by a
stranger's rule. Document filters were keyed by (module, name) all along.
A clash between two modules is now refused; the same module registering its
own name again still replaces it, which is what a reload does.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest

from app.core.exceptions import ContractViolationError
from app.modules.warehouse import pick_order_strategies as registry


async def _walk(db: Any, org_id: UUID, lines: list[Any]) -> list[Any]:
    return lines


@pytest.fixture(autouse=True)
def _own_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(registry, '_STRATEGIES', dict(registry._STRATEGIES))


@pytest.mark.unit
class TestOneNameOneOwner:
    def test_another_module_cannot_take_the_default(self) -> None:
        with pytest.raises(ContractViolationError, match='warehouse'):
            registry.register_pick_order_strategy(
                'route_planner', registry.DEFAULT_PICK_ORDER_STRATEGY, _walk
            )
        owner, _ = registry.pick_order_strategies()[
            registry.DEFAULT_PICK_ORDER_STRATEGY
        ]
        assert owner == 'warehouse'

    def test_the_owner_registering_again_replaces_its_own(self) -> None:
        registry.register_pick_order_strategy('route_planner', 'by_zone', _walk)

        async def _other(db: Any, org_id: UUID, lines: list[Any]) -> list[Any]:
            return lines

        registry.register_pick_order_strategy('route_planner', 'by_zone', _other)

        assert registry.pick_order_strategies()['by_zone'] == ('route_planner', _other)

"""Integration test for the public maker_api singleton (cross-module contract)."""

from __future__ import annotations

import pytest

from app.modules.maker import maker_api as maker_api_pkg  # noqa: F401
from app.modules.maker.maker_api import maker_api

pytestmark = pytest.mark.integration


class TestMakerApiSingleton:
    """`maker_api` is a process-wide singleton — same memory address across imports."""

    def test_maker_api_is_singleton(self) -> None:
        from app.modules.maker.maker_api import maker_api as api_2

        assert maker_api is api_2

    def test_maker_api_exposes_required_methods(self) -> None:
        required = (
            'list_bom_lines_async',
            'explode_bom_async',
            'compute_total_cost_async',
            'compute_unit_cost_async',
            'get_breakdown_async',
            'complete_production_async',
        )
        for name in required:
            assert hasattr(maker_api, name), f'maker_api missing {name}'
            assert callable(getattr(maker_api, name))

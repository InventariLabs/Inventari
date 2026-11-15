"""Maker module — Bill of Materials, production runs and cost rollup."""

from typing import Any

from fastapi import APIRouter

from app.core.define_module import define_module


def _get_router() -> APIRouter:
    from app.modules.maker.router import router

    return router


def _get_interceptors() -> list[Any]:
    from app.modules.maker.interceptors import ProductionOrderStorageGuard

    return [ProductionOrderStorageGuard()]


def _register_work_item_provider() -> None:
    """Put the production runs planned for the day into To do.

    Registered at import, like the other cross-module providers, so the list
    does not depend on which organisation started first; the warehouse module
    only calls it while this module is enabled for the organisation asking.
    """
    from app.modules.maker.maker_api import maker_api
    from app.modules.warehouse.warehouse_api import warehouse_api

    warehouse_api.register_work_item_provider('maker', maker_api.list_work_items_async)


_register_work_item_provider()


def _register_typed_prices() -> None:
    """Let Core's estimate policy ask the prices typed on a product.

    The table is this module's; the order of the answers — layers, then a
    supplier's quote, then a typed price — is Core's. A feature that wants
    its own source plugs in the same way, which is why the port lives in
    Core beside the supplier one.
    """
    from app.core.cost_estimates import register_typed_price_provider

    from .ingredient_prices import typed_rates_async

    register_typed_price_provider(typed_rates_async)


_register_typed_prices()


def _register_lot_trace_source() -> None:
    """Make a production run a hop in a batch's recall trace.

    At import, like the provider above; Core's trace calls it for the runs
    it finds in the ledger.
    """
    from app.core.module_sdk import register_lot_trace_source
    from app.modules.maker.lot_trace_source import ProductionLotTraceSource

    register_lot_trace_source(ProductionLotTraceSource())


_register_lot_trace_source()


def _register_contributions() -> None:
    """Let ``/uploads/`` serve a run's files to its own organization."""
    from typing import cast

    from app.core.module_sdk import BaseContribution, contribution_registry

    from .resolvers import ProductionAttachmentResolver

    contribution_registry.register(
        'upload_path_resolvers',
        cast(BaseContribution, ProductionAttachmentResolver()),
    )


module = define_module(
    router_factory=_get_router,
    interceptors=_get_interceptors(),
    register_contributions_hook=_register_contributions,
    consumes_stock_quant=True,
)

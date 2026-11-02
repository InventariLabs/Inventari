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


module = define_module(
    router_factory=_get_router,
    interceptors=_get_interceptors(),
    consumes_stock_quant=True,
)

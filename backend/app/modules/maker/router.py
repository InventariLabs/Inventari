"""Maker module router aggregator.

Sub-routers: BOM (lines), production orders, cost breakdown, pricing.
The module gate (require_module('maker')) is applied here so all
sub-routers are protected uniformly.
"""

from fastapi import APIRouter, Depends

from app.core.deps import require_read_write
from app.core.modules import require_module

from ._router_bom import router as bom_router
from ._router_breakdown import router as breakdown_router
from ._router_pricing import router as pricing_router
from ._router_production import router as production_router
from ._router_recipes import router as recipes_router
from ._router_recipes import settings_router as maker_settings_router

_MODULE_DEPS = [
    Depends(require_module('maker')),
    require_read_write('maker:read', 'maker:write'),
]

router = APIRouter(dependencies=_MODULE_DEPS)
router.include_router(bom_router)
router.include_router(recipes_router)
router.include_router(maker_settings_router)
router.include_router(production_router)
router.include_router(breakdown_router)
router.include_router(pricing_router)

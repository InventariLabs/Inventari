from fastapi import APIRouter, Depends

from app.core.deps import require_read_write
from app.core.modules import require_module

from ._router_approvals import router as approvals_router
from ._router_assets import router as assets_router
from ._router_assignments import router as assignments_router
from ._router_attachments import router as attachments_router
from ._router_bulk import router as bulk_router
from ._router_campaigns import router as campaigns_router
from ._router_dashboard import router as dashboard_router
from ._router_import import router as import_router
from ._router_maintenance import router as maintenance_router
from ._router_models import router as models_router
from ._router_my_assets import router as my_assets_router
from ._router_protocols import router as protocols_router
from ._router_templates import router as templates_router
from .router_valuation import router as valuation_router

router = APIRouter()

_MODULE_DEPS = [
    Depends(require_module('equipment')),
    require_read_write('equipment:read', 'equipment:write'),
]

router.include_router(bulk_router, dependencies=_MODULE_DEPS)
router.include_router(assets_router, dependencies=_MODULE_DEPS)
router.include_router(assignments_router, dependencies=_MODULE_DEPS)
router.include_router(attachments_router, dependencies=_MODULE_DEPS)
router.include_router(approvals_router, dependencies=_MODULE_DEPS)
router.include_router(my_assets_router, dependencies=_MODULE_DEPS)
router.include_router(models_router, dependencies=_MODULE_DEPS)
router.include_router(maintenance_router, dependencies=_MODULE_DEPS)
router.include_router(dashboard_router, dependencies=_MODULE_DEPS)
router.include_router(import_router, dependencies=_MODULE_DEPS)
router.include_router(protocols_router, dependencies=_MODULE_DEPS)
router.include_router(templates_router, dependencies=_MODULE_DEPS)
router.include_router(campaigns_router, dependencies=_MODULE_DEPS)
router.include_router(valuation_router, dependencies=_MODULE_DEPS)

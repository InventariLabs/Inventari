"""Purchase Order API endpoints."""

from fastapi import APIRouter, Depends

from app.core.deps import require_read_write
from app.core.modules import require_module

from ._router_approval import register_approval_routes
from ._router_import import register_import_routes
from ._router_po import register_po_routes
from ._router_pricelist import register_pricelist_routes
from ._router_reorder import register_reorder_routes
from ._router_settings import register_settings_routes
from ._router_templates import _templates_router

#: The module's declared permissions, enforced once for every route below
#:. Confirming an order, turning it into a receipt or e-mailing a
#: supplier were open to any member of the organization; the manifest promised
#: otherwise. Every POST here writes, so the HTTP method carries the split.
router = APIRouter(
    dependencies=[
        Depends(require_module('purchase_orders')),
        require_read_write('purchase_orders:read', 'purchase_orders:write'),
    ]
)

router.include_router(_templates_router, prefix='/templates')

# Single-segment routes (reorder-rules, settings) MUST be registered
# before register_po_routes: GET /{po_id} would otherwise shadow them
# and fail UUID validation.
register_reorder_routes(router)
register_settings_routes(router)
register_po_routes(router)
register_import_routes(router)
register_pricelist_routes(router)
register_approval_routes(router)

"""What the warehouse asks of the purchase orders module, when it is there.

The warehouse stands on its own: a receipt that names no order line never
meets this file. A receipt that does — ``source_po_line_id`` is a permanent
column of the document line — can be weighed against the order, priced in
the order's currency, and counted on the order when it completes, and a
shelf's capacity can be read beside the reorder rule that fills it. Each of
those is a question for the orders module, which answers it only while it is
installed and switched on for the organization; without it the warehouse goes
on with what it has, as for any line that names no order.

The orders module is a declared optional companion in the manifest
(``optional_requires``), so the store names it. Nothing here is imported when
the warehouse is: the orders module is reached on the call, never on import,
so the warehouse runs without it switched on.
The reverse edge is the orders module's — it requires the warehouse, and the
over-order guard is a pre-post check it registers (``purchase_orders``
``_over_order_check``).
"""

from __future__ import annotations

import importlib.util
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.public_api import core_api

if TYPE_CHECKING:
    from app.modules.purchase_orders.purchase_orders_api import PurchaseOrdersAPI

MODULE = 'purchase_orders'


async def order_side_async(db: AsyncSession, org_id: UUID) -> PurchaseOrdersAPI | None:
    """The orders module's API, or ``None`` when it is absent or switched off."""
    if importlib.util.find_spec(f'app.modules.{MODULE}') is None:
        return None
    if not await core_api.organizations.is_module_enabled_async(db, org_id, MODULE):
        return None
    from app.modules.purchase_orders.purchase_orders_api import purchase_orders_api

    return purchase_orders_api

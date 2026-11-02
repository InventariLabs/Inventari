"""What the approvals engine's decisions do to the purchase order they were about.

The order's own routes move it on approve and reject. A request released
because its workflow was switched off left the order in PENDING_APPROVAL with
nothing pending; a released order goes on as if no approval had been asked:
CONFIRMED. A request the requester withdrew changes nothing here.

Registered at import time (see ``module.py``); runs inside the deciding
transaction and must not commit.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.approvals.approvals_api import TargetDecision


async def apply_approval_decision(db: AsyncSession, decision: TargetDecision) -> None:
    """Take an order out of PENDING_APPROVAL when its request was closed."""
    # Approve and reject are the order routes' own business. A request the
    # requester withdrew leaves the order parked (it still has to be approved);
    # only a request released with its workflow lets the order go on, and only
    # an order still parked is touched, so a cancelled order stays cancelled.
    if decision.outcome != 'CANCELLED' or not decision.released:
        return
    # Absolute and late: ``module.py`` registers this while the package is
    # still being imported, and a relative import reached from the registry's
    # own import binds a second copy of the models to the same metadata.
    from app.modules.purchase_orders._service_crud import get_purchase_order

    po = await get_purchase_order(db, decision.organization_id, decision.target_id)
    if po is None or po.status != 'PENDING_APPROVAL':
        return
    po.status = 'CONFIRMED'
    po.confirmed_by = decision.decided_by or decision.requester_id
    po.confirmed_at = datetime.now(UTC)
    await db.flush()

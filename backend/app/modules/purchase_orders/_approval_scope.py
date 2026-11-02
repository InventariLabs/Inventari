"""What an active purchase-order workflow holds — the settings rule, told in advance.

A purchase-order workflow carries out what the order settings ask for and
holds nothing on its own: ``_service_workflow._is_approval_required`` reads
the settings, never the workflow. The approvals screen shows this before an
administrator switches a workflow on, so the answer comes from here, next to
the rule it describes.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.public_api import core_api
from app.modules.approvals.approvals_api import WorkflowScope, WorkflowScopeCondition


async def describe_po_approval_scope(db: AsyncSession, org_id: UUID) -> WorkflowScope:
    """What a purchase-order workflow holds under this organization's settings."""
    # Imported here: this module is registered while the package is still
    # being imported, and the settings service pulls in the ORM models.
    from app.modules.purchase_orders._service_settings import get_po_settings

    settings = await get_po_settings(db, org_id)
    if settings is None:
        return WorkflowScope(holds='nothing')
    if settings.approval_required:
        return WorkflowScope(holds='all', required_by_settings=['approval_required'])
    if settings.approval_threshold is None:
        return WorkflowScope(holds='nothing')

    org = await core_api.organizations.get_async(db, org_id)
    org_currency = (org.currency if org else None) or 'USD'
    return WorkflowScope(
        holds='some',
        conditions=[
            # An order nobody priced cannot be shown to be under the limit.
            WorkflowScopeCondition(
                kind='value_above',
                amount=settings.approval_threshold,
                currency=org_currency,
                unpriced_included=True,
            ),
            # No exchange rates: an order in another currency cannot be
            # compared with the threshold, so it is always held.
            WorkflowScopeCondition(kind='foreign_currency', currency=org_currency),
        ],
        required_by_settings=['approval_threshold'],
    )

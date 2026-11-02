"""What an active document workflow holds — the gate's rule, told in advance.

The approvals screen asks before an administrator switches a document
workflow on, and shows the answer on the workflow's card while it is on. The
answer has to be the one the approvals module's document gate gives a
document (``document_sign_off``): a profile that names nothing leaves the workflow to hold every
confirmed document; a type list or a threshold is the filter.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from .approval_service import required_types
from .document_profile_service import get_profile, resolve_document_currency

if TYPE_CHECKING:
    from app.modules.approvals.approvals_api import WorkflowScope


async def describe_document_approval_scope(
    db: AsyncSession, org_id: UUID
) -> WorkflowScope:
    """What a document workflow holds under this organization's profile.

    Read-only on purpose: an organization with no profile row yet has the
    default one's answer (it names nothing), and creating the row is the
    profile screen's business, not a list's.
    """
    # Asked only by the approvals module, so it is there to import from.
    from app.modules.approvals.approvals_api import (
        WorkflowScope,
        WorkflowScopeCondition,
    )

    profile = await get_profile(db, org_id)
    if profile is None:
        return WorkflowScope(holds='all')

    types = required_types(profile)
    threshold = profile.approval_threshold
    if not types and threshold is None:
        return WorkflowScope(holds='all')

    conditions: list[WorkflowScopeCondition] = []
    settings: list[str] = []
    if types:
        conditions.append(
            WorkflowScopeCondition(kind='document_types', document_types=types)
        )
        settings.append('approval_required_for_types')
    if threshold is not None:
        # An unpriced document cannot be shown to be under the limit, so the
        # gate holds it too — the sentence says so rather than surprise anyone.
        conditions.append(
            WorkflowScopeCondition(
                kind='value_above',
                amount=threshold,
                currency=await resolve_document_currency(db, org_id, profile),
                unpriced_included=True,
            )
        )
        settings.append('approval_threshold')
    return WorkflowScope(
        holds='some', conditions=conditions, required_by_settings=settings
    )

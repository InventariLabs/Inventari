"""What the organization log is told about an approval request.

The log holds the whole life of a request, not only its end: somebody asked,
somebody answered, or the asker took the question back. Only the answers were
written down at first, so the journal showed a decision with nothing before it
-- and a request still waiting showed nothing at all, while it was the reason
a document would not move.

A leaf module on purpose: the request service and the decision service both
need the same shape, and neither should have to import the other for it.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import AuditAction, AuditTargetType
from app.core.public_api import core_api

from .models import ApprovalRequest
from .target_summaries import get_target_summary_provider

#: The reason column is 500 characters and a note is unbounded text. A note
#: too long to store must not be able to fail the decision it explains.
_REASON_LIMIT = 500


def as_reason(notes: str | None) -> str | None:
    if notes is None or len(notes) <= _REASON_LIMIT:
        return notes
    return notes[: _REASON_LIMIT - 1] + '…'


async def people_names_async(
    db: AsyncSession, org_id: UUID, user_ids: list[UUID]
) -> dict[str, str]:
    """The names the log writes for people, keyed by the id as a string.

    A journal reader cannot look an id up: an entry naming an approver by
    ``b1235cdc-…`` answers nothing. The name a person had when the entry was
    written is what the entry keeps; an id nobody in the organization
    carries any more stays as it was.
    """
    if not user_ids:
        return {}
    users = await core_api.users.get_by_ids_async(db, org_id, user_ids)
    return {str(user.id): user.full_name or user.email for user in users}


def approves(request: ApprovalRequest) -> dict[str, str]:
    """What the request stands in front of.

    The entry is about the request; this is the thing a reader is actually
    after -- an entry saying "approved" without naming the document is an
    answer to a question the log never recorded.
    """
    return {'type': request.target_type, 'id': str(request.target_id)}


async def _target_number_async(
    db: AsyncSession, request: ApprovalRequest
) -> str | None:
    """The number the target is known by, when its module can say one.

    The journal's Target column showed eight characters of the request's
    uuid and the type — "8d6f4bf7 Wniosek o akceptację" — so an auditor
    filtering for a document number found nothing to read. Whoever
    registered the target's summary provider names the record; a type
    nobody claimed keeps the identifier it had.
    """
    provider = get_target_summary_provider(request.target_type)
    if provider is None:
        return None
    summaries = await provider(db, request.organization_id, [request.target_id])
    summary = summaries.get(request.target_id)
    number = getattr(summary, 'number', None)
    return str(number) if number else None


async def log_request_async(
    db: AsyncSession,
    request: ApprovalRequest,
    *,
    user_id: UUID,
    action: AuditAction,
    snapshot: dict[str, Any],
    reason: str | None = None,
    meta_data: dict[str, Any] | None = None,
) -> None:
    descriptor = approves(request)
    number = await _target_number_async(db, request)
    if number:
        descriptor['number'] = number
    await core_api.audit_log.log_action_async(
        db,
        organization_id=request.organization_id,
        user_id=user_id,
        action=action,
        target_type=AuditTargetType.APPROVAL_REQUEST,
        target_id=request.id,
        snapshot={**snapshot, 'approves': descriptor},
        reason=reason,
        meta_data=meta_data,
    )

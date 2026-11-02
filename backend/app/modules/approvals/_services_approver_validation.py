# architecture: allow_direct_db_access
# reason: approver cross-tenant validation requires a sync-friendly IN
# query against the Core User table that CoreUsersAPI does not provide.
from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.user import User

from .exceptions import ApprovalError

logger = get_logger(__name__)


async def validate_approvers_in_org(
    db: AsyncSession,
    org_id: UUID,
    approver_ids: Iterable[UUID | str],
) -> set[UUID]:
    """Return the subset of ``approver_ids`` that do NOT belong to ``org_id``.

    Closes a cross-tenant leak: callers can pass any UUID in
    ``stage.approver_user_ids`` (the field is a ``list[UUID]`` with no FK),
    so without this check a workflow could pin approvals to users from
    another organisation (or to non-existent IDs). The check is a single
    ``id IN (...) AND organization_id = :org`` query against the Core
    ``users`` table.

    ``approver_ids`` may contain either UUID objects (in-process callers)
    or strings (when ``stages`` has been run through
    ``model_dump(mode='json')`` at the router boundary); both forms are
    normalised to UUIDs before the query. Pydantic validates the
    schema-level shape, so malformed strings cannot reach this path.
    """
    parsed: set[UUID] = {
        uid if isinstance(uid, UUID) else UUID(str(uid)) for uid in approver_ids if uid
    }
    if not parsed:
        return set()
    stmt = select(User.id).where(
        User.id.in_(parsed),
        User.organization_id == org_id,
    )
    result = await db.execute(stmt)
    valid = {row[0] for row in result.all()}
    return parsed - valid


async def ensure_approvers_in_org(
    db: AsyncSession,
    org_id: UUID,
    approver_ids: Iterable[UUID | str],
) -> None:
    """Raise ``ApprovalError`` when any of ``approver_ids`` is outside org_id."""
    invalid = await validate_approvers_in_org(db, org_id, approver_ids)
    if invalid:
        # The ids go to the log, not to the reader: a list of UUIDs tells
        # someone picking approvers nothing they can act on.
        logger.warning(
            '[Approvals] approvers outside org %s: %s',
            org_id,
            ', '.join(sorted(str(uid) for uid in invalid)),
        )
        raise ApprovalError.translated('approval_unknown_approvers')

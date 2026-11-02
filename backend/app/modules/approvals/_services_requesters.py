"""Whose submissions a workflow holds.

A workflow says who decides (its stages) and, in ``requester_scope``, whose
documents, orders or checkouts it holds: everyone, or the people and roles
it names. The module that owns a target still decides *what* needs an
approval (``docs/purpose/approvals.md``); this answers the question every
one of them asks first — is this person's submission under the workflow at
all? Somebody outside the scope never waits, whatever the module's settings
say.

A role is read at the moment of the question, so a person moved out of a
scoped role stops being held from their next submission. Requests already
open are not asked again: they were raised, and they wait on their stages.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.public_api import core_api

from ._services_approver_validation import validate_approvers_in_org
from .exceptions import ApprovalError
from .models import ApprovalWorkflow
from .schemas import RequesterLabel

logger = get_logger(__name__)


async def requester_in_scope_async(
    db: AsyncSession, org_id: UUID, workflow: ApprovalWorkflow, user_id: UUID
) -> bool:
    """Whether ``workflow`` holds what ``user_id`` submits."""
    scope = workflow.requester_scope or {'everyone': True}
    if scope.get('everyone', True):
        return True
    if str(user_id) in {str(uid) for uid in scope.get('user_ids') or []}:
        return True
    role_ids = {str(rid) for rid in scope.get('role_ids') or []}
    if not role_ids:
        return False
    held = await core_api.roles.role_ids_for_user_async(db, org_id, user_id)
    return bool(role_ids & {str(rid) for rid in held})


async def ensure_requesters_in_org(
    db: AsyncSession, org_id: UUID, scope: dict[str, Any]
) -> None:
    """Refuse a scope naming people or roles from outside the organization."""
    if scope.get('everyone', True):
        return
    unknown_users = await validate_approvers_in_org(
        db, org_id, scope.get('user_ids') or []
    )
    known_roles = {
        str(role.id) for role in await core_api.roles.list_for_org_async(db, org_id)
    }
    unknown_roles = {str(rid) for rid in scope.get('role_ids') or []} - known_roles
    if unknown_users or unknown_roles:
        logger.warning(
            '[Approvals] requester scope outside org %s: users %s, roles %s',
            org_id,
            sorted(str(uid) for uid in unknown_users),
            sorted(unknown_roles),
        )
        raise ApprovalError.translated('approval_unknown_requesters')


async def requester_labels_async(
    db: AsyncSession, org_id: UUID, workflows: list[ApprovalWorkflow]
) -> dict[UUID, list[RequesterLabel]]:
    """The people and roles each workflow names, by name, roles first.

    Read once for the whole list. Somebody who has since left the
    organization, or a role deleted after it was chosen, is left out rather
    than shown as an id nobody can read.
    """
    scoped = [
        wf for wf in workflows if not (wf.requester_scope or {}).get('everyone', True)
    ]
    if not scoped:
        return {wf.id: [] for wf in workflows}
    roles = {
        str(role.id): role
        for role in await core_api.roles.list_for_org_async(db, org_id)
    }
    user_ids = {
        UUID(str(uid))
        for wf in scoped
        for uid in wf.requester_scope.get('user_ids') or []
    }
    users = {
        str(user.id): user
        for user in await core_api.users.get_by_ids_async(db, org_id, list(user_ids))
    }
    labels: dict[UUID, list[RequesterLabel]] = {wf.id: [] for wf in workflows}
    for wf in scoped:
        for rid in wf.requester_scope.get('role_ids') or []:
            role = roles.get(str(rid))
            if role is not None:
                labels[wf.id].append(
                    RequesterLabel(
                        kind='role',
                        id=role.id,
                        name=role.name,
                        is_system=role.is_system,
                    )
                )
        for uid in wf.requester_scope.get('user_ids') or []:
            user = users.get(str(uid))
            if user is not None:
                labels[wf.id].append(
                    RequesterLabel(
                        kind='user', id=user.id, name=user.full_name or user.email
                    )
                )
    return labels

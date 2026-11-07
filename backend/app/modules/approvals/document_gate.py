"""The approvals module's gate on the warehouse's documents.

The warehouse used to ask for approvals itself: confirming a document called
this module to decide whether a request was due, raised it and parked the
document; completing it called the check that refuses an unapproved one. It
imported the module to do so, in a dozen files, so documents did not load
without it and no other module could gate a document the same way.

The direction is now the platform's. The warehouse asks every module's
pre-post check before it confirms a document and before it moves its stock;
this module registers one (``module.py``). At confirmation the check raises
the request and answers ``'hold'`` — the warehouse parks the document for
this module — and at posting it refuses a document under the control that
has no approval. A decision on the request releases the document, takes the
hold back or sends it to a draft through ``warehouse_api``, and a document
cancelled or deleted withdraws its open request.

One rule says whether a document needs approval. The profile, which is the
warehouse's, says *what* needs signing off — a listed type, a value over the
threshold — and the workflow, which is ours, says *who* approves. An active
workflow on its own demands approval only while the profile names nothing:
naming the approvers and listing nothing is the statement that everything is
approved. A profile that names a threshold or a type has said what it means,
and the workflow carries that answer out instead of widening it. The
requester comes first: somebody the workflow does not name submits without
an approval, whatever the profile says of everybody else's documents.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import DocumentToPostDTO
from app.core.exceptions import ServiceRejectionError
from app.core.logging import get_logger
from app.core.module_sdk import InterceptorError
from app.i18n.service import get_current_lang, get_error_message

from .approvals_api import approvals_api
from .exceptions import ApprovalError, ApprovalRequiredError
from .target_decisions import TargetDecisionRefusedError
from .target_types import TargetType

if TYPE_CHECKING:
    from app.modules.warehouse.warehouse_api import WarehouseAPI

    from .target_decisions import TargetDecision

logger = get_logger(__name__)

#: The name a document waits under, and the one its pre-post check answers to.
MODULE = 'approvals'
_TARGET = TargetType.DOCUMENT.value


def warehouse_documents() -> WarehouseAPI:
    # Imported when asked: the check, the listener and the routes run only
    # where the warehouse is installed (``module.py`` registers them so).
    from app.modules.warehouse.warehouse_api import warehouse_api

    return warehouse_api


async def document_needs_approval_async(
    db: AsyncSession,
    org_id: UUID,
    document_id: UUID,
    *,
    requester_id: UUID | None,
    as_status: str | None = None,
    requester_exempt: bool | None = None,
) -> bool:
    """Whether this document needs an approval, by the one rule above.

    ``requester_id`` is whoever submits the document — the person confirming
    it, or for a document already confirmed, the one who did. ``as_status``
    weighs the document at a status other than its own: a screen that has to
    name the consequence before the confirm button is pressed asks about the
    document a draft is about to become — one rule answered twice, rather
    than a second rule. ``requester_exempt`` is a caller's cached answer to
    the workflow's first question, for a list screen asking about many
    documents of one person; left out, the question is asked here.
    """
    if requester_exempt is None:
        requester_exempt = await approvals_api.requester_exempt(
            db, org_id, _TARGET, requester_id
        )
    if requester_exempt:
        return False
    sign_off = await warehouse_documents().document_sign_off_async(
        db, org_id, document_id, as_status=as_status
    )
    if sign_off != 'unspecified':
        return sign_off == 'required'
    return await approvals_api.get_active_workflow(db, org_id, _TARGET) is not None


async def documents_needing_approval_async(
    db: AsyncSession,
    org_id: UUID,
    documents: Sequence[tuple[UUID, UUID | None]],
) -> set[UUID]:
    """Which of ``(document_id, requester_id)`` pairs the rule covers.

    The list form of ``document_needs_approval_async``, for a screen that has
    to say before the tap which rows its own action would refuse. Every
    answer is that function's, asked in batches: the exemption once per
    requester, who is usually the same person across a page; the profile's
    verdict once for all the documents of the people it does not exempt; and
    the active workflow once, and only when the profile left a document to it.
    """
    exemptions: dict[UUID | None, bool] = {}
    for _, requester_id in documents:
        if requester_id not in exemptions:
            exemptions[requester_id] = await approvals_api.requester_exempt(
                db, org_id, _TARGET, requester_id
            )
    covered = [
        document_id
        for document_id, requester_id in documents
        if not exemptions[requester_id]
    ]
    sign_offs = await warehouse_documents().documents_sign_off_async(
        db, org_id, covered
    )
    required = {
        document_id
        for document_id, sign_off in sign_offs.items()
        if sign_off == 'required'
    }
    # Silence in the profile leaves the document to the workflow: it needs
    # approval exactly when one is active, which is one answer for them all.
    left_to_workflow = {
        document_id
        for document_id, sign_off in sign_offs.items()
        if sign_off == 'unspecified'
    }
    if (
        left_to_workflow
        and await approvals_api.get_active_workflow(db, org_id, _TARGET) is not None
    ):
        required |= left_to_workflow
    return required


async def gate_document_async(
    db: AsyncSession, org_id: UUID, document: DocumentToPostDTO
) -> Literal['hold'] | None:
    """The pre-post check: hold at confirmation, refuse at posting."""
    if document.stage == 'confirm':
        return await _hold_when_due(db, org_id, document)
    await _refuse_unless_approved(db, org_id, document)
    return None


async def _hold_when_due(
    db: AsyncSession, org_id: UUID, document: DocumentToPostDTO
) -> Literal['hold'] | None:
    if document.confirmed_by is None or not await document_needs_approval_async(
        db,
        org_id,
        document.id,
        requester_id=document.confirmed_by,
        as_status='CONFIRMED',
    ):
        return None
    # The profile asked for an approval there is nothing to carry out. That
    # is a configuration error, not graceful degradation: confirming silently
    # would let the "require approval" setting do nothing while the reader
    # believes the document is controlled. A workflow that is there gated the
    # document in the first place.
    if await approvals_api.get_active_workflow(db, org_id, _TARGET) is None:
        raise ServiceRejectionError('documents_approval_workflow_missing')
    # In the confirmation's transaction: a refusal after this check takes the
    # request with it, and the approvers hear of it only once it commits.
    request = await approvals_api.request_approval(
        db,
        org_id,
        _TARGET,
        document.id,
        document.confirmed_by,
        meta_data={'auto_created': True, 'source': 'confirm_document'},
    )
    # A workflow whose every stage is the requester's own is decided the
    # moment it is raised; holding the document then would leave it waiting
    # for an answer it already has.
    return None if request.status == 'APPROVED' else 'hold'


async def _refuse_unless_approved(
    db: AsyncSession, org_id: UUID, document: DocumentToPostDTO
) -> None:
    """Refuse to post a document that needs an approval it has not got.

    A document waiting for one never gets here — the warehouse refuses it
    while it is held. This is the document confirmed before the control
    reached it: the workflow switched on, or the threshold lowered, while it
    was in flight; and the one somebody asked an approval for by hand.
    """
    # Asked about the person who submitted it, not the one carrying it out: a
    # receipt the administrator confirmed without an approval does not start
    # needing one in the hands of somebody the workflow holds.
    if await document_needs_approval_async(
        db, org_id, document.id, requester_id=document.confirmed_by
    ):
        try:
            # Under the control, so a workflow that has gone away since it
            # was confirmed must not stand in for an approval.
            await approvals_api.check_and_block(
                db, org_id, _TARGET, document.id, require_workflow=True
            )
        except ApprovalRequiredError as exc:
            raise InterceptorError(str(exc), error_code='APPROVAL_REQUIRED') from exc
        return

    if await approvals_api.find_active_request(db, org_id, _TARGET, document.id):
        raise InterceptorError(
            get_error_message('document_active_approval_request', get_current_lang()),
            error_code='APPROVAL_REQUIRED',
        )


async def withdraw_request_async(
    db: AsyncSession, org_id: UUID, document_id: UUID, user_id: UUID | None
) -> None:
    """A document was cancelled or deleted: withdraw the request open on it.

    The queue would otherwise ask somebody to decide on a document that is
    gone. The person withdrawing the document is the one who withdrew the
    request; with nobody named, its requester is.
    """
    active = await approvals_api.find_active_request(db, org_id, _TARGET, document_id)
    if active is None:
        return
    try:
        await approvals_api.cancel_request(
            db, org_id, active.id, user_id or active.created_by, cascade=True
        )
    except ApprovalError as exc:
        # Decided a moment ago in another tab: the document goes all the
        # same — that is what the reader asked for.
        logger.warning(
            'Could not cascade-cancel active request %s for document %s: %s',
            active.id,
            document_id,
            exc,
        )


async def follow_document_decision(db: AsyncSession, decision: TargetDecision) -> None:
    """Move the document to where the decision on its request leaves it.

    Approved releases it, posting it too when it was submitted through the
    one-step action — a posting that is refused refuses the approval, rather
    than leave a granted approval in front of a document that moved nothing.
    Withdrawn takes the hold back. Rejected sends it to a draft — refused
    likewise when it cannot go back — and its requester is told. Every branch is a no-op on a document that is already
    there, and the decision stands alone for a document that no longer
    exists.
    """
    warehouse = warehouse_documents()
    org_id = decision.organization_id
    doc_id = decision.target_id
    # A request about a document that is gone has nothing left to move.
    if await warehouse.get_document_state_async(db, org_id, doc_id) is None:
        return
    if decision.outcome == 'APPROVED':
        try:
            await warehouse.release_document_async(
                db, org_id, doc_id, MODULE, user_id=decision.decided_by
            )
        except Exception as exc:
            raise TargetDecisionRefusedError(exc) from exc
    elif decision.outcome == 'CANCELLED':
        await warehouse.withdraw_hold_async(db, org_id, doc_id, MODULE)
    elif decision.outcome == 'REJECTED':
        # The rejection is what sends the document back to be corrected; one
        # that cannot go back (posted in the meantime) refuses the rejection
        # in the reader's words, rather than leave it decided over nothing.
        try:
            await warehouse.return_to_draft_async(db, org_id, doc_id, MODULE)
        except Exception as exc:
            raise TargetDecisionRefusedError(exc) from exc
        await approvals_api.notify_rejection_async(
            db,
            org_id=org_id,
            doc_id=doc_id,
            request_id=decision.request_id,
            requester_id=decision.requester_id,
            reason=decision.notes,
        )

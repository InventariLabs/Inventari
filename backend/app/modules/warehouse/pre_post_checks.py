"""Who may stop a document from posting, or hold it until they say so.

The warehouse module enforces its own rules — the period, the partner, the
stock, the order's ceiling. A rule only one customer has ("no lot is received
without its certificate") belongs to that customer's module, which registers a
check here under its own name, at its import time (like a To do provider). The
posting asks every check of a module enabled for the organization, inside its
own transaction, so a check that refuses leaves nothing behind.

A check can also *hold* a document: the confirmation goes through, and the
document waits in PENDING_APPROVAL, naming the module in ``held_by``, until
that module releases it, withdraws the hold or sends the document back to a
draft (``warehouse_api``). The approvals module gates documents this way; the
state is the document's own, so any other module can hold one the same way.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import (
    AuditAction,
    AuditTargetType,
    DocumentLineToPostDTO,
    DocumentToPostDTO,
)
from app.core.public_api import core_api
from app.i18n.service import get_current_lang, get_error_message

from .models import DocumentStatus

if TYPE_CHECKING:
    from .models import Document

#: ``None`` lets the posting go on; ``'hold'`` parks the document for the
#: module that answered it (asked at confirmation; see ``run_pre_post_checks_async``).
PrePostVerdict = Literal['hold'] | None

#: ``(db, org_id, document) -> verdict``; raises ``InterceptorError`` to refuse.
PrePostCheck = Callable[
    [AsyncSession, UUID, DocumentToPostDTO], Awaitable[PrePostVerdict]
]

#: ``(db, org_id, document_id, user_id) -> None``: the document was cancelled
#: or deleted, by ``user_id`` when a person did it.
WithdrawalListener = Callable[[AsyncSession, UUID, UUID, UUID | None], Awaitable[None]]

_CHECKS: dict[str, PrePostCheck] = {}
_WITHDRAWAL_LISTENERS: dict[str, WithdrawalListener] = {}


class DocumentHeldError(ValueError):
    """The document waits for a module that has not released it yet.

    Raised by every door that would act on it — completion, a scanning
    session — in the reader's language. The routers answer it with the
    ``APPROVAL_REQUIRED`` conflict the screens already read.
    """

    def __init__(self) -> None:
        super().__init__(
            get_error_message('document_post_waiting_for_approval', get_current_lang())
        )


def register_pre_post_check(
    module: str,
    check: PrePostCheck,
    on_withdrawn: WithdrawalListener | None = None,
) -> None:
    """Claim a say over postings for one module.

    Registering twice for the same module replaces the earlier check (and
    listener), which keeps module reloads (and tests) from accumulating stale
    entries.
    """
    _CHECKS[module] = check
    if on_withdrawn is None:
        _WITHDRAWAL_LISTENERS.pop(module, None)
    else:
        _WITHDRAWAL_LISTENERS[module] = on_withdrawn


def _document_to_post(
    doc: Document,
    stage: Literal['confirm', 'post'],
    confirmed_by: UUID | None,
    may_exceed_over_receipt: bool,
) -> DocumentToPostDTO:
    return DocumentToPostDTO(
        stage=stage,
        id=doc.id,
        type=doc.type,
        number=doc.number,
        partner_id=doc.partner_id,
        source_location_id=doc.source_location_id,
        target_location_id=doc.target_location_id,
        scheduled_date=doc.scheduled_date,
        external_reference=doc.external_reference,
        meta_data=doc.meta_data or {},
        confirmed_by=confirmed_by,
        may_exceed_over_receipt=may_exceed_over_receipt,
        lines=[
            DocumentLineToPostDTO(
                id=line.id,
                line_number=line.line_number,
                item_id=line.item_id,
                product_template_id=line.product_template_id,
                name=line.name,
                expected_quantity=line.expected_quantity,
                done_quantity=line.done_quantity,
                uom_id=line.uom_id,
                batch_number=line.batch_number,
                serial_number=line.serial_number,
                expiry_date=line.expiry_date,
                source_location_id=line.source_location_id,
                target_location_id=line.target_location_id,
                source_po_line_id=line.source_po_line_id,
                meta_data=line.meta_data or {},
            )
            for line in doc.lines
        ],
    )


async def run_pre_post_checks_async(
    db: AsyncSession,
    org_id: UUID,
    doc: Document,
    stage: Literal['confirm', 'post'],
    *,
    confirmed_by: UUID | None,
    may_exceed_over_receipt: bool = False,
) -> str | None:
    """Ask the check of every module enabled for the organization.

    Returns the module that holds the document, when one does: the first to
    answer ``'hold'``. Every check is still asked, so a refusal behind a hold
    refuses the confirmation. A hold is honoured at confirmation only — at
    posting the document is already numbered and reserved, and a check that
    cannot let it through refuses it instead; a hold answered there is taken
    as that refusal.

    A refusal propagates: the caller's transaction is the posting's, so the
    whole posting goes with it. So does any other error — a check that cannot
    answer has not said yes, and the posting does not go ahead without it.
    """
    holder: str | None = None
    for module, check in dict(_CHECKS).items():
        if await core_api.organizations.is_module_enabled_async(db, org_id, module):
            verdict = await check(
                db,
                org_id,
                _document_to_post(doc, stage, confirmed_by, may_exceed_over_receipt),
            )
            if verdict == 'hold' and holder is None:
                holder = module
    if holder is not None and stage == 'post':
        raise DocumentHeldError()
    return holder


async def hold_stands_async(db: AsyncSession, org_id: UUID, doc: Document) -> bool:
    """Whether the document waits for a module that is there to release it.

    A hold of a module switched off for the organization stands down: nobody
    could decide on the document or withdraw what it waits for, and a
    switched-off module is one the organization has chosen to go without.
    """
    if doc.status != DocumentStatus.PENDING_APPROVAL.value:
        return False
    if doc.held_by is None:
        return True
    return await core_api.organizations.is_module_enabled_async(db, org_id, doc.held_by)


async def works_as_confirmed_async(
    db: AsyncSession, org_id: UUID, doc: Document
) -> bool:
    """Whether work may start on *doc* as on a confirmed document.

    A confirmed one, and one parked for a module switched off since: that
    hold has stood down (``hold_stands_async``), and the document is worked
    as the confirmed document it was.
    """
    if doc.status == DocumentStatus.CONFIRMED.value:
        return True
    return doc.status == DocumentStatus.PENDING_APPROVAL.value and not (
        await hold_stands_async(db, org_id, doc)
    )


async def lift_a_stood_down_hold_async(
    db: AsyncSession, org_id: UUID, doc: Document, user_id: UUID | None
) -> bool:
    """Take a stood-down hold off *doc* as work starts on it; whether it did.

    A module switched off stands down whole: nobody can decide on a document
    parked for it, and the document is worked as the confirmed one it was.
    The door that starts that work — a scanning session, the one-step press,
    a completion — lifts the hold here, so everything downstream reads a
    CONFIRMED document, and withdraws what the document waited on, so a
    module switched back on does not ask about work already under way. A
    document nobody touches keeps waiting where it is: switching the module
    back on finds it in the queue.
    """
    if doc.status != DocumentStatus.PENDING_APPROVAL.value or await hold_stands_async(
        db, org_id, doc
    ):
        return False
    doc.status = DocumentStatus.CONFIRMED.value
    doc.held_by = None
    await core_api.audit_log.log_action_async(
        db,
        organization_id=org_id,
        user_id=user_id,
        action=AuditAction.UPDATE,
        target_type=AuditTargetType.DOCUMENT,
        target_id=doc.id,
        snapshot={
            'number': doc.number,
            'type': doc.type,
            'old_status': DocumentStatus.PENDING_APPROVAL.value,
            'new_status': DocumentStatus.CONFIRMED.value,
        },
    )
    await notify_withdrawn_async(db, org_id, doc.id, user_id)
    await db.flush()
    return True


async def refuse_while_held_async(
    db: AsyncSession, org_id: UUID, doc: Document
) -> None:
    """Refuse to act on a document that waits for a module."""
    if await hold_stands_async(db, org_id, doc):
        raise DocumentHeldError()


async def notify_withdrawn_async(
    db: AsyncSession, org_id: UUID, doc_id: UUID, user_id: UUID | None
) -> None:
    """Tell every module that may hold documents that this one is gone.

    The document is cancelled or deleted in the same transaction — or goes
    on without the hold of a module switched off since — so what a module
    keeps about it — the approvals module's open request — goes with it. A listener that raises takes the withdrawal down with it; one whose
    follow-up is best-effort catches its own refusal, as the approvals module
    does for a request somebody decided a moment earlier.
    """
    for listener in dict(_WITHDRAWAL_LISTENERS).values():
        await listener(db, org_id, doc_id, user_id)

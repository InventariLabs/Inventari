from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.contracts import AuditAction, AuditTargetType
from app.core.db_utils import acquire_advisory_lock
from app.core.events import emit_transactional_safe
from app.core.exceptions import ServiceRejectionError
from app.core.public_api import core_api
from app.i18n.service import (
    get_current_lang,
    get_error_message,
)

from . import document_types as dt
from ._document_rework_service import rework_to_draft_after_reject  # noqa: F401
from ._document_workflow_crud import (
    _apply_execution_quantities,
    _build_partner_snapshot,
    _check_document_period_open,
    _get_doc_for_update,
    _release_quants_for_doc,
    _reserve_quants_for_doc,
    _unpin_the_lines,
    get_or_raise,
)
from ._document_workflow_helpers import (
    assert_receipt_lines_dated_async,
    assert_receipt_over_receipts_allowed_async,
    build_document_event_payload,
    keep_line_tracking,
)
from ._order_side import order_side_async
from ._wms_line_utils import session_holds_document
from ._wms_session_close import (
    destination_awaited,
    document_lines_resolved_async,
    pin_picked_lots_async,
)
from ._wms_session_release import (
    session_released_async,
    settle_released_session_async,
)
from .document_backorder_service import maybe_create_backorder
from .document_numbering_service import generate_number, is_temporary_number
from .document_profile_service import (
    get_or_create_profile,
    resolve_partner_tax_id_required,
)
from .document_stock_executor import execute_stock_operations
from .document_type_config_service import get_type_config
from .document_value_service import recompute_document_values
from .events import DocumentEvent
from .models import Document, DocumentLine, DocumentStatus, WmsPickLine, WmsPickSession
from .packing_service import assert_packed_within_done_async
from .pre_post_checks import (
    notify_withdrawn_async,
    refuse_while_held_async,
    run_pre_post_checks_async,
)
from .schemas import (
    DocumentComplete,
    DocumentCreate,
    DocumentLineExecution,
    DocumentTracking,
)
from .shipment_service import (
    attach_shipments_async,
    emit_shipped_async,
    record_shipment_async,
)


class WmsSessionActiveError(ValueError):
    """Raised when a document transition is blocked because a WMS session
    is still open. Carries the session count and the direction's own word,
    so the sentence the reader gets names the kind of session standing in
    the way — receiving used to be answered with picking's sentence — and
    no session id, which meant nothing to a worker reading the document
    page."""


def _session_kind(session: WmsPickSession) -> str:
    """The direction a session runs in.

    Receiving marks its rows ``direction: inbound`` and picking marks none;
    this is the same read ``list_sessions_for_document_async`` makes of
    them, so the list and the refusal cannot name a session differently.
    """
    meta = session.meta_data or {}
    return 'receiving' if meta.get('direction') == 'inbound' else 'picking'


async def _destination_awaited(db: AsyncSession, session: WmsPickSession) -> bool:
    lines = (
        await db.scalars(
            select(WmsPickLine).where(WmsPickLine.session_id == session.id)
        )
    ).all()
    return destination_awaited(session, lines) is not None


async def _check_no_active_wms_sessions(
    db: AsyncSession,
    org_id: UUID,
    doc_id: UUID,
    user_id: UUID,
) -> None:
    """Block document transitions while WMS sessions are active.

    Raises ``WmsSessionActiveError`` so the router can return a 409
    with a structured payload (code=WMS_SESSION_ACTIVE, message naming
    the kind of session in the way).

    A session over several dispatches lets each go once all of its lines
    are resolved, so the one picked first completes while the session goes
    on for the rest — the same moment a session over that document alone
    would have closed.

    A session nobody is working in — its sheet closed, or idle past the
    organization's time — blocks nothing: it lets the document go with what
    was scanned (see ``_wms_session_release``).
    """
    holding = (
        await db.scalars(
            select(WmsPickSession).where(
                session_holds_document(doc_id),
                WmsPickSession.organization_id == org_id,
                WmsPickSession.status.in_(['active', 'paused']),
            )
        )
    ).all()
    active = []
    for session in holding:
        if await session_released_async(db, session):
            await settle_released_session_async(db, session, doc_id, user_id)
        elif not await document_lines_resolved_async(db, session.id, doc_id):
            active.append(session)
        elif await _destination_awaited(db, session):
            # A transfer whose last line is answered still waits for the
            # destination label; completing now would book the goods onto a
            # shelf nobody confirmed.
            active.append(session)
        elif _session_kind(session) == 'picking':
            # Letting go of a document while the session goes on for the
            # others is a closing for this document: the batches its lines
            # were picked from are written to them, so completion books
            # those and not the strategy's.
            document_lines = await db.scalars(
                select(WmsPickLine)
                .join(DocumentLine, DocumentLine.id == WmsPickLine.document_line_id)
                .where(
                    WmsPickLine.session_id == session.id,
                    DocumentLine.document_id == doc_id,
                )
            )
            await pin_picked_lots_async(db, document_lines.all())
    if not active:
        return
    kinds = {_session_kind(session) for session in active}
    # A document takes one direction of sessions only — ``start`` decides
    # it from the document's type — and the start guard keeps one open at a
    # time, so the kinds agree. A set that does not is read as picking, the
    # wording every refusal carried before receiving shared the guard.
    key = (
        'document_wms_receiving_active'
        if kinds == {'receiving'}
        else 'document_wms_picking_active'
    )
    raise WmsSessionActiveError(
        get_error_message(key, get_current_lang(), count=len(active))
    )


async def _refuse_unanswered_skips_async(
    db: AsyncSession, doc: Document, execution_data: DocumentComplete | None
) -> None:
    """Refuse a completion that would book a skipped session line in full.

    A skip writes no discrepancy code on the document line, so a line the
    summary never answered looks like one nobody touched, and
    ``complete_as_planned`` books such a line as delivered in full. The
    refusal reads the session instead: a line whose session skipped it and
    that still carries no reason is waiting for its answer, however the
    completion is worded. A body that answers the line itself is that answer.
    Sessions from before the document's last confirmation and cancelled ones
    say nothing about its lines now.
    """
    answered = {
        execution.line_id
        for execution in (execution_data.lines if execution_data else [])
    }
    query = (
        select(DocumentLine.id, DocumentLine.line_number)
        .join(WmsPickLine, WmsPickLine.document_line_id == DocumentLine.id)
        .join(WmsPickSession, WmsPickSession.id == WmsPickLine.session_id)
        .where(
            DocumentLine.document_id == doc.id,
            DocumentLine.discrepancy_code.is_(None),
            WmsPickLine.status == 'skipped',
            WmsPickSession.status != 'cancelled',
        )
        .order_by(DocumentLine.line_number)
    )
    if doc.confirmed_at is not None:
        query = query.where(WmsPickSession.started_at >= doc.confirmed_at)
    waiting = sorted(
        {
            number
            for line_id, number in (await db.execute(query)).all()
            if line_id not in answered
        }
    )
    if waiting:
        raise ServiceRejectionError(
            'document_complete_skipped_lines',
            lines=', '.join(str(number) for number in waiting),
        )


async def _emit_document_confirmed(
    db: AsyncSession, org_id: UUID, doc: Document
) -> None:
    """Publish ``document.confirmed`` on the same transaction as the status flip.

    Mirrors the COMPLETED/CANCELLED outbox pattern: a crash
    between commit and publish cannot lose DOCUMENT_CONFIRMED.
    """
    await emit_transactional_safe(
        db,
        DocumentEvent.CONFIRMED,
        await build_document_event_payload(db, doc, org_id),
    )


def _require_stock_rows_on_lines(doc: Document) -> None:
    """Refuse to commit a document whose lines have nothing to take.

    A document that takes goods off a shelf moves stock by record, and its
    executors refuse a line naming only a product — except scrap, which used
    to skip the whole stock block and let the document close as COMPLETED,
    writing off goods that never left the shelf.

    Confirmation is where this belongs: a draft may still be half-written, but
    confirming reserves the stock and promises the movement. Refusing here
    means the promise is never made, rather than broken two steps later.
    """
    if not dt.requires_stock_row(doc.type):
        return
    missing = [
        line.line_number
        for line in doc.lines
        if line.item_id is None and line.expected_quantity > 0
    ]
    if missing:
        # Counted nouns agree with the count: one missing line reads
        # "line 1 names only a product", several read "lines 1, 4 name".
        raise ServiceRejectionError(
            'document_lines_need_stock_row',
            plural=len(missing),
            type=doc.type,
            lines=', '.join(str(n) for n in missing),
        )


def _require_positive_quantities(doc: Document) -> None:
    """Refuse to commit a document carrying a line of zero or less.

    Every door that writes a line asks this already — ``DocumentLineCreate``
    declares ``expected_quantity`` as ``Field(gt=0)`` and the quantity field
    on screen carries a ``min`` from its unit. Line import wrote straight to
    the table and so walked past both, and a single negative line does not
    lie idle: "Plan", "received X of Y" and the picking screens are plain
    sums, so a receipt of 5 + 2 + (-5) declared a plan of 2 and reported a
    complete receipt after two of seven units.

    Which types may is the type's own business (``allows_negative_quantity``):
    a correction's lines are deltas and a delta of -2 is the document.

    Confirming is where this belongs for a line that is already in the table:
    a draft may still be half-written, but confirming promises the movement.
    """
    if dt.allows_negative_quantity(doc.type):
        return
    wrong = [
        line.line_number for line in doc.lines if (line.expected_quantity or 0) <= 0
    ]
    if wrong:
        raise ServiceRejectionError(
            'document_lines_quantity_not_positive',
            lines=', '.join(str(n) for n in wrong),
        )


async def _require_products_on_receipt_lines(
    db: AsyncSession, doc: Document, *, posting: bool
) -> None:
    """Refuse to take goods into stock under words no product stands behind.

    A receipt line typed by hand used to post as it was written — "Test
    laptop Dell" at 3000 landed on a shelf as stock of nothing on the
    product list. A line now names a record, a product, or a code the list
    knows; the code is settled onto the line as the product it stands for.
    The form offers to make a typed name a product, so the refusal names the
    lines the reader has to fix.

    Asked at confirmation, where the receipt commits, and again at posting
    (*posting*), for a receipt confirmed before the rule: its lines can no
    longer change, and posting is what puts the words on the shelf. A line
    that brings nothing is not posted and is not asked.
    """
    if not dt.is_receipt(doc.type) or doc.stock_already_applied:
        return
    typed: list[DocumentLine] = []
    for line in doc.lines:
        brings = line.done_quantity if posting else line.expected_quantity
        if line.item_id or line.product_template_id or (brings or 0) <= 0:
            continue
        known = (
            await core_api.product_templates.lookup_by_barcode_async(
                db, doc.organization_id, line.barcode
            )
            if line.barcode
            else None
        )
        if known is not None:
            line.product_template_id = known.id
            continue
        typed.append(line)
    if typed:
        raise ServiceRejectionError(
            'document_receipt_lines_need_product',
            plural=len(typed),
            lines=', '.join(f'{line.line_number} ({line.name})' for line in typed),
        )


async def confirm_document(
    db: AsyncSession,
    org_id: UUID,
    doc_id: UUID,
    user_id: UUID,
    *,
    may_exceed_over_receipt: bool = False,
    complete_on_approval: bool = False,
) -> Document:
    """Confirm a draft: give it a number, reserve its stock, gate its approval.

    ``complete_on_approval`` records that the caller is the one-step action:
    when an approval stands between the confirmation and the posting, the
    approval completes the document rather than handing it back to the reader
    (see ``confirm_after_approval``).

    Nothing is committed here: the caller owns the transaction, so the
    one-step action writes nothing until both halves have succeeded.
    """

    # Under the row's lock, like completion takes it: the status is read
    # only after the wait, so a confirm racing a cancel or a completion
    # sees what the other left behind.
    doc = await _get_doc_for_update(db, org_id, doc_id)
    await _check_document_period_open(db, org_id, doc)
    if doc.status == DocumentStatus.CONFIRMED.value:
        return doc
    if doc.status != DocumentStatus.DRAFT.value:
        raise ServiceRejectionError(
            'document_confirm_invalid_status', status=doc.status
        )

    profile = await get_or_create_profile(db, org_id)
    if doc.partner_id is not None and await resolve_partner_tax_id_required(
        db, org_id, profile
    ):
        partner_dto = await core_api.partners.get_async(db, org_id, doc.partner_id)
        # A private person has no tax id to give; the requirement is the
        # law asking it of businesses.
        if (
            partner_dto is not None
            and not partner_dto.tax_id
            and not partner_dto.is_consumer
        ):
            raise ServiceRejectionError(
                'document_partner_tax_id_required', name=partner_dto.name
            )

    _require_positive_quantities(doc)
    _require_stock_rows_on_lines(doc)
    await _require_products_on_receipt_lines(db, doc, posting=False)
    # The number is given out here, where the draft becomes a document of
    # the register. A draft written and thrown away costs nothing (it never
    # held a number), and the number drawn now carries the period the
    # document is dated to *today* — the date a draft is free to move
    # while it is still a plan. A document that already carries a number —
    # one written before numbering moved to confirmation, or rejected back
    # to a draft after it was given out — keeps the number it has.
    if is_temporary_number(doc.number):
        type_config = await get_type_config(db, org_id, dt.normalize(doc.type))
        doc.number = await generate_number(
            db,
            org_id,
            doc.type,
            type_config.sequence_format if type_config else None,
            doc.scheduled_date,
        )

    # Last of the rules, and before the stock is reserved. The checks see
    # the number the document will carry — the approvals module raises its
    # request under it — and a refusal takes the number back with the rest of
    # the transaction. A module may hold the document instead — the approvals
    # module does, when the profile or its workflow asks for a sign-off — and
    # the confirmation then parks it.
    holder = await run_pre_post_checks_async(
        db,
        org_id,
        doc,
        'confirm',
        confirmed_by=user_id,
        may_exceed_over_receipt=may_exceed_over_receipt,
    )

    doc.status = DocumentStatus.CONFIRMED.value
    doc.complete_on_approval = complete_on_approval
    doc.confirmed_by = user_id
    doc.confirmed_at = datetime.now(UTC)

    if holder is not None:
        # The stamp stays with the hand that confirmed the document and sent
        # it to wait. The release is a moment of its own — the approval's
        # decision names the approver.
        doc.status = DocumentStatus.PENDING_APPROVAL.value
        doc.held_by = holder
    else:
        # document.confirmed rides the same transaction as the status flip;
        # a held document announces it when it is released.
        await _emit_document_confirmed(db, org_id, doc)

    # Nothing to hold when the stock is already gone: reserving it again would
    # refuse a document whose goods have been used up.
    if dt.needs_quant_reservation(doc.type) and not doc.stock_already_applied:
        await _reserve_quants_for_doc(db, doc)

    if doc.partner_id is not None:
        partner_dto = await core_api.partners.get_async(db, org_id, doc.partner_id)
        if partner_dto is not None:
            doc.partner_snapshot = _build_partner_snapshot(partner_dto)

    await core_api.audit_log.log_action_async(
        db,
        organization_id=org_id,
        user_id=user_id,
        action=AuditAction.UPDATE,
        target_type=AuditTargetType.DOCUMENT,
        target_id=doc.id,
        snapshot={
            'number': doc.number,
            'new_status': doc.status,
            'requires_approval': holder is not None,
            'approval_workflow_configured': holder is not None,
        },
    )
    await db.flush()
    await db.refresh(doc, attribute_names=['lines'])
    return doc


async def _post_the_stock_of(
    db: AsyncSession,
    org_id: UUID,
    doc_id: UUID,
    user_id: UUID,
    execution_data: DocumentComplete | None,
    *,
    may_exceed_over_receipt: bool,
) -> tuple[Document, Document | None]:
    """Everything of completing a document up to, not including, the commit."""
    doc = await _get_doc_for_update(db, org_id, doc_id)
    await _check_document_period_open(db, org_id, doc)
    if doc.status not in (
        DocumentStatus.CONFIRMED.value,
        DocumentStatus.PENDING_APPROVAL.value,
    ):
        raise ServiceRejectionError(
            'document_complete_invalid_status', status=doc.status
        )

    await _check_no_active_wms_sessions(db, org_id, doc_id, user_id)

    # A document waiting for a module is not posted until that module lets it
    # go; the scanning sessions ask the same. Whatever else a module wants
    # of the posting it says in its pre-post check below.
    await refuse_while_held_async(db, org_id, doc)

    # Written ahead of the stock, in the same transaction: a posting that
    # fails below takes the hand-over with it, so no shipment ever records
    # goods that did not leave.
    shipment = (
        await record_shipment_async(db, doc, user_id, execution_data.shipment)
        if execution_data is not None and execution_data.shipment is not None
        else None
    )

    await _release_quants_for_doc(db, doc)
    await _refuse_unanswered_skips_async(db, doc, execution_data)
    _apply_execution_quantities(doc, execution_data)
    await assert_packed_within_done_async(db, doc)
    await _require_products_on_receipt_lines(db, doc, posting=True)
    # The last door onto the shelf asks the receiving screens' question: a
    # product taken by earliest expiry may not arrive undated, where it
    # would sort behind every dated record of it.
    await assert_receipt_lines_dated_async(db, org_id, doc)
    # Asked again on the way out: confirmation weighed what the document
    # expected to bring, and completion is free to say a different number.
    # A line with no order link is weighed against its own expectation
    # through the over-receipt tolerance; an order-linked one by the orders
    # module's pre-post check, asked just below.
    await assert_receipt_over_receipts_allowed_async(
        db, org_id, doc, may_exceed=may_exceed_over_receipt
    )
    await run_pre_post_checks_async(
        db,
        org_id,
        doc,
        'post',
        confirmed_by=doc.confirmed_by,
        may_exceed_over_receipt=may_exceed_over_receipt,
    )

    await execute_stock_operations(
        db,
        doc,
        user_id,
        unit_confirmed_over_template=(
            execution_data.unit_confirmed_over_template
            if execution_data is not None
            else False
        ),
    )

    # What the document is worth is now what it delivered. Until this point
    # the value was the plan's, recomputed only when a draft was written or a
    # correction raised — so a partial delivery kept the whole order's value,
    # and the shortfall was counted in the register and read by the approval
    # threshold as goods that never came.
    recompute_document_values(doc, executed=True)

    doc.status = DocumentStatus.COMPLETED.value
    doc.completed_by = user_id
    doc.completed_at = datetime.now(UTC)

    backorder = await maybe_create_backorder(db, doc, org_id, user_id)

    # The order counts the goods in this transaction rather than when the
    # completion event is delivered seconds later: the order screen opened
    # straight after posting still said nothing had arrived.
    po_line_ids = [
        line.source_po_line_id for line in doc.lines if line.source_po_line_id
    ]
    orders = await order_side_async(db, org_id) if po_line_ids else None
    if orders is not None:
        # An order line typed by hand arrives as the product its receiver
        # named on this receipt, and keeps it for the rest of the line.
        await orders.adopt_line_products_async(
            db,
            org_id,
            {
                line.source_po_line_id: line.product_template_id
                for line in doc.lines
                if line.source_po_line_id and line.product_template_id
            },
        )
        await db.flush()
        await orders.count_received_async(db, org_id, po_line_ids)

    # Confirming was logged; executing was not — so the log held documents
    # that were created and changed and never appeared to have moved
    # anything, while the goods had left the shelf. This is the step the
    # stock actually turns on, which makes it the one entry that cannot be
    # inferred from the others.
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
            'old_status': DocumentStatus.CONFIRMED.value,
            'new_status': doc.status,
            'lines': len(doc.lines),
        },
        reason='document_completed',
        meta_data=({'generated_backorder': backorder.number} if backorder else None),
    )

    # The event rides the SAME transaction as the completion — a crash
    # between commit and publish can no longer lose DOCUMENT_COMPLETED.
    await emit_transactional_safe(
        db,
        DocumentEvent.COMPLETED,
        await build_document_event_payload(db, doc, org_id),
    )
    if shipment is not None:
        await emit_shipped_async(db, org_id, doc, shipment)
        # Before the commit: a session that expires on commit would load the
        # document's columns again outside the greenlet.
        await attach_shipments_async(db, org_id, [doc])

    return doc, backorder


async def complete_document(
    db: AsyncSession,
    org_id: UUID,
    doc_id: UUID,
    user_id: UUID,
    execution_data: DocumentComplete | None = None,
    *,
    may_exceed_over_receipt: bool = False,
) -> Any:
    """Post a confirmed document's stock.

    Like ``confirm_document`` it leaves the commit to the caller: the one-step
    action and an approval that releases a document waiting on it run this
    half in their own transaction and commit once, together with everything
    else.
    """

    # Everything up to the commit reads the same organization, units and shelves
    # for each line, and appends a movement, a layer and two journal rows per
    # line: the reads are answered once and the appended rows written as sets.
    async with core_api.stock.posting_scope_async(db):
        doc, backorder = await _post_the_stock_of(
            db,
            org_id,
            doc_id,
            user_id,
            execution_data,
            may_exceed_over_receipt=may_exceed_over_receipt,
        )

    await db.flush()
    await db.refresh(doc, attribute_names=['lines'])

    if backorder is not None:
        # expose the generated backorder on the complete response.
        doc.generated_backorder_id = backorder.id  # type: ignore[attr-defined]
        doc.generated_backorder_number = backorder.number  # type: ignore[attr-defined]

    return doc


#: Statuses a document can still be cancelled from.
#:
#: The screen offers the action from its own copy of this list — see
#: ``frontend/src/modules/warehouse/components/DocumentActionButtons.tsx``.
#: The two used to disagree: the API cancelled a CONFIRMED document for
#: anyone holding ``warehouse:manage``, and the screen offered it on a draft
#: only, so a document stuck at execution held its reservation over a whole
#: shelf with no button anywhere to let it go.
CANCELLABLE_STATUSES = frozenset(
    {
        DocumentStatus.DRAFT.value,
        DocumentStatus.CONFIRMED.value,
        DocumentStatus.PENDING_APPROVAL.value,
    }
)

#: Of those, the ones holding a reservation that cancelling gives back.
RESERVING_STATUSES = frozenset(
    {
        DocumentStatus.CONFIRMED.value,
        DocumentStatus.PENDING_APPROVAL.value,
    }
)


async def cancel_document(
    db: AsyncSession,
    org_id: UUID,
    doc_id: UUID,
    user_id: UUID,
) -> Any:
    # Under the row's lock, like confirm and completion: cancelling
    # decides on the status it read after the wait, so a cancel cannot
    # close a document another door has just moved, and the anchors it
    # takes afterwards are waited for in the same order everywhere.
    doc = await _get_doc_for_update(db, org_id, doc_id)
    await _check_document_period_open(db, org_id, doc)

    await _check_no_active_wms_sessions(db, org_id, doc_id, user_id)

    if doc.status not in CANCELLABLE_STATUSES:
        raise ServiceRejectionError('document_cancel_invalid_status')

    previous_status = doc.status
    released = False
    if previous_status in RESERVING_STATUSES:
        # Only the types that hold a reservation give one back: a receipt
        # parked at CONFIRMED holds nothing, and saying it "went back to
        # the shelf" promises a return that never happens.
        released = dt.needs_quant_reservation(doc.type)
        if released:
            await _release_quants_for_doc(db, doc)
            _unpin_the_lines(doc)

    # A module that holds documents drops what it keeps about this one —
    # the approvals module withdraws the open request, so its queue does not
    # ask anybody to decide on a document that is gone.
    await notify_withdrawn_async(db, org_id, doc_id, user_id)

    doc.status = DocumentStatus.CANCELLED.value
    doc.cancelled_by = user_id
    doc.cancelled_at = datetime.now(UTC)

    # Confirming and executing were logged; cancelling was not — so a
    # withdrawal left the organization log silent and, with no
    # ``cancelled_by``/``cancelled_at`` on the row, nobody could later say
    # who took the document out of the books and when. The entry carries
    # both (its own ``user_id`` and ``created_at``), like the others.
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
            'old_status': previous_status,
            'new_status': doc.status,
            'released_reservation': released,
            'lines': len(doc.lines),
        },
        reason='document_cancelled',
    )

    # Outbox row rides the cancel transaction (see complete_document).
    await emit_transactional_safe(
        db,
        DocumentEvent.CANCELLED,
        await build_document_event_payload(db, doc, org_id),
    )

    await db.flush()
    # ``canceller`` with the row: the response says who cancelled, and the
    # relationship is not otherwise loaded on this session's copy.
    await db.refresh(doc, attribute_names=['lines', 'canceller'])

    return doc


def _held_by(doc: Document, module: str) -> bool:
    """Whether this module is the one the document waits for.

    A document parked before ``held_by`` existed names nobody and is taken
    as anybody's to release; the migration that added the column named the
    approvals module on every such row.
    """
    return doc.status == DocumentStatus.PENDING_APPROVAL.value and (
        doc.held_by is None or doc.held_by == module
    )


async def hold_document(
    db: AsyncSession, org_id: UUID, doc_id: UUID, module: str
) -> bool:
    """Park a confirmed document for ``module``, outside a confirmation.

    For a hold somebody asks for by hand — a sign-off requested on a
    document no rule demanded it for. Returns whether the document now
    waits for the module; one in any other state, or already waiting for
    somebody else, is left as it is.
    """
    doc = await _get_doc_for_update(db, org_id, doc_id)
    if _held_by(doc, module):
        return True
    if doc.status != DocumentStatus.CONFIRMED.value:
        return False
    # The confirmation stands: asking for a sign-off on top of a confirmed
    # document does not un-confirm it, and the person who confirmed it keeps
    # the place the card names them at.
    doc.status = DocumentStatus.PENDING_APPROVAL.value
    doc.held_by = module
    await db.flush()
    return True


async def release_after_approval_withdrawn(
    db: AsyncSession,
    org_id: UUID,
    doc_id: UUID,
    module: str,
) -> Any:
    """Take a document back out of PENDING_APPROVAL when nothing is pending.

    Withdrawing the request removes the question; the document that was
    parked waiting for its answer goes back to where it was parked from.
    Left as it was, it kept its place in the "Pending Approval" filter with
    no request behind it and no one able to decide anything.

    Not a confirmation: the document was already CONFIRMED when the request
    was raised, so nothing new is announced.
    """
    doc = await get_or_raise(db, org_id, doc_id)
    if not _held_by(doc, module):
        return doc

    doc.status = DocumentStatus.CONFIRMED.value
    doc.held_by = None
    # The confirmation the document carried before the request stands:
    # withdrawing takes back the question, not the act that asked it.
    await db.flush()
    await db.refresh(doc, attribute_names=['lines'])
    return doc


async def confirm_after_approval(
    db: AsyncSession,
    org_id: UUID,
    doc_id: UUID,
    module: str,
    user_id: UUID | None = None,
) -> Any:
    """Transition a document from PENDING_APPROVAL to CONFIRMED.

    Called when the module the document waits for lets it go — for the
    approvals module, when its request is fully approved. A document
    submitted through the one-step action carries ``complete_on_approval``:
    the release was the only thing left between the confirmation and the
    posting, so the release posts it instead of handing the reader a second
    button.
    """
    doc = await get_or_raise(db, org_id, doc_id)
    if not _held_by(doc, module):
        return doc

    doc.status = DocumentStatus.CONFIRMED.value
    doc.held_by = None
    # The approval does not overwrite the confirmation: the stamp names the
    # hand that confirmed the document, and the decision names the one that
    # approved it. Rows written before the stamp survived the approval kept
    # only the approver, so an unstamped row is stamped here as it was then.
    if doc.confirmed_by is None and user_id is not None:
        doc.confirmed_at = datetime.now(UTC)
        doc.confirmed_by = user_id
    # The approval's request and decision are journaled by the approvals
    # module; this status change is the document's own, so the log carries
    # it here — the rung the ladder climbed, with who stood on it.
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
    await _emit_document_confirmed(db, org_id, doc)
    if doc.complete_on_approval:
        # Runs in the releasing transaction: the numbered document, the stock
        # it moves and the decision that allowed both land together or not at
        # all. A posting that is refused -- the month closed, the stock gone
        # while it waited -- raises, and the releasing module refuses its
        # decision with it rather than leave a granted approval in front of
        # a document that moved nothing.
        return await complete_document(
            db,
            org_id,
            doc_id,
            user_id or doc.confirmed_by or doc.created_by,
            DocumentComplete(complete_as_planned=True),
        )
    await db.refresh(doc, attribute_names=['lines'])
    return doc


def _apply_line_tracking(doc: Document, tracking: DocumentTracking) -> None:
    """Put a one-step posting's lot and expiry on the lines it names."""
    lines = {line.id: line for line in doc.lines}
    for entry in tracking.lines:
        line = lines.get(entry.line_id)
        if line is None:
            raise ServiceRejectionError('document_execution_line_foreign')
        keep_line_tracking(line, entry.batch_number, entry.expiry_date)


#: What a one-step press is told when the document it names has already left
#: the states a press can act on, by the state it is found in.
_PRESS_REFUSED_AFTER = {
    DocumentStatus.COMPLETED.value: 'document_post_already_posted',
    DocumentStatus.CANCELLED.value: 'document_post_cancelled',
    DocumentStatus.PENDING_APPROVAL.value: 'document_post_waiting_for_approval',
}


async def post_document_now(
    db: AsyncSession,
    org_id: UUID,
    doc_id: UUID,
    user_id: UUID,
    *,
    may_exceed_over_receipt: bool = False,
    tracking: DocumentTracking | None = None,
    answers: list[DocumentLineExecution] | None = None,
) -> Document:
    """Confirm and complete a draft in one transaction, as one action.

    This is the one-step door behind "Przyjmij na stan / Wydaj / Przenieś".
    It runs the same ``confirm_document`` and ``complete_document`` every other
    door runs — the period, partner, stock-row, order-ceiling, reservation,
    lot and stock-posting rules all still apply — with two differences:

    * nothing commits between the halves, so a completion that fails leaves
      the draft exactly as it was, with no number drawn and no stock reserved;
    * the lines are completed as planned (``complete_as_planned``), since the
      action states the whole movement and has no per-line answers to give.

    *tracking* is the one answer such a posting can carry: the lot and expiry
    the execution screen's question collected, put on the lines exactly as a
    receiving scan puts them there. *answers* is the other: the lines of a
    receipt that say part of what arrived is held back, completed with the
    same per-line body a completion takes — every line they leave out is
    still booked as planned.

    When the profile puts an approval in front of the document, the same call
    stops at PENDING_APPROVAL and marks it to be completed by the approval.
    """
    # Under the row's lock, so a press that arrives while another is posting
    # the same document waits for it and then reads what it left behind: a
    # second press, a second tab or a retry is told the document has moved
    # on, in words, rather than "cannot confirm a document in COMPLETED
    # status".
    already = _PRESS_REFUSED_AFTER.get(
        (await _get_doc_for_update(db, org_id, doc_id)).status
    )
    if already is not None:
        raise ServiceRejectionError(already)
    doc = await confirm_document(
        db,
        org_id,
        doc_id,
        user_id,
        may_exceed_over_receipt=may_exceed_over_receipt,
        complete_on_approval=True,
    )
    if tracking is not None:
        _apply_line_tracking(doc, tracking)
    if doc.status == DocumentStatus.CONFIRMED.value:
        doc = await complete_document(
            db,
            org_id,
            doc_id,
            user_id,
            DocumentComplete(complete_as_planned=True, lines=answers or []),
            may_exceed_over_receipt=may_exceed_over_receipt,
        )
    else:
        # The approval completes this document with nobody in front of the
        # screen to ask, and an approver has no pack to read. Ask here, at
        # the press that has the reader, and let the answer stay on the
        # lines the approval posts.
        await assert_receipt_lines_dated_async(db, org_id, doc, as_planned=True)
        # Nor can the approval be asked which goods were held back: the
        # answers stay on the lines, which complete as planned from them.
        if answers:
            _apply_execution_quantities(
                doc, DocumentComplete(complete_as_planned=True, lines=answers)
            )

    await db.flush()
    await db.refresh(doc, attribute_names=['lines'])
    return doc


async def post_new_document(
    db: AsyncSession,
    org_id: UUID,
    data: DocumentCreate,
    user_id: UUID,
    *,
    currency: str | None = None,
    post_key: str | None = None,
    may_exceed_over_receipt: bool = False,
) -> Document:
    """Create a document from scratch and post it, in one transaction.

    The same door as ``post_document_now`` for a caller that has no draft to
    begin with — a one-screen receipt or dispatch. Creation, confirmation and
    completion share one transaction, so a refusal at any step writes no
    draft, no number and no stock.

    ``post_key`` identifies the press. A press sent twice — a double click, a
    retry after the answer was lost on the way back — finds the document the
    first one made and is answered with it, so the stock moves once. The
    lock makes the second wait for the first to commit instead of racing it.
    """
    from ._document_workflow_crud import create_document

    if post_key:
        await acquire_advisory_lock(db, f'document_post_key:{org_id}:{post_key}')
        made = (
            await db.execute(
                select(Document)
                .where(
                    Document.organization_id == org_id, Document.post_key == post_key
                )
                .options(selectinload(Document.lines))
            )
        ).scalar_one_or_none()
        if made is not None:
            return made

    doc = await create_document(db, org_id, data, user_id, currency=currency)
    if post_key:
        doc.post_key = post_key
    return await post_document_now(
        db,
        org_id,
        doc.id,
        user_id,
        may_exceed_over_receipt=may_exceed_over_receipt,
        answers=[
            DocumentLineExecution(
                line_id=line.id,
                done_quantity=line.expected_quantity,
                held_quantity=sent.held_quantity,
                discrepancy_code=sent.discrepancy_code,
                discrepancy_reason=sent.discrepancy_reason,
            )
            for line, sent in zip(doc.lines, data.lines, strict=True)
            if sent.held_quantity
        ],
    )

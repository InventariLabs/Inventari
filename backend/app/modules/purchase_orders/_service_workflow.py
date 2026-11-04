"""Workflow operations for Purchase Orders: confirm, cancel, receipt creation.

Split out from the original service for the 400-line quality gate; this
half has since grown past it again, and the gate has the file on its list
rather than in its rules.

Workflow operations write their events to the outbox in the caller's
transaction; the relay publishes them once it commits, so listeners only see
committed state.
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import AuditAction, AuditTargetType, ReceiptLineFromPODTO
from app.core.contracts.events import (
    PurchaseOrderCancelledPayload,
    PurchaseOrderConfirmedPayload,
    ReceiptCreatedFromPOPayload,
)
from app.core.exceptions import ServiceRejectionError
from app.core.logging import get_logger
from app.core.public_api import core_api
from app.i18n.service import (
    get_current_lang,
    get_error_message,
)
from app.modules.approvals.approvals_api import approvals_api
from app.modules.approvals.exceptions import ApprovalError
from app.modules.warehouse.warehouse_api import warehouse_api
from app.schemas.partner import SUPPLIER_ROLE_TYPES

from . import _notification_labels as _labels
from ._journal import journal_order_act
from ._service_crud import get_purchase_order

# Re-export: ``recalculate_po_quantities`` was moved to
# ``_service_po_completion`` to keep this file under the 400 LOC limit, but
# ``module.py`` imports it from here — keep the re-export so callers don't
# need to know about the move.
from ._service_po_completion import recalculate_po_quantities  # noqa: F401
from ._service_settings import get_po_settings
from .events import PurchaseOrderEvent
from .models import POSettings, PurchaseOrder, PurchaseOrderLine
from .schemas import PurchaseOrderApprovalRequirement

logger = get_logger(__name__)

# canonical supplier role set lives in Core (app/schemas/partner.py).
_SUPPLIER_PARTNER_TYPES = SUPPLIER_ROLE_TYPES

# Receipt statuses that block PO cancellation (active, not terminal). A receipt
# in any of these states has reserved PO-line capacity and must be resolved first.
_OPEN_RECEIPT_STATUSES = frozenset({'DRAFT', 'PENDING_APPROVAL', 'CONFIRMED'})


class POHasOpenReceiptsError(ValueError):
    """Raised when cancelling a PO that still has active (non-terminal) receipts.

    Distinct from a plain ``ValueError`` so the router can map it to HTTP 409
    (state conflict) instead of the default 400 validation error.
    """

    def __init__(self, message: str, receipt_numbers: list[str]) -> None:
        super().__init__(message)
        self.receipt_numbers = receipt_numbers


def _po_line_remaining(
    po_line: PurchaseOrderLine,
    pending: dict[UUID, Decimal],
) -> Decimal:
    """Return how much can still be received on a PO line.

    Subtracts already-received (COMPLETED receipts, via ``quantity_received``)
    and quantities reserved by active receipts (DRAFT/PENDING_APPROVAL/CONFIRMED).
    """
    received = po_line.quantity_received or Decimal('0')
    reserved = pending.get(po_line.id, Decimal('0'))
    return po_line.quantity_ordered - received - reserved


def po_net_total(po: PurchaseOrder) -> Decimal | None:
    """Net total of the order's lines, or ``None`` where it cannot be known.

    ``unit_price`` is nullable, and a line with no price used to count as
    zero — so the one order whose worth nobody had written down passed
    under every threshold. Zero and unknown are not the same answer: a
    price of 0.00 is a price, and a missing one is a total that cannot be
    compared with anything. The warehouse module keeps the same distinction
    for its own threshold.

    The one figure both readers of an order's worth work from: the approval
    threshold compares against it, and the approvals-queue card
    (``PurchaseOrderTargetSummaryDTO.total_value``) shows it. A second
    computation of "what is this order worth" is how the card came to show a
    partial sum about an order the rule refused to call below the limit.
    """
    total: Decimal = Decimal('0')
    for line in po.lines:
        if line.unit_price is None:
            return None
        total += line.quantity_ordered * line.unit_price
    return total


async def _is_approval_required(
    db: AsyncSession,
    org_id: UUID,
    settings: POSettings | None,
    po: PurchaseOrder,
    *,
    requester_id: UUID | None,
) -> bool:
    """Decide whether this PO must go through approval before confirmation.

    The workflow names whose orders it holds, and that is asked first: an
    order confirmed by somebody it does not name needs no approval, whatever
    the settings ask of everybody else's. Inside the scope the settings
    decide, as below.

    The threshold is denominated in the organization's currency and the
    system has no FX conversion. A PO in any other currency is always routed
    to approval instead of comparing numbers across currencies — a silent
    1:1 comparison would let uncontrolled spend through (same fail-closed
    logic as the missing-workflow gate in ``confirm_purchase_order``).

    A stored 0.00 is a threshold like any other — every order with a net
    total above it goes to approval, which at a zero threshold means every
    positively priced order; the comparison is ``>``, matching the screen's
    "above this net total", so a non-positive net total (an order priced at
    or below zero — a state the API should not produce) passes without
    approval rather than being silently swallowed. The column is read with
    ``is not None``, never with truthiness: ``Decimal('0.00')`` is falsy,
    and a truthiness read turned the zero threshold into the same thing as
    no threshold while the settings screen kept promising that orders above
    zero are controlled.
    The warehouse module reads its own threshold the same way
    (``approval_service.is_approval_required``).
    """
    if settings is None:
        return False
    if await approvals_api.requester_exempt(db, org_id, 'purchase_order', requester_id):
        return False
    if settings.approval_required:
        return True
    threshold = settings.approval_threshold
    if threshold is None:
        return False
    org = await core_api.organizations.get_async(db, org_id)
    org_currency = (org.currency if org else None) or 'USD'
    po_currency = po.currency or org_currency
    if po_currency != org_currency:
        return True
    total = po_net_total(po)
    # A total nobody can state is not a total below the limit. The way out
    # is the same in both directions: price the lines, or get the approval.
    if total is None:
        return True
    return total > threshold


async def confirm_approval_requirement(
    db: AsyncSession, org_id: UUID, po: PurchaseOrder, requester_id: UUID
) -> PurchaseOrderApprovalRequirement:
    """What confirming this order would do, and asking for approval, before the click.

    The rule is the one ``confirm_purchase_order`` obeys and the verdict the
    parked request would carry, so the dialog can neither promise a queue the
    request will never reach nor warn of one the order will not enter. The
    verdict does not wait for the rule: Request approval parks an order the
    rule would let through, and its dialog reads the same answer. So does an
    order parked with nothing pending on it (its request was withdrawn): asking
    again lands on the same stages, and that dialog owes the same warning. It
    is not confirmed from there, so no rule is asked. Any other order has
    nothing left to ask about.
    """
    required = False
    if po.status == 'DRAFT':
        settings = await get_po_settings(db, org_id)
        required = await _is_approval_required(
            db, org_id, settings, po, requester_id=requester_id
        )
    elif po.status != 'PENDING_APPROVAL' or await approvals_api.find_active_request(
        db, org_id, 'purchase_order', po.id
    ):
        return PurchaseOrderApprovalRequirement(approval_required=False)
    verdict = await approvals_api.first_stage_verdict(
        db, org_id, 'purchase_order', requester_id
    )
    if verdict is None or verdict.solvable:
        return PurchaseOrderApprovalRequirement(approval_required=required)
    return PurchaseOrderApprovalRequirement(
        approval_required=required,
        approval_solvable=False,
        undecidable_reason=verdict.undecidable_reason,
        undecidable_stage=verdict.stage_label,
    )


async def _refuse_unusable_supplier(
    db: AsyncSession, org_id: UUID, po: PurchaseOrder
) -> Any:
    """The supplier control every road to CONFIRMED performs.

    Returns the partner row the caller may name further on (the audit
    snapshot names the supplier as the create entry names them).

    The supplier is required where it can still be filled in. It used
    to be optional all the way through confirmation and then demanded
    by the receipt — in the one place with no way to add one, in
    English, with internal vocabulary ("IN documents require a
    partner"). The approval road used to skip this control and carry an
    order with a missing, inactive or non-supplier partner straight
    into Confirmed.
    """
    if not po.partner_id:
        raise ServiceRejectionError('po_supplier_required')

    partner = await core_api.partners.get_async(db, org_id, po.partner_id)
    if partner is not None:
        if not partner.is_active:
            raise ServiceRejectionError('po_partner_inactive', name=partner.name)
        if partner.type not in _SUPPLIER_PARTNER_TYPES:
            raise ServiceRejectionError(
                'po_partner_not_supplier', name=partner.name, partner_type=partner.type
            )
    return partner


async def _confirm_po_after_approval(
    db: AsyncSession,
    po: PurchaseOrder,
    user_id: UUID,
) -> None:
    """Flip PENDING_APPROVAL → CONFIRMED after approval is granted.

    The approving user is recorded as ``confirmed_by`` (informative:
    they are the one who released the PO).
    """
    if po.status == 'PENDING_APPROVAL':
        await _refuse_unusable_supplier(db, po.organization_id, po)
        po.status = 'CONFIRMED'
        po.confirmed_by = user_id
        po.confirmed_at = datetime.now(UTC)
        await db.flush()


async def confirm_purchase_order(
    db: AsyncSession,
    org_id: UUID,
    po_id: UUID,
    user_id: UUID,
) -> PurchaseOrder:
    po = await get_purchase_order(db, org_id, po_id)
    if not po:
        raise ServiceRejectionError('purchase_order_not_found')

    if po.status != 'DRAFT':
        raise ServiceRejectionError('po_confirm_invalid_status')

    partner = await _refuse_unusable_supplier(db, org_id, po)

    # Approval gate: per-org settings decide whether this PO must be
    # parked in PENDING_APPROVAL before it can become CONFIRMED. With no
    # workflow for target_type "purchase_order" the request would have
    # nowhere to go — and confirming anyway (the old behavior)
    # turned the whole setting into an ornament: the manager who switched
    # it on believed purchases were controlled while every PO sailed
    # through. Refusing names the missing piece instead.
    settings = await get_po_settings(db, org_id)
    approval_required = await _is_approval_required(
        db, org_id, settings, po, requester_id=user_id
    )

    if approval_required:
        workflow = await approvals_api.get_active_workflow(db, org_id, 'purchase_order')
        if workflow is None:
            raise ServiceRejectionError('po_approval_workflow_missing')
        po.status = 'PENDING_APPROVAL'
        try:
            request_obj = await approvals_api.request_approval(
                db,
                org_id,
                'purchase_order',
                po.id,
                user_id,
                meta_data={'auto_created': True, 'source': 'confirm_po'},
            )
        except ApprovalError as exc:
            # The request may have been moved to a terminal state by a
            # concurrent actor — surface a clean business error.
            raise ServiceRejectionError('po_approval_race_condition') from exc
        if request_obj.status == 'APPROVED':
            await _confirm_po_after_approval(db, po, user_id)
            # PO is CONFIRMED — same event as the direct path below.
            payload_obj = PurchaseOrderConfirmedPayload(
                po_id=str(po.id),
                po_number=po.number,
                organization_id=str(org_id),
            )
            await core_api.events.emit_transactional_async(
                db, PurchaseOrderEvent.CONFIRMED, payload_obj
            )
        await db.flush()
        await db.refresh(po)
        await core_api.audit_log.log_action_async(
            db,
            organization_id=org_id,
            user_id=user_id,
            action=AuditAction.UPDATE,
            target_type=AuditTargetType.PURCHASE_ORDER,
            target_id=po.id,
            snapshot={
                'number': po.number,
                'new_status': po.status,
                'approval_gate': True,
            },
        )
        return po

    po.status = 'CONFIRMED'
    po.confirmed_by = user_id
    po.confirmed_at = datetime.now(UTC)

    await db.flush()
    await db.refresh(po)
    await core_api.audit_log.log_action_async(
        db,
        organization_id=org_id,
        user_id=user_id,
        action=AuditAction.UPDATE,
        target_type=AuditTargetType.PURCHASE_ORDER,
        target_id=po.id,
        snapshot={
            'number': po.number,
            'new_status': po.status,
            'partner_id': str(po.partner_id) if po.partner_id else None,
            # The supplier, named as the create entry names them — the row was
            # read above to check it is an active supplier.
            'partner_name': partner.name if partner else None,
        },
    )

    # the event rides this transaction through the outbox
    payload_obj = PurchaseOrderConfirmedPayload(
        po_id=str(po.id),
        po_number=po.number,
        organization_id=str(org_id),
    )
    await core_api.events.emit_transactional_async(
        db, PurchaseOrderEvent.CONFIRMED, payload_obj
    )

    return po


async def cancel_purchase_order(
    db: AsyncSession,
    org_id: UUID,
    po_id: UUID,
    user_id: UUID,
) -> PurchaseOrder:
    # Lock PO row to prevent concurrent cancel races
    po = await get_purchase_order(db, org_id, po_id, for_update=True)
    if not po:
        raise ServiceRejectionError('purchase_order_not_found')

    if po.status == 'CANCELLED':
        raise ServiceRejectionError('po_already_cancelled')

    if po.status == 'COMPLETED':
        raise ServiceRejectionError('po_cancel_completed')

    if po.status == 'CONFIRMED':
        has_received = any(
            (po_line.quantity_received or Decimal('0')) > 0 for po_line in po.lines
        )
        if has_received:
            raise ServiceRejectionError('po_cancel_received_quantities')

        # Block cancel when any active (non-terminal) receipt still
        # references this PO. Previously only DRAFT receipts blocked; a
        # CONFIRMED (in-progress) receipt would let the PO cancel and later
        # "resurrect" quantity_received on a cancelled PO.
        linked_receipts = await list_linked_receipts(db, po.id, org_id)
        open_receipts = [
            r
            for r in linked_receipts
            if getattr(r, 'status', None) in _OPEN_RECEIPT_STATUSES
        ]
        if open_receipts:
            numbers = [
                getattr(r, 'number', None) or str(getattr(r, 'id', '?'))
                for r in open_receipts
            ]
            raise POHasOpenReceiptsError(
                get_error_message(
                    'po_cancel_open_receipts',
                    get_current_lang(),
                    numbers=', '.join(numbers),
                ),
                numbers,
            )

    previous_status = po.status
    po.status = 'CANCELLED'
    po.cancelled_by = user_id
    po.cancelled_at = datetime.now(UTC)

    # Best-effort cancel of any active approval request so the queue
    # does not show a PENDING/IN_PROGRESS request for a CANCELLED PO.
    try:
        active = await approvals_api.find_active_request(
            db, org_id, 'purchase_order', po.id
        )
        if active:
            await approvals_api.cancel_request(
                db, org_id, active.id, user_id, cascade=True
            )
    except Exception:  # noqa: BLE001 — best-effort; the cancel itself succeeds
        logger.warning('Failed to cancel approval request for PO %s', po.id)

    await db.flush()
    await db.refresh(po)
    await journal_order_act(
        db,
        org_id,
        user_id,
        po,
        before={'status': previous_status},
        after={'status': po.status},
    )

    # the event rides this transaction through the outbox
    payload_obj = PurchaseOrderCancelledPayload(
        po_id=str(po.id),
        po_number=po.number,
        organization_id=str(org_id),
    )
    await core_api.events.emit_transactional_async(
        db, PurchaseOrderEvent.CANCELLED, payload_obj
    )

    return po


async def _name_products_of_typed_lines(
    db: AsyncSession,
    org_id: UUID,
    po_lines: list[PurchaseOrderLine],
    chosen: dict[str, UUID],
) -> None:
    """Give each order line typed by hand the product its receiver named.

    A receipt takes only products into stock, and the receipt built from an
    order commits as it is created. An order line typed by hand is the buyer
    naming what they ordered; which product on the list that is — or whether
    it is a new one, with which unit — is for whoever receives it to say,
    not for the receipt to guess from the name. Their answer stays on the
    order line, so the rest of it arrives without asking again; a line with
    no answer, or one naming another organization's product, is refused by
    its number and name before anything is written.
    """
    unnamed: list[PurchaseOrderLine] = []
    for po_line in po_lines:
        if po_line.product_template_id is not None:
            continue
        choice = chosen.get(str(po_line.id))
        product = (
            await core_api.product_templates.get_async(db, org_id, choice)
            if choice
            else None
        )
        if product is None:
            unnamed.append(po_line)
            continue
        po_line.product_template_id = product.id
    if unnamed:
        raise ServiceRejectionError(
            'document_receipt_lines_need_product',
            plural=len(unnamed),
            lines=', '.join(
                f'{po_line.line_number} ({po_line.name})' for po_line in unnamed
            ),
        )


async def create_receipt_from_po(  # noqa: C901 - existing complexity/size
    db: AsyncSession,
    org_id: UUID,
    po_id: UUID,
    user_id: UUID,
    target_location_id: UUID,
    lines: list[dict[str, Any]] | None = None,
) -> Any:
    # Lock PO row to prevent concurrent receipt creation (TOCTOU race)
    result = await db.execute(
        select(PurchaseOrder)
        .where(PurchaseOrder.id == po_id, PurchaseOrder.organization_id == org_id)
        .with_for_update()
    )
    po = result.scalars().first()
    if not po:
        raise ServiceRejectionError('purchase_order_not_found')

    if po.status != 'CONFIRMED':
        raise ServiceRejectionError('po_receipt_requires_confirmed')

    po_lines_map = {str(po_line.id): po_line for po_line in po.lines}

    # count quantities already reserved by active (non-terminal)
    # receipts so two receipts created before the first completes cannot
    # over-receive. quantity_received only reflects COMPLETED receipts.
    pending = await warehouse_api.get_pending_receipt_quantities_async(
        db, org_id, [po_line.id for po_line in po.lines]
    )

    chosen: dict[str, UUID] = {}
    if lines is not None:
        # aggregate duplicate po_line_id entries in a single request
        # so their quantities are summed before validation (otherwise each
        # entry would be validated independently against the same remaining).
        aggregated: dict[str, Decimal] = {}
        for line_data in lines:
            po_line_id_str = str(line_data['po_line_id'])
            if line_data.get('product_template_id'):
                chosen[po_line_id_str] = line_data['product_template_id']
            if po_line_id_str not in po_lines_map:
                raise ServiceRejectionError(
                    'po_line_not_found', po_line_id=line_data['po_line_id']
                )
            aggregated[po_line_id_str] = aggregated.get(
                po_line_id_str, Decimal('0')
            ) + Decimal(line_data['quantity'])

        po_lines_to_receive = []
        for po_line_id_str, qty in aggregated.items():
            po_line = po_lines_map[po_line_id_str]
            remaining = _po_line_remaining(po_line, pending)
            if qty > remaining:
                raise ServiceRejectionError(
                    'po_receive_quantity_exceeds',
                    quantity=qty,
                    remaining=remaining,
                    line=po_line.line_number,
                )
            po_lines_to_receive.append((po_line, qty))
    else:
        po_lines_to_receive = []
        for po_line in po.lines:
            remaining = _po_line_remaining(po_line, pending)
            if remaining <= 0:
                continue
            po_lines_to_receive.append((po_line, remaining))

    await _name_products_of_typed_lines(
        db, org_id, [po_line for po_line, _ in po_lines_to_receive], chosen
    )
    doc_lines = []
    for po_line, receive_qty in po_lines_to_receive:
        line_name = po_line.name
        if not line_name and po_line.product_template_id:
            pt = await core_api.product_templates.get_async(
                db, org_id, po_line.product_template_id
            )
            if pt:
                line_name = pt.name
        doc_lines.append(
            ReceiptLineFromPODTO(
                product_template_id=po_line.product_template_id,
                name=line_name,
                quantity=receive_qty,
                unit_price=po_line.unit_price,
                uom_id=po_line.uom_id,
                tax_rate=po_line.tax_rate,
                notes=po_line.notes,
                source_po_line_id=po_line.id,
            )
        )

    # The PO number prints in the receipt's own reference row, in the
    # document's language; only the PO's own notes travel with it.
    po_notes = po.notes or ''

    doc = await warehouse_api.create_receipt_from_po_async(
        db=db,
        org_id=org_id,
        user_id=user_id,
        partner_id=po.partner_id,
        target_location_id=target_location_id,
        po_number=po.number,
        scheduled_date=po.scheduled_date,
        notes=po_notes,
        lines=doc_lines,
        currency=po.currency,
    )

    # quantity_received is NOT incremented here — it is recalculated
    # when the receipt document is COMPLETED (via DOCUMENT_COMPLETED event).
    # The PO transitions to COMPLETED in recalculate_po_quantities.

    # the event rides this transaction through the outbox
    payload_obj = ReceiptCreatedFromPOPayload(
        receipt_id=str(doc.id),
        receipt_number=doc.number,
        po_id=str(po.id),
        po_number=po.number,
        organization_id=str(org_id),
    )
    await core_api.events.emit_transactional_async(
        db, PurchaseOrderEvent.RECEIPT_CREATED_FROM_PO, payload_obj
    )
    if po.created_by:
        receipt_notification = await core_api.notifications.create_async(
            db,
            user_id=po.created_by,
            title=core_api.notifications.localize(
                _labels.RECEIPT_CREATED_TITLE, receipt=doc.number
            ),
            content=core_api.notifications.localize(
                _labels.RECEIPT_CREATED_CONTENT,
                receipt=doc.number,
                po=po.number,
            ),
            notification_type='info',
            link=f'/warehouse/documents/{doc.id}',
        )
        await core_api.notifications.publish_async(db, receipt_notification)
    return doc


async def list_linked_receipts(
    db: AsyncSession, po_id: UUID, org_id: UUID
) -> list[Any]:
    result = await db.execute(
        select(PurchaseOrderLine.id).where(PurchaseOrderLine.purchase_order_id == po_id)
    )
    po_line_ids = list(result.scalars().all())
    return await warehouse_api.list_by_source_po_line_ids_async(db, org_id, po_line_ids)

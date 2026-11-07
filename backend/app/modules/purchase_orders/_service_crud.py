from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import noload

from app.core.contracts import AuditAction, AuditTargetType
from app.core.db_utils import escape_ilike, paginate_async
from app.core.exceptions import ServiceRejectionError
from app.core.logging import get_logger
from app.core.public_api import core_api
from app.modules.warehouse.warehouse_api import warehouse_api

from ._journal import edit_state, journal_order_act
from .models import PurchaseOrder, PurchaseOrderLine, ReorderRule
from .schemas import (
    OrderLineTally,
    PurchaseOrderCreate,
    PurchaseOrderLineCreate,
    PurchaseOrderUnitProgressSchema,
    PurchaseOrderUpdate,
)

logger = get_logger(__name__)


async def _validate_line_templates(
    db: AsyncSession, org_id: UUID, lines: list[PurchaseOrderLineCreate]
) -> None:
    """ensure every product_template_id on PO lines belongs to org.

    Without this a non-existent template_id surfaced as a 500 (FK violation at
    flush) instead of a clear 400. Free-text lines (no template) are skipped.
    """
    seen: set[UUID] = set()
    for line_data in lines:
        tid = line_data.product_template_id
        if tid is None or tid in seen:
            continue
        seen.add(tid)
        if not await core_api.product_templates.exists_for_org_async(db, org_id, tid):
            raise ServiceRejectionError(
                'po_line_product_template_not_found', template_id=tid
            )


async def _validate_source_rules(
    db: AsyncSession, org_id: UUID, lines: list[PurchaseOrderLineCreate]
) -> None:
    """ensure every source_reorder_rule_id names a rule of this org.

    Same failure shape as the template check: a made-up rule id would
    otherwise surface as a 500 (FK violation at flush) instead of a 400.
    """
    rule_ids = {
        line.source_reorder_rule_id
        for line in lines
        if line.source_reorder_rule_id is not None
    }
    if not rule_ids:
        return
    found = await db.scalars(
        select(ReorderRule.id).where(
            ReorderRule.organization_id == org_id,
            ReorderRule.id.in_(rule_ids),
        )
    )
    if rule_ids - set(found.all()):
        raise ServiceRejectionError('reorder_rule_not_found')


#: The register calls an order this. Everything else about its number —
#: the shape, the width, the counter — is the organization's document
#: numbering, which is the point: an order is one of the things it numbers.
PO_DOC_TYPE = 'PO'


async def _highest_po_number_async(db: AsyncSession, org_id: UUID, prefix: str) -> int:
    """The largest sequence already printed on an order under *prefix*.

    Orders are not documents, so the numbering engine cannot find its own
    floor for them — it counts the ``documents`` table. Without this, an
    organization a year into its register would be offered number one
    again and the unique index would refuse the order.
    """
    numbers = await db.scalars(
        select(PurchaseOrder.number).where(
            PurchaseOrder.organization_id == org_id,
            PurchaseOrder.number.like(f'{prefix}%'),
        )
    )
    return warehouse_api.highest_sequence(numbers.all(), prefix)


async def generate_po_number(
    db: AsyncSession,
    org_id: UUID,
    document_date: date | None = None,
) -> str:
    """Next free number for an order dated *document_date*.

    Through the document numbering engine: it holds the advisory lock, the
    persistent counter and the organization's format. This used to be a
    second engine beside it — its own lock, its own regex, the shape
    ``PO/{year}/{seq}`` hardcoded — so an organization that changed how its
    documents are numbered saw the change everywhere except on its orders.
    """
    return await warehouse_api.generate_number_async(
        db,
        org_id,
        PO_DOC_TYPE,
        document_date=document_date,
        highest_in_use=lambda prefix: _highest_po_number_async(db, org_id, prefix),
    )


async def create_purchase_order(
    db: AsyncSession,
    org_id: UUID,
    data: PurchaseOrderCreate,
    user_id: UUID,
) -> PurchaseOrder:
    # Validate partner belongs to this org
    partner = None
    if data.partner_id:
        partner = await core_api.partners.get_async(db, org_id, data.partner_id)
        if partner is None:
            raise ServiceRejectionError('partner_not_found')

    # validate line product_template_ids belong to org (400, not 500)
    await _validate_line_templates(db, org_id, data.lines)
    await _validate_source_rules(db, org_id, data.lines)

    number = await generate_po_number(db, org_id, document_date=data.scheduled_date)

    # currency is required in practice — fall back to the
    # organization currency when the client did not send one.
    currency = data.currency
    if not currency:
        org = await core_api.organizations.get_async(db, org_id)
        if org is not None and org.currency:
            currency = org.currency

    po = PurchaseOrder(
        organization_id=org_id,
        number=number,
        status='DRAFT',
        partner_id=data.partner_id,
        scheduled_date=data.scheduled_date,
        notes=data.notes,
        currency=currency,
        created_by=user_id,
    )

    lines: list[PurchaseOrderLine] = []
    for i, line_data in enumerate(data.lines, 1):
        line = PurchaseOrderLine(
            purchase_order=po,
            product_template_id=line_data.product_template_id,
            name=line_data.name or '',
            quantity_ordered=line_data.quantity_ordered,
            quantity_received=Decimal('0'),
            unit_price=line_data.unit_price,
            uom_id=line_data.uom_id,
            tax_rate=line_data.tax_rate,
            line_number=i,
            notes=line_data.notes,
            source_reorder_rule_id=line_data.source_reorder_rule_id,
        )
        db.add(line)
        lines.append(line)
    await warehouse_api.fill_line_tax_rates_async(db, org_id, lines)

    db.add(po)
    await db.flush()
    await db.refresh(po)
    # A refresh does not cascade into the lines' own relationships, so a
    # line's product template arrives unloaded -- and the response schema
    # resolves names only from what is already in memory, because a lazy
    # load is what the async session refuses. Load it explicitly: the
    # response that creates a line sent without a name answers with the
    # template's name.
    for line in po.lines:
        await db.refresh(line, ['product_template'])
    await core_api.audit_log.log_action_async(
        db,
        organization_id=org_id,
        user_id=user_id,
        action=AuditAction.CREATE,
        target_type=AuditTargetType.PURCHASE_ORDER,
        target_id=po.id,
        snapshot={
            'number': po.number,
            'partner_id': str(po.partner_id) if po.partner_id else None,
            'partner_name': partner.name if partner else None,
            'line_count': len(data.lines),
        },
    )
    return po


async def get_purchase_order(
    db: AsyncSession,
    org_id: UUID,
    po_id: UUID,
    *,
    for_update: bool = False,
) -> PurchaseOrder | None:
    """Fetch a PO scoped to *org_id*; ``for_update`` locks the row.

    Single getter — the _for_update twin was an identical query with
    ``with_for_update()``.
    """
    stmt = select(PurchaseOrder).where(
        PurchaseOrder.id == po_id,
        PurchaseOrder.organization_id == org_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    result = await db.execute(stmt)
    return result.scalars().first()


async def list_purchase_orders(
    db: AsyncSession,
    org_id: UUID,
    *,
    search: str | None = None,
    status: str | None = None,
    partner_id: UUID | None = None,
    with_lines: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[PurchaseOrder], int]:
    """A page of the organization's orders, newest first.

    The lines are left unloaded unless ``with_lines``: the list sums them
    with ``order_line_tallies_async``.
    """
    conditions = [PurchaseOrder.organization_id == org_id]
    normalized_search = search.strip() if search else ''
    if normalized_search:
        pattern = f'%{escape_ilike(normalized_search)}%'
        conditions.append(
            or_(
                PurchaseOrder.number.ilike(pattern),
                PurchaseOrder.notes.ilike(pattern),
            )
        )
    if status:
        conditions.append(PurchaseOrder.status == status)
    # the partner card links here to answer "what have we ordered from
    # them?", which the documents list has always been able to answer for
    # itself.
    if partner_id:
        conditions.append(PurchaseOrder.partner_id == partner_id)

    stmt = (
        select(PurchaseOrder)
        .where(*conditions)
        .order_by(PurchaseOrder.created_at.desc())
    )
    if not with_lines:
        stmt = stmt.options(noload(PurchaseOrder.lines))
    return await paginate_async(db, stmt, limit=limit, offset=offset)


async def order_line_tallies_async(
    db: AsyncSession, org_id: UUID, po_ids: list[UUID]
) -> dict[UUID, OrderLineTally]:
    """Each order's lines counted, and summed per unit and in money.

    One grouped statement for a page: no line and no product is loaded. The
    unit groups keep the order the lines first name them in, and a blank
    symbol is no unit — the screen's own grouping.
    """
    if not po_ids:
        return {}
    symbols = {
        uom.id: (uom.symbol or '').strip() or None
        for uom in await core_api.uoms.list_for_org_async(db, org_id)
    }
    line = PurchaseOrderLine
    priced = line.unit_price.is_not(None)
    net = line.quantity_ordered * line.unit_price
    rows = await db.execute(
        select(
            line.purchase_order_id,
            line.uom_id,
            func.count(),
            func.sum(line.quantity_ordered),
            func.sum(func.coalesce(line.quantity_received, 0)),
            func.sum(net).filter(priced),
            func.sum(net * func.coalesce(line.tax_rate, 0)).filter(priced),
            func.count().filter(line.unit_price.is_(None)),
        )
        .join(PurchaseOrder, PurchaseOrder.id == line.purchase_order_id)
        .where(
            PurchaseOrder.organization_id == org_id, line.purchase_order_id.in_(po_ids)
        )
        .group_by(line.purchase_order_id, line.uom_id)
        .order_by(line.purchase_order_id, func.min(line.line_number))
    )
    tallies: dict[UUID, OrderLineTally] = {}
    groups: dict[tuple[UUID, str | None], PurchaseOrderUnitProgressSchema] = {}
    for po_id, uom_id, count, ordered, received, net_sum, tax_sum, unpriced in rows:
        tally = tallies.setdefault(po_id, OrderLineTally())
        tally.count += count
        tally.unpriced += unpriced
        unit = symbols.get(uom_id) if uom_id is not None else None
        group = groups.get((po_id, unit))
        if group is None:
            group = PurchaseOrderUnitProgressSchema(
                unit=unit, ordered=Decimal(0), received=Decimal(0)
            )
            groups[po_id, unit] = group
            tally.unit_progress.append(group)
        group.ordered += ordered
        group.received += received
        if net_sum is not None:
            tally.net = net_sum if tally.net is None else tally.net + net_sum
            tally.tax_basis = (
                tax_sum if tally.tax_basis is None else tally.tax_basis + tax_sum
            )
    return tallies


async def update_purchase_order(
    db: AsyncSession,
    org_id: UUID,
    po_id: UUID,
    data: PurchaseOrderUpdate,
    user_id: UUID,
) -> PurchaseOrder:
    po = await get_purchase_order(db, org_id, po_id, for_update=True)
    if not po:
        raise ServiceRejectionError('purchase_order_not_found')

    if po.status != 'DRAFT':
        raise ServiceRejectionError('po_update_not_draft')

    before = await edit_state(db, org_id, po)

    # §2b: partner_id is nullable — presence decides. A named null
    # detaches the supplier, a value re-validates org-ownership first
    # (create already did), an absent key leaves the column alone.
    if 'partner_id' in data.model_fields_set:
        if data.partner_id is not None:
            partner = await core_api.partners.get_async(db, org_id, data.partner_id)
            if partner is None:
                raise ServiceRejectionError('partner_not_found')
        po.partner_id = data.partner_id
    if data.scheduled_date is not None and data.scheduled_date != po.scheduled_date:
        po.scheduled_date = data.scheduled_date
        # The number carries the period the order is dated to; a draft moved
        # to another one is renumbered there. The engine decides whether the
        # number it holds still belongs to that period — the prefix depends
        # on the organization's format, which is not this module's to guess.
        po.number = await warehouse_api.renumber_for_date_async(
            db,
            org_id,
            PO_DOC_TYPE,
            po.number,
            po.scheduled_date,
            highest_in_use=lambda prefix: _highest_po_number_async(db, org_id, prefix),
        )
    # A named null on notes is a clearing instruction — the column is
    # nullable and the screen sends null on an emptied field. Absent from
    # the payload, the note stays untouched.
    if 'notes' in data.model_fields_set:
        po.notes = data.notes
    # §2b: the currency column is nullable — a named null clears it, an
    # absent key leaves it alone. The screen sends the key absent, via
    # `undefined`, whenever it has nothing to say about the currency.
    if 'currency' in data.model_fields_set:
        po.currency = data.currency

    if data.lines is not None:
        received = [
            line
            for line in po.lines
            if line.quantity_received and line.quantity_received > 0
        ]
        if received:
            raise ServiceRejectionError('po_lines_received')

        # log removed lines for audit trail before cascade-deleting
        removed_names = [line.name for line in po.lines]
        if removed_names:
            logger.info(
                'Removing %d PO line(s) from PO %s: %s',
                len(removed_names),
                po.number,
                ', '.join(removed_names),
            )

        for line in po.lines:
            await db.delete(line)
        await db.flush()

        # validate replacement line template_ids belong to org
        await _validate_line_templates(db, org_id, data.lines)
        await _validate_source_rules(db, org_id, data.lines)

        lines: list[PurchaseOrderLine] = []
        for i, line_data in enumerate(data.lines, 1):
            line = PurchaseOrderLine(
                purchase_order=po,
                product_template_id=line_data.product_template_id,
                name=line_data.name or '',
                quantity_ordered=line_data.quantity_ordered,
                quantity_received=Decimal('0'),
                unit_price=line_data.unit_price,
                uom_id=line_data.uom_id,
                tax_rate=line_data.tax_rate,
                line_number=i,
                notes=line_data.notes,
                source_reorder_rule_id=line_data.source_reorder_rule_id,
            )
            db.add(line)
            lines.append(line)
        await warehouse_api.fill_line_tax_rates_async(db, org_id, lines)

    await db.flush()
    await db.refresh(po)
    # The create path's explicit template load, for the same reason: the
    # replacement lines' names must resolve on this response, not only on
    # the next read.
    for line in po.lines:
        await db.refresh(line, ['product_template', 'uom'])
    await journal_order_act(
        db,
        org_id,
        user_id,
        po,
        before=before,
        after=await edit_state(db, org_id, po),
    )
    return po

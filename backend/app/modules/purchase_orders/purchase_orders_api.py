"""Public API for the purchase_orders module.

Exposes stable read/write access to reorder rules + supplier pricelist
so other modules (documents, equipment, recipes) can decide whether
to trigger a PO or compute a fallback price without importing
internal models.  Follows the ``approvals_api`` / ``warehouse_api``
singleton pattern.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import (
    PartnerPricelistDTO,
    PurchaseOrderCreateInput,
    PurchaseOrderDTO,
    ReorderRuleDTO,
    ReplenishmentAlertDTO,
    ReplenishmentProposalDTO,
    WorkItemDTO,
    WorkItemQueryDTO,
)


class PurchaseOrdersAPI:
    """Public Core API surface for the purchase_orders module."""

    async def list_reorder_rules_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        *,
        product_template_id: UUID | None = None,
        storage_location_id: UUID | None = None,
    ) -> list[ReorderRuleDTO]:
        from app.modules.purchase_orders.reorder_service import (
            list_for_org_async,
        )

        rules = await list_for_org_async(
            db,
            organization_id,
            product_template_id=product_template_id,
            storage_location_id=storage_location_id,
        )
        return [ReorderRuleDTO.model_validate(r) for r in rules]

    async def create_reorder_rule_async(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID,
        product_template_id: UUID,
        storage_location_id: UUID,
        min_quantity: Decimal,
        max_quantity: Decimal,
        safety_stock: Decimal = Decimal('0'),
        preferred_partner_id: UUID | None = None,
        notes: str | None = None,
    ) -> ReorderRuleDTO:
        from app.modules.purchase_orders.reorder_service import create_async

        rule = await create_async(
            db,
            organization_id=organization_id,
            product_template_id=product_template_id,
            storage_location_id=storage_location_id,
            min_quantity=min_quantity,
            max_quantity=max_quantity,
            safety_stock=safety_stock,
            preferred_partner_id=preferred_partner_id,
            notes=notes,
        )
        return ReorderRuleDTO.model_validate(rule)

    async def list_pricelist_for_partner_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        partner_id: UUID,
        *,
        active_on: date | None = None,
        product_template_id: UUID | None = None,
    ) -> list[PartnerPricelistDTO]:
        """Return all supplier offers for one partner (optionally filtered).

        Args:
            organization_id: Org scope.
            partner_id: Supplier partner id.
            active_on: If set, only entries valid on that date.
            product_template_id: Optional template filter.
        """
        from app.modules.purchase_orders.pricelist_service import (
            list_for_partner_async,
        )

        entries = await list_for_partner_async(
            db,
            organization_id,
            partner_id,
            active_on=active_on,
            product_template_id=product_template_id,
        )
        return [PartnerPricelistDTO.model_validate(e) for e in entries]

    async def list_supplier_prices_for_template_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        product_template_id: UUID,
        *,
        active_on: date | None = None,
    ) -> list[PartnerPricelistDTO]:
        """Return all supplier offers for one product (price comparison).

        Ordered by ``unit_price`` ascending (cheapest first).
        """
        from app.modules.purchase_orders.pricelist_service import (
            list_for_template_async,
        )

        entries = await list_for_template_async(
            db, organization_id, product_template_id, active_on=active_on
        )
        return [PartnerPricelistDTO.model_validate(e) for e in entries]

    async def get_replenishment_alerts_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
    ) -> list[ReplenishmentAlertDTO]:
        """Return stock-shortage alerts for every ReorderRule below its threshold.

        Each alert is a typed ``ReplenishmentAlertDTO`` (reorder_rule_id,
        product_template_id, product_name, sku, storage_location_id,
        available_quantity, min_quantity, max_quantity, safety_stock,
        shortage, suggested_reorder_quantity, reserve_available_quantity,
        proposed_move_quantity, remaining_to_buy).

        Used by the documents dashboard to surface re-order needs
        without requiring callers to import the internal
        ``replenishment_service``.
        """
        from app.modules.purchase_orders.replenishment_service import (
            get_replenishment_alerts,
        )

        return await get_replenishment_alerts(db, organization_id)

    async def get_replenishment_proposal_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        rule_id: UUID,
    ) -> ReplenishmentProposalDTO | None:
        """The reserve move an alert proposes, with its lines prepared.

        ``None`` when the rule does not belong to the organisation. A rule
        whose shortage is gone, or that reserve cannot cover at all, answers
        with an empty plan — the caller decides what an expired proposal
        means to its screen.
        """
        from app.modules.purchase_orders import reorder_service
        from app.modules.purchase_orders.replenishment_service import (
            get_reserve_move_plan_async,
        )

        rule = await reorder_service.get_async(db, organization_id, rule_id)
        if rule is None:
            return None
        return await get_reserve_move_plan_async(db, organization_id, rule)

    async def create_purchase_order_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        data: PurchaseOrderCreateInput,
        user_id: UUID,
    ) -> PurchaseOrderDTO:
        """Create a DRAFT Purchase Order from another module (e.g. shopping_lists).

        Delegates to the internal CRUD service (number generation, partner and
        template validation, audit log). Does NOT commit — the caller owns the
        transaction. Raises ``ValueError`` on invalid partner/template refs.
        """
        from app.modules.purchase_orders._service_crud import (
            create_purchase_order,
        )
        from app.modules.purchase_orders.schemas import (
            PurchaseOrderCreate,
            PurchaseOrderLineCreate,
        )

        internal = PurchaseOrderCreate(
            partner_id=data.partner_id,
            scheduled_date=data.scheduled_date,
            notes=data.notes,
            currency=data.currency,
            lines=[
                PurchaseOrderLineCreate(
                    product_template_id=line.product_template_id,
                    name=line.name,
                    quantity_ordered=line.quantity_ordered,
                    unit_price=line.unit_price,
                    uom_id=line.uom_id,
                    tax_rate=line.tax_rate,
                    notes=line.notes,
                )
                for line in data.lines
            ],
        )
        po = await create_purchase_order(db, organization_id, internal, user_id)
        return PurchaseOrderDTO.model_validate(po)

    async def list_work_items_async(
        self,
        db: AsyncSession,
        org_id: UUID,
        query: WorkItemQueryDTO,
    ) -> tuple[list[WorkItemDTO], int]:
        """This module's tasks: orders waiting for goods, and reserve moves.

        To do's provider. An order is expected while it is confirmed and one
        of its lines has arrived short of what was ordered; one with no date
        counts as due now, since nothing says it can wait. A reorder rule
        below its threshold whose reserve shelf can cover part of the
        shortage contributes the internal move that fills the location first.
        Oldest first. ``count`` is the number of lines still outstanding, or
        the quantity a reserve move would carry.
        """
        from sqlalchemy import func, or_, select

        from app.modules.purchase_orders.models import (
            PurchaseOrder,
            PurchaseOrderLine,
        )
        from app.modules.warehouse.warehouse_api import warehouse_api

        being_received = select(PurchaseOrderLine.purchase_order_id).where(
            PurchaseOrderLine.id.in_(
                list(
                    await warehouse_api.list_po_line_ids_with_confirmed_receipt_async(
                        db, org_id
                    )
                )
            )
        )
        outstanding = (
            select(
                PurchaseOrderLine.purchase_order_id.label('po_id'),
                func.count().label('lines'),
            )
            .where(
                PurchaseOrderLine.quantity_received < PurchaseOrderLine.quantity_ordered
            )
            .group_by(PurchaseOrderLine.purchase_order_id)
            .subquery()
        )
        due = (
            PurchaseOrder.organization_id == org_id,
            PurchaseOrder.status == 'CONFIRMED',
            PurchaseOrder.id.not_in(being_received),
            or_(
                PurchaseOrder.scheduled_date.is_(None),
                PurchaseOrder.scheduled_date <= query.date_to,
            ),
        )
        total = (
            await db.scalar(
                select(func.count())
                .select_from(PurchaseOrder)
                .join(outstanding, outstanding.c.po_id == PurchaseOrder.id)
                .where(*due)
            )
        ) or 0
        rows = (
            await db.execute(
                select(PurchaseOrder, outstanding.c.lines)
                .join(outstanding, outstanding.c.po_id == PurchaseOrder.id)
                .where(*due)
                .order_by(
                    PurchaseOrder.scheduled_date.asc().nulls_first(),
                    PurchaseOrder.number,
                )
                .limit(query.limit)
            )
        ).all()
        from app.modules.purchase_orders.replenishment_service import (
            replenishment_work_items_async,
        )

        # Reserve moves are tasks too: an alert whose reserve shelf can cover
        # part of the shortage proposes the carry before anything is bought.
        # They are derived here, on the same read, and disappear with the
        # shortage that raised them.
        replenishment = await replenishment_work_items_async(db, org_id)
        items = [
            WorkItemDTO(
                kind='expected_delivery',
                source_kind='purchase_order',
                source_id=po.id,
                due_date=po.scheduled_date,
                number=po.number,
                subject=getattr(po.partner, 'name', None),
                count=Decimal(lines),
                next_action='receive_delivery',
            )
            for po, lines in rows
        ] + replenishment
        items.sort(
            key=lambda item: (
                item.due_date is None,
                item.due_date or date.min,
                item.subject or '',
            )
        )
        return items[: query.limit], total + len(replenishment)

    async def get_target_summaries_by_ids_async(
        self,
        db: AsyncSession,
        org_id: UUID,
        target_ids: list[UUID],
    ) -> dict[UUID, Any]:
        """Lightweight purchase order summaries for the approvals queue.

               Returns ``{po_id: PurchaseOrderTargetSummaryDTO}``; ids outside this
               organisation, or unknown, are omitted rather than raising. Registered
        as this module's target-summary provider at startup.

               One IN-query; ``lines`` and ``partner`` are eager (``lazy='selectin'``)
               so the totals and the supplier name cost no extra round trips.
        """
        from sqlalchemy import select

        from app.modules.purchase_orders._service_workflow import po_net_total
        from app.modules.purchase_orders.models import PurchaseOrder
        from app.modules.purchase_orders.schemas import (
            PurchaseOrderTargetSummaryDTO,
        )

        if not target_ids:
            return {}

        result = await db.execute(
            select(PurchaseOrder).where(
                PurchaseOrder.id.in_(target_ids),
                PurchaseOrder.organization_id == org_id,
            )
        )
        summaries: dict[UUID, Any] = {}
        for po in result.scalars().all():
            summaries[po.id] = PurchaseOrderTargetSummaryDTO(
                id=po.id,
                number=po.number,
                partner_name=getattr(po.partner, 'name', None),
                # The same figure the approval threshold compares against —
                # ``None`` where it cannot be known, like the rule that raised
                # the request (see ``po_net_total``).
                total_value=po_net_total(po),
                currency=po.currency,
                lines_count=len(po.lines),
            )
        return summaries

    async def get_currencies_for_lines_async(
        self,
        db: AsyncSession,
        org_id: UUID,
        po_line_ids: list[UUID],
    ) -> dict[UUID, str | None]:
        """``{po_line_id: currency}`` for lines of this organization.

        A receipt that names order lines carries the order's prices
        digit for digit; stamping the document with the organization's
        currency would show those numbers under another sign, unconverted.
        The caller decides what to do when the answer is not one currency.
        Ids that are unknown, or belong to somebody else, are absent.
        """
        from sqlalchemy import select

        from app.modules.purchase_orders.models import (
            PurchaseOrder,
            PurchaseOrderLine,
        )

        if not po_line_ids:
            return {}

        rows = await db.execute(
            select(PurchaseOrderLine.id, PurchaseOrder.currency)
            .join(
                PurchaseOrder, PurchaseOrder.id == PurchaseOrderLine.purchase_order_id
            )
            .where(
                PurchaseOrderLine.id.in_(po_line_ids),
                PurchaseOrder.organization_id == org_id,
            )
        )
        currencies: dict[UUID, str | None] = {}
        for line_id, currency in rows.all():
            currencies[line_id] = currency
        return currencies

    async def get_ordered_quantities_async(
        self,
        db: AsyncSession,
        org_id: UUID,
        po_line_ids: list[UUID],
    ) -> dict[UUID, Decimal]:
        """``{po_line_id: quantity ordered}`` for lines of this organization.

        What a receipt naming an order line is allowed to add up to, **in the
        product's stock unit** — the order may be written in grams and the
        receipt in kilograms, and a ceiling compared in whatever unit each
        side happened to use let 20 kg through against 10000 g. Ids that are
        unknown, or belong to somebody else, are simply absent — a consumer
        that cannot find the order it names has nothing to check against,
        which is also the answer when this module is disabled.

        The rows are locked (``FOR UPDATE``) until the caller's transaction
        ends: the answer is a ceiling the caller is about to spend, and two
        receipts confirmed in the same instant each read the order line
        before the other had written against it. Held in order-line order,
        so two callers naming the same lines cannot deadlock on them.
        """
        from sqlalchemy import select

        from app.core.public_api import core_api
        from app.modules.purchase_orders.models import (
            PurchaseOrder,
            PurchaseOrderLine,
        )

        if not po_line_ids:
            return {}

        rows = await db.execute(
            select(
                PurchaseOrderLine.id,
                PurchaseOrderLine.quantity_ordered,
                PurchaseOrderLine.product_template_id,
                PurchaseOrderLine.uom_id,
            )
            .join(
                PurchaseOrder, PurchaseOrder.id == PurchaseOrderLine.purchase_order_id
            )
            .where(
                PurchaseOrderLine.id.in_(po_line_ids),
                PurchaseOrder.organization_id == org_id,
            )
            .order_by(PurchaseOrderLine.id)
            .with_for_update(of=PurchaseOrderLine)
        )
        ordered: dict[UUID, Decimal] = {}
        for line_id, quantity, template_id, uom_id in rows.all():
            ordered[line_id] = await core_api.uoms.to_stock_uom_async(
                db, org_id, template_id, Decimal(str(quantity or 0)), uom_id
            )
        return ordered

    async def get_line_labels_async(
        self,
        db: AsyncSession,
        org_id: UUID,
        po_line_ids: list[UUID],
    ) -> dict[UUID, tuple[str, int]]:
        """``{po_line_id: (order number, line number)}`` for this organization.

        How a sentence names an order line to a reader — the order's number
        and the line's position on it, as the order's own screen lists it.
        Ids that are unknown, or belong to somebody else, are absent.
        """
        from sqlalchemy import select

        from app.modules.purchase_orders.models import (
            PurchaseOrder,
            PurchaseOrderLine,
        )

        if not po_line_ids:
            return {}
        rows = await db.execute(
            select(
                PurchaseOrderLine.id,
                PurchaseOrder.number,
                PurchaseOrderLine.line_number,
            )
            .join(
                PurchaseOrder, PurchaseOrder.id == PurchaseOrderLine.purchase_order_id
            )
            .where(
                PurchaseOrderLine.id.in_(po_line_ids),
                PurchaseOrder.organization_id == org_id,
            )
        )
        return {line_id: (number, line_number) for line_id, number, line_number in rows}

    async def adopt_line_products_async(
        self,
        db: AsyncSession,
        org_id: UUID,
        products: dict[UUID, UUID],
    ) -> None:
        """Give order lines typed by hand the product their receipt arrived as.

        ``products`` is ``{po_line_id: product_template_id}`` as a completing
        receipt states it. An order line typed by hand names no product; the
        person receiving it says which product it is, and that answer stays
        on the order line so the rest of it arrives without asking again.
        A line that already names a product keeps it, and only the lines of
        this organization's orders are touched. Does NOT commit.
        """
        from sqlalchemy import select

        from app.modules.purchase_orders.models import (
            PurchaseOrder,
            PurchaseOrderLine,
        )

        if not products:
            return
        rows = await db.execute(
            select(PurchaseOrderLine)
            .join(
                PurchaseOrder, PurchaseOrder.id == PurchaseOrderLine.purchase_order_id
            )
            .where(
                PurchaseOrderLine.id.in_(products),
                PurchaseOrderLine.product_template_id.is_(None),
                PurchaseOrder.organization_id == org_id,
            )
        )
        for line in rows.scalars().all():
            line.product_template_id = products[line.id]

    async def count_received_async(
        self,
        db: AsyncSession,
        org_id: UUID,
        po_line_ids: list[UUID],
    ) -> None:
        """Bring the named order lines up to what completed receipts brought.

        Called by a receipt as it completes, in its own transaction, so the
        order answers with the goods the moment the receipt is posted. The
        ``document.completed`` subscription runs the same count once the
        event is delivered; it finds nothing left to change. Moves an order
        whose every line is now in to COMPLETED. Does NOT commit — the
        caller owns the transaction.

        An order line carries no organization of its own, and the id comes
        from a field the client fills in: only the lines of this
        organization's orders are counted.
        """
        from app.modules.purchase_orders._service_po_completion import (
            recalculate_po_quantities,
        )

        own = list(await self.get_currencies_for_lines_async(db, org_id, po_line_ids))
        await recalculate_po_quantities(db, org_id, own)


purchase_orders_api = PurchaseOrdersAPI()

__all__ = ['purchase_orders_api']

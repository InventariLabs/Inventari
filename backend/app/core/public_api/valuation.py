"""Module-safe access to ValuationService operations."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cost_estimates import UnitCostEstimate


class CoreValuationAPI:
    """Public Core API for inventory valuation operations."""

    async def estimate_unit_cost_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        product_template_ids: list[UUID],
    ) -> dict[UUID, UnitCostEstimate]:
        """Estimate stock-unit costs: priced layers, supplier offers, unknown.

        All prices are in the organization's money and stock units. A stated
        zero is a price, not a missing rate. This is for forecasts only:
        accounting must keep using the costs of the layers actually consumed.
        """
        from app.core.cost_estimates import supplier_rates_async
        from app.core.public_api import core_api

        ids = list(dict.fromkeys(product_template_ids))
        if not ids:
            return {}
        org = await core_api.organizations.get_async(db, organization_id)
        currency = org.currency if org else None
        rates = await self.get_rates_batch_async(db, organization_id, ids)
        missing = [tid for tid in ids if rates.get(tid) is None]
        supplier = await supplier_rates_async(db, organization_id, missing, currency)
        estimates = {}
        for tid in ids:
            rate = rates.get(tid)
            if rate is not None:
                estimates[tid] = UnitCostEstimate(rate, currency, 'layers')
            elif tid in supplier:
                estimates[tid] = UnitCostEstimate(supplier[tid], currency, 'supplier')
            else:
                estimates[tid] = UnitCostEstimate()
        return estimates

    async def record_receipt_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        product_template_id: UUID,
        quantity: Decimal,
        unit_cost: Decimal | None,
        document_line_id: UUID | None = None,
        currency: str | None = None,
        document_date: date | None = None,
        reverses_line_id: UUID | None = None,
    ) -> None:
        """Record a receipt into the cost history.

        Pass ``currency`` when the price came in one — a supplier's, say.
        Left out, the layer is written in the organization's own, which is
        what every reader assumed before there was anywhere to say otherwise.

        Pass ``document_date`` — the document's business date, the scheduled
        date of the delivery — so FIFO consumes in business-date order; a
        booking typed late must not push the goods it describes to the back
        of the queue. Left out, the layer falls back to its write time.

        ``unit_cost=None`` means the price was not stated; see
        ``record_unpriced_receipt_async`` for what happens then. Both spellings
        reach the same policy — a line with no price is not a different kind
        of event from a surplus with no price.

        Pass ``reverses_line_id`` — the outflow line whose goods are coming
        back — where the receipt is a return from a customer or a dispatch
        corrected downwards. The goods then come back at what that outflow
        cost, and ``unit_cost`` is ignored: the price on a return line is
        what the customer paid, not what the goods are worth on the shelf.
        The mirror of the same argument on ``record_delivery_async``.
        """
        from app.services.valuation_service import ValuationService

        await ValuationService.record_receipt_by_id_async(
            db,
            organization_id,
            product_template_id,
            quantity,
            unit_cost,
            document_line_id=document_line_id,
            currency=currency,
            document_date=document_date,
            reverses_line_id=reverses_line_id,
        )

    async def record_unpriced_receipt_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        product_template_id: UUID,
        quantity: Decimal,
    ) -> None:
        """Record stock arriving with nobody having named a price.

        A surplus off a count, a quantity raised by hand, a correction. It
        used to be posted at 0.00 — which diluted the average and understated
        the assets every time — so it is now valued at the organization's own
        current rate, and marked ``unknown`` where there is no rate to use.
        """
        from app.services.valuation_service import ValuationService

        await ValuationService.record_receipt_by_id_async(
            db,
            organization_id,
            product_template_id,
            quantity,
            None,
        )

    async def lock_open_layers_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        product_template_ids: Iterable[UUID],
    ) -> None:
        """Lock and read the cost layers of these products in one statement.

        For a posting that is about to take stock off several products with
        ``record_delivery_async``: each of those calls then drains the layers
        read here instead of asking for them. Outside a posting this does
        nothing.
        """
        from app.services.valuation_service import ValuationService

        await ValuationService.lock_open_layers_async(
            db, organization_id, product_template_ids
        )

    async def record_delivery_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        product_template_id: UUID,
        quantity: Decimal,
        document_line_id: UUID | None = None,
        reason: str | None = None,
        item_id: UUID | None = None,
        reverses_line_id: UUID | None = None,
    ) -> Decimal | None:
        """Take stock off the receipt layers and post what it was worth.

        Returns what the consumed layers cost, or ``None`` when the layers
        could not say — they did not cover the move, or they disagree on a
        currency. A caller that has to price what the outflow produced (a
        production run valuing its output) needs that figure and needs to
        know when there is none; a caller that only moves stock ignores it.

        *reason* is why the stock left, where the caller knows it — a use, a
        disposal, a scrapping. It lands on the outgoing layer, which is what
        lets the consumption and waste reports tell those apart. Goods
        dispatched to a customer are neither, and pass nothing.

        *reverses_line_id* names the receipt line whose goods are going back,
        where the outflow is a correction or a return. Those goods came in on
        one layer at one price, so that layer is drained before the rest of
        the queue.
        """
        from app.services.valuation_service import ValuationService

        posting = await ValuationService.post_delivery_by_id_async(
            db,
            organization_id,
            product_template_id,
            quantity,
            document_line_id=document_line_id,
            reason=reason,
            item_id=item_id,
            reverses_line_id=reverses_line_id,
        )
        return posting.cost

    async def get_current_rate_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        product_template_id: UUID,
    ) -> Decimal | None:
        """Return the template's layer-average valuation rate, or None.

        Stock value is FIFO — layers leave first-in-first-out — and this
        rate is the average cost of the layers still on hand: an indicative
        figure that steps when a layer empties, not a true running average
        (AVCO). Source fields keep the historical ``avco`` label; this is
        the formula a reader is actually getting.

        Tier 2 read for modules that need the rate without mutating
        valuation (e.g. recipes picking undo falls back to current rate
        when consumed_valuation_rate is missing on legacy rows).

        ``None`` also when the organization's layers cannot back a rate in
        its own money — they mix currencies, or all of the stock was bought
        in one foreign currency: a rate is only ever handed out in the
        house currency, never as a bare number to be taken for it.
        """
        from app.services.valuation_service import ValuationService

        return await ValuationService.get_current_valuation_rate_async(
            db, organization_id, product_template_id
        )

    async def get_rates_batch_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        product_template_ids: list[UUID],
    ) -> dict[UUID, Decimal | None]:
        """Return ``{template_id: layer-average valuation rate}`` for *product_template_ids*.

        Stock value is FIFO; the rate is the average cost of the layers
        still on hand — an indicative figure, not a true running average
        (see ``get_current_rate_async``). The ``avco`` label in source
        fields predates the honest naming.

        Batch read for multi-level BoM cost computation (maker module):
        one query instead of one per ingredient. Templates without a rate
        map to ``None``; unknown ids are omitted.

        The rate is only ever handed out in the organization's own currency:
        a template whose layers mix currencies, or were all bought in a
        foreign one, maps to ``None`` rather than offering a bare number
        every reader would take for the house's money.
        """
        from app.services.valuation_service import ValuationService

        return await ValuationService.get_valuation_rates_batch_async(
            db, organization_id, product_template_ids
        )

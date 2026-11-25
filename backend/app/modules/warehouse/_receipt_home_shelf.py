"""The home-shelf question a receipt in one step asks.

A warehouse that receives straight onto its shelves has no put-away task to
ask from, so the question is asked of the posted receipt: for each product
whose line was put on a shelf other than the one the rules suggest, is that
shelf now the product's home? The rules, the refusals, the silenced products
and the fixed-places setting are the put-away's (``home_shelf_service``); a
warehouse that receives in two steps is not asked here, its put-away asks.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from . import document_types as dt
from ._receipt_planning import ReceiptLocationPlanner, receipt_line_card_async
from ._receiving_area import list_receiving_modes_async, warehouse_of_async
from .home_shelf_service import (
    home_refusal_async,
    home_shelf_offer_async,
    is_silenced_async,
)
from .models import Document, DocumentStatus
from .putaway_schemas import HomeShelfOffer


async def receipt_home_shelf_offers_async(
    db: AsyncSession, org_id: UUID, doc: Document
) -> list[HomeShelfOffer]:
    """The offers a posted receipt makes, one for each product at most.

    Only a line that names its own shelf asks: a line left to the rules
    followed the suggestion by definition. The offer for a shelf the rules
    already name first, and for one chosen because the suggested shelf could
    not take the goods, is none (``home_shelf_offer_async``).
    """
    if doc.status != DocumentStatus.COMPLETED.value or not dt.is_receipt(doc.type):
        return []
    planner = await ReceiptLocationPlanner.for_document(db, doc)
    if planner.receiving_location_id is not None:
        return []
    warehouse_id = await warehouse_of_async(db, org_id, doc.target_location_id)
    mode = next(
        (
            row
            for row in await list_receiving_modes_async(db, org_id)
            if row.warehouse_id == warehouse_id
        ),
        None,
    )
    if mode is not None and mode.free_placement:
        return []

    offers: list[HomeShelfOffer] = []
    asked: set[UUID] = set()
    for line in doc.lines:
        chosen_id = line.target_location_id
        if chosen_id is None:
            continue
        template_id = await receipt_line_card_async(
            db,
            org_id,
            product_template_id=line.product_template_id,
            named=line.item,
            barcode=line.barcode,
        )
        if template_id is None or template_id in asked:
            continue
        asked.add(template_id)
        if await is_silenced_async(db, org_id, template_id):
            continue
        decision = await planner.decide(
            named=line.item,
            stock_template_id=template_id,
            line_target_id=chosen_id,
        )
        suggested_id = decision.rule_target_location_id
        offer = await home_shelf_offer_async(
            db,
            org_id,
            template_id=template_id,
            chosen_id=chosen_id,
            suggested_by_rule=suggested_id,
            forced=suggested_id is not None
            and await home_refusal_async(db, org_id, suggested_id) is not None,
        )
        if offer is not None:
            offers.append(offer)
    return offers

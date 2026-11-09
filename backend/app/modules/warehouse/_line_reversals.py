"""How much of an executed line is still there to take back.

A correction and a return both restate part of one line of one completed
document, and each used to be measured against that line on its own: a
delivery of ten accepted a correction of minus ten, and then accepted a
second one, because the question asked was always "is ten more than ten?"
and never "how much of it is left?". The two paths did not see each other
either, so six returned and six corrected away took twelve off a line that
received ten.

One rule, asked once, in one place: what is left is what the line executed,
plus what corrections have added to it, less what corrections and returns
have already taken away.

"What is left" is a question about the document. Undo also has to ask about
the stock: a receipt of ten whose four goods were issued, replenished by
another four, still reads as ten left on the line while the shelf holds a
different ten. The movement ledger is the only record that can tell them
apart, so the second half of this module reads it through the movement
contract.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from uuid import UUID

from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import StockMoveReferenceType
from app.core.public_api import core_api

from .models import (
    Document,
    DocumentLine,
    DocumentRelation,
    DocumentStatus,
    DocumentType,
)


async def reversible_quantities_async(
    db: AsyncSession, organization_id: UUID, original_lines: Sequence[DocumentLine]
) -> dict[UUID, Decimal]:
    """What is still available on each of *original_lines* to correct away or return.

    The same rule as :func:`reversible_quantity_async`, asked of a whole
    document in one statement instead of one per line.
    """
    ids = [line.id for line in original_lines]
    net: dict[UUID, Decimal] = {}
    for start in range(0, len(ids), 5000):
        rows = await db.execute(
            select(
                DocumentLine.corrects_line_id,
                func.coalesce(
                    func.sum(
                        case(
                            (
                                Document.type == DocumentType.CORRECTION.value,
                                DocumentLine.quantity,
                            ),
                            else_=-func.abs(DocumentLine.quantity),
                        )
                    ),
                    0,
                ),
            )
            .join(Document, Document.id == DocumentLine.document_id)
            .where(
                DocumentLine.corrects_line_id.in_(ids[start : start + 5000]),
                Document.organization_id == organization_id,
                Document.status != DocumentStatus.CANCELLED.value,
            )
            .group_by(DocumentLine.corrects_line_id)
        )
        net.update({row[0]: Decimal(str(row[1])) for row in rows.all()})
    return {
        line.id: line.done_quantity + net.get(line.id, Decimal('0'))
        for line in original_lines
    }


async def reversible_quantity_async(
    db: AsyncSession, organization_id: UUID, original_line: DocumentLine
) -> Decimal:
    """What is still available on *original_line* to correct away or return.

    A correction's quantity is signed: taking five back leaves five less to
    take, and an over-receipt correction of plus five leaves five more.
    A return is always a taking-back, whatever its sign convention.

    Cancelled documents restated nothing. Drafts have not yet, but they are
    counted all the same — two corrections of the same goods, both still
    open, would otherwise each pass on its own and collide only when the
    second is completed, by which time the first is history.
    """
    left = await reversible_quantities_async(db, organization_id, [original_line])
    return left[original_line.id]


async def stock_the_document_posted_was_used_async(
    db: AsyncSession, organization_id: UUID, original: Document
) -> bool:
    """Whether stock the original put on a shelf has since been taken off it.

    ``reversible_quantity_async`` measures the document; this measures the
    shelf. The two disagree exactly when the stock was used and replaced: a
    receipt of ten, four issued and another four received leaves ten on the
    line and ten on the shelf, and a correction of minus ten would empty a
    shelf whose first four goods are already gone. The line cannot see that,
    and the completion's own shortage check cannot either — the shelf is not
    short.

    The ledger names the stock each document *added*: the product, the shelf
    it landed on, the batch and the owner. Every later movement that takes
    stock out of that same group — an issue, a transfer to another shelf, a
    stock take, a production draw — means the goods have moved on, and the
    safe answer is Correct rather than Undo. A movement that restates the
    original itself (a correction or a return of it) is not a use: the line
    already accounts for it, and the undo is measured on what those left
    behind.

    Only what the document put somewhere is checked. An issue writes a
    movement with no destination, and undoing it adds stock back rather
    than taking any away, so nothing can be consumed out from under it.
    """
    posted = await core_api.stock_moves.posted_groups_async(
        db,
        organization_id,
        StockMoveReferenceType.DOCUMENT.value,
        original.id,
    )
    if not posted:
        return False

    # Documents that restate the original: its corrections, reversals and
    # returns. Their movements are the partial reversal the line's remainder
    # already knows about, not stock something else used. Corrections and
    # reversals are stored restating -> original, a return original ->
    # return, so the relation is read from either end and the original is
    # the one end that is not the answer.
    relations = await db.execute(
        select(DocumentRelation.source_document_id, DocumentRelation.target_document_id)
        .join(Document, Document.id == DocumentRelation.source_document_id)
        .where(
            Document.organization_id == organization_id,
            or_(
                DocumentRelation.source_document_id == original.id,
                DocumentRelation.target_document_id == original.id,
            ),
            DocumentRelation.relation_type.in_(('corrects', 'returns', 'reverses')),
        )
    )
    restatements = {document_id for pair in relations.all() for document_id in pair}
    restatements.add(original.id)

    return await core_api.stock_moves.any_departure_from_groups_async(
        db, organization_id, posted, excluded_reference_ids=sorted(restatements)
    )

"""Splitting one document line into siblings that copy its columns.

A line that must be served from more than one place becomes one line per
place: the batches a picker drew from at the session close, the shelves a
dispatch from a zone takes from at confirmation. Each sibling copies every
column of the line it came from, so what the line says about the product,
the owner, the unit and the document's order link stays the same on all of
them; the quantities, the identity of the record and the place are the
sibling's own.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .document_value_service import compute_line_values
from .models import Document, DocumentLine

#: Columns a sibling never copies: its identity, its quantities, its
#: discrepancy and its place in the document.
_OWN_COLUMNS = frozenset(
    {
        'id',
        'quantity',
        'expected_quantity',
        'done_quantity',
        'batch_number',
        'discrepancy_code',
        'discrepancy_reason',
        'line_number',
    }
)


async def insert_sibling_lines_async(
    db: AsyncSession,
    doc: Document,
    line: DocumentLine,
    siblings: list[dict[str, Any]],
) -> list[DocumentLine]:
    """Add one sibling of *line* per entry of *siblings*, and renumber the document.

    Each entry gives the sibling's own columns; every other column is copied
    from *line* as it stands when this is called. The siblings are placed
    directly after *line*, in the order given, and the document's lines are
    renumbered in that order. The caller has already written *line* itself.
    """
    columns = [
        column.key
        for column in DocumentLine.__table__.columns
        if column.key not in _OWN_COLUMNS
    ]
    shared = {column: getattr(line, column) for column in columns}
    existing = list(
        (
            await db.scalars(
                select(DocumentLine)
                .where(DocumentLine.document_id == doc.id)
                .order_by(DocumentLine.line_number)
                .with_for_update()
            )
        ).all()
    )
    clones: list[DocumentLine] = []
    for fields in siblings:
        clone = DocumentLine(**{**shared, **fields})
        compute_line_values(clone)
        db.add(clone)
        clones.append(clone)
    ordered: list[DocumentLine] = []
    for sibling in existing:
        ordered.append(sibling)
        if sibling.id == line.id:
            ordered.extend(clones)
    for number, sibling in enumerate(ordered, start=1):
        sibling.line_number = number
    await db.flush()
    await db.refresh(doc, ['lines'])
    return clones


async def date_line_by_goods_taken_async(
    db: AsyncSession,
    doc: Document,
    line: DocumentLine,
    taken: list[tuple[date | None, Decimal, UUID | None, str | None]],
) -> list[tuple[DocumentLine, Decimal]]:
    """Write the date and batch of the goods a line took on it, one line per part.

    *taken* is what the draw took, per date and batch, in the order it was
    drawn, as ``(date, quantity, record, batch name)`` with the quantity in
    the product's unit: stock with no batch is told apart by the date of its
    records, and a batch by its name. One part goes on the line itself;
    several split it, the way a picker's several batches do, each sibling
    picked in full. Every line stands for the record its goods were drawn
    from, even when that is not the record the line named, so a correction of
    it lands on that record. A line in the
    supplier's unit is split in that unit, in proportion to what each part
    gave; goods that carried neither a date nor a batch leave the line as it
    was, but for the record it stands for. A batch without a date still splits the line, so the correction of
    an issue that crossed batches restates each one.

    Answers every line the goods now stand on with what it took in the
    product's unit, which is what the line's delivery is valued by.
    """
    total = sum((q for _, q, _, _ in taken), Decimal('0'))
    if not any(day is not None or batch is not None for day, _, _, batch in taken):
        # Still the record the goods left: a line naming a batch's record
        # that drew the batchless unit would otherwise be undone into the batch.
        line.item_id = taken[0][2] or line.item_id
        return [(line, total)]
    if len(taken) == 1:
        line.expiry_date = taken[0][0]
        line.batch_number = taken[0][3] or line.batch_number
        line.item_id = taken[0][2] or line.item_id
        return [(line, total)]
    done = line.done_quantity
    in_line_unit = [q * done / total for _, q, _, _ in taken[:-1]]
    in_line_unit.append(done - sum(in_line_unit, Decimal('0')))
    first_day, _, first_record, first_batch = taken[0]
    elsewhere = done - in_line_unit[0]
    line.expiry_date = first_day
    line.batch_number = first_batch or line.batch_number
    line.item_id = first_record or line.item_id
    line.done_quantity = in_line_unit[0]
    line.quantity -= elsewhere
    line.expected_quantity -= elsewhere
    compute_line_values(line)
    clones = await insert_sibling_lines_async(
        db,
        doc,
        line,
        [
            {
                'expiry_date': day,
                'item_id': record or line.item_id,
                'batch_number': batch,
                'quantity': share,
                'expected_quantity': share,
                'done_quantity': share,
            }
            for (day, _, record, batch), share in zip(
                taken[1:], in_line_unit[1:], strict=True
            )
        ],
    )
    return [(line, taken[0][1])] + [
        (clone, q) for clone, (_, q, _, _) in zip(clones, taken[1:], strict=True)
    ]

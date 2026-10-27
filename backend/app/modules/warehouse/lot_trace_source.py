"""Name a document in a batch's trace: its number and the partner on it.

Every receipt and delivery posts its movements under
``reference_type='document'`` and the document's id; the trace in Core finds
them by batch and asks here what each document is. The partner comes from the
snapshot the document took when it was confirmed — the name and address the
paper carries, which is what an inspector compares against — and, for a
document confirmed before snapshots were taken, only as the partner's id,
which Core reads from the partner record.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import LotTraceReferenceDTO
from app.core.module_sdk import LotTraceSource

from .models import Document


class DocumentLotTraceSource(LotTraceSource):
    """The warehouse's documents, as a recall reads them."""

    # The literal, not StockMoveReferenceType: a module does not import a
    # core model. The value is StockMoveReferenceType.DOCUMENT's.
    reference_type = 'document'

    async def describe_async(
        self,
        db: AsyncSession,
        organization_id: UUID,
        reference_ids: Sequence[UUID],
    ) -> dict[UUID, LotTraceReferenceDTO]:
        rows = (
            await db.execute(
                select(
                    Document.id,
                    Document.number,
                    Document.partner_id,
                    Document.partner_snapshot,
                ).where(
                    Document.organization_id == organization_id,
                    Document.id.in_(reference_ids),
                )
            )
        ).all()
        described: dict[UUID, LotTraceReferenceDTO] = {}
        for document_id, number, partner_id, snapshot in rows:
            snapshot = snapshot or {}
            described[document_id] = LotTraceReferenceDTO(
                label=number,
                partner_id=partner_id,
                partner_name=snapshot.get('name'),
                partner_address=snapshot.get('address')
                if snapshot.get('name')
                else None,
            )
        return described

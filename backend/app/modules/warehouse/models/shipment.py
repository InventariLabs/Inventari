"""What left with a dispatch: carrier, tracking number, when and by whom.

Shipping is a record, not a carrier integration — the carrier's own system
prints the label, and Inventari keeps what was handed over. The record is
written by the completion of the dispatch, in its transaction, so a dispatch
whose stock did not post carries no shipment either; a document has at most
one.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.module_sdk import CoreModelBase


class DocumentShipment(CoreModelBase):
    """The hand-over of one dispatch to a carrier."""

    __tablename__ = 'document_shipments'
    __table_args__ = (
        UniqueConstraint('document_id', name='uq_document_shipments_document'),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('organizations.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('documents.id', ondelete='CASCADE'),
        nullable=False,
    )
    #: Free text, as the operator names the carrier: suggestions come from
    #: the organization's earlier shipments, and the tracking link from the
    #: name (``shipment_service.tracking_url``).
    carrier: Mapped[str] = mapped_column(String(100), nullable=False)
    #: Empty for a hand-over that has none — the organization's own van.
    tracking_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    shipped_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    shipped_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('users.id', ondelete='SET NULL'), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

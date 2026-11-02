"""Packages under a dispatch, and what each one holds.

Packing sits between "all picked" and completion: the picked goods go into
boxes, each box gets a number within its document and, optionally, a weight,
and the slip and the label printed for it carry the same code. Packing is
optional — a document with no packages completes as it always did — and a
completed document's packages are a record, not a workspace.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.module_sdk import CoreModelBase


class DocumentPackage(CoreModelBase):
    """One box of a dispatch, numbered within its document."""

    __tablename__ = 'document_packages'
    __table_args__ = (
        UniqueConstraint('document_id', 'number', name='uq_document_packages_number'),
        CheckConstraint('weight_kg > 0', name='ck_document_packages_weight'),
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
        index=True,
    )
    #: 1, 2, 3 … within the document, without gaps: deleting a package moves
    #: the ones after it down (``packing_service.delete_package_async``).
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(10, 3), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('users.id', ondelete='SET NULL'), nullable=True
    )

    lines: Mapped[list[DocumentPackageLine]] = relationship(
        'DocumentPackageLine',
        back_populates='package',
        cascade='all, delete-orphan',
        order_by='DocumentPackageLine.created_at',
    )


class DocumentPackageLine(CoreModelBase):
    """How much of one document line a package holds."""

    __tablename__ = 'document_package_lines'
    __table_args__ = (
        UniqueConstraint(
            'document_package_id',
            'document_line_id',
            name='uq_document_package_lines_line',
        ),
        CheckConstraint('quantity > 0', name='ck_document_package_lines_quantity'),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    #: Not ``package_id``: that name belonged to the handling units the
    #: stock model dropped, and this is a document's package, not one.
    document_package_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('document_packages.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    document_line_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('document_lines.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    package: Mapped[DocumentPackage] = relationship(
        'DocumentPackage', back_populates='lines'
    )

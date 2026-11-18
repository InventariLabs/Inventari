"""A delivery cost that reached no product, kept as a figure with a reason.

A freight bill that arrives after the receipt is posted cannot be spread over
the goods: the layers are written and some of them may be gone. The amount is
still a fact about the delivery, so it is recorded here instead of being
refused, and listed and summed where a manager looks for it.

It is never part of a stock value. Nothing in the valuation reports reads this
table, and there is no counter-account behind it: a system with a general
ledger books the same figure to a price-variance account, this product keeps
the figure and the reason.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import AuditAction, AuditTargetType
from app.core.public_api import core_api

from .extra_costs_service import assert_currency
from .models import Document, DocumentCostVariance


async def add_async(
    db: AsyncSession,
    organization_id: UUID,
    doc: Document,
    *,
    kind: str,
    amount: Decimal,
    currency: str | None,
    reason: str,
    occurred_on: date,
    user_id: UUID | None,
) -> DocumentCostVariance:
    assert_currency(doc, currency)
    variance = DocumentCostVariance(
        organization_id=organization_id,
        document_id=doc.id,
        kind=kind,
        amount=amount,
        currency=currency,
        reason=reason,
        occurred_on=occurred_on,
        created_by=user_id,
    )
    db.add(variance)
    await db.flush()
    await core_api.audit_log.log_action_async(
        db,
        organization_id=organization_id,
        user_id=user_id,
        action=AuditAction.CREATE,
        target_type=AuditTargetType.DOCUMENT,
        target_id=doc.id,
        snapshot={
            'number': doc.number,
            'cost_kind': kind,
            'amount': str(amount),
            'currency': currency or doc.currency,
            'reason': reason,
            'occurred_on': occurred_on.isoformat(),
        },
    )
    return variance


async def delete_async(
    db: AsyncSession,
    organization_id: UUID,
    doc: Document,
    variance_id: UUID,
    *,
    user_id: UUID | None = None,
) -> bool:
    variance = await db.scalar(
        select(DocumentCostVariance).where(
            DocumentCostVariance.id == variance_id,
            DocumentCostVariance.organization_id == organization_id,
            DocumentCostVariance.document_id == doc.id,
        )
    )
    if variance is None:
        return False
    await core_api.audit_log.log_action_async(
        db,
        organization_id=organization_id,
        user_id=user_id,
        action=AuditAction.HARD_DELETE,
        target_type=AuditTargetType.DOCUMENT,
        target_id=doc.id,
        snapshot={
            'number': doc.number,
            'cost_kind': variance.kind,
            'amount': str(variance.amount),
            'currency': variance.currency or doc.currency,
            'reason': variance.reason,
        },
    )
    await db.delete(variance)
    await db.flush()
    return True


async def list_for_document_async(
    db: AsyncSession, organization_id: UUID, document_id: UUID
) -> list[DocumentCostVariance]:
    rows = await db.scalars(
        select(DocumentCostVariance)
        .where(
            DocumentCostVariance.organization_id == organization_id,
            DocumentCostVariance.document_id == document_id,
        )
        .order_by(
            DocumentCostVariance.occurred_on.asc(),
            DocumentCostVariance.created_at.asc(),
        )
    )
    return list(rows.all())


def _in_period(
    stmt: Select[Any], date_from: date | None, date_to: date | None
) -> Select[Any]:
    if date_from is not None:
        stmt = stmt.where(DocumentCostVariance.occurred_on >= date_from)
    if date_to is not None:
        stmt = stmt.where(DocumentCostVariance.occurred_on <= date_to)
    return stmt


def _own_currency() -> ColumnElement[str | None]:
    """The currency a figure is in: its own, else its document's."""
    return func.coalesce(DocumentCostVariance.currency, Document.currency)


async def list_for_organization_async(
    db: AsyncSession,
    organization_id: UUID,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int,
    offset: int,
) -> tuple[list[tuple[DocumentCostVariance, str | None, str | None]], int]:
    """One page of ``(variance, document number, document currency)`` and the
    count of the whole period, newest first."""
    base = (
        select(DocumentCostVariance.id)
        .join(Document, Document.id == DocumentCostVariance.document_id)
        .where(DocumentCostVariance.organization_id == organization_id)
    )
    total = await db.scalar(
        _in_period(base, date_from, date_to).with_only_columns(func.count())
    )
    stmt = _in_period(
        select(DocumentCostVariance, Document.number, Document.currency)
        .join(Document, Document.id == DocumentCostVariance.document_id)
        .where(DocumentCostVariance.organization_id == organization_id),
        date_from,
        date_to,
    )
    rows = await db.execute(
        stmt.order_by(
            DocumentCostVariance.occurred_on.desc(),
            DocumentCostVariance.created_at.desc(),
        )
        .offset(offset)
        .limit(limit)
    )
    return [(row[0], row[1], row[2]) for row in rows.all()], total or 0


async def totals_by_currency_async(
    db: AsyncSession,
    organization_id: UUID,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict[str, Decimal]:
    """Sum per currency over the whole period, not the page; the key is empty
    when neither the figure nor its document names one."""
    currency = _own_currency()
    stmt = _in_period(
        select(currency, func.sum(DocumentCostVariance.amount))
        .join(Document, Document.id == DocumentCostVariance.document_id)
        .where(DocumentCostVariance.organization_id == organization_id)
        .group_by(currency),
        date_from,
        date_to,
    )
    return {code or '': Decimal(total) for code, total in await db.execute(stmt)}

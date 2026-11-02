"""Freight, duty and insurance, spread over the goods they arrived with.

Without them the shelf is worth what the supplier invoiced and nothing else,
so every margin computed from it is short by the cost of getting the goods
there — the most common reason a warehouse's stock value disagrees with its
accounts.

Only while the receipt is unposted. Once the layers are written the goods may
already have left, and "spread it over what is still there" is a division by
zero on a delivery that sold out. The standard answers (ERPNext reposts
backwards, Odoo books the uncoverable part to a price-difference account)
both need a general ledger, and this product deliberately has none — so the
refusal says that, and says what to do instead.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import AuditAction, AuditTargetType
from app.core.exceptions import ServiceRejectionError
from app.core.public_api import core_api

from ._stock_executor_helpers import _executed_quantity
from .models import (
    Document,
    DocumentExtraCost,
    DocumentLine,
    DocumentStatus,
    ExtraCostAllocation,
)

#: The states in which the goods are not yet on the books, so a cost added
#: now still reaches every unit it belongs to.
OPEN_STATES = frozenset(
    {
        DocumentStatus.DRAFT,
        DocumentStatus.PENDING_APPROVAL,
        DocumentStatus.CONFIRMED,
    }
)

_CENT = Decimal('0.01')


class AllocatableLine(Protocol):
    """The three fields an allocation reads off a line.

    A protocol rather than the ORM class: the arithmetic is the part worth
    testing on its own, and a test that has to build a Document, its lines
    and a session to divide two hundred by a hundred is a test nobody writes.
    """

    id: UUID
    unit_price: Decimal | None
    product_template_id: UUID | None


def _planned_quantity(line: DocumentLine) -> Decimal:
    """What the line will bring, before anybody has received it.
    The preview runs on a draft, where nothing is done yet, so it reads the
    expected quantity; the allocation that actually prices the layers reads
    what was received, because that is what reached the shelf.
    """
    return line.done_quantity or line.expected_quantity


class ExtraCostRefusedError(ServiceRejectionError):
    """The cost cannot be taken; the key says why."""


def _quantise(value: Decimal) -> Decimal:
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


def _weights(
    lines: Sequence[AllocatableLine],
    method: str,
    weight_by_template: dict[UUID, Decimal],
    quantity_of: Callable[[Any], Decimal],
) -> tuple[dict[UUID, Decimal], str]:
    """``({line_id: weight}, method actually used)``.

    A share of a total of zero is a division by zero, not a cost. Value
    allocation on a delivery nobody priced, and weight allocation on products
    whose weight nobody filled in, both fall back to quantity — and say so,
    rather than quietly producing a number.
    """

    def _by_quantity() -> dict[UUID, Decimal]:
        return {line.id: quantity_of(line) for line in lines}

    if method == ExtraCostAllocation.QUANTITY:
        return _by_quantity(), ExtraCostAllocation.QUANTITY

    if method == ExtraCostAllocation.VALUE:
        weights = {
            line.id: quantity_of(line) * (line.unit_price or Decimal('0'))
            for line in lines
        }
    else:
        weights = {
            line.id: quantity_of(line)
            * weight_by_template.get(
                line.product_template_id or UUID(int=0), Decimal('0')
            )
            for line in lines
        }

    if sum(weights.values(), start=Decimal('0')) <= 0:
        return _by_quantity(), ExtraCostAllocation.QUANTITY
    return weights, method


def allocate(
    amount: Decimal,
    lines: Sequence[AllocatableLine],
    method: str,
    weight_by_template: dict[UUID, Decimal] | None = None,
    quantity_of: Callable[[Any], Decimal] = _executed_quantity,
) -> tuple[dict[UUID, Decimal], str]:
    """Spread one invoice over the lines. ``({line_id: share}, method used)``.

    The shares add up to the amount to the cent, and the remainder lands on
    the last line. Which line carries it is convention rather than
    arithmetic, so it follows the systems our users arrive from: Odoo rounds
    half-up per line and adds the difference to the last valuation line,
    ERPNext rounds to the field precision and adds it to the last item. The
    same delivery priced there and priced here comes out the same, which is
    worth more than a cent placed more elegantly.
    """
    weights, used = _weights(lines, method, weight_by_template or {}, quantity_of)
    total_weight = sum(weights.values(), start=Decimal('0'))
    if total_weight <= 0 or not lines:
        return {}, used

    shares = {
        line_id: _quantise(amount * weight / total_weight)
        for line_id, weight in weights.items()
    }
    remainder = amount - sum(shares.values(), start=Decimal('0'))
    if remainder != 0:
        last = lines[-1].id
        shares[last] = shares[last] + remainder
    return shares, used


async def list_async(
    db: AsyncSession, organization_id: UUID, document_id: UUID
) -> list[DocumentExtraCost]:
    rows = await db.scalars(
        select(DocumentExtraCost)
        .where(
            DocumentExtraCost.organization_id == organization_id,
            DocumentExtraCost.document_id == document_id,
        )
        .order_by(DocumentExtraCost.created_at.asc())
    )
    return list(rows.all())


def assert_open(doc: Document) -> None:
    """Refuse a cost on a receipt that is already on the books."""
    if doc.status in OPEN_STATES:
        return
    raise ExtraCostRefusedError('extra_cost_document_posted')


def assert_currency(doc: Document, currency: str | None) -> None:
    """The cost is in the document's currency, or names none at all.

    Both halves matter. Converting at a rate nobody recorded is how a value
    becomes a number with no history behind it, which is the standing policy
    for prices — and a cost that names a currency the document does not is the
    same problem with the mismatch hidden one level down, because a document
    without a currency means "the organization's".
    """
    if currency == doc.currency or currency is None:
        return
    raise ExtraCostRefusedError('extra_cost_currency_mismatch')


async def add_async(
    db: AsyncSession,
    organization_id: UUID,
    doc: Document,
    *,
    kind: str,
    amount: Decimal,
    currency: str | None,
    allocation_method: str,
    note: str | None,
    user_id: UUID | None,
) -> DocumentExtraCost:
    assert_open(doc)
    assert_currency(doc, currency)
    cost = DocumentExtraCost(
        organization_id=organization_id,
        document_id=doc.id,
        kind=kind,
        amount=amount,
        currency=currency,
        allocation_method=allocation_method,
        note=note,
        created_by=user_id,
    )
    db.add(cost)
    await db.flush()
    # A freight bill on a receipt moves what the delivery cost: the log keeps
    # the kind and the amount, so the document's total has an author.
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
            'allocation_method': allocation_method,
        },
    )
    return cost


async def delete_async(
    db: AsyncSession,
    organization_id: UUID,
    doc: Document,
    cost_id: UUID,
    *,
    user_id: UUID | None = None,
) -> bool:
    assert_open(doc)
    cost = await db.scalar(
        select(DocumentExtraCost).where(
            DocumentExtraCost.id == cost_id,
            DocumentExtraCost.organization_id == organization_id,
            DocumentExtraCost.document_id == doc.id,
        )
    )
    if cost is None:
        return False
    # The row is about to be gone: kind and amount travel in the snapshot.
    await core_api.audit_log.log_action_async(
        db,
        organization_id=organization_id,
        user_id=user_id,
        action=AuditAction.HARD_DELETE,
        target_type=AuditTargetType.DOCUMENT,
        target_id=doc.id,
        snapshot={
            'number': doc.number,
            'cost_kind': cost.kind,
            'amount': str(cost.amount),
            'currency': cost.currency,
            'allocation_method': cost.allocation_method,
        },
    )
    await db.delete(cost)
    await db.flush()
    return True


async def _weight_by_template_async(
    db: AsyncSession, organization_id: UUID, lines: Sequence[Any]
) -> dict[UUID, Decimal]:
    template_ids = {
        line.product_template_id for line in lines if line.product_template_id
    }
    weights: dict[UUID, Decimal] = {}
    for template_id in template_ids:
        template = await core_api.product_templates.get_async(
            db, organization_id, template_id
        )
        value = getattr(template, 'weight_value', None) if template else None
        if value:
            weights[template_id] = Decimal(str(value))
    return weights


async def surcharges_async(
    db: AsyncSession, doc: Document, *, planned: bool = False
) -> tuple[dict[UUID, Decimal], list[str]]:
    """``({line_id: total surcharge}, methods that had to fall back)``.

    Each cost is spread on its own terms and the shares are summed, so a
    freight bill split by weight and a customs bill split by value do not
    have to agree on a method.
    """
    costs = await list_async(db, doc.organization_id, doc.id)
    if not costs:
        return {}, []

    quantity_of = _planned_quantity if planned else _executed_quantity
    lines = [line for line in doc.lines if quantity_of(line) > 0]
    if not lines:
        return {}, []

    weight_by_template = await _weight_by_template_async(db, doc.organization_id, lines)
    totals: dict[UUID, Decimal] = {}
    fallbacks: list[str] = []
    for cost in costs:
        shares, used = allocate(
            Decimal(cost.amount),
            lines,
            cost.allocation_method,
            weight_by_template,
            quantity_of,
        )
        if used != cost.allocation_method:
            fallbacks.append(cost.allocation_method)
        for line_id, share in shares.items():
            totals[line_id] = totals.get(line_id, Decimal('0')) + share
    return totals, fallbacks

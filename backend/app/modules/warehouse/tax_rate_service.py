from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db_utils import acquire_advisory_lock
from app.core.module_sdk import journal_config_change, record_settings
from app.core.money import quantise

from .models import TaxRate


async def _journal_rate(
    db: AsyncSession,
    org_id: UUID,
    user_id: UUID | None,
    name: str,
    before: Any,
    after: Any,
) -> None:
    """A rate is what every line naming it is taxed at: its changes are journalled,
    in the transaction of the request that changed it."""
    await journal_config_change(
        db,
        org_id,
        user_id,
        module='warehouse',
        subject=f'tax-rate:{name}',
        keys={'name', 'rate', 'code', 'country', 'is_default'},
        before=before,
        after=after,
    )


async def list_tax_rates(db: AsyncSession, org_id: UUID) -> list[TaxRate]:
    result = await db.scalars(
        select(TaxRate)
        .where(TaxRate.organization_id == org_id)
        .order_by(TaxRate.created_at)
    )
    return list(result.all())


async def get_tax_rate(
    db: AsyncSession, org_id: UUID, rate_id: UUID, *, for_update: bool = False
) -> TaxRate | None:
    """``for_update`` reads the rate under its row lock, for a write that
    journals what it changed: a request that reached the rate while another
    was changing it waits for that commit and reads what it really changes,
    so the same edit saved twice at once is journalled once."""
    query = select(TaxRate).where(
        TaxRate.id == rate_id,
        TaxRate.organization_id == org_id,
    )
    if for_update:
        query = query.with_for_update()
    return cast(TaxRate | None, await db.scalar(query))


async def _ensure_single_default(
    db: AsyncSession,
    org_id: UUID,
    user_id: UUID | None,
    exclude_id: UUID | None = None,
) -> None:
    """Take the default off the rate that holds it. Losing the flag is a change
    to that rate of its own, journalled under its name beside the entry of the
    rate that took it (AUDIT.md: one row per record).

    The holder is read under its row lock: a request that read it while another
    was clearing it waits for that commit, and the re-read no longer finds it
    the default — cleared once, journalled once.

    The row lock alone does not make the default single: with no holder there
    is no row to wait on, and a request released from the old holder's row does
    not see the rate another request has just committed as the default. So the
    organization's default is changed under one lock, taken before the read —
    the next request reads after the first has committed."""
    await acquire_advisory_lock(db, f'tax-default:{org_id}')
    query = select(TaxRate).where(
        TaxRate.organization_id == org_id,
        TaxRate.is_default.is_(True),
    )
    if exclude_id:
        query = query.where(TaxRate.id != exclude_id)
    for previous in (await db.scalars(query.with_for_update())).all():
        before = record_settings(previous)
        previous.is_default = False
        await _journal_rate(db, org_id, user_id, previous.name, before, previous)


async def create_tax_rate(
    db: AsyncSession,
    org_id: UUID,
    name: str,
    rate: Decimal,
    *,
    user_id: UUID | None = None,
    **kwargs: Any,
) -> TaxRate:
    is_default = kwargs.get('is_default', False)
    if is_default:
        await _ensure_single_default(db, org_id, user_id)

    tr = TaxRate(
        organization_id=org_id,
        name=name,
        rate=rate,
        code=kwargs.get('code'),
        country=kwargs.get('country'),
        is_default=is_default,
    )
    db.add(tr)
    await db.flush()
    await _journal_rate(db, org_id, user_id, name, None, tr)
    await db.refresh(tr)
    return tr


async def update_tax_rate(
    db: AsyncSession,
    org_id: UUID,
    rate_id: UUID,
    *,
    user_id: UUID | None = None,
    **fields: Any,
) -> TaxRate | None:
    tr = await get_tax_rate(db, org_id, rate_id, for_update=True)
    if not tr:
        return None
    before = record_settings(tr)

    if fields.get('is_default') is True:
        await _ensure_single_default(db, org_id, user_id, exclude_id=rate_id)

    for key, value in fields.items():
        if value is not None and hasattr(tr, key):
            setattr(tr, key, value)

    await db.flush()
    await _journal_rate(db, org_id, user_id, str(before['name']), before, tr)
    await db.refresh(tr)
    return tr


async def delete_tax_rate(
    db: AsyncSession, org_id: UUID, rate_id: UUID, *, user_id: UUID | None = None
) -> bool:
    tr = await get_tax_rate(db, org_id, rate_id, for_update=True)
    if not tr:
        return False
    before = record_settings(tr)
    await db.delete(tr)
    await _journal_rate(db, org_id, user_id, tr.name, before, None)
    await db.flush()
    return True


async def compute_tax_summary(db: AsyncSession, org_id: UUID) -> list[dict[str, Any]]:
    from sqlalchemy import func

    from .models import Document, DocumentLine

    result = await db.execute(
        select(
            DocumentLine.tax_rate,
            func.sum(DocumentLine.line_value).label('total_net'),
            func.sum(DocumentLine.line_tax).label('total_tax'),
            func.sum(DocumentLine.line_gross).label('total_gross'),
            func.count(DocumentLine.id).label('line_count'),
        )
        .join(Document, DocumentLine.document_id == Document.id)
        .where(
            Document.organization_id == org_id,
            Document.status == 'COMPLETED',
            DocumentLine.tax_rate.isnot(None),
            DocumentLine.line_value.isnot(None),
        )
        .group_by(DocumentLine.tax_rate)
        .order_by(DocumentLine.tax_rate)
    )
    rows = result.all()

    summary = []
    for tax_rate, total_net, total_tax, total_gross, line_count in rows:
        summary.append(
            {
                'tax_rate': tax_rate,
                'net': quantise(total_net or Decimal('0.00')),
                'tax': quantise(total_tax or Decimal('0.00')),
                'gross': quantise(total_gross or Decimal('0.00')),
                'line_count': line_count,
            }
        )

    return summary

import uuid
from collections.abc import Iterable
from decimal import Decimal
from typing import Literal

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db_utils import escape_ilike, paginate_async
from app.core.events import SystemEvent, emit_safe
from app.core.exceptions import (
    ServiceRejectionError,
    catalogue_refusal,
)
from app.core.logging import get_logger
from app.models.audit_log import AuditAction, AuditTargetType
from app.models.item import Item
from app.models.partner import Partner
from app.schemas.partner import (
    PartnerCreate,
    PartnerListItem,
    PartnerUpdate,
)
from app.services.audit_service import audit_key, audit_value, log_action_async

logger = get_logger(__name__)

SortBy = Literal['name', 'created_at', 'type']
SortOrder = Literal['asc', 'desc']

_NOT_CLEARABLE = frozenset({'name', 'type', 'is_consumer'})
_SORTABLE_COLUMNS = {
    'name': Partner.name,
    'created_at': Partner.created_at,
    'type': Partner.type,
}

# The pair this module's update entry draws its keys from: `before` and
# `after` are cut from the payload, so every key is a field the schema and
# the model share (backend/scripts/export_audit_snapshot_keys.py).
AUDIT_PAYLOAD_SCHEMA = ('PartnerUpdate', 'Partner')


def _identity(partner: Partner) -> dict:
    """What names a partner in the journal, after the row itself is gone."""
    return {'name': partner.name, 'type': partner.type, 'code': partner.code}


async def _journal_change_async(
    db: AsyncSession,
    partner: Partner,
    before: dict,
    after: dict,
    user_id: uuid.UUID | None,
) -> None:
    """One UPDATE entry for the fields that moved; none when nothing did."""
    changed = [f for f in after if audit_key(before[f]) != audit_key(after[f])]
    if not changed:
        return
    await log_action_async(
        db,
        organization_id=partner.organization_id,
        user_id=user_id,
        action=AuditAction.UPDATE,
        target_type=AuditTargetType.PARTNER,
        target_id=partner.id,
        snapshot={
            'name': partner.name,
            'before': {f: audit_value(before[f]) for f in changed},
            'after': {f: audit_value(after[f]) for f in changed},
        },
    )


async def create_async(
    db: AsyncSession, org_id: uuid.UUID, data: PartnerCreate, user_id: uuid.UUID
) -> Partner:
    await _check_unique_async(db, org_id, data.name, data.type)
    if data.code is not None:
        await _check_code_unique_async(db, org_id, data.code)
    partner = Partner(
        organization_id=org_id,
        created_by=user_id,
        **data.model_dump(),
    )
    db.add(partner)
    await db.flush()
    await db.refresh(partner)
    await log_action_async(
        db,
        organization_id=org_id,
        user_id=user_id,
        action=AuditAction.CREATE,
        target_type=AuditTargetType.PARTNER,
        target_id=partner.id,
        snapshot=_identity(partner),
    )
    logger.info('Partner created: %s (org=%s)', partner.id, org_id)
    return partner


async def _check_unique_async(
    db: AsyncSession,
    org_id: uuid.UUID,
    name: str,
    partner_type: str,
    exclude_id: uuid.UUID | None = None,
) -> None:
    q = select(Partner).where(
        Partner.organization_id == org_id,
        Partner.name == name,
        Partner.type == partner_type,
    )
    if exclude_id is not None:
        q = q.where(Partner.id != exclude_id)
    if await db.scalar(q) is not None:
        raise ServiceRejectionError(
            'partner_name_exists', name=name, partner_type=partner_type
        )


async def _check_code_unique_async(
    db: AsyncSession,
    org_id: uuid.UUID,
    code: str,
    exclude_id: uuid.UUID | None = None,
) -> None:
    q = select(Partner).where(
        Partner.organization_id == org_id,
        Partner.code == code,
    )
    if exclude_id is not None:
        q = q.where(Partner.id != exclude_id)
    if await db.scalar(q) is not None:
        raise ServiceRejectionError('partner_code_exists', code=code)


async def get_async(
    db: AsyncSession,
    org_id: uuid.UUID,
    partner_id: uuid.UUID,
    *,
    for_update: bool = False,
) -> Partner | None:
    """The partner, or ``None``; ``for_update`` locks the row first.

    A write locks it before it reads what it journals as ``before``: a
    concurrent edit is then waited for and read, not overwritten in the
    journal by the state from before it. ``populate_existing`` because a
    locking select otherwise hands back the instance already in the session
    without its columns read again.
    """
    stmt = select(Partner).where(
        Partner.organization_id == org_id, Partner.id == partner_id
    )
    if for_update:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    return await db.scalar(stmt)


async def display_names_by_ids_async(
    db: AsyncSession,
    org_id: uuid.UUID,
    partner_ids: Iterable[uuid.UUID],
) -> dict[uuid.UUID, str]:
    """The display name of each partner these ids name, in one query.

    A screen printing a name beside a stored partner id asks for exactly
    the ids it shows: one read for the page instead of a fetch per row,
    and no walk of the organization's whole partner book to resolve a
    handful. Deactivated partners answer too — a document filed under one
    still prints the name it was filed with — and an id another
    organization owns, or that no longer exists, is simply absent, so the
    caller falls back to the name it froze with the row itself.
    """
    ids = list(dict.fromkeys(partner_ids))
    if not ids:
        return {}
    rows = await db.execute(
        select(Partner.id, Partner.name).where(
            Partner.organization_id == org_id,
            Partner.id.in_(ids),
        )
    )
    names: dict[uuid.UUID, str] = {}
    for partner_id, name in rows.all():
        names[partner_id] = name
    return names


async def ids_named_like_async(
    db: AsyncSession, org_id: uuid.UUID, term: str
) -> list[uuid.UUID]:
    """Ids of this organization's partners whose name contains *term*.

    The read a screen asks to match a document by the partner it names: it
    answers with ids only, for the caller's own query, instead of
    materializing a partner list that a limit could truncate. Match is
    case-insensitive on the name alone, and deactivated partners answer —
    a document filed under a vendor that has since been retired still has
    to be found by that vendor's name.
    """
    pattern = f'%{escape_ilike(term)}%'
    rows = await db.scalars(
        select(Partner.id).where(
            Partner.organization_id == org_id,
            Partner.name.ilike(pattern),
        )
    )
    return list(rows.all())


async def list_partners_async(
    db: AsyncSession,
    org_id: uuid.UUID,
    search: str | None = None,
    partner_type: str | None = None,
    partner_types: list[str] | None = None,
    is_active: bool | None = True,
    limit: int = 100,
    offset: int = 0,
    sort_by: SortBy = 'name',
    sort_order: SortOrder = 'asc',
) -> tuple[list[PartnerListItem], int]:
    sort_col = _SORTABLE_COLUMNS.get(sort_by)
    if sort_col is None:
        raise ServiceRejectionError('invalid_input')
    q = select(Partner).where(Partner.organization_id == org_id)
    if is_active is not None:
        q = q.where(Partner.is_active == is_active)

    if partner_types:
        q = q.where(Partner.type.in_(partner_types))
    elif partner_type is not None:
        q = q.where(Partner.type == partner_type.upper())

    if search:
        pattern = f'%{escape_ilike(search)}%'
        q = q.where(
            (Partner.name.ilike(pattern))
            | (Partner.code.ilike(pattern))
            | (Partner.tax_id.ilike(pattern))
            | (Partner.contact_person.ilike(pattern))
            | (Partner.email.ilike(pattern))
        )

    q = q.order_by(sort_col.desc() if sort_order == 'desc' else sort_col)

    partners, total = await paginate_async(db, q, limit=limit, offset=offset)
    items = await _attach_document_stats_async(db, org_id, partners)
    return items, total


async def _attach_document_stats_async(
    db: AsyncSession,
    org_id: uuid.UUID,
    partners: list[Partner],
) -> list[PartnerListItem]:
    """Attach per-partner document collaboration stats.

       One grouped query over ``documents`` for the page's partner ids.
       All three numbers now share the same ``status <> 'DRAFT'`` set, so a
       partner with only drafts reports zero documents and no last activity
       together. Turnover is summed per ``currency`` and never mixes currencies:
       ``total_amount`` carries a total only when the partner's non-draft
       documents fall under exactly one currency (an unknown/NULL currency
       counts as a single group); a partner whose documents carry no value has
       a total of zero; otherwise it stays ``None`` so the UI can
       say "multiple currencies" instead of labelling a mixed sum with the
       organization's currency. ``turnover_currency`` names the currency of a
    shown total so the UI labels the amount correctly.

    A second grouped query counts the partner's purchase orders. It counts
    EVERY order — all statuses, DRAFT and CANCELLED included — because the
    link this number backs opens the purchase-order list, whose status filter
    defaults to ALL. The documents count beside it deliberately excludes
    DRAFT; the difference between the two is intended, not accidental.
    """
    items: list[PartnerListItem] = [
        PartnerListItem.model_validate(p, from_attributes=True) for p in partners
    ]
    if not items:
        return items

    rows = (
        await db.execute(
            text(
                """
                SELECT partner_id,
                       currency,
                       COUNT(*) FILTER (WHERE status <> 'DRAFT') AS document_count,
                       SUM(total_gross) FILTER (WHERE status <> 'DRAFT')
                           AS total_amount,
                       MAX(created_at) FILTER (WHERE status <> 'DRAFT')
                           AS last_activity_at
                FROM documents
                WHERE organization_id = :org
                  AND partner_id = ANY(:ids)
                GROUP BY partner_id, currency
                HAVING COUNT(*) FILTER (WHERE status <> 'DRAFT') > 0
                """
            ),
            {'org': org_id, 'ids': [p.id for p in partners]},
        )
    ).all()
    # One grouped query over the module's own table: every status counts,
    # DRAFT and CANCELLED included — see the docstring above for why this
    # differs from document_count.
    po_rows = (
        await db.execute(
            text(
                """
                SELECT partner_id,
                       COUNT(*) AS purchase_order_count
                FROM purchase_orders
                WHERE organization_id = :org
                  AND partner_id = ANY(:ids)
                GROUP BY partner_id
                """
            ),
            {'org': org_id, 'ids': [p.id for p in partners]},
        )
    ).all()
    po_counts: dict[uuid.UUID, int] = {
        row.partner_id: row.purchase_order_count for row in po_rows
    }

    stats: dict[uuid.UUID, list] = {}
    for row in rows:
        stats.setdefault(row.partner_id, []).append(row)
    for item in items:
        item.purchase_order_count = po_counts.get(item.id, 0)
        partner_rows = stats.get(item.id)
        if not partner_rows:
            continue
        item.document_count = sum(r.document_count for r in partner_rows)
        item.last_activity_at = max(
            (
                r.last_activity_at
                for r in partner_rows
                if r.last_activity_at is not None
            ),
            default=None,
        )
        # A currency with no gross total contributes nothing to turnover, so
        # only rows with a non-NULL SUM participate in the single-currency
        # check. Mixing two real currencies (or a real currency with unknown)
        # leaves the total unset rather than emitting a cross-currency sum.
        totals = [
            (r.currency, r.total_amount)
            for r in partner_rows
            if r.total_amount is not None
        ]
        currencies = {currency for currency, _ in totals}
        if not totals:
            # Documents without a value add up to nothing — not to a mix.
            item.total_amount = Decimal(0)
            item.turnover_currency = None
        elif len(currencies) == 1:
            item.total_amount = sum(amount for _, amount in totals)
            # name the currency of the total so the UI can label the
            # amount instead of guessing (or printing a bare number).
            item.turnover_currency = next(iter(currencies))
        else:
            item.total_amount = None
            item.turnover_currency = None
    return items


async def update_async(
    db: AsyncSession,
    org_id: uuid.UUID,
    partner_id: uuid.UUID,
    data: PartnerUpdate,
    *,
    user_id: uuid.UUID | None = None,
) -> Partner | None:
    partner = await get_async(db, org_id, partner_id, for_update=True)
    if partner is None:
        return None

    updates = data.model_dump(exclude_unset=True)
    # name, type and is_consumer back NOT NULL columns: a null naming one is
    # refused by name (backend/AGENTS.md §2b) instead of reaching setattr.
    cleared = sorted(f for f in _NOT_CLEARABLE & updates.keys() if updates[f] is None)
    if cleared:
        raise catalogue_refusal('field_cannot_be_cleared', fields=', '.join(cleared))
    new_name = updates.get('name', partner.name)
    new_type = updates.get('type', partner.type)
    new_code = updates.get('code', partner.code)
    if new_name != partner.name or new_type != partner.type:
        await _check_unique_async(db, org_id, new_name, new_type, exclude_id=partner_id)
    if 'code' in updates and new_code is not None and new_code != partner.code:
        await _check_code_unique_async(db, org_id, new_code, exclude_id=partner_id)

    audited = [f for f in updates if hasattr(partner, f)]
    before = {f: getattr(partner, f) for f in audited}
    for field, value in updates.items():
        setattr(partner, field, value)

    await db.flush()
    await db.refresh(partner)
    after = {f: getattr(partner, f) for f in audited}
    await _journal_change_async(db, partner, before, after, user_id)
    return partner


async def deactivate_async(
    db: AsyncSession,
    org_id: uuid.UUID,
    partner_id: uuid.UUID,
    *,
    user_id: uuid.UUID | None = None,
) -> Partner | None:
    partner = await get_async(db, org_id, partner_id, for_update=True)
    if partner is None:
        return None
    was_active = partner.is_active
    partner.is_active = False
    await db.flush()
    await db.refresh(partner)
    await _journal_change_async(
        db, partner, {'is_active': was_active}, {'is_active': False}, user_id
    )
    payload = {'partner_id': str(partner.id), 'organization_id': str(org_id)}
    await emit_safe(SystemEvent.PARTNER_DEACTIVATED, payload)
    return partner


async def activate_async(
    db: AsyncSession,
    org_id: uuid.UUID,
    partner_id: uuid.UUID,
    *,
    user_id: uuid.UUID | None = None,
) -> Partner | None:
    partner = await get_async(db, org_id, partner_id, for_update=True)
    if partner is None:
        return None
    was_active = partner.is_active
    partner.is_active = True
    await db.flush()
    await db.refresh(partner)
    await _journal_change_async(
        db, partner, {'is_active': was_active}, {'is_active': True}, user_id
    )
    payload = {'partner_id': str(partner.id), 'organization_id': str(org_id)}
    await emit_safe(SystemEvent.PARTNER_ACTIVATED, payload)
    return partner


async def delete_async(
    db: AsyncSession,
    org_id: uuid.UUID,
    partner_id: uuid.UUID,
    *,
    user_id: uuid.UUID | None = None,
) -> bool:
    partner = await get_async(db, org_id, partner_id, for_update=True)
    if partner is None:
        return False

    open_po_count = await db.scalar(
        text(
            'SELECT COUNT(*) FROM purchase_orders '
            'WHERE partner_id = :pid AND organization_id = :oid '
            "AND status IN ('DRAFT', 'CONFIRMED', 'PENDING_APPROVAL')"
        ),
        {'pid': partner_id, 'oid': org_id},
    )
    if open_po_count:
        raise ServiceRejectionError(
            'partner_delete_open_purchase_orders', count=open_po_count
        )

    # Unlink items referencing this partner
    items_q = select(Item).where(
        Item.organization_id == org_id,
        Item.partner_id == partner_id,
    )
    items = (await db.scalars(items_q)).all()
    for item in items:
        item.partner_id = None
    # Written before the row goes: after it, nothing is left to read the
    # name from.
    await log_action_async(
        db,
        organization_id=org_id,
        user_id=user_id,
        action=AuditAction.HARD_DELETE,
        target_type=AuditTargetType.PARTNER,
        target_id=partner.id,
        snapshot=_identity(partner),
    )
    await db.delete(partner)
    await db.flush()
    logger.info(
        'Partner deleted: %s (org=%s, unlinked %d items)',
        partner_id,
        org_id,
        len(items),
    )
    return True


async def get_items_async(
    db: AsyncSession,
    org_id: uuid.UUID,
    partner_id: uuid.UUID,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[Item], int]:
    q = select(Item).where(
        Item.organization_id == org_id,
        Item.partner_id == partner_id,
        Item.is_deleted.is_(False),
    )
    return await paginate_async(db, q, limit=limit, offset=offset)

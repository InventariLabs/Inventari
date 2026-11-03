from __future__ import annotations

import csv
import io
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, Date, case, func, null, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ServiceRejectionError
from app.core.export_hygiene import defuse
from app.core.module_sdk import PaginatedResponse
from app.core.public_api import core_api

from . import document_types as dt
from .document_profile_service import get_profile
from .models import Document, DocumentShipment, DocumentStatus
from .schemas import (
    RegisterCurrencyTotal,
    RegisterDocumentRow,
    RegisterGroup,
    RegisterResponse,
    RegisterSummary,
)
from .shipment_service import attach_shipments_async

_VALID_GROUP_BY = ('type', 'partner', 'location', 'month')
_VALID_STATUSES = frozenset({'DRAFT', 'CONFIRMED', 'COMPLETED', 'CANCELLED'})
# Grouping key for documents with no partner / no location. Only ever an
# identity — the group's ``label`` is None so the reader names it.
_NO_VALUE_KEY = ''
# The types whose documents are worth something: goods bought, sold, or
# written off. A transfer or a correction has no value of its own, so a
# document of those types without one is not "missing" anything.
_VALUE_TYPES = sorted(
    {t for t in (*dt.ALL_TYPES, *dt.LEGACY_MAP) if dt.carries_value(t)} | {dt.SCRAP}
)
# Rows per page the register serves. The window can hold a year of
# a busy warehouse; the rows endpoint is the only thing that must not try to
# render it in one answer.
DEFAULT_ROWS_LIMIT = 50


def _window_conditions(
    org_id: UUID,
    date_from: date,
    date_to: date,
    doc_type: str | None,
    status_filter: str | None,
    partner_id: UUID | None,
    location_id: UUID | None,
) -> list[Any]:
    effective_status = (
        status_filter.upper()
        if status_filter and status_filter.upper() in _VALID_STATUSES
        else DocumentStatus.COMPLETED.value
    )

    conditions: list[Any] = [
        Document.organization_id == org_id,
        document_date_column() >= date_from,
        document_date_column() <= date_to,
        Document.status == effective_status,
    ]
    if doc_type:
        conditions.append(Document.type == doc_type.upper())
    if partner_id:
        conditions.append(Document.partner_id == partner_id)
    if location_id:
        conditions.append(
            (Document.source_location_id == location_id)
            | (Document.target_location_id == location_id)
        )
    return conditions


def document_date_column() -> ColumnElement[Any]:
    """The date a document is *for* — the one date the module files it under.

    ``scheduled_date`` is what the period guard closes on and what the cost
    layers queue by; ``created_at`` is the moment somebody typed the document
    in. The register used the second, so a delivery entered on 2 January and
    dated to 31 December belonged to December for the books and to January
    for the register. One date, asked once, and the same one the guard asks
    — and the same one the plain list filters and sorts by, so a range asked
    of the list and of the register names the same documents.
    """
    return func.coalesce(Document.scheduled_date, func.cast(Document.created_at, Date))


async def _partner_names_async(
    db: AsyncSession, org_id: UUID, conditions: list[Any]
) -> dict[UUID, str]:
    """The names of the partners the window of documents names."""
    partner_ids = {
        partner_id
        for partner_id in (
            await db.scalars(
                select(Document.partner_id)
                .where(*conditions, Document.partner_id.is_not(None))
                .distinct()
            )
        ).all()
        if partner_id is not None
    }
    return await core_api.queries.get_partner_display_names_async(
        db, org_id, partner_ids
    )


async def _location_names_async(
    db: AsyncSession, org_id: UUID, conditions: list[Any]
) -> dict[UUID, str]:
    """The names of the shelves the window of documents moves between.

    Both foreign keys point at the same table, so their ids are asked in one
    read; the map is what lets a grouping or a row print the name without a
    join to Core's table.
    """
    source_ids = (
        select(Document.source_location_id)
        .where(*conditions, Document.source_location_id.is_not(None))
        .distinct()
    )
    target_ids = (
        select(Document.target_location_id)
        .where(*conditions, Document.target_location_id.is_not(None))
        .distinct()
    )
    location_ids = {
        location_id
        for location_id in (await db.scalars(source_ids.union(target_ids))).all()
        if location_id is not None
    }
    return await core_api.queries.get_storage_display_names_async(
        db, org_id, location_ids
    )


def _name_lookup(column: Any, names: dict[UUID, str]) -> ColumnElement[Any]:
    """A ``CASE`` naming each id, or ``NULL`` when the map is empty.

    The map is small — the ids of one register window — and it is what the
    grouping expression used to read from a joined Core table.
    """
    if not names:
        return null()
    return case(*[(column == name_id, name) for name_id, name in names.items()])


def _group_column(
    group_by: str,
    partner_names: dict[UUID, str],
    location_names: dict[UUID, str],
) -> ColumnElement[Any]:
    """The SQL expression a group's key and label both read from.

    The Python register used to group rows after fetching all of them; the
    expression moves that grouping into the database so the sums
    describe the whole window while the rows stay a page. ``partner`` reads
    the frozen snapshot first and falls back to the live partner — the same
    order ``_row`` uses for its column.
    """
    if group_by == 'month':
        return func.to_char(document_date_column(), 'YYYY-MM')
    if group_by == 'partner':
        return func.coalesce(
            Document.partner_snapshot['name'].as_string(),
            _name_lookup(Document.partner_id, partner_names),
        )
    if group_by == 'location':
        return func.coalesce(
            _name_lookup(Document.target_location_id, location_names),
            _name_lookup(Document.source_location_id, location_names),
        )
    # An ORM column IS a column element; mypy's plugin narrows the attribute
    # to its own type and cannot see that.
    return Document.type  # type: ignore[return-value]


def _fold_currency_totals(
    buckets: list[tuple[str | None, Decimal | None, Decimal | None, Decimal | None]],
) -> tuple[
    Decimal | None,
    Decimal | None,
    Decimal | None,
    str | None,
    list[RegisterCurrencyTotal],
]:
    """sums must never cross currencies — now over aggregated tuples.

    One tuple per (group, currency) arrives from the SQL ``GROUP BY``, so a
    grouped window carries one tuple per GROUP for the same currency — and
    the window summary answers per currency, not per group. Same-currency
    tuples therefore merge into one bucket here: three type groups of PLN
    used to leave three PLN entries in the summary, the React list above
    them keyed three children "PLN", and the window total read as three
    parallel amounts instead of one. A bucket with a currency counts even
    when it sums to nothing (two currencies make the scope multi-currency),
    while a bucket with neither a currency nor a figure is not a currency
    at all.
    """
    merged: dict[str | None, list[Decimal | None]] = {}
    for cur, net, tax, gross in buckets:
        if cur is None and net is None and tax is None and gross is None:
            continue
        slot = merged.setdefault(cur, [None, None, None])
        for index, value in enumerate((net, tax, gross)):
            if value is None:
                continue
            current = slot[index]
            slot[index] = value if current is None else current + value
    totals = [
        RegisterCurrencyTotal(
            currency=cur, total_net=net, total_tax=tax, total_gross=gross
        )
        for cur, (net, tax, gross) in sorted(
            merged.items(), key=lambda item: item[0] or ''
        )
    ]
    if len(totals) == 1:
        only = totals[0]
        return only.total_net, only.total_tax, only.total_gross, only.currency, totals
    return None, None, None, None, totals


async def get_register_summary_async(
    db: AsyncSession,
    org_id: UUID,
    date_from: date,
    date_to: date,
    doc_type: str | None,
    status_filter: str | None,
    partner_id: UUID | None,
    location_id: UUID | None,
    group_by: str,
) -> RegisterResponse:
    """Groups and totals over the whole window — no document rows.

        The register used to fetch every document in the window to sum it
    ; a year of a busy warehouse made the answer — and the DOM it
        fed — grow with the window. The sums still describe the whole window,
        but one tuple per (group, currency) is all that crosses the wire.
    """
    if group_by not in _VALID_GROUP_BY:
        group_by = 'type'

    conditions = _window_conditions(
        org_id, date_from, date_to, doc_type, status_filter, partner_id, location_id
    )
    partner_names = (
        await _partner_names_async(db, org_id, conditions)
        if group_by == 'partner'
        else {}
    )
    location_names = (
        await _location_names_async(db, org_id, conditions)
        if group_by == 'location'
        else {}
    )
    group_col = _group_column(group_by, partner_names, location_names)

    result = await db.execute(
        select(
            group_col.label('gkey'),
            Document.currency.label('currency'),
            func.count().label('doc_count'),
            func.sum(Document.total_net).label('net'),
            func.sum(Document.total_tax).label('tax'),
            func.sum(Document.total_gross).label('gross'),
        )
        .where(*conditions)
        .group_by(group_col, Document.currency)
    )
    agg_rows = result.all()

    buckets_by_key: dict[str, list[tuple[str | None, Any, Any, Any]]] = {}
    counts: dict[str, int] = {}
    labels: dict[str, str | None] = {}
    for row in agg_rows:
        # A NULL group (no partner / no location) keeps its anonymous key so
        # the frontend can name the absence; the label stays None.
        key = row.gkey if row.gkey is not None else _NO_VALUE_KEY
        labels[key] = row.gkey
        buckets_by_key.setdefault(key, []).append(
            (row.currency, row.net, row.tax, row.gross)
        )
        counts[key] = counts.get(key, 0) + row.doc_count

    groups: list[RegisterGroup] = []
    window_buckets: list[tuple[str | None, Any, Any, Any]] = []
    for key in sorted(buckets_by_key):
        buckets = buckets_by_key[key]
        net, tax, gross, currency, by_currency = _fold_currency_totals(buckets)
        groups.append(
            RegisterGroup(
                key=key,
                label=labels[key],
                document_count=counts[key],
                total_net=net,
                total_tax=tax,
                total_gross=gross,
                currency=currency,
                totals_by_currency=by_currency,
            )
        )
        window_buckets.extend(buckets)

    net, tax, gross, currency, by_currency = _fold_currency_totals(window_buckets)
    # Whether the register has anything to put in a carrier column at all.
    # Asked over the same window as the rows, so a column shown here is one
    # some row under it can fill.
    has_shipments = bool(
        await db.scalar(
            select(func.count())
            .select_from(DocumentShipment)
            .join(Document, Document.id == DocumentShipment.document_id)
            .where(DocumentShipment.organization_id == org_id, *conditions)
        )
    )
    scrap_documents = await db.scalar(
        select(func.count())
        .select_from(Document)
        .where(*conditions, Document.type == dt.SCRAP)
    )
    profile = await get_profile(db, org_id)
    documents_without_value = (
        await db.scalar(
            select(func.count())
            .select_from(Document)
            .where(
                *conditions,
                Document.total_net.is_(None),
                Document.type.in_(_VALUE_TYPES),
            )
        )
        if profile is not None and profile.value_tracking_enabled
        else 0
    )
    summary = RegisterSummary(
        total_documents=sum(counts.values()),
        total_net=net,
        total_tax=tax,
        total_gross=gross,
        currency=currency,
        totals_by_currency=by_currency,
        has_shipments=has_shipments,
        scrap_documents=scrap_documents or 0,
        documents_without_value=documents_without_value or 0,
    )

    return RegisterResponse(
        date_from=date_from,
        date_to=date_to,
        group_by=group_by,
        groups=groups,
        summary=summary,
    )


async def get_register_rows_async(
    db: AsyncSession,
    org_id: UUID,
    date_from: date,
    date_to: date,
    doc_type: str | None,
    status_filter: str | None,
    partner_id: UUID | None,
    location_id: UUID | None,
    group_by: str,
    group_key: str,
    offset: int,
    limit: int,
) -> PaginatedResponse[RegisterDocumentRow]:
    """One group's documents, one page at a time.

    Always inside a single group and always ordered the way the register
    reads (oldest first) — the sums above stay true for the whole window,
    this is only the page under them.
    """
    if group_by not in _VALID_GROUP_BY:
        group_by = 'type'

    conditions = _window_conditions(
        org_id, date_from, date_to, doc_type, status_filter, partner_id, location_id
    )
    partner_names = await _partner_names_async(db, org_id, conditions)
    location_names = await _location_names_async(db, org_id, conditions)
    group_col = _group_column(group_by, partner_names, location_names)
    if group_key == _NO_VALUE_KEY and group_by in ('partner', 'location'):
        conditions.append(group_col.is_(None))
    else:
        conditions.append(group_col == group_key)

    count_stmt = select(func.count()).select_from(Document).where(*conditions)
    total = await db.scalar(count_stmt)

    rows_stmt = (
        select(Document)
        .where(*conditions)
        # Oldest first by the date the register is about; the write time
        # breaks ties so a page boundary lands in the same place twice.
        .order_by(document_date_column().asc(), Document.created_at.asc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(rows_stmt)
    docs = list(result.scalars().all())
    await attach_shipments_async(db, org_id, docs)

    return PaginatedResponse[RegisterDocumentRow].from_slice(
        [_row(doc, partner_names, location_names) for doc in docs],
        offset=offset,
        limit=limit,
        total=total or 0,
    )


def _row(
    doc: Document,
    partner_names: dict[UUID, str],
    location_names: dict[UUID, str],
) -> RegisterDocumentRow:
    partner_name: str | None = None
    if doc.partner_snapshot and isinstance(doc.partner_snapshot, dict):
        partner_name = doc.partner_snapshot.get('name')
    if not partner_name and doc.partner_id:
        partner_name = partner_names.get(doc.partner_id)

    shipment = getattr(doc, 'shipment', None)

    return RegisterDocumentRow(
        id=doc.id,
        number=doc.number,
        type=doc.type,
        status=doc.status,
        # The date it is filed under, so the row cannot show one outside
        # the window that returned it.
        date=doc.scheduled_date or doc.created_at.date(),
        partner_name=partner_name,
        source_location_name=(
            location_names.get(doc.source_location_id)
            if doc.source_location_id
            else None
        ),
        target_location_name=(
            location_names.get(doc.target_location_id)
            if doc.target_location_id
            else None
        ),
        total_net=doc.total_net,
        total_tax=doc.total_tax,
        total_gross=doc.total_gross,
        currency=doc.currency,
        carrier=shipment.carrier if shipment is not None else None,
        tracking_number=shipment.tracking_number if shipment is not None else None,
        tracking_url=shipment.tracking_url if shipment is not None else None,
    )


async def get_register_csv(
    db: AsyncSession,
    org_id: UUID,
    date_from: date,
    date_to: date,
    doc_type: str | None,
    status_filter: str | None,
    partner_id: UUID | None,
    location_id: UUID | None,
) -> str:
    """The export stays the one way to get everything.

    It used to read the register's groups, so once the register started
    serving pages the export would have silently lost everything past page
    one. It queries its own rows, and no limit touches it.

    It reads only the columns it prints: a whole ``Document`` brings every
    line, product, partner and user through its relations, none of which the
    file shows. A reversed range is refused here and not on the screen's own
    reads, whose answers stay empty while somebody is typing the two dates.
    """
    if date_from > date_to:
        raise ServiceRejectionError('register_date_from_after_date_to')
    conditions = _window_conditions(
        org_id, date_from, date_to, doc_type, status_filter, partner_id, location_id
    )
    partner_names = await _partner_names_async(db, org_id, conditions)
    location_names = await _location_names_async(db, org_id, conditions)
    result = await db.execute(
        select(
            Document.number,
            Document.type,
            document_date_column().label('filed_on'),
            Document.partner_snapshot['name'].as_string().label('frozen_partner'),
            Document.partner_id,
            Document.source_location_id,
            Document.target_location_id,
            Document.total_net,
            Document.total_tax,
            Document.total_gross,
            Document.currency,
            Document.status,
        )
        .where(*conditions)
        .order_by(document_date_column().asc(), Document.created_at.asc())
    )

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            'Document Number',
            'Type',
            'Date',
            'Partner',
            'Source Location',
            'Target Location',
            'Net',
            'Tax',
            'Gross',
            'Currency',
            'Status',
        ]
    )
    for row in result:
        writer.writerow(
            [
                defuse(value)
                for value in (
                    row.number,
                    row.type,
                    row.filed_on.strftime('%Y-%m-%d'),
                    row.frozen_partner or partner_names.get(row.partner_id) or '',
                    location_names.get(row.source_location_id) or '',
                    location_names.get(row.target_location_id) or '',
                    str(row.total_net) if row.total_net is not None else '',
                    str(row.total_tax) if row.total_tax is not None else '',
                    str(row.total_gross) if row.total_gross is not None else '',
                    row.currency or '',
                    row.status,
                )
            ]
        )
    return buf.getvalue()

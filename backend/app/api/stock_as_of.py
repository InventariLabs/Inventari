"""GET /api/v1/stock-as-of — what the warehouse held on a given day.

An auditor, an accountant closing a quarter and an insurer after a fire all
ask this, and the application could only answer "what is on the shelf now".

It refuses rather than guesses. Before the oldest movement the ledger holds,
nothing is known — not zero — and a report that shows calm numbers for a year
nothing was recorded in is more dangerous than one that names the boundary.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta, tzinfo
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import (
    StockAsOfReportDTO,
    StockValueMovementDTO,
    SystemPermission,
    UserContextDTO,
)
from app.core.datetimes import format_date_for
from app.core.deps import (
    get_async_db,
    get_current_user_context,
    require_org,
    require_permission,
)
from app.core.exceptions import catalogue_refusal
from app.core.public_api import core_api
from app.core.work_in_progress import work_in_progress_value_async
from app.core.xlsx_export import to_xlsx_response
from app.i18n.service import get_current_lang
from app.services.analytics._common import (
    VALUE_FROM_LAYERS,
    get_org_currency_async,
    org_uses_valuation_layers_async,
)
from app.services.stock_as_of_service import (
    layer_movements_async,
    ledger_starts_at_async,
    report_async,
)

router = APIRouter()

#: Rows one printed report carries. WeasyPrint lays out about a hundred pages
#: (≈ 50 rows each) in seconds, but the time grows with every row and the
#: request waits for all of it: 94 000 rows took ten minutes, twice the
#: production worker's timeout. Past this the spreadsheet carries the report.
PDF_ROW_LIMIT = 5_000


def _resolve_instant(as_of: date | datetime, zone: tzinfo = UTC) -> datetime:
    """The instant a caller meant by what they typed.

    A bare date is the whole day on the organization's calendar (*zone*), so
    it resolves to the end of it there: the shelf on the 23rd is the shelf
    once the 23rd is over where the organization lives, not the one at
    midnight before the day's movements, and not the one at midnight UTC. A
    timestamp without an offset is read as UTC — the ledger is stored in UTC,
    and a naive value compared against it would end the request in a 500
    rather than an answer.
    """
    if isinstance(as_of, datetime):
        return as_of if as_of.tzinfo else as_of.replace(tzinfo=UTC)
    return datetime.combine(as_of, time.max, tzinfo=zone)


async def _build_report(
    db: AsyncSession,
    org_id: UUID,
    as_of: date | datetime,
    location_id: UUID | None,
    *,
    limit: int | None = None,
    offset: int = 0,
    search: str | None = None,
) -> tuple[StockAsOfReportDTO, Any]:
    """The report, or the refusal — shared by the screen, the sheet and the PDF.

    The screen asks for a page; the files ask for no ``limit`` and carry
    every row.
    """
    zone = await core_api.organizations.timezone_async(db, org_id)
    as_of = _resolve_instant(as_of, zone)
    starts_at = await ledger_starts_at_async(db, org_id)
    if starts_at is None:
        raise catalogue_refusal('stock_as_of_no_history')
    if as_of < starts_at:
        # The refusal is prose the reader reads, not a record to compare:
        # the screen prints its own footnote about the same boundary two
        # rows below, names the ledger the same way and formats the day
        # the reader's language way — so the dates go through
        # format_date_for, not isoformat (the wire field complete_from
        # below is the record, and stays canonical).
        lang = get_current_lang()
        organization = await core_api.organizations.get_async(db, org_id)
        country = organization.country if organization else None
        raise catalogue_refusal(
            'stock_as_of_before_ledger',
            starts_at=format_date_for(
                lang, starts_at.astimezone(zone), country=country
            ),
            as_of=format_date_for(lang, as_of.astimezone(zone), country=country),
        )

    org_currency = await get_org_currency_async(db, org_id)
    has_layers = await org_uses_valuation_layers_async(db, org_id)
    page = await report_async(
        db,
        org_id,
        as_of,
        location_id=location_id,
        org_currency=org_currency,
        has_layers=has_layers,
        limit=limit,
        offset=offset,
        search=search,
        zone=zone,
    )
    organization = await core_api.organizations.get_async(db, org_id)
    # What a started production run still holds is the organization's on that
    # date, though its ingredients already left the layers. It has no shelf, so
    # a report narrowed to one location does not include it.
    in_production = (
        await work_in_progress_value_async(db, org_id, as_of)
        if page.total_value is not None and location_id is None and not search
        else Decimal('0')
    )

    report = StockAsOfReportDTO(
        as_of=as_of,
        generated_at=datetime.now(UTC),
        complete_from=starts_at,
        organization_name=organization.name if organization else None,
        currency=org_currency,
        value_source=VALUE_FROM_LAYERS if page.total_value is not None else None,
        excluded_currency_rows=page.excluded,
        total_value=(
            page.total_value + in_production if page.total_value is not None else None
        ),
        work_in_progress_value=in_production if in_production else None,
        items=page.rows,
        total=page.total,
        limit=limit,
        offset=offset,
        has_more=limit is not None and offset + len(page.rows) < page.total,
        unpriced=page.unpriced,
    )
    return report, organization


async def _shows_inventory_value_async(db: AsyncSession, org_id: UUID) -> bool:
    """Whether this organization states what its stock is worth, in a file too.

    The switch is the stats module's ``show_inventory_value`` — the same one
    the inventory screens read — because a printout or an export is the
    screen in the reader's hands: where the profile withholds the figure,
    the file withholds it too. Core runs with no module identity, so naming
    a module's namespace is allowed, and an organization that never touched
    the switch keeps the value (the schema default).
    """
    return bool(
        await core_api.settings.get_async(
            db, org_id, 'stats', 'show_inventory_value', default=True
        )
    )


async def _place_named_async(
    db: AsyncSession, org_id: UUID, location_id: UUID | None
) -> str | None:
    """The place a report is narrowed to, as the way to it — None for the whole.

    The way, not the bare name: two shelves called "Top" in two aisles are
    two places, and a filed sheet has only its words to say which it was.
    """
    if location_id is None:
        return None
    from app.services.storage._queries import get_storage_async
    from app.services.storage_query_service import location_paths_async

    location = await get_storage_async(db, org_id, location_id)
    if location is None:
        return None
    return (await location_paths_async(db, org_id, [location]))[location.id]


@router.get('/stock-as-of', response_model=StockAsOfReportDTO)
async def stock_as_of(
    as_of: date | datetime = Query(
        ...,
        description=(
            'The instant the report is about, not when it is run. A bare '
            'date means the end of that day.'
        ),
    ),
    location_id: UUID | None = Query(
        None,
        description=(
            'This place and everything below it. Quantities only — the cost '
            'history is kept per product, not per shelf.'
        ),
    ),
    search: str | None = Query(
        None,
        description=(
            'Narrows the report to the products whose name, brand, barcode, '
            'catalogue number or batch contains this text. The total and the '
            'unpriced count then speak about those products only.'
        ),
    ),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _: object = require_permission(SystemPermission.ITEMS_READ),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    current_user: UserContextDTO = Depends(get_current_user_context),
) -> Any:
    """The shelves as they stood on a date, and what they were worth.

    One page of the rows, with the total value and the count of unpriced
    rows taken over all of them.
    """
    org_id = require_org(current_user)
    report, _organization = await _build_report(
        db, org_id, as_of, location_id, limit=limit, offset=offset, search=search
    )
    return report


@router.get('/stock-as-of/export/xlsx', response_model=None)
async def stock_as_of_xlsx(
    as_of: date | datetime = Query(...),
    location_id: UUID | None = Query(None),
    search: str | None = Query(
        None,
        description=(
            'Narrows the report to the products whose name, brand, barcode, '
            'catalogue number or batch contains this text. The total and the '
            'unpriced count then speak about those products only.'
        ),
    ),
    _: object = require_permission(SystemPermission.ITEMS_READ),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    current_user: UserContextDTO = Depends(get_current_user_context),
) -> Any:
    """The same report, as one spreadsheet."""
    from app.services.stock_report_pdf_service import rows_to_export_frame

    org_id = require_org(current_user)
    report, _organization = await _build_report(
        db, org_id, as_of, location_id, search=search
    )
    show_value = await _shows_inventory_value_async(db, org_id)
    return to_xlsx_response(
        rows_to_export_frame(report, show_value=show_value),
        sheet_name='Stock',
        filename_stem=f'inventari_stock_{report.as_of.date().isoformat()}',
    )


@router.get('/stock-as-of/export/pdf', response_model=None)
async def stock_as_of_pdf(
    as_of: date | datetime = Query(...),
    location_id: UUID | None = Query(None),
    search: str | None = Query(
        None,
        description=(
            'Narrows the report to the products whose name, brand, barcode, '
            'catalogue number or batch contains this text. The total and the '
            'unpriced count then speak about those products only.'
        ),
    ),
    _: object = require_permission(SystemPermission.ITEMS_READ),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    current_user: UserContextDTO = Depends(get_current_user_context),
) -> Any:
    """The sheet that goes into a binder.

    It carries the date it is about and the date it was made, because the
    confusion between those two is the whole reason an audit rejects a
    printout — and the place it was asked about, or a sheet for one shelf
    reads as the whole warehouse.
    """
    from fastapi.responses import Response

    from app.services.stock_report_pdf_service import generate_stock_as_of_pdf

    org_id = require_org(current_user)
    report, organization = await _build_report(
        db, org_id, as_of, location_id, limit=PDF_ROW_LIMIT, search=search
    )
    if report.has_more:
        # A printout that silently stops at row five thousand would be read
        # as the whole shelf; refusing names the count and the way out.
        raise catalogue_refusal(
            'stock_as_of_pdf_too_many', total=report.total, limit=PDF_ROW_LIMIT
        )
    show_value = await _shows_inventory_value_async(db, org_id)
    pdf = await generate_stock_as_of_pdf(
        report,
        organization,
        get_current_lang(),
        show_value=show_value,
        search=search,
        location=await _place_named_async(db, org_id, location_id),
    )
    filename = f'inventari_stock_{report.as_of.date().isoformat()}.pdf'
    return Response(
        content=pdf,
        media_type='application/pdf',
        headers={'Content-Disposition': f'attachment; filename={filename}'},
    )


async def _default_period_start(db: AsyncSession, org_id: UUID, date_to: date) -> date:
    """The first day a statement ending on *date_to* can honestly open on.

    The month *date_to* is in — unless the ledger began inside it, when the
    first day with a known evening before it: the day after the ledger's
    first movement, on the organization's calendar. An organization in its
    first month is shown a statement at once instead of a refusal to be
    argued with by hand. A ledger that begins on *date_to* itself, or later,
    leaves no such day; the refusal then names the ledger's first day and
    the day the first statement can open on, not an evening nobody asked
    about.
    """
    first = date_to.replace(day=1)
    starts_at = await ledger_starts_at_async(db, org_id)
    if starts_at is not None:
        zone = await core_api.organizations.timezone_async(db, org_id)
        started_on = starts_at.astimezone(zone)
        first = max(first, started_on.date() + timedelta(days=1))
        if first > date_to:
            lang = get_current_lang()
            organization = await core_api.organizations.get_async(db, org_id)
            country = organization.country if organization else None
            raise catalogue_refusal(
                'stock_value_first_day',
                starts_at=format_date_for(lang, started_on, country=country),
                first_day=format_date_for(
                    lang,
                    datetime.combine(first, time.min, tzinfo=zone),
                    country=country,
                ),
            )
    return first


async def _build_value_movement(
    db: AsyncSession, org_id: UUID, date_from: date | None, date_to: date
) -> StockValueMovementDTO:
    """The statement of a period: the value it opened with, what moved it,
    the value it closed with.

    The two ends are the stock-on-a-date report itself, asked for the evening
    before the first day and for the last — one source of truth, so the
    closing here is the figure that report gives for the same day. The
    movements are what the cost layers say between them; whatever the two
    ends differ by that the layers do not account for is said, not hidden,
    as ``other_changes``.
    """
    if date_from is None:
        date_from = await _default_period_start(db, org_id, date_to)
    if date_to < date_from:
        raise catalogue_refusal('stock_value_period_reversed')
    opening, _ = await _build_report(
        db, org_id, date_from - timedelta(days=1), None, limit=1
    )
    closing, organization = await _build_report(db, org_id, date_to, None, limit=1)

    base = {
        'date_from': date_from,
        'date_to': date_to,
        'generated_at': closing.generated_at,
        'complete_from': closing.complete_from,
        'organization_name': closing.organization_name,
        'currency': closing.currency,
    }
    if opening.total_value is None or closing.total_value is None:
        # No cost history: the two ends are quantities only, and a statement
        # of value over them would be a page of zeros nobody computed.
        return StockValueMovementDTO(**base)

    moved = await layer_movements_async(
        db,
        org_id,
        opening.as_of,
        closing.as_of,
        org_currency=closing.currency or '',
        zone=await core_api.organizations.timezone_async(db, org_id),
    )
    in_production = (closing.work_in_progress_value or Decimal('0')) - (
        opening.work_in_progress_value or Decimal('0')
    )
    listed = (
        moved.receipts
        + moved.internal_receipts
        + moved.used
        + moved.disposed
        + moved.dispatched
        + moved.other_issues
        + in_production
    )
    return StockValueMovementDTO(
        **base,
        value_source=closing.value_source,
        excluded_currency_receipts=moved.excluded,
        opening_value=opening.total_value,
        receipts=moved.receipts,
        internal_receipts=moved.internal_receipts,
        used=moved.used,
        disposed=moved.disposed,
        dispatched=moved.dispatched,
        other_issues=moved.other_issues,
        work_in_progress_change=in_production,
        other_changes=closing.total_value - opening.total_value - listed,
        closing_value=closing.total_value,
    )


@router.get('/stock-value-movement', response_model=StockValueMovementDTO)
async def stock_value_movement(
    date_from: date | None = Query(
        None,
        description=(
            'The first day of the period. Left out, it is the first day of '
            'the month of `date_to` — or the first day the ledger can open '
            'on, when it began inside that month.'
        ),
    ),
    date_to: date = Query(..., description='The last day of the period, included.'),
    _: object = require_permission(SystemPermission.ITEMS_READ),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    current_user: UserContextDTO = Depends(get_current_user_context),
) -> Any:
    """What the stock was worth at the start of a period, what moved it, and
    what it was worth at the end.

    Not a ledger: no chart of accounts, no double entry, no closing of
    periods. A statement over the cost layers, for a person or a bookkeeper
    to take from.
    """
    return await _build_value_movement(
        db, require_org(current_user), date_from, date_to
    )


#: The lines of the spreadsheet, in the order the statement reads them.
_MOVEMENT_LINES = (
    ('Opening value', 'opening_value'),
    ('Receipts', 'receipts'),
    ('Produced and returned to stock', 'internal_receipts'),
    ('Used', 'used'),
    ('Disposed', 'disposed'),
    ('Dispatched', 'dispatched'),
    ('Other issues', 'other_issues'),
    ('Work in progress change', 'work_in_progress_change'),
    ('Other changes', 'other_changes'),
    ('Closing value', 'closing_value'),
)


@router.get('/stock-value-movement/export/xlsx', response_model=None)
async def stock_value_movement_xlsx(
    date_from: date | None = Query(None),
    date_to: date = Query(...),
    _: object = require_permission(SystemPermission.ITEMS_READ),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    current_user: UserContextDTO = Depends(get_current_user_context),
) -> Any:
    """The same statement, as one spreadsheet."""
    import pandas as pd

    org_id = require_org(current_user)
    # The statement is nothing but value: where the profile withholds the
    # figure, a file of it would say what the screen does not.
    if not await _shows_inventory_value_async(db, org_id):
        raise catalogue_refusal('stock_value_hidden')
    statement = await _build_value_movement(db, org_id, date_from, date_to)
    frame = pd.DataFrame(
        [
            {
                'Line': label,
                'Value': (
                    float(value)
                    if (value := getattr(statement, field)) is not None
                    else None
                ),
            }
            for label, field in _MOVEMENT_LINES
        ],
        columns=['Line', 'Value'],
    )
    return to_xlsx_response(
        frame,
        sheet_name='Value movement',
        filename_stem=(
            f'inventari_value_movement_{statement.date_from.isoformat()}'
            f'_{date_to.isoformat()}'
        ),
    )

"""GET /api/v1/stock-as-of — what the warehouse held on a given day.

An auditor, an accountant closing a quarter and an insurer after a fire all
ask this, and the application could only answer "what is on the shelf now".

It refuses rather than guesses. Before the oldest movement the ledger holds,
nothing is known — not zero — and a report that shows calm numbers for a year
nothing was recorded in is more dangerous than one that names the boundary.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import StockAsOfReportDTO, SystemPermission, UserContextDTO
from app.core.datetimes import format_date_for
from app.core.deps import (
    get_async_db,
    get_current_user_context,
    require_org,
    require_permission,
)
from app.core.exceptions import catalogue_refusal
from app.core.public_api import core_api
from app.core.xlsx_export import to_xlsx_response
from app.i18n.service import get_current_lang
from app.services.analytics._common import (
    VALUE_FROM_LAYERS,
    get_org_currency_async,
    org_uses_valuation_layers_async,
)
from app.services.stock_as_of_service import ledger_starts_at_async, report_async

router = APIRouter()

#: Rows one printed report carries. WeasyPrint lays out about a hundred pages
#: (≈ 50 rows each) in seconds, but the time grows with every row and the
#: request waits for all of it: 94 000 rows took ten minutes, twice the
#: production worker's timeout. Past this the spreadsheet carries the report.
PDF_ROW_LIMIT = 5_000


def _resolve_instant(as_of: date | datetime) -> datetime:
    """The instant a caller meant by what they typed.

    A bare date is the whole day, so it resolves to the end of it: the shelf
    on the 23rd is the shelf once the 23rd is over, not the one at midnight
    before the day's movements. A timestamp without an offset is read as UTC
    — the ledger is stored in UTC, and comparing it against a naive value is
    what used to end the request in a 500 rather than an answer.
    """
    if isinstance(as_of, datetime):
        return as_of if as_of.tzinfo else as_of.replace(tzinfo=UTC)
    return datetime.combine(as_of, time.max, tzinfo=UTC)


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
    as_of = _resolve_instant(as_of)
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
            starts_at=format_date_for(lang, starts_at, country=country),
            as_of=format_date_for(lang, as_of, country=country),
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
    )
    organization = await core_api.organizations.get_async(db, org_id)

    report = StockAsOfReportDTO(
        as_of=as_of,
        generated_at=datetime.now(UTC),
        complete_from=starts_at,
        organization_name=organization.name if organization else None,
        currency=org_currency,
        value_source=VALUE_FROM_LAYERS if page.total_value is not None else None,
        excluded_currency_rows=page.excluded,
        total_value=page.total_value,
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
    printout.
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
    )
    filename = f'inventari_stock_{report.as_of.date().isoformat()}.pdf'
    return Response(
        content=pdf,
        media_type='application/pdf',
        headers={'Content-Disposition': f'attachment; filename={filename}'},
    )

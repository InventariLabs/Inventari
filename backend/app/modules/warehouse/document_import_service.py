from __future__ import annotations

from decimal import InvalidOperation
from typing import Any
from uuid import UUID

import pandas as pd
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db_utils import acquire_advisory_lock, get_org_owned_or_404_async
from app.core.exceptions import (
    ServiceRejectionError,
    is_reader_facing_value_error,
    refusal_row,
)
from app.core.file_import import PREVIEW_ROWS
from app.core.import_sheet import (
    PASTE_DELIMITERS,
    read_csv_sheet,
    read_rows,
    refuse_beyond_row_cap,
)
from app.core.logging import get_logger
from app.core.public_api import core_api
from app.core.uom_resolver import UomResolverAsync
from app.i18n.service import get_current_lang

from . import document_types as dt
from ._import_line_builder import _build_document_line, _extract_string
from .models import Document, DocumentLine

logger = get_logger(__name__)


def parse_pasted_text(text: str) -> pd.DataFrame:
    """Parse pasted clipboard text (Excel/Sheets) into a DataFrame.

    Reads through the core's tolerant CSV reader (delimiter picked from the
    header's shape, clipboard-first: tab, then semicolon, then comma — a
    paste from a spreadsheet is tabs, and the comma inside a header cell
    ("Name, full") is part of the name), skips blank lines, strips
    surrounding whitespace from each cell, and normalises NaN to None.
    Returns an empty DataFrame (no columns) when the input is blank. A
    paste past the row cap is refused with the same words the file upload
    refuses it.
    """
    if not text or not text.strip():
        return pd.DataFrame()

    normalised = text.replace('\r\n', '\n').replace('\r', '\n')
    lines = [line for line in normalised.split('\n') if line.strip()]
    if not lines:
        return pd.DataFrame()

    try:
        df = read_csv_sheet(
            '\n'.join(lines).encode('utf-8'), delimiters=PASTE_DELIMITERS
        )
    except (pd.errors.ParserError, ValueError, OSError) as e:
        logger.warning('Pasted text unreadable: %s', e)
        raise ServiceRejectionError('pasted_text_unreadable') from e

    df = df.where(pd.notnull(df), None)
    refuse_beyond_row_cap(len(df))
    str_cols = df.select_dtypes(include=['object']).columns
    for col in str_cols:
        df[col] = df[col].map(lambda v: v.strip() if isinstance(v, str) else v)
    return df


async def analyze_pasted_text(text: str) -> dict[str, Any]:
    """Analyse pasted text and return the same shape as :func:`analyze_import_file`.

    The frontend reuses the same preview UI for file uploads and pasted text,
    so the response contract (``headers`` / ``preview_rows`` / ``total_rows``)
    must match exactly.
    """
    df = parse_pasted_text(text)
    if df.empty:
        return {'headers': [], 'preview_rows': [], 'total_rows': 0}

    preview_df = df.head(PREVIEW_ROWS)
    return {
        'headers': [str(c) for c in df.columns],
        'preview_rows': preview_df.fillna('').to_dict(orient='records'),
        'total_rows': len(df),
    }


def _row_number(index: Any) -> int:
    """The row as the import preview numbers it: data rows from 1, no header.

    One numbering for the whole import screen — the preview the reader
    chooses the mapping on, and the refusals the result screen lists.
    """
    return int(index) + 1


async def _acquire_document_import_lock(db: AsyncSession, doc_id: UUID) -> None:
    """Hold a transaction-scoped advisory lock so concurrent imports serialize."""
    await acquire_advisory_lock(db, f'document_import:{doc_id}')


async def _load_draft_document_or_raise(
    db: AsyncSession, doc_id: UUID, org_id: UUID
) -> Document:
    """Fetch the document, or raise 404/400 when not found or not in DRAFT status."""
    lang = get_current_lang()
    doc = await get_org_owned_or_404_async(db, Document, doc_id, org_id, lang=lang)
    if doc.status != 'DRAFT':
        raise ServiceRejectionError('import_only_draft')
    return doc


def _text_or_none(value: Any) -> str | None:
    return str(value) if value is not None else None


def _build_import_response(
    imported: int,
    matched: int,
    unmatched: int,
    stubs_created: int,
    errors: list[dict[str, Any]],
    created_lines: list[DocumentLine],
    no_stock: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compose the response body for the import call.

    A line carries everything the line form holds, so the create form can
    take the lines of an import it read before any document existed.
    """
    return {
        'imported': imported,
        'matched': matched,
        'unmatched': unmatched,
        'stubs_created': stubs_created,
        'failed': len(errors),
        'errors': errors[:10],
        'no_stock': no_stock,
        'lines': [
            {
                'id': str(line.id),
                'name': line.name,
                'brand': line.brand,
                'barcode': line.barcode,
                'quantity': str(line.quantity),
                'product_template_id': _text_or_none(line.product_template_id),
                'item_id': _text_or_none(line.item_id),
                'uom_id': _text_or_none(line.uom_id),
                'unit_price': _text_or_none(line.unit_price),
                'tax_rate': _text_or_none(line.tax_rate),
                'batch_number': line.batch_number,
                'expiry_date': line.expiry_date,
            }
            for line in created_lines
        ],
    }


async def _name_the_stock_record(
    db: AsyncSession,
    org_id: UUID,
    line: DocumentLine,
    source_location_id: UUID | None,
) -> bool:
    """Give a line that takes goods off a shelf the record it will take from.

    Confirmation refuses a dispatch, issue, transfer or scrap line naming
    only a product, and import used to stop at the product — so a document
    built from a sheet never confirmed. The record is the first one the
    draw would take: on the document's source shelf (every shelf when it
    names none), in the product's removal strategy's order, among the stock
    nobody has reserved, whoever owns it — the scope the dispatch itself
    takes in. Returns False when there is nothing free to name.
    """
    if line.product_template_id is None:
        return False
    # A zone names the shelves under it as the place to draw from.
    below = (
        await core_api.locations.descendant_ids_async(db, org_id, source_location_id)
        if source_location_id is not None
        else []
    )
    among = (
        [source_location_id, *below]
        if source_location_id is not None and below
        else None
    )
    plan = await core_api.stock.plan_draw_async(
        db,
        org_id,
        line.product_template_id,
        None if among is not None else source_location_id,
        None,
        any_owner=True,
        by_record=True,
        among_shelves=among,
    )
    if not plan:
        return False
    line.item_id = plan[0].record_id
    return True


async def _maybe_create_stub_for_line(
    db: AsyncSession,
    org_id: UUID,
    line: DocumentLine,
    barcode: str | None,
    user_id: UUID | None = None,
    *,
    need_barcode: bool = True,
) -> bool:
    """If the line is unmatched, create a stub template via
    ``quick_create_stub_async`` and attach it. Returns True if a stub was
    created (line.product_template_id is now populated).

    With ``need_barcode`` a row without one stays unmatched — the option the
    document import offers is worded around barcodes. Opening stock turns it
    off: every row must end with a product, or posting the draft puts goods on
    the shelf that no movement and no cost layer has heard of.
    """
    if line.product_template_id is not None:
        return False
    # _build_document_line refuses rows whose name is missing, so a persisted
    # line.name should be a real string at runtime. Guard anyway to keep
    # mypy happy (line.name: Mapped[str | None]).
    if not line.name or (need_barcode and not barcode):
        return False
    from .product_stub_service import quick_create_stub_async

    template = await quick_create_stub_async(db, org_id, line.name, barcode, user_id)
    line.product_template_id = template.id
    # Populate snapshot from the freshly created stub so downstream renders
    # show the resolved product (rather than the bare free-text row).
    line.product_snapshot = {
        'name': template.name,
        'brand': template.brand,
        'barcode': template.barcode,
        'uom_id': str(template.uom_id) if template.uom_id else None,
        'uom_symbol': None,
        'image_url': template.image_url,
    }
    # Mirror what _resolve_template_for_barcode returned for matched rows so
    # totals/value calculations see consistent data.
    if template.uom_id and not line.uom_id:
        line.uom_id = template.uom_id
    return True


async def _lines_from_rows(
    db: AsyncSession,
    org_id: UUID,
    df: pd.DataFrame,
    column_mapping: dict[str, Any],
    *,
    doc_type: str,
    source_location_id: UUID | None,
    doc_id: UUID | None,
    first_line_number: int,
    create_stubs_for_unmatched: bool,
    stubs_need_barcode: bool = True,
    user_id: UUID | None,
) -> dict[str, Any]:
    """Build a line from every row and report what became of each.

    With *doc_id* the lines join that document's session; without one they
    are only read back, for a form that has no document yet.
    """
    uom_resolver = UomResolverAsync(db, org_id)
    needs_stock_row = dt.requires_stock_row(doc_type)
    imported = 0
    matched = 0
    unmatched = 0
    stubs_created = 0
    errors: list[dict[str, Any]] = []
    no_stock: list[dict[str, Any]] = []
    created_lines: list[DocumentLine] = []

    line_number = first_line_number
    for index, row in df.iterrows():
        try:
            barcode_value = _extract_string(row, column_mapping.get('barcode'))
            line, was_matched = await _build_document_line(
                db,
                org_id,
                doc_id,
                row,
                line_number,
                column_mapping,
                uom_resolver,
                allow_negative_quantity=dt.allows_negative_quantity(doc_type),
            )
            if doc_id is not None:
                db.add(line)
            created_lines.append(line)
            imported += 1
            if was_matched:
                matched += 1
            else:
                if create_stubs_for_unmatched and await _maybe_create_stub_for_line(
                    db,
                    org_id,
                    line,
                    barcode_value,
                    user_id,
                    need_barcode=stubs_need_barcode,
                ):
                    stubs_created += 1
                    matched += 1
                else:
                    unmatched += 1
            if needs_stock_row and not await _name_the_stock_record(
                db, org_id, line, source_location_id
            ):
                no_stock.append({'row': _row_number(index), 'name': line.name})
            line_number += 1
        except (ValueError, SQLAlchemyError, InvalidOperation) as e:
            # The number the reader just saw. The mapping step numbers the
            # rows of *data* from 1; this used to count the header as row 1,
            # so a refusal pointed at the row below the one it meant and the
            # reader looked at a row where nothing was wrong.
            if isinstance(e, ValueError) and is_reader_facing_value_error(e):
                # A refusal this codebase wrote, in the request's language.
                errors.append(refusal_row(e, row=_row_number(index)))
            else:
                # A library's text (SQL, a decimal's class name) is not the
                # reader's to see: the traceback goes to the log, the row gets
                # the generic sentence.
                logger.exception('Document import row %d failed', _row_number(index))
                errors.append(
                    refusal_row(
                        ServiceRejectionError('internal_error'),
                        row=_row_number(index),
                    )
                )

    if doc_id is not None:
        # Flush so the response carries the created lines' ids; the commit
        # belongs to the caller (AGENTS.md §3, "the caller commits, you flush").
        await db.flush()

    return _build_import_response(
        imported, matched, unmatched, stubs_created, errors, created_lines, no_stock
    )


async def import_lines_from_dataframe(
    db: AsyncSession,
    doc_id: UUID,
    df: pd.DataFrame,
    column_mapping: dict[str, Any],
    org_id: UUID,
    *,
    create_stubs_for_unmatched: bool = False,
    stubs_need_barcode: bool = True,
    user_id: UUID | None = None,
) -> dict[str, Any]:
    """Import lines from an already-parsed DataFrame into a DRAFT document.

    Shared by :func:`import_lines_from_file` (CSV/Excel upload) and
    :func:`import_lines_from_text` (clipboard paste). Acquires the
    per-document import lock, loads the draft, iterates rows building
    DocumentLines, and flushes — the caller owns the commit, so the lines
    compose with whatever else the caller is writing (the opening-stock
    import in particular is one unit of work, not this import plus a
    second transaction for whose value the draft waits).

    When ``create_stubs_for_unmatched`` is True, unmatched rows that carry a
    barcode auto-create a stub ProductTemplate via quick_create_stub_async
    and are imported as matched.
    """
    await _acquire_document_import_lock(db, doc_id)
    doc = await _load_draft_document_or_raise(db, doc_id, org_id)
    return await _lines_from_rows(
        db,
        org_id,
        df,
        column_mapping,
        doc_type=doc.type,
        source_location_id=doc.source_location_id,
        doc_id=doc_id,
        first_line_number=len(doc.lines) + 1,
        create_stubs_for_unmatched=create_stubs_for_unmatched,
        stubs_need_barcode=stubs_need_barcode,
        user_id=user_id,
    )


async def read_lines_for_new_document(
    db: AsyncSession,
    org_id: UUID,
    df: pd.DataFrame,
    column_mapping: dict[str, Any],
    *,
    doc_type: str,
    source_location_id: UUID | None,
    create_stubs_for_unmatched: bool = False,
    user_id: UUID | None = None,
) -> dict[str, Any]:
    """Read the rows into lines for a document still being written.

    The create form had no import at all: import wrote into a saved draft,
    and a draft cannot be saved without a line — so an order arriving as a
    spreadsheet was typed in by hand. The lines come back for the form to
    hold beside the ones typed; nothing is written but the stubs the caller
    asked for, and the document is saved the way any other is.

    A type that takes from a source shelf is refused without one: every
    record a line names stands on it.
    """
    if dt.requires_source(doc_type) and source_location_id is None:
        raise ServiceRejectionError('document_type_requires_source_location')
    return await _lines_from_rows(
        db,
        org_id,
        df,
        column_mapping,
        doc_type=doc_type,
        source_location_id=source_location_id,
        doc_id=None,
        first_line_number=1,
        create_stubs_for_unmatched=create_stubs_for_unmatched,
        user_id=user_id,
    )


async def import_lines_from_file(
    db: AsyncSession,
    doc_id: UUID,
    file_content: bytes,
    filename: str,
    column_mapping: dict[str, Any],
    org_id: UUID,
    *,
    create_stubs_for_unmatched: bool = False,
    user_id: UUID | None = None,
) -> dict[str, Any]:
    """Import lines from a CSV/Excel file into a DRAFT document."""
    df = read_rows(file_content, filename)
    return await import_lines_from_dataframe(
        db,
        doc_id,
        df,
        column_mapping,
        org_id,
        create_stubs_for_unmatched=create_stubs_for_unmatched,
        user_id=user_id,
    )


async def import_lines_from_text(
    db: AsyncSession,
    doc_id: UUID,
    text: str,
    column_mapping: dict[str, Any],
    org_id: UUID,
    *,
    create_stubs_for_unmatched: bool = False,
    user_id: UUID | None = None,
) -> dict[str, Any]:
    """Import lines from pasted clipboard text into a DRAFT document.

    Parses the text with :func:`parse_pasted_text` (auto-detected delimiter)
    and delegates to :func:`import_lines_from_dataframe`. Raises HTTPException
    (400) when the text is empty or unparseable.
    """
    df = parse_pasted_text(text)
    if df.empty:
        raise ServiceRejectionError('paste_empty')
    return await import_lines_from_dataframe(
        db,
        doc_id,
        df,
        column_mapping,
        org_id,
        create_stubs_for_unmatched=create_stubs_for_unmatched,
        user_id=user_id,
    )

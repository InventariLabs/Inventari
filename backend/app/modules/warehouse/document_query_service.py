import re
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import ColumnElement, false, func, literal_column, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, load_only, noload, selectinload

from app.core.contracts import DocumentFilterDTO
from app.core.db_utils import escape_ilike, in_ids, paginate_async
from app.core.public_api import core_api

from . import document_types as dt
from .document_register_service import document_date_column
from .models import Document, DocumentLine, DocumentRelation, DocumentStatus
from .schemas import (
    DocumentListLineSchema,
    DocumentListRowSchema,
    DocumentModuleLineSchema,
    DocumentSchema,
    DocumentUnitProgressSchema,
)
from .shipment_service import attach_shipments_async


def number_matches(term: str, document: Any = Document) -> ColumnElement[bool]:
    """Match *term* inside a document number.

    Plain substring matching answered ``OUT/2026/001`` with
    ``INTERNAL_OUT/2026/001`` as well: one number contains the other, and
    the two documents are not the same type. A term that begins with a
    letter therefore may not sit inside a word — it must begin the number
    or follow a digit or separator. A term that begins with a digit or a
    separator (``14``, ``/001``, ``26/001``) cannot be mistaken for a type
    code, so it keeps matching anywhere, which is how a number without
    separators is still found.

    *document* is the table the number is read from, or an alias of it.
    """
    stripped = term.strip()
    escaped = re.escape(stripped)
    number: ColumnElement[str] = document.number
    if stripped[:1].isalpha():
        return number.op('~*')(f'(^|[^A-Za-z_]){escaped}')
    return number.op('~*')(escaped)


#: The columns a caller may order the register by. A dict, not getattr: the
#: router's `sort_by` regex is what kept an arbitrary attribute name off the
#: ORDER BY, and a service is not entitled to assume its caller validated the
#: argument — the next caller may not be a route at all. `document_date` is
#: handled separately, because it sorts by a second column as well.
_SORTABLE_COLUMNS = {
    'number': Document.number,
    'created_at': Document.created_at,
    'completed_at': Document.completed_at,
    'type': Document.type,
    'status': Document.status,
}


def document_row(document: Document) -> DocumentSchema:
    """One list row, naming the shelves the document goes between.

    ``source_location_name``/``target_location_name`` are plain strings on
    the schema, while the document stores relations — ``model_validate``
    alone therefore leaves both ``None``, and the row's location line never
    appeared. Both relations are eager-loaded by ``list_documents`` (and by
    the approvals queue), so reading them costs no query.
    """
    row = DocumentSchema.model_validate(document)
    row.source_location_name = (
        document.source_location.name if document.source_location else None
    )
    row.target_location_name = (
        document.target_location.name if document.target_location else None
    )
    return row


#: The lines a list row names by product: the one line of a one-line
#: document, the first names of a longer one.
_FIRST_LINES = 2

#: What a list row reads off its lines, and nothing more: the product, the
#: unit and the quantities for the summary, the module fields (and the batch
#: beside them) for a module's column. The line's own relations (its record, its product,
#: its shelves) are not loaded — a list does not name them.
_LIST_LINE_COLUMNS = (
    DocumentLine.id,
    DocumentLine.document_id,
    DocumentLine.line_number,
    DocumentLine.name,
    DocumentLine.quantity,
    DocumentLine.expected_quantity,
    DocumentLine.done_quantity,
    DocumentLine.uom_id,
    DocumentLine.batch_number,
    DocumentLine.meta_data,
)


def document_list_row(document: Document) -> DocumentListRowSchema:
    """One row of the documents list: the document, its lines summed.

    The unit groups keep the order the lines first name them in, as the
    detail screen lists the lines.
    """
    lines = document.lines
    progress: dict[str | None, DocumentUnitProgressSchema] = {}
    for line in lines:
        # The screen's own grouping: a blank symbol is no unit.
        unit = (line.uom.symbol or '').strip() or None if line.uom else None
        group = progress.setdefault(
            unit,
            DocumentUnitProgressSchema(unit=unit, planned=Decimal(0), done=Decimal(0)),
        )
        group.planned += line.expected_quantity
        group.done += line.done_quantity or Decimal(0)
    return DocumentListRowSchema.model_validate(
        {
            **{
                field: getattr(document, field)
                for field in DocumentListRowSchema.model_fields
                if hasattr(document, field)
            },
            'source_location_name': (
                document.source_location.name if document.source_location else None
            ),
            'target_location_name': (
                document.target_location.name if document.target_location else None
            ),
            'line_count': len(lines),
            'unit_progress': list(progress.values()),
            'first_lines': [
                DocumentListLineSchema.model_validate(line)
                for line in lines[:_FIRST_LINES]
            ],
            'module_lines': [
                DocumentModuleLineSchema.model_validate(line)
                for line in lines
                if line.meta_data
            ],
        }
    )


async def _attach_corrected_types(
    db: AsyncSession, org_id: UUID, documents: Sequence[Document]
) -> None:
    """Name the original's type on each correction of a list page.

    A column read and not the relation: ``Document`` eagerly loads its lines
    and people, which is a page's worth of work for one word on each row.
    """
    original_ids = {
        doc.corrects_document_id for doc in documents if doc.corrects_document_id
    }
    if not original_ids:
        return
    result = await db.execute(
        select(Document.id, Document.type).where(
            Document.id.in_(original_ids), Document.organization_id == org_id
        )
    )
    types = {row.id: row.type for row in result}
    for doc in documents:
        if doc.corrects_document_id:
            doc.corrects_document_type = types.get(doc.corrects_document_id)  # type: ignore[attr-defined]


async def get_document(
    db: AsyncSession,
    org_id: UUID,
    doc_id: UUID,
) -> Document | None:
    result = await db.execute(
        select(Document)
        .options(
            selectinload(Document.lines),
            # The PDF renderer reads both pointers inside its worker thread,
            # where a lazy load is a ``MissingGreenlet`` rather than a query:
            # a correction prints ``corrected_document`` and a backorder
            # prints ``backorder_of``.
            selectinload(Document.corrected_document),
            selectinload(Document.backorder_of),
        )
        .where(Document.id == doc_id, Document.organization_id == org_id)
    )
    doc = result.scalars().first()
    if doc is not None:
        await _attach_generated_backorder(db, doc)
        await _attach_return_of(db, doc)
        await _attach_reversed_by(db, doc)
        # The original's type comes from the relation loaded above; the
        # screen reads it to tell which way a correction's signed delta
        # moved stock (see ``DocumentSchema.corrects_document_type``).
        corrected = doc.corrected_document
        if corrected is not None:
            doc.corrects_document_type = corrected.type  # type: ignore[attr-defined]
        await attach_shipments_async(db, org_id, [doc])
    return doc


async def _attach_generated_backorder(db: AsyncSession, doc: Document) -> None:
    """Populate transient ``generated_backorder_*`` fields.

    The child backorder points at this document via ``backorder_id``; expose
    the reverse pointer so the UI can banner-link from the original document.
    """
    result = await db.execute(
        select(Document.id, Document.number)
        .where(
            Document.backorder_id == doc.id,
            Document.status != DocumentStatus.CANCELLED.value,
        )
        .order_by(Document.created_at.desc())
        .limit(1)
    )
    row = result.first()
    if row is not None:
        doc.generated_backorder_id = row.id  # type: ignore[attr-defined]
        doc.generated_backorder_number = row.number  # type: ignore[attr-defined]


async def _attach_return_of(db: AsyncSession, doc: Document) -> None:
    """Populate transient ``return_of_*`` fields.

    A return stores no note sentence naming the document it reverses — one
    written at creation time reaches every reader in that one language. The
    ``returns`` relation it stores is the pointer; expose it beside the
    document so the screen and the printout can name the original in the
    reader's own language.
    """
    result = await db.execute(
        select(Document.id, Document.number)
        .join(
            DocumentRelation,
            DocumentRelation.source_document_id == Document.id,
        )
        .where(
            DocumentRelation.target_document_id == doc.id,
            DocumentRelation.relation_type == 'returns',
        )
        .limit(1)
    )
    row = result.first()
    if row is not None:
        doc.return_of_id = row.id  # type: ignore[attr-defined]
        doc.return_of_number = row.number  # type: ignore[attr-defined]


async def _attach_reversed_by(db: AsyncSession, doc: Document) -> None:
    """Populate transient ``reversed_by_*`` fields.

    "Undo" writes a correction and stores a ``reverses`` relation beside the
    ``corrects`` one; the original's screen names that correction from it, in
    the reader's own language. Only a completed reversal counts — one waiting
    for an approval has not moved the stock yet.
    """
    result = await db.execute(
        select(Document.id, Document.number)
        .join(
            DocumentRelation,
            DocumentRelation.source_document_id == Document.id,
        )
        .where(
            DocumentRelation.target_document_id == doc.id,
            DocumentRelation.relation_type == 'reverses',
            Document.status == DocumentStatus.COMPLETED.value,
        )
        .order_by(Document.created_at.desc())
        .limit(1)
    )
    row = result.first()
    if row is not None:
        doc.reversed_by_id = row.id  # type: ignore[attr-defined]
        doc.reversed_by_number = row.number  # type: ignore[attr-defined]


async def get_document_by_number(
    db: AsyncSession,
    org_id: UUID,
    number: str,
) -> Document | None:
    """Read a document by its printed number — the same shape as by id.

    The number only names the row; ``get_document`` does the reading, so the
    backorder, return-of and corrected-type fields cannot drift between the
    two reads.
    """
    result = await db.execute(
        select(Document.id).where(
            Document.number == number, Document.organization_id == org_id
        )
    )
    doc_id = result.scalars().first()
    if doc_id is None:
        return None
    return await get_document(db, org_id, doc_id)


def _module_filter_conditions(
    module_filters: list[tuple[str, DocumentFilterDTO]],
) -> list[ColumnElement[bool]]:
    """What the modules' filters narrow the list to.

    A filter that answers no fragment matches nothing on this organization's
    documents, which is an answer, not a filter to drop. Each fragment is
    wrapped in the module's own name: a filter reads the fields of the module
    that registered it and no other's.
    """
    conditions: list[ColumnElement[bool]] = []
    for module, answer in module_filters:
        if not answer.line_meta_data:
            conditions.append(false())
            continue
        conditions.append(
            Document.id.in_(
                select(DocumentLine.document_id).where(
                    or_(
                        *(
                            DocumentLine.meta_data.contains({module: fragment})
                            for fragment in answer.line_meta_data
                        )
                    )
                )
            )
        )
    return conditions


def _line_loading(lines: Literal['all', 'rows', 'none']) -> Any:
    """How much of each line ``list_documents`` loads (see its ``lines``)."""
    if lines == 'none':
        return noload(Document.lines)
    loading = selectinload(Document.lines)
    if lines == 'rows':
        loading = loading.options(
            load_only(*_LIST_LINE_COLUMNS),
            noload(DocumentLine.item),
            noload(DocumentLine.product_template),
            noload(DocumentLine.executed_location),
            noload(DocumentLine.source_location),
        )
    return loading


def not_undone_conditions() -> list[ColumnElement[bool]]:
    """What "Undo" reversed and the reversal it wrote are both left out.

    The ``reverses`` relation says which; only a completed reversal has moved
    the stock back, so a document whose reversal still waits is not undone.
    """
    reversal = aliased(Document)
    undone = (
        select(DocumentRelation.target_document_id)
        .join(reversal, reversal.id == DocumentRelation.source_document_id)
        .where(
            DocumentRelation.relation_type == 'reverses',
            reversal.status == DocumentStatus.COMPLETED.value,
        )
    )
    reversals = select(DocumentRelation.source_document_id).where(
        DocumentRelation.relation_type == 'reverses'
    )
    return [Document.id.not_in(undone), Document.id.not_in(reversals)]


async def list_documents(
    db: AsyncSession,
    org_id: UUID,
    *,
    search: str | None = None,
    doc_type: str | None = None,
    status: str | None = None,
    discrepancy_code: str | None = None,
    partner_id: UUID | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    completed_from: datetime | None = None,
    completed_to: datetime | None = None,
    location_ids: list[UUID] | None = None,
    target_ids: list[UUID] | None = None,
    module_filters: list[tuple[str, DocumentFilterDTO]] | None = None,
    backorder_only: bool = False,
    extra_conditions: Sequence[ColumnElement[bool]] = (),
    limit: int = 50,
    offset: int = 0,
    sort_by: str = 'document_date',
    sort_order: str = 'desc',
    lines: Literal['all', 'rows', 'none'] = 'all',
) -> tuple[list[Document], int]:
    """A page of documents, filtered and ordered as asked.

    ``lines`` is how much of the lines comes with them: ``all`` of each
    line; ``rows``, only what ``document_list_row`` and the work stage read;
    ``none`` for a caller that counts them itself. A page of fifty documents
    loaded with every line's record, product and shelves spent most of its
    time building objects the list never printed.
    """
    conditions = [Document.organization_id == org_id]

    if target_ids is not None:
        if not target_ids:
            # Short-circuit: caller filtered to an empty set.
            return [], 0
        conditions.append(Document.id.in_(target_ids))

    conditions += _module_filter_conditions(module_filters or [])

    if search:
        pattern = f'%{escape_ilike(search.strip())}%'
        # Who the document is with. It is on every row of the list and it is
        # half of what a person remembers about a document — the other half
        # being when — so it was the one thing the search would not accept.
        # Two clauses because a document names its partner twice: the frozen
        # snapshot is what the row prints, and a draft has none yet, so its
        # partner is found through the live record. The ids come from Core in
        # one read rather than from a join on Core's table.
        partner_ids = await core_api.partners.ids_named_like_async(
            db, org_id, search.strip()
        )
        #
        # Asked as a set of document ids, one branch for the document's own
        # fields and one for its lines, each answered by its trigram indexes
        # (``doc_list_reads01``). As one ``OR`` over the
        # row, no index could answer it and every search read every document
        # and every line of the organization, twice: once for the page and
        # once for its count.
        matched = aliased(Document)
        by_document = select(matched.id).where(
            matched.organization_id == org_id,
            or_(
                number_matches(search, matched),
                matched.external_reference.ilike(pattern),
                matched.notes.ilike(pattern),
                # The key is written into the statement, not bound, so the
                # expression is the one the index is built on.
                matched.partner_snapshot.op('->>')(literal_column("'name'")).ilike(
                    pattern
                ),
                matched.partner_id.in_(partner_ids),
            ),
        )
        # What moved: the other half of what a person remembers. A set of
        # ids, so a document with two matching lines is one row, not two.
        by_line = select(DocumentLine.document_id).where(
            or_(
                DocumentLine.name.ilike(pattern),
                DocumentLine.brand.ilike(pattern),
            )
        )
        conditions.append(Document.id.in_(by_document.union(by_line)))

    if doc_type:
        # The stored types are canonical; a caller still filtering with the
        # legacy Polish codes (PZ/WZ/MM) used to get an empty list rather than
        # their receipts. Several list filters — and the API docs —
        # promised those codes for years.
        # Several types may be asked at once, comma-separated: a work queue
        # of receipts and dispatches is one list, one order and one count.
        conditions.append(
            Document.type.in_(
                [dt.normalize(t.strip()) for t in doc_type.split(',') if t.strip()]
            )
        )
    if status:
        # Several statuses may be asked at once, comma-separated, like types:
        # drafts and planned work are one list.
        conditions.append(
            Document.status.in_(
                [s.strip().upper() for s in status.split(',') if s.strip()]
            )
        )
    if discrepancy_code:
        line_match_subquery = select(DocumentLine.document_id).where(
            DocumentLine.discrepancy_code == discrepancy_code.upper()
        )
        conditions.append(Document.id.in_(line_match_subquery))
    if partner_id:
        conditions.append(Document.partner_id == partner_id)
    if completed_from is not None:
        conditions.append(Document.completed_at >= completed_from)
    if completed_to is not None:
        conditions.append(Document.completed_at <= completed_to)
    if location_ids is not None:
        # A document names the place its goods came from or went to; a
        # warehouse is that place or one of the shelves below it, and either
        # side of the document may stand there.
        conditions.append(
            or_(
                in_ids(Document.source_location_id, location_ids),
                in_ids(Document.target_location_id, location_ids),
            )
        )
    conditions += extra_conditions
    if backorder_only:
        # The drafts the application raises on a short completion, told
        # apart from the drafts a person typed. A backorder stores the
        # document it continues in ``backorder_id``; an ordinary draft has
        # none.
        conditions.append(Document.backorder_id.is_not(None))
    # The date the document is for, the same one the register, the period
    # guard and the cost layers read. The list used ``created_at`` — the
    # moment somebody typed the document in — so one range asked of the list
    # and of the register named two different sets of documents.
    document_date = document_date_column()
    if date_from:
        conditions.append(document_date >= date_from)
    if date_to:
        conditions.append(document_date <= date_to)

    if sort_by == 'document_date':
        sort_cols = [document_date, Document.created_at]
    else:
        sort_cols = [_SORTABLE_COLUMNS.get(sort_by, Document.created_at)]
    order = [col.asc() if sort_order == 'asc' else col.desc() for col in sort_cols]

    stmt = (
        select(Document)
        .options(
            _line_loading(lines),
            selectinload(Document.source_location),
            selectinload(Document.target_location),
        )
        .where(*conditions)
        .order_by(*order)
    )
    documents, total = await paginate_async(db, stmt, limit=limit, offset=offset)
    await attach_shipments_async(db, org_id, documents)
    await _attach_corrected_types(db, org_id, documents)
    return documents, total


class LastPurchasePrice:
    """Last priced purchase for one template (price hint)."""

    def __init__(self, unit_price: Decimal, currency: str | None) -> None:
        self.unit_price = unit_price
        self.currency = currency


async def get_last_purchase_price_async(
    db: AsyncSession,
    org_id: UUID,
    template_id: UUID,
) -> LastPurchasePrice | None:
    """Most recent priced purchase of *template_id* in this organization.

    Fallback in the price-hint chain when the partner has no pricelist
    entry. Only CONFIRMED/COMPLETED documents count — drafts must not
    leak placeholder prices. A line names its product through its own
    template or, when the scanner built it, through its stock record alone —
    both feed the hint.
    """
    # The module reads the record's template through the relation, not the
    # Item model: it is core's table and the module never imports it.
    item = aliased(DocumentLine.item.property.mapper.class_)
    stmt = (
        select(DocumentLine.unit_price, Document.currency)
        .join(Document, Document.id == DocumentLine.document_id)
        .outerjoin(item, item.id == DocumentLine.item_id)
        .where(
            Document.organization_id == org_id,
            func.coalesce(DocumentLine.product_template_id, item.template_id)
            == template_id,
            DocumentLine.unit_price.is_not(None),
            Document.status.in_(
                [DocumentStatus.CONFIRMED.value, DocumentStatus.COMPLETED.value]
            ),
        )
        .order_by(Document.created_at.desc())
        .limit(1)
    )
    row = (await db.execute(stmt)).first()
    if row is None:
        return None
    return LastPurchasePrice(unit_price=row[0], currency=row[1])

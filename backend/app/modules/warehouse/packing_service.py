"""Packing a picked dispatch: packages, what each holds, and the one rule.

The rule is that a package holds only goods that were picked and are not in
another package yet — the picked quantity is the line's ``done_quantity``,
which the picking session writes as the goods come off the shelf. Packing is
optional: a dispatch with no packages completes exactly as it did before
packages existed. It is also open only while the dispatch is CONFIRMED; once
the dispatch is completed its packages say what was shipped, and a record of
what was shipped does not change afterwards.

Every write takes the document's row first (``_get_doc_for_update``), the
same door the status transitions use, so packing and completing one dispatch
serialize instead of each deciding on a state the other is replacing.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.contracts import AuditAction, AuditTargetType
from app.core.exceptions import EntityNotFoundError, ServiceRejectionError
from app.core.public_api import core_api

from . import document_types as dt
from ._wms_line_utils import _line_matches_scan
from .models import (
    Document,
    DocumentLine,
    DocumentPackage,
    DocumentPackageLine,
    DocumentStatus,
)
from .packing_schemas import PackageLineOut, PackageOut, PackingLineOut, PackingView

_ZERO = Decimal('0')


def package_code(document_number: str, package_number: int) -> str:
    """The code a package is known by on its slip and its label."""
    return f'{document_number}-P{package_number}'


def _quantity_text(value: Decimal) -> str:
    """``3`` rather than ``3.000`` in a sentence a person reads."""
    return format(value.normalize(), 'f')


def is_editable(doc: Document) -> bool:
    return dt.is_dispatch(doc.type) and doc.status == DocumentStatus.CONFIRMED.value


def _assert_packable(doc: Document) -> None:
    if not dt.is_dispatch(doc.type):
        raise ServiceRejectionError('packing_not_a_dispatch')
    if doc.status != DocumentStatus.CONFIRMED.value:
        raise ServiceRejectionError('packing_document_not_open')


async def _locked_document_async(
    db: AsyncSession, org_id: UUID, doc_id: UUID
) -> Document:
    # The row lock serializes packing with completion; see the module docstring.
    doc = await db.scalar(
        select(Document)
        .where(Document.id == doc_id, Document.organization_id == org_id)
        .with_for_update()
    )
    if doc is None:
        raise EntityNotFoundError('document')
    await db.refresh(doc, attribute_names=['lines'])
    return doc


async def get_document_async(db: AsyncSession, org_id: UUID, doc_id: UUID) -> Document:
    doc = await db.scalar(
        select(Document).where(
            Document.id == doc_id, Document.organization_id == org_id
        )
    )
    if doc is None:
        raise EntityNotFoundError('document')
    return doc


async def list_packages_async(
    db: AsyncSession, org_id: UUID, doc_id: UUID
) -> list[DocumentPackage]:
    rows = await db.scalars(
        select(DocumentPackage)
        .options(selectinload(DocumentPackage.lines))
        .where(
            DocumentPackage.organization_id == org_id,
            DocumentPackage.document_id == doc_id,
        )
        .order_by(DocumentPackage.number)
        .execution_options(populate_existing=True)
    )
    return list(rows.all())


async def _package_async(
    db: AsyncSession, doc: Document, package_id: UUID
) -> DocumentPackage:
    package = await db.scalar(
        select(DocumentPackage)
        .options(selectinload(DocumentPackage.lines))
        .where(
            DocumentPackage.id == package_id,
            DocumentPackage.organization_id == doc.organization_id,
            DocumentPackage.document_id == doc.id,
        )
    )
    if package is None:
        raise EntityNotFoundError('package')
    return package


def packed_by_line(packages: list[DocumentPackage]) -> dict[UUID, Decimal]:
    packed: dict[UUID, Decimal] = defaultdict(lambda: _ZERO)
    for package in packages:
        for line in package.lines:
            packed[line.document_line_id] += line.quantity
    return packed


def _picked(line: DocumentLine) -> Decimal:
    return line.done_quantity or _ZERO


async def assert_packed_within_done_async(db: AsyncSession, doc: Document) -> None:
    """Refuse to complete a dispatch whose packages hold more than it shipped.

    Completion may settle on fewer goods than were picked — a count came out
    short — and the packages, which are what the slip, the labels and the
    shipment's package count describe, would then say more left than did.
    """
    packed = packed_by_line(await list_packages_async(db, doc.organization_id, doc.id))
    for line in doc.lines:
        held = packed.get(line.id, _ZERO)
        done = line.done_quantity or _ZERO
        # Only a line with goods in a package is bound: a correction's signed
        # delta is below zero without ever having been packed.
        if held > 0 and held > done:
            raise ServiceRejectionError(
                'packing_exceeds_done',
                name=line.name or '',
                packed=_quantity_text(held),
                done=_quantity_text(done),
            )


async def _packed_quantity_async(db: AsyncSession, line: DocumentLine) -> Decimal:
    """What the packages hold of *line*, across every package of its document."""
    packed = await db.scalar(
        select(func.sum(DocumentPackageLine.quantity)).where(
            DocumentPackageLine.document_line_id == line.id
        )
    )
    return packed or _ZERO


async def assert_pick_not_packed_async(
    db: AsyncSession,
    line: DocumentLine | None,
    *,
    refusal: str = 'wms_undo_line_is_packed',
) -> None:
    """Refuse a door that would take a line's picked goods back to zero.

    A package may already hold them. Undo, skip and the session's cancel all
    lower ``done_quantity`` to zero, and each names its own sentence — the
    goods come out of the package first, whichever door the reader is
    standing at — so the caller hands the refusal its door's key. A session
    line whose document line is gone stands behind no package, so nothing
    holds the door shut for it.
    """
    if line is None:
        return
    packed = await _packed_quantity_async(db, line)
    if packed:
        raise ServiceRejectionError(
            refusal,
            name=line.name or '',
            packed=_quantity_text(packed),
        )


async def assert_packed_within_quantity_async(
    db: AsyncSession, line: DocumentLine | None, quantity: Decimal
) -> None:
    """Refuse a count that would settle the line below what its packages hold.

    The same rule ``assert_packed_within_done_async`` holds at completion,
    asked at the door the reader is standing at: a short-confirm that ships
    fewer goods than a box already holds is refused here, not left to
    completion to discover. A count the packages fit passes, and a line
    whose document line is gone stands behind no package.
    """
    if line is None:
        return
    packed = await _packed_quantity_async(db, line)
    if packed > quantity:
        raise ServiceRejectionError(
            'packing_exceeds_done',
            name=line.name or '',
            packed=_quantity_text(packed),
            done=_quantity_text(quantity),
        )


async def _next_number_async(db: AsyncSession, doc: Document) -> int:
    # The highest number standing, plus one; the document row is locked while
    # it is taken, so two packers cannot both take the same one.
    highest = await db.scalar(
        select(func.max(DocumentPackage.number)).where(
            DocumentPackage.document_id == doc.id
        )
    )
    return int(highest or 0) + 1


async def _log_async(
    db: AsyncSession,
    doc: Document,
    user_id: UUID | None,
    action: AuditAction,
    snapshot: dict[str, Any],
) -> None:
    # The package is the document's content, so its journal entry sits on the
    # document — next to the confirmation and the completion it falls between.
    await core_api.audit_log.log_action_async(
        db,
        organization_id=doc.organization_id,
        user_id=user_id,
        action=action,
        target_type=AuditTargetType.DOCUMENT,
        target_id=doc.id,
        snapshot={'number': doc.number, **snapshot},
    )


async def create_package_async(
    db: AsyncSession,
    org_id: UUID,
    doc_id: UUID,
    user_id: UUID | None,
    *,
    weight_kg: Decimal | None = None,
) -> DocumentPackage:
    doc = await _locked_document_async(db, org_id, doc_id)
    _assert_packable(doc)
    package = DocumentPackage(
        organization_id=org_id,
        document_id=doc.id,
        number=await _next_number_async(db, doc),
        weight_kg=weight_kg,
        created_by=user_id,
    )
    db.add(package)
    await db.flush()
    await _log_async(
        db,
        doc,
        user_id,
        AuditAction.CREATE,
        {
            'code': package_code(doc.number, package.number),
            'weight_value': _quantity_text(weight_kg)
            if weight_kg is not None
            else None,
        },
    )
    return package


async def update_package_async(
    db: AsyncSession,
    org_id: UUID,
    doc_id: UUID,
    package_id: UUID,
    user_id: UUID | None,
    changes: dict[str, Any],
) -> DocumentPackage:
    """Apply *changes* — the keys the request named, and only those."""
    doc = await _locked_document_async(db, org_id, doc_id)
    _assert_packable(doc)
    package = await _package_async(db, doc, package_id)
    if 'weight_kg' in changes and changes['weight_kg'] != package.weight_kg:
        package.weight_kg = changes['weight_kg']
        await db.flush()
        await _log_async(
            db,
            doc,
            user_id,
            AuditAction.UPDATE,
            {
                'code': package_code(doc.number, package.number),
                'weight_value': (
                    _quantity_text(package.weight_kg)
                    if package.weight_kg is not None
                    else None
                ),
            },
        )
    return package


async def set_line_async(
    db: AsyncSession,
    org_id: UUID,
    doc_id: UUID,
    package_id: UUID,
    document_line_id: UUID,
    quantity: Decimal,
    user_id: UUID | None,
) -> DocumentPackage:
    """Make the package hold *quantity* of the line; zero takes it out.

    The bound is what was picked of the line less what the other packages
    already hold — the same goods cannot be in two boxes, and goods still on
    the shelf are in none.
    """
    doc = await _locked_document_async(db, org_id, doc_id)
    _assert_packable(doc)
    doc_line = next((ln for ln in doc.lines if ln.id == document_line_id), None)
    if doc_line is None:
        raise EntityNotFoundError('document_line')
    package = await _package_async(db, doc, package_id)

    packages = await list_packages_async(db, org_id, doc.id)
    elsewhere = sum(
        (
            ln.quantity
            for other in packages
            if other.id != package.id
            for ln in other.lines
            if ln.document_line_id == doc_line.id
        ),
        start=_ZERO,
    )
    available = _picked(doc_line) - elsewhere
    if quantity > available:
        raise ServiceRejectionError(
            'packing_exceeds_picked',
            name=doc_line.name or '',
            remaining=_quantity_text(max(available, _ZERO)),
        )

    package = next(p for p in packages if p.id == package.id)
    current = next(
        (ln for ln in package.lines if ln.document_line_id == doc_line.id), None
    )
    old = current.quantity if current is not None else _ZERO
    if quantity == old:
        return package
    if quantity == 0 and current is not None:
        package.lines.remove(current)
    elif current is not None:
        current.quantity = quantity
    else:
        package.lines.append(
            DocumentPackageLine(document_line_id=doc_line.id, quantity=quantity)
        )
    await db.flush()
    await _log_async(
        db,
        doc,
        user_id,
        AuditAction.UPDATE,
        {
            'code': package_code(doc.number, package.number),
            'name': doc_line.name,
            'quantity': _quantity_text(quantity),
            'old_quantity': _quantity_text(old),
        },
    )
    return package


async def scan_into_package_async(
    db: AsyncSession,
    org_id: UUID,
    doc_id: UUID,
    package_id: UUID,
    code: str,
    quantity: Decimal,
    user_id: UUID | None,
) -> DocumentPackage:
    """Put *quantity* more of the scanned product into the package.

    The line is found as the picking session finds it (``_line_matches_scan``),
    so a code the picker scanned off the shelf is one the packer can scan into
    the box. Of several lines naming the product — two lots, say — the first
    with anything left to pack takes the scan; when none has, the first one
    answers with the over-packing refusal, which says how much is left.
    """
    doc = await _locked_document_async(db, org_id, doc_id)
    _assert_packable(doc)
    package = await _package_async(db, doc, package_id)
    template = await core_api.product_templates.lookup_by_barcode_async(
        db, org_id, code
    )
    if template is None:
        raise ServiceRejectionError('packing_scan_unrecognized', code=code)
    matching = sorted(
        (ln for ln in doc.lines if _line_matches_scan(ln, template.id, code)),
        key=lambda ln: ln.line_number,
    )
    if not matching:
        raise ServiceRejectionError('packing_scan_not_in_document', name=template.name)
    packed = packed_by_line(await list_packages_async(db, org_id, doc.id))
    line = next((ln for ln in matching if _picked(ln) - packed[ln.id] > 0), matching[0])
    left = _picked(line) - packed[line.id]
    if quantity > left:
        # Said here rather than by ``set_line_async``: its bound counts what
        # this package already holds as available to it again, and "2 left"
        # of a line already in the box would send the packer looking for 2.
        raise ServiceRejectionError(
            'packing_exceeds_picked',
            name=line.name or '',
            remaining=_quantity_text(max(left, _ZERO)),
        )
    held = sum(
        (ln.quantity for ln in package.lines if ln.document_line_id == line.id),
        start=_ZERO,
    )
    return await set_line_async(
        db, org_id, doc_id, package.id, line.id, held + quantity, user_id
    )


async def delete_package_async(
    db: AsyncSession,
    org_id: UUID,
    doc_id: UUID,
    package_id: UUID,
    user_id: UUID | None,
) -> None:
    """Remove a package; what it held is unpacked again, not unpicked.

    The packages after it move down one, so the numbers stay 1..N and a slip
    or a label saying "package N of M" never names a box beyond M. A printout
    that carries the total is stale once a package is added or removed, so
    the boxes are relabelled either way; closing the gap keeps them honest.
    """
    doc = await _locked_document_async(db, org_id, doc_id)
    _assert_packable(doc)
    package = await _package_async(db, doc, package_id)
    later = [
        p
        for p in await list_packages_async(db, org_id, doc.id)
        if p.number > package.number
    ]
    await _log_async(
        db,
        doc,
        user_id,
        AuditAction.HARD_DELETE,
        {
            'code': package_code(doc.number, package.number),
            'line_count': len(package.lines),
        },
    )
    await db.delete(package)
    await db.flush()
    # One at a time, lowest first: each takes the number just freed, which
    # the unique (document, number) pair checks row by row.
    for moved in later:
        moved.number -= 1
        await db.flush()


async def pack_all_async(
    db: AsyncSession,
    org_id: UUID,
    doc_id: UUID,
    user_id: UUID | None,
) -> DocumentPackage:
    """One package holding everything picked and not packed yet.

    The common case of a dispatch that leaves as a single box, in one step
    instead of one per line.
    """
    doc = await _locked_document_async(db, org_id, doc_id)
    _assert_packable(doc)
    packed = packed_by_line(await list_packages_async(db, org_id, doc.id))
    remaining = [
        (line, _picked(line) - packed[line.id])
        for line in doc.lines
        if _picked(line) - packed[line.id] > 0
    ]
    if not remaining:
        raise ServiceRejectionError('packing_nothing_to_pack')

    package = DocumentPackage(
        organization_id=org_id,
        document_id=doc.id,
        number=await _next_number_async(db, doc),
        created_by=user_id,
        lines=[
            DocumentPackageLine(document_line_id=line.id, quantity=quantity)
            for line, quantity in remaining
        ],
    )
    db.add(package)
    await db.flush()
    await _log_async(
        db,
        doc,
        user_id,
        AuditAction.CREATE,
        {
            'code': package_code(doc.number, package.number),
            'line_count': len(remaining),
        },
    )
    return package


def _uom_symbol(line: DocumentLine) -> str | None:
    return line.uom.symbol if line.uom is not None else None


def build_view(doc: Document, packages: list[DocumentPackage]) -> PackingView:
    """The packages, and per document line how far packing has got."""
    by_id = {line.id: line for line in doc.lines}
    packed = packed_by_line(packages)
    return PackingView(
        editable=is_editable(doc),
        packages=[
            PackageOut(
                id=package.id,
                number=package.number,
                code=package_code(doc.number, package.number),
                weight_kg=package.weight_kg,
                created_at=package.created_at,
                lines=sorted(
                    (
                        PackageLineOut(
                            document_line_id=ln.document_line_id,
                            line_number=by_id[ln.document_line_id].line_number,
                            product_name=by_id[ln.document_line_id].name,
                            uom_symbol=_uom_symbol(by_id[ln.document_line_id]),
                            quantity=ln.quantity,
                        )
                        for ln in package.lines
                    ),
                    key=lambda out: out.line_number,
                ),
            )
            for package in packages
        ],
        lines=[
            PackingLineOut(
                document_line_id=line.id,
                line_number=line.line_number,
                product_name=line.name,
                uom_symbol=_uom_symbol(line),
                picked_quantity=_picked(line),
                packed_quantity=packed[line.id],
                remaining_quantity=_picked(line) - packed[line.id],
            )
            for line in doc.lines
        ],
    )


async def view_async(db: AsyncSession, org_id: UUID, doc_id: UUID) -> PackingView:
    doc = await get_document_async(db, org_id, doc_id)
    return build_view(doc, await list_packages_async(db, org_id, doc_id))


async def packing_slip_pdf_async(
    db: AsyncSession,
    org_id: UUID,
    doc_id: UUID,
    package_id: UUID | None,
    lang: str,
) -> tuple[str, bytes]:
    """``(file name, PDF)`` of one package's slip, or of every package's.

    Printable once confirmed and after completion too — the slip of a
    shipped dispatch is what a returned box is checked against.
    """
    from ._print_template_pick import pick_packing_slip_html
    from .document_pdf_service import generate_packing_slip_pdf_async, print_packages
    from .document_profile_service import get_or_create_profile
    from .document_query_service import get_document

    doc = await get_document(db, org_id, doc_id)
    if doc is None:
        raise EntityNotFoundError('document')
    if not dt.is_dispatch(doc.type):
        raise ServiceRejectionError('packing_not_a_dispatch')
    packages = await list_packages_async(db, org_id, doc_id)
    printed = packages
    if package_id is not None:
        printed = [p for p in packages if p.id == package_id]
        if not printed:
            raise EntityNotFoundError('package')
    if not printed:
        raise ServiceRejectionError('packing_no_packages')

    pdf = await generate_packing_slip_pdf_async(
        doc,
        await get_or_create_profile(db, org_id),
        print_packages(doc, printed, total=len(packages)),
        template_html=await pick_packing_slip_html(db, org_id),
        lang=lang,
        organization=await core_api.organizations.get_async(db, org_id),
    )
    name = (
        package_code(doc.number, printed[0].number)
        if package_id is not None
        else doc.number
    )
    return name, pdf


async def package_label_png_async(
    db: AsyncSession,
    org_id: UUID,
    doc_id: UUID,
    package_id: UUID,
    *,
    width_mm: float,
    height_mm: float,
) -> tuple[str, bytes]:
    """``(file name, PNG)`` of the package's label, drawn by the printing module.

    The label prints the package code under its QR — the code the slip's
    barcode carries — and says whom the box is for and which of how many it
    is. The QR opens the dispatch, as the document's own printed QR does:
    that is the record a person holding the box wants to see.
    """
    from app.config import settings
    from app.core.async_utils import run_sync_in_thread
    from app.core.label_rendering import render_label_png

    label, qr_url = await _package_label_async(db, org_id, doc_id, package_id)
    png = await run_sync_in_thread(
        lambda: render_label_png(
            label,
            width_mm=width_mm,
            height_mm=height_mm,
            base_url=settings.FRONTEND_URL,
            qr_url_override=qr_url,
            show_code=True,
        )
    )
    return f'package_label_{label.short_code.replace("/", "-")}.png', png


async def print_package_label_async(
    db: AsyncSession,
    org_id: UUID,
    doc_id: UUID,
    package_id: UUID,
    user_id: UUID | None,
    *,
    agent_id: UUID | None,
    width_mm: float,
    height_mm: float,
) -> UUID:
    """Send the package's label to a printer's queue; the job's id.

    The label the download draws — the same code, words and QR — queued for
    the print agent next to the printer, so a packer at a label printer does
    not open a file and print it by hand for every box.
    """
    from app.modules.printing.printing_api import printing_api

    label, qr_url = await _package_label_async(db, org_id, doc_id, package_id)
    return await printing_api.queue_label_async(
        db,
        org_id,
        user_id,
        short_code=label.short_code,
        caption=label.description,
        qr_url=qr_url,
        # The label says whom the package is for: the queue shows the job to
        # the warehouse's readers, not to every reader of products.
        read_permission='warehouse:read',
        agent_id=agent_id,
        width_mm=width_mm,
        height_mm=height_mm,
    )


async def _package_label_async(
    db: AsyncSession, org_id: UUID, doc_id: UUID, package_id: UUID
) -> tuple[_PackageLabel, str]:
    """What the package's label says, and the address its QR opens."""
    from app.core.scan_links import printable_scan_url

    doc = await get_document_async(db, org_id, doc_id)
    packages = await list_packages_async(db, org_id, doc_id)
    package = next((p for p in packages if p.id == package_id), None)
    if package is None:
        raise EntityNotFoundError('package')

    code = package_code(doc.number, package.number)
    partner = (doc.partner_snapshot or {}).get('name') or (
        doc.partner.name if doc.partner is not None else None
    )
    count = f'{package.number}/{len(packages)}'
    label = _PackageLabel(
        short_code=code,
        description=f'{partner} · {count}' if partner else count,
    )
    return label, printable_scan_url(doc.number) or doc.number


class _PackageLabel:
    """The two fields the label renderer reads off a label."""

    label_type = 'PACKAGE'

    def __init__(self, short_code: str, description: str) -> None:
        self.short_code = short_code
        self.description = description

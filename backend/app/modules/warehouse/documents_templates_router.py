import dataclasses
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts.dtos import UserContextDTO
from app.core.deps import (
    get_async_db,
    get_current_user_context,
    read_only_post,
    require_org,
)
from app.core.exceptions import NotFoundException, ServiceRejectionError
from app.core.module_sdk import PaginatedResponse
from app.core.modules import require_module
from app.core.print_identity import IssuerContext
from app.core.public_api import core_api
from app.core.template_schemas import (
    DocumentTemplateCreate,
    DocumentTemplateSchema,
    DocumentTemplateUpdate,
    PlaceholderInfo,
)
from app.core.utils import content_disposition
from app.i18n.service import get_current_lang

from . import _template_transfer as template_transfer
from .document_pdf_service import (
    build_pdf_context,
    build_pick_list_context,
    print_lang,
    print_packages,
)
from .models import Document, DocumentLine, DocumentPackage, DocumentPackageLine

router = APIRouter(dependencies=[Depends(require_module('warehouse'))])


class BuiltInTemplate(BaseModel):
    """A layout shipped with the module, before anyone has copied it."""

    name: str
    document_type: str
    body_html: str


# ---------------------------------------------------------------------------
# Placeholders catalog
# ---------------------------------------------------------------------------
#
# The catalog is generated from the actual render context
# (``build_pdf_context``), so it cannot drift from what a template really
# receives. The annotation below only adds what the context cannot tell:
# what a field means, when it is empty, and for which document types it
# makes sense. A key that has no annotation still surfaces in the catalog
# (with a description derived from its name) instead of hiding.

# Context keys that template authors must not touch: ORM objects, helper
# dictionaries, and the variant switch the built-in families use to pick
# their partials (user templates get their includes inlined at save time).
_INTERNAL_CONTEXT_KEYS = frozenset(
    {
        'profile',
        'labels',
        'line_status_map',
        'doc_status_map',
        'discrepancy_map',
        'lang',
        'doc_variant',
    }
)

# Objects in the context are exposed as ``{{parent.attr}}`` entries. The
# issuer attrs come from the dataclass itself, so a new IssuerContext
# field surfaces in the catalog automatically; partner is a plain class, so
# its list stays manual — the coverage test below still demands an
# annotation for every entry.
_NESTED_PLACEHOLDERS: dict[str, list[str]] = {
    # The document itself. It used to be hidden as "internal", while every
    # built-in layout is written in terms of it — `{{ document.number }}`,
    # `{% for line in document.lines %}`. So the catalogue described one
    # dialect and the layout a template author copies was written in
    # another, with no way to look up the half that mattered most.
    'document': [
        'number',
        'type',
        'status',
        'created_at',
        'scheduled_date',
        'external_reference',
        'notes',
        'lines',
    ],
    'partner': ['name', 'code', 'tax_id', 'address'],
    'issuer': [field.name for field in dataclasses.fields(IssuerContext)],
}

#: Document types used in the catalog's ``document_types`` column.
_IN = ['IN', 'PZ']
_OUT = ['OUT', 'WZ']
_TRANSFER = ['INT', 'MM']
_INTERNAL = ['INTERNAL_IN', 'INTERNAL_OUT']
_CORRECTION = ['CORRECTION']
_SCRAP = ['SCRAP']
_ALL: list[str] | None = None


def _types(*groups: list[str] | None) -> list[str] | None:
    """Merge type groups; None stays None (= any type)."""
    merged: list[str] = []
    for group in groups:
        if group is None:
            return None
        merged.extend(group)
    return merged


#: Human annotation per placeholder key (flat key or ``parent.attr``).
_PLACEHOLDER_META: dict[str, dict[str, Any]] = {
    'document.number': {
        'description': 'The document number, as the register knows it',
        'possibly_empty': False,
    },
    'document.type': {
        'description': 'Type code (IN, OUT, INT, CORRECTION, …)',
        'possibly_empty': False,
    },
    'document.status': {
        'description': 'DRAFT, CONFIRMED or COMPLETED — the raw code',
        'possibly_empty': False,
    },
    'document.created_at': {
        'description': 'When the document was created; pair with |format_date',
        'possibly_empty': False,
    },
    'document.scheduled_date': {
        'description': 'The date the document is planned for, when one was set',
        'possibly_empty': True,
    },
    'document.external_reference': {
        'description': "The other side's own number for this, when given",
        'possibly_empty': True,
    },
    'document.notes': {
        'description': 'Free-text notes recorded on the document',
        'possibly_empty': True,
    },
    'document.lines': {
        'description': (
            'The lines, for {% for line in document.lines %} — each carries '
            'name, quantity, done_quantity, uom and the value columns'
        ),
        'possibly_empty': False,
    },
    'doc_title': {
        'description': 'Document display title, localised for the print language',
        'possibly_empty': False,
    },
    'doc_subtitle': {
        'description': 'Long-form description of the document type',
        'possibly_empty': False,
    },
    'print_title': {
        'description': (
            'Title as the shared header prints it — same value as doc_title, '
            'under the name every print family reads'
        ),
        'possibly_empty': False,
    },
    'print_subtitle': {
        'description': 'Subtitle as the shared header prints it (doc_subtitle)',
        'possibly_empty': True,
    },
    'print_number': {
        'description': 'The document number, as the shared header prints it',
        'possibly_empty': False,
    },
    'print_status': {
        'description': 'Localised status, as the shared header prints it',
        'possibly_empty': False,
    },
    'print_dates': {
        'description': (
            'Date stamps worth printing, as [{label, value}] — a stamp that '
            'repeats the one above it is left out'
        ),
        'possibly_empty': False,
    },
    'source_location': {
        'description': 'Name of the source storage location (empty for receipts)',
        'possibly_empty': True,
        'document_types': _types(_OUT, _TRANSFER, ['INTERNAL_OUT']),
    },
    'target_location': {
        'description': 'Name of the target storage location (empty for issues)',
        'possibly_empty': True,
        'document_types': _types(_IN, _TRANSFER, ['INTERNAL_IN']),
    },
    'total_expected': {
        'description': 'Sum of expected quantities across all lines',
        'possibly_empty': False,
    },
    'total_done': {
        'description': 'Sum of done quantities across all lines',
        'possibly_empty': False,
    },
    'totals_by_unit': {
        'description': (
            'Quantity totals grouped by unit — [{symbol, expected, done}] — '
            'one entry per unit; quantities in different units have no '
            'common sum, so a layout printing a total prints these'
        ),
        'possibly_empty': True,
    },
    'tax_by_rate': {
        'description': (
            'Net, tax and gross grouped by tax rate — [{rate, net, tax, '
            'gross}], highest rate first; empty when no tax is printed'
        ),
        'possibly_empty': True,
        'document_types': _types(_IN, _OUT, _INTERNAL),
    },
    'code128_img': {
        'description': 'Code128 barcode image (data URI) of the document number',
        'possibly_empty': False,
    },
    'code128_width_mm': {
        'description': (
            'Width the barcode must print at, in millimetres — set '
            'width: {{ code128_width_mm }}mm and do not scale the image'
        ),
        'possibly_empty': False,
    },
    'code128_height_mm': {
        'description': 'Height the barcode must print at, in millimetres',
        'possibly_empty': False,
    },
    'qr_img': {
        'description': (
            'QR code image (data URI) — carries the scan address of this '
            'document, or its number when the installation has no public address'
        ),
        'possibly_empty': False,
    },
    'qr_size_mm': {
        'description': 'Side the QR must print at, in millimetres',
        'possibly_empty': False,
    },
    'corrected_doc_number': {
        'description': 'Number of the document this correction corrects',
        'possibly_empty': True,
        'document_types': _CORRECTION,
    },
    'backorder_of_number': {
        'description': 'Number of the document this backorder continues',
        'possibly_empty': True,
        'document_types': _types(_IN, _OUT, _TRANSFER, ['INTERNAL_IN']),
    },
    'return_of_number': {
        'description': 'Number of the document this return reverses',
        'possibly_empty': True,
        'document_types': _types(_IN, _OUT, _TRANSFER),
    },
    'doc_type': {
        'description': 'Document type code (IN, OUT, INT, PW, RW, CORRECTION, …)',
        'possibly_empty': False,
    },
    'is_correction': {
        'description': 'True when the document is a correction',
        'possibly_empty': False,
        'document_types': _CORRECTION,
    },
    'is_external_in': {
        'description': 'True for receipts (IN, PZ)',
        'possibly_empty': False,
        'document_types': _IN,
    },
    'is_external_out': {
        'description': 'True for issues (OUT, WZ)',
        'possibly_empty': False,
        'document_types': _OUT,
    },
    'is_internal_in': {
        'description': 'True for internal receipts (PW)',
        'possibly_empty': False,
        'document_types': ['INTERNAL_IN'],
    },
    'is_internal_out': {
        'description': 'True for internal issues (RW)',
        'possibly_empty': False,
        'document_types': ['INTERNAL_OUT'],
    },
    'is_transfer': {
        'description': 'True for transfers between locations (INT, MM)',
        'possibly_empty': False,
        'document_types': _TRANSFER,
    },
    'is_scrap': {
        'description': (
            'True for a write-off; its cost is document.total_net, empty when '
            'the profile tracks no value'
        ),
        'possibly_empty': False,
        'document_types': _SCRAP,
    },
    'scrap_reason': {
        'description': 'Why the goods were written off, in the print language',
        'possibly_empty': True,
        'document_types': _SCRAP,
    },
    'is_external': {
        'description': 'True for documents with a partner (IN, PZ, OUT, WZ)',
        'possibly_empty': False,
        'document_types': _types(_IN, _OUT),
    },
    'is_internal': {
        'description': 'True for internal documents (PW, RW, INT, MM)',
        'possibly_empty': False,
        'document_types': _types(_INTERNAL, _TRANSFER),
    },
    'show_line_status': {
        'description': 'True when per-line statuses are printed',
        'possibly_empty': False,
    },
    'show_payment': {
        'description': 'True when the totals/payment block is printed',
        'possibly_empty': False,
        'document_types': _types(_IN, _OUT),
    },
    'show_value_columns': {
        'description': 'True when price/value columns are printed',
        'possibly_empty': False,
        'document_types': _types(_IN, _OUT, _INTERNAL),
    },
    'show_tax_column': {
        'description': 'True when the tax column is printed',
        'possibly_empty': False,
        'document_types': _types(_IN, _OUT, _INTERNAL),
    },
    'partner.name': {
        'description': 'Partner (supplier/customer) name',
        'possibly_empty': True,
        'document_types': _types(_IN, _OUT),
    },
    'partner.code': {
        'description': 'Partner code',
        'possibly_empty': True,
        'document_types': _types(_IN, _OUT),
    },
    'partner.tax_id': {
        'description': 'Partner tax ID (VAT/NIP number)',
        'possibly_empty': True,
        'document_types': _types(_IN, _OUT),
    },
    'partner.address': {
        'description': 'Partner address, country name localised',
        'possibly_empty': True,
        'document_types': _types(_IN, _OUT),
    },
    'issuer.name': {
        'description': 'Issuing organization name (printed from Organization)',
        'possibly_empty': True,
    },
    'issuer.tax_id': {
        'description': 'Issuing organization tax ID (VAT/NIP number)',
        'possibly_empty': True,
    },
    'packages': {
        'description': (
            'Packing slip only: the packages printed, one sheet each — '
            'number, count, code, code128_img, weight_kg and lines'
        ),
        'possibly_empty': True,
        'document_types': _OUT,
    },
    'pick_lines': {
        'description': (
            'Pick list only: the lines in walk order — shelf_code, shelf_name, '
            'quantity, unit, name, sku, lot and document_number'
        ),
        'possibly_empty': True,
        'document_types': _OUT,
    },
    'documents': {
        'description': (
            'Pick list only: the dispatches on the sheet — number and the '
            'Code128 of it (code128_img, code128_width_mm, code128_height_mm)'
        ),
        'possibly_empty': True,
        'document_types': _OUT,
    },
    'issuer.address': {
        'description': 'Issuing organization address, country name localised',
        'possibly_empty': True,
    },
    'issuer.logo': {
        'description': 'Issuing organization logo (embedded data URI)',
        'possibly_empty': True,
    },
}


def _example_context(lang: str = 'en') -> dict[str, Any]:
    """A render context for a representative document (IN, DRAFT).

    Purely in-memory — nothing is persisted. Used only to produce example
    values for the placeholders catalog.
    """
    doc = Document(
        organization_id=UUID('00000000-0000-0000-0000-000000000001'),
        type='IN',
        number='IN/2026/001',
        status='DRAFT',
    )
    doc.partner_snapshot = {
        'name': 'Acme Supplies',
        'code': 'SUP-001',
        'tax_id': 'PL1234567890',
        'address': {
            'street': 'Cold Storage Rd 1',
            'city': 'Warsaw',
            'postal_code': '00-001',
            'country': 'PL',
        },
    }
    line = DocumentLine(
        id=UUID('00000000-0000-0000-0000-000000000002'),
        name='Example Item',
        quantity=2,
        expected_quantity=2,
        done_quantity=0,
        line_number=1,
    )
    doc.lines.append(line)
    # One package holding the line, so a packing slip previews with a sheet
    # rather than an empty page.
    package = DocumentPackage(
        number=1,
        weight_kg=Decimal('2.5'),
        lines=[DocumentPackageLine(document_line_id=line.id, quantity=2)],
    )
    issuer = IssuerContext(
        name='Acme Supplies',
        tax_id='PL1234567890',
        # Formatted for the print language, as a real issuer's is: a fixed
        # "Poland" sat above the partner's "Polska" on a Polish preview.
        address=core_api.pdf.format_partner_address(
            doc.partner_snapshot['address'], lang
        ),
    )
    # The same one line, so a pick list previews with a row of its own.
    pick_list = build_pick_list_context(
        [doc],
        [
            {
                'shelf_code': 'A-01',
                'shelf_name': 'Shelf A-01',
                'quantity': 2,
                'unit': 'pcs',
                'name': line.name,
                'sku': 'SKU-001',
                'lot': None,
                'document_number': doc.number,
            }
        ],
        lang,
        issuer,
    )
    return {
        **build_pdf_context(
            doc,
            None,
            lang=lang,
            issuer=issuer,
            packages=print_packages(doc, [package], total=1),
        ),
        'documents': pick_list['documents'],
        'pick_lines': pick_list['pick_lines'],
    }


def _format_scalar(value: Any) -> str:
    """One value as a reader writes it: no ``Decimal(...)``, no ``None``."""
    if value is None:
        return ''
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, Decimal):
        return format(value.normalize(), 'f')
    if isinstance(value, str) and value.startswith('data:'):
        return '[embedded image data URI]'
    return str(value)


def _format_example(value: Any) -> str:
    """A short printable example value from a context value."""
    if isinstance(value, list):
        # A list of rows is shown as what each row carries, never as the
        # list's repr (a module path and a memory address).
        text = '; '.join(_format_row_example(row) for row in value)
    else:
        text = _format_scalar(value)
    return text if len(text) <= 80 else f'{text[:77]}…'


def _format_row_example(row: Any) -> str:
    """One row of a list-valued placeholder.

    A line reads ``name × quantity``; a record (``totals_by_unit``,
    ``packages``) reads ``field: value`` for each field it carries, leaving
    out what is empty, embedded or itself a list.
    """
    if isinstance(row, dict):
        return ', '.join(
            f'{key}: {text}'
            for key, item in row.items()
            if not isinstance(item, list | dict)
            and (text := _format_scalar(item))
            and not text.startswith('[embedded')
        )
    name = getattr(row, 'name', None)
    quantity = getattr(row, 'quantity', None)
    if name is not None and quantity is not None:
        return f'{name} × {quantity:g}'
    return str(name if name is not None else row)


def _catalog_entry(key: str, value: Any) -> PlaceholderInfo:
    meta = _PLACEHOLDER_META.get(key, {})
    example = _format_example(value)
    return PlaceholderInfo(
        key=f'{{{{{key}}}}}',
        description=meta.get('description', key.replace('_', ' ').capitalize()),
        example=example,
        # A field whose example is empty is empty for some documents by
        # definition; the annotation can only add more cases.
        possibly_empty=bool(meta.get('possibly_empty') or not example),
        document_types=meta.get('document_types'),
    )


def _build_placeholders_catalog(lang: str = 'en') -> list[PlaceholderInfo]:
    """The catalog, derived from the real render context.

    The example values are the ones the document prints in ``lang``, so a
    Polish editor does not show an English title beside a Polish description.
    """
    context = _example_context(lang)
    items: list[PlaceholderInfo] = []

    for key, value in sorted(context.items()):
        if key in _INTERNAL_CONTEXT_KEYS:
            continue
        if key in _NESTED_PLACEHOLDERS:
            for attr in _NESTED_PLACEHOLDERS[key]:
                nested = getattr(value, attr, None) if value is not None else None
                items.append(_catalog_entry(f'{key}.{attr}', nested))
            continue
        items.append(_catalog_entry(key, value))
    return items


class TemplatePreviewRequest(BaseModel):
    """A layout to render, as the editor currently has it."""

    body_html: str


class TemplatePreviewResponse(BaseModel):
    """The layout rendered onto the example document."""

    html: str


@router.post('/preview', response_model=TemplatePreviewResponse)
@read_only_post
async def preview_template(
    data: TemplatePreviewRequest,
    current_user: UserContextDTO = Depends(get_current_user_context),
) -> TemplatePreviewResponse:
    """What this layout prints, on a document made up for the purpose.

    The preview used to show the source — `{% for line in lines %}` and all —
    which answers "what does this template say" and not "what will the paper
    look like". The rendering is the same one the PDF goes through, on the
    same example context the placeholder catalog is derived from, so a
    preview cannot describe a document the printer would not produce.
    """
    try:
        from pathlib import Path

        html = core_api.pdf.render_html(
            data.body_html,
            # A layout written in one language previews in it, header and
            # all, as it prints.
            _example_context(print_lang(data.body_html, get_current_lang())),
            # The same directory the PDF path passes: a built-in layout's
            # `{% include 'print_header.html' %}` must resolve in the preview
            # exactly as it does on paper.
            templates_dir=Path(__file__).parent / 'templates',
        )
    except Exception as exc:  # a draft template is user input
        # A half-written layout is the normal state of the editor; saying
        # which line Jinja objected to beats an empty frame.
        raise ServiceRejectionError(
            'template_import_not_renderable', detail=str(exc)
        ) from exc
    return TemplatePreviewResponse(html=html)


@router.get(
    '/placeholders',
    # list-envelope-exception: the placeholder catalogue, a vocabulary in the code
    response_model=list[PlaceholderInfo],
)
async def list_placeholders(
    current_user: UserContextDTO = Depends(get_current_user_context),
) -> list[PlaceholderInfo]:
    return _build_placeholders_catalog(get_current_lang())


@router.get('', response_model=PaginatedResponse[DocumentTemplateSchema])
async def list_templates(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    org_id = require_org(current_user)
    # Passing the built-ins is what lets a copy be told from the layout it
    # came from — nothing is rewritten, the screen just stops being
    # silent about it.
    templates = await core_api.templates.list_async(
        db, org_id, module='warehouse', built_ins=_read_built_ins()
    )
    return PaginatedResponse.from_full_list(templates, offset=offset, limit=limit)


_BUILT_IN_TEMPLATES = [
    ('Standard Template', 'STANDARD', 'standard.html'),
    ('PL PZ Template', 'PL_PZ', 'pl_pz.html'),
    ('Packing Slip', 'PACKING_SLIP', 'packing_slip.html'),
    ('Pick List', 'PICK_LIST', 'pick_list.html'),
]


def _read_built_ins() -> list[tuple[str, str, str]]:
    """The layouts a PDF falls back to, as (name, document type, HTML)."""
    from pathlib import Path

    templates_dir = Path(__file__).parent / 'templates'
    found: list[tuple[str, str, str]] = []
    for name, doc_type, filename in _BUILT_IN_TEMPLATES:
        path = templates_dir / filename
        if path.exists():
            found.append((name, doc_type, path.read_text(encoding='utf-8')))
    return found


@router.get(
    '/built-in',
    # list-envelope-exception: the layouts shipped with the module, fixed in the code
    response_model=list[BuiltInTemplate],
)
async def list_built_in_templates(
    current_user: UserContextDTO = Depends(get_current_user_context),
) -> Any:
    """The built-in layouts, readable before anyone copies them.

    Without this the only way to find out what a printed document looks like
    was to create one — the screen offered to copy layouts it would not show.
    """
    require_org(current_user)
    return [
        BuiltInTemplate(name=name, document_type=doc_type, body_html=html)
        for name, doc_type, html in _read_built_ins()
    ]


@router.get('/{template_id}/export')
async def export_template(
    template_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Response:
    """The template as one file, ready to import on another installation.

    No instance identity travels in the file — no ids, no timestamps — so
    it lands elsewhere as if the template had been typed there.
    """
    org_id = require_org(current_user)
    tpl = await core_api.templates.get_async(
        db, org_id, template_id, module='warehouse'
    )
    if not tpl:
        raise NotFoundException('template')
    filename, raw = template_transfer.build_export_file(tpl)
    return Response(
        content=raw,
        media_type='application/json',
        headers={'Content-Disposition': content_disposition(filename)},
    )


@router.post('/import', response_model=DocumentTemplateSchema, status_code=201)
async def import_template(
    file: UploadFile = File(...),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    """Save a template from an exported file: validated, then the ordinary door.

    The file is untrusted data. It is parsed, its field references are
    checked against the render context, and it is rendered on the example
    document — nothing more; what passes goes through the same create path
    a hand-typed template uses, so the sandbox and the render-time
    sanitizer stay the only things that ever execute it.
    """
    org_id = require_org(current_user)
    fields = template_transfer.parse_export_file(await file.read())
    template_transfer.validate_body(fields['body_html'])
    return await core_api.templates.create_async(
        db=db,
        organization_id=org_id,
        module='warehouse',
        user_id=current_user.id,
        name=fields['name'],
        body_html=fields['body_html'],
        document_type=fields['document_type'],
        is_default=fields['is_default'],
    )


@router.post(
    '/seed-defaults',
    # list-envelope-exception: a bulk result, the templates this request just created
    response_model=list[DocumentTemplateSchema],
    status_code=201,
)
async def seed_default_templates(
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    org_id = require_org(current_user)
    built_ins = _read_built_ins()

    return await core_api.templates.seed_defaults_async(
        db=db,
        organization_id=org_id,
        module='warehouse',
        user_id=current_user.id,
        built_ins=built_ins,
    )


@router.post(
    '/{template_id}/refresh-copy',
    response_model=DocumentTemplateSchema,
    status_code=status.HTTP_201_CREATED,
)
async def refresh_builtin_copy(
    template_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    """Copy the current built-in next to an organization's older copy.

    Alongside, not over: whatever the organization has edited into its own
    template stays, the new copy does not become the default, and which of
    the two prints remains a decision somebody makes.
    """
    org_id = require_org(current_user)
    return await core_api.templates.copy_builtin_alongside_async(
        db=db,
        organization_id=org_id,
        module='warehouse',
        user_id=current_user.id,
        template_id=template_id,
        built_ins=_read_built_ins(),
    )


@router.get('/{template_id}', response_model=DocumentTemplateSchema)
async def get_template(
    template_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    org_id = require_org(current_user)
    tpl = await core_api.templates.get_async(
        db, org_id, template_id, module='warehouse'
    )
    if not tpl:
        raise NotFoundException('template')
    return tpl


@router.post(
    '', response_model=DocumentTemplateSchema, status_code=status.HTTP_201_CREATED
)
async def create_template(
    data: DocumentTemplateCreate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    org_id = require_org(current_user)
    if data.module != 'warehouse':
        raise ServiceRejectionError('document_template_wrong_module')
    return await core_api.templates.create_async(
        db=db,
        organization_id=org_id,
        module='warehouse',
        user_id=current_user.id,
        name=data.name,
        body_html=data.body_html,
        document_type=data.document_type,
        is_default=data.is_default,
    )


@router.put('/{template_id}', response_model=DocumentTemplateSchema)
async def update_template(
    template_id: UUID,
    data: DocumentTemplateUpdate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    org_id = require_org(current_user)
    return await core_api.templates.update_async(
        db=db,
        organization_id=org_id,
        template_id=template_id,
        module='warehouse',
        name=data.name,
        body_html=data.body_html,
        document_type=data.document_type,
        is_default=data.is_default,
        user_id=current_user.id,
    )


@router.delete('/{template_id}', status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(
    template_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> None:
    org_id = require_org(current_user)
    await core_api.templates.delete_async(
        db, org_id, template_id, module='warehouse', user_id=current_user.id
    )

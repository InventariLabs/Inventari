from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts.dtos import UserContextDTO
from app.core.deps import (
    get_async_db,
    get_current_user_context,
    read_only_post,
    require_org,
)
from app.core.exceptions import (
    NotFoundException,
    ServiceRejectionError,
    catalogue_refusal,
)
from app.core.logging import get_logger
from app.core.module_sdk import PaginatedResponse
from app.core.modules import require_module
from app.core.public_api import core_api
from app.core.template_schemas import (
    DocumentTemplateCreate,
    DocumentTemplateSchema,
    DocumentTemplateUpdate,
    PlaceholderInfo,
)
from app.i18n.service import (
    SUPPORTED_LANGUAGES,
    Language,
    get_current_lang,
    get_error_message,
)

_templates_router = APIRouter(
    dependencies=[Depends(require_module('purchase_orders'))],
)

logger = get_logger(__name__)

_TEMPLATES_DIR = Path(__file__).parent / 'templates'

PO_PLACEHOLDERS: list[PlaceholderInfo] = [
    PlaceholderInfo(key='{{po_number}}', description='PO number (auto-generated)'),
    PlaceholderInfo(key='{{po_date}}', description='PO creation date'),
    PlaceholderInfo(key='{{po_status}}', description='PO status'),
    PlaceholderInfo(key='{{po_title}}', description='PO display title'),
    PlaceholderInfo(key='{{vendor_name}}', description='Supplier name'),
    PlaceholderInfo(key='{{vendor_tax_id}}', description='Supplier tax ID'),
    PlaceholderInfo(key='{{vendor_address}}', description='Supplier address'),
    PlaceholderInfo(key='{{total_net}}', description='Total net value'),
    PlaceholderInfo(key='{{total_tax}}', description='Total tax'),
    PlaceholderInfo(key='{{total_gross}}', description='Total gross value'),
    PlaceholderInfo(key='{{lines_count}}', description='Number of line items'),
    PlaceholderInfo(key='{{organization_name}}', description='Organization name'),
    PlaceholderInfo(
        key='{{barcode_img}}', description='Code128 barcode image (data URI)'
    ),
    PlaceholderInfo(key='{{qr_img}}', description='QR code image (data URI)'),
    PlaceholderInfo(key='{{currency}}', description='Currency code'),
    PlaceholderInfo(key='{{lang}}', description='Document language code'),
    PlaceholderInfo(
        key='{{labels.footer}}', description='Footer text in the document language'
    ),
]


def _built_ins(lang: Language) -> list[tuple[str, str, str]]:
    """The layouts a purchase order PDF falls back to, named in one language."""
    tpl_path = _TEMPLATES_DIR / 'po_standard.html'
    if not tpl_path.exists():
        return []
    return [
        (
            get_error_message('purchase_order_standard_template', lang),
            'STANDARD',
            tpl_path.read_text(encoding='utf-8'),
        )
    ]


def _built_ins_under_every_name() -> list[tuple[str, str, str]]:
    """The same layouts under each name they could have been seeded with.

    A copy is matched to its built-in by the name it was made under, and the
    built-in is named in the seeding language, so a copy made in Polish and
    read in English would match nothing. Same body under every name; whichever
    one the copy carries, the checksum compared is the right one.
    """
    return [entry for lang in SUPPORTED_LANGUAGES for entry in _built_ins(lang)]


@_templates_router.get('', response_model=PaginatedResponse[DocumentTemplateSchema])
async def list_templates(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> PaginatedResponse[DocumentTemplateSchema]:
    # Without the built-ins `source_modified` and `source_outdated` are never
    # computed, so a copy that no longer matches its layout would not say so.
    templates = await core_api.templates.list_async(
        db,
        org_id,
        module='purchase_orders',
        built_ins=_built_ins_under_every_name(),
    )
    return PaginatedResponse.from_full_list(templates, offset=offset, limit=limit)


@_templates_router.get(
    '/placeholders',
    # list-envelope-exception: the placeholder catalogue, a vocabulary in the code
    response_model=list[PlaceholderInfo],
)
async def list_placeholders(
    current_user: UserContextDTO = Depends(get_current_user_context),
) -> list[PlaceholderInfo]:
    return PO_PLACEHOLDERS


class PoTemplatePreviewRequest(BaseModel):
    """A layout to render, as the editor currently has it."""

    body_html: str


class PoTemplatePreviewResponse(BaseModel):
    """The layout rendered onto the example order."""

    html: str


@_templates_router.post('/preview', response_model=PoTemplatePreviewResponse)
@read_only_post
async def preview_template(
    data: PoTemplatePreviewRequest,
    current_user: UserContextDTO = Depends(get_current_user_context),
) -> PoTemplatePreviewResponse:
    """What this layout prints, on an order made up for the purpose.

    The same render the PDF goes through, on the context ``build_po_context``
    builds, so the preview cannot describe a document the printer would not
    produce.
    """
    from pathlib import Path

    from ._po_render_context import build_po_context, example_order

    try:
        html = core_api.pdf.render_html(
            data.body_html,
            build_po_context(example_order(), get_current_lang()),
            templates_dir=Path(__file__).parent / 'templates',
        )
    except Exception as exc:  # a draft template is user input
        raise ServiceRejectionError(
            'template_import_not_renderable', detail=str(exc)
        ) from exc
    return PoTemplatePreviewResponse(html=html)


@_templates_router.post(
    '/seed-defaults',
    # list-envelope-exception: a bulk result, the templates this request just created
    response_model=list[DocumentTemplateSchema],
    status_code=201,
)
async def seed_default_templates(
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> list[DocumentTemplateSchema]:
    return await core_api.templates.seed_defaults_async(
        db=db,
        organization_id=org_id,
        module='purchase_orders',
        user_id=current_user.id,
        built_ins=_built_ins(get_current_lang()),
    )


@_templates_router.post(
    '/{template_id}/refresh-copy',
    response_model=DocumentTemplateSchema,
    status_code=status.HTTP_201_CREATED,
)
async def refresh_builtin_copy(
    template_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> DocumentTemplateSchema:
    """Copy the current built-in next to an organization's older copy.

    Alongside, not over: whatever the organization has edited into its own
    template stays, the new copy does not become the default, and which of
    the two prints remains a decision somebody makes.
    """
    return await core_api.templates.copy_builtin_alongside_async(
        db=db,
        organization_id=org_id,
        module='purchase_orders',
        user_id=current_user.id,
        template_id=template_id,
        built_ins=_built_ins_under_every_name(),
    )


@_templates_router.post('/{template_id}/reset', response_model=DocumentTemplateSchema)
async def reset_template_to_built_in(
    template_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> DocumentTemplateSchema:
    """Put a copy back as the built-in it came from, in place.

    Whatever was written into the copy is gone; its name, its place among
    the defaults and everything that points at it stay. A template that was
    not copied from a built-in has nothing to go back to: 404.
    """
    return await core_api.templates.reset_to_builtin_async(
        db=db,
        organization_id=org_id,
        module='purchase_orders',
        user=current_user,
        template_id=template_id,
        built_ins=_built_ins_under_every_name(),
    )


@_templates_router.get('/{template_id}', response_model=DocumentTemplateSchema)
async def get_template(
    template_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> DocumentTemplateSchema:
    tpl = await core_api.templates.get_async(
        db, org_id, template_id, module='purchase_orders'
    )
    if not tpl:
        raise NotFoundException('template', get_current_lang())
    return tpl


@_templates_router.post(
    '',
    response_model=DocumentTemplateSchema,
    status_code=status.HTTP_201_CREATED,
)
async def create_template(
    data: DocumentTemplateCreate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> DocumentTemplateSchema:
    if data.module != 'purchase_orders':
        raise catalogue_refusal('invalid_template_module', module='purchase_orders')
    return await core_api.templates.create_async(
        db=db,
        organization_id=org_id,
        module='purchase_orders',
        user_id=current_user.id,
        name=data.name,
        body_html=data.body_html,
        document_type=data.document_type,
        is_default=data.is_default,
        templates_dir=_TEMPLATES_DIR,
    )


@_templates_router.put('/{template_id}', response_model=DocumentTemplateSchema)
async def update_template(
    template_id: UUID,
    data: DocumentTemplateUpdate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> DocumentTemplateSchema:
    return await core_api.templates.update_async(
        db=db,
        organization_id=org_id,
        template_id=template_id,
        module='purchase_orders',
        name=data.name,
        body_html=data.body_html,
        document_type=data.document_type,
        is_default=data.is_default,
        user_id=current_user.id,
        templates_dir=_TEMPLATES_DIR,
    )


@_templates_router.delete('/{template_id}', status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(
    template_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> None:
    await core_api.templates.delete_async(
        db, org_id, template_id, module='purchase_orders', user_id=current_user.id
    )

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts.dtos import UserContextDTO
from app.core.deps import get_async_db, get_current_user_context, require_org
from app.core.exceptions import (
    NotFoundException,
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
from app.i18n.service import get_current_lang, get_error_message

_templates_router = APIRouter(
    dependencies=[Depends(require_module('purchase_orders'))],
)

logger = get_logger(__name__)

PO_PLACEHOLDERS: list[PlaceholderInfo] = [
    PlaceholderInfo(key='{{po_number}}', description='PO number (auto-generated)'),
    PlaceholderInfo(key='{{po_date}}', description='PO creation date'),
    PlaceholderInfo(key='{{po_status}}', description='PO status'),
    PlaceholderInfo(key='{{po_title}}', description='PO display title'),
    PlaceholderInfo(key='{{vendor_name}}', description='Vendor name'),
    PlaceholderInfo(key='{{vendor_tax_id}}', description='Vendor tax ID'),
    PlaceholderInfo(key='{{vendor_address}}', description='Vendor address'),
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
]


@_templates_router.get('', response_model=PaginatedResponse[DocumentTemplateSchema])
async def list_templates(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> PaginatedResponse[DocumentTemplateSchema]:
    templates = await core_api.templates.list_async(
        db, org_id, module='purchase_orders'
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
    from pathlib import Path

    templates_dir = Path(__file__).parent / 'templates'
    tpl_path = templates_dir / 'po_standard.html'
    lang = get_current_lang()
    built_ins: list[tuple[str, str, str]] = []
    if tpl_path.exists():
        built_ins.append(
            (
                get_error_message('purchase_order_standard_template', lang),
                'STANDARD',
                tpl_path.read_text(encoding='utf-8'),
            )
        )

    return await core_api.templates.seed_defaults_async(
        db=db,
        organization_id=org_id,
        module='purchase_orders',
        user_id=current_user.id,
        built_ins=built_ins,
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

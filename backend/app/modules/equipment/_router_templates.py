from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import SystemPermission, UserContextDTO
from app.core.deps import (
    get_async_db,
    get_current_user_context,
    require_org,
    require_permission,
)
from app.core.exceptions import NotFoundException, catalogue_refusal
from app.core.module_sdk import PaginatedResponse
from app.core.modules import require_module
from app.core.public_api import core_api
from app.core.template_schemas import DocumentTemplateSchema, PlaceholderInfo
from app.i18n import Language
from app.i18n.service import get_current_lang, get_error_message

from ._schemas_dashboard import DocumentTemplateCreate, DocumentTemplateUpdate

router = APIRouter(dependencies=[Depends(require_module('equipment'))])


_BUILT_IN_NAME_KEYS = [
    ('equipment_default_checkout_template', 'CHECKOUT'),
    ('equipment_default_checkin_template', 'CHECKIN'),
]


def _built_ins(lang: Language) -> list[tuple[str, str, str]]:
    """The layouts a protocol falls back to, named in one language."""
    from .protocol_service import _DEFAULT_CHECKIN_TEMPLATE, _DEFAULT_CHECKOUT_TEMPLATE

    bodies = {
        'CHECKOUT': _DEFAULT_CHECKOUT_TEMPLATE,
        'CHECKIN': _DEFAULT_CHECKIN_TEMPLATE,
    }
    return [
        (get_error_message(name_key, lang), doc_type, bodies[doc_type])
        for name_key, doc_type in _BUILT_IN_NAME_KEYS
    ]


def _built_ins_under_every_name() -> list[tuple[str, str, str]]:
    """The same layouts under each name they could have been seeded with.

    A copy is matched to its built-in by the name it was made under, and this
    module names its built-ins in the seeding language — so a protocol copied
    in Polish and read in English matched nothing, and the screen said the
    layout was current when it was not. Same body under five names; whichever
    one the copy carries, the checksum compared is the right one.
    """
    from app.i18n.service import SUPPORTED_LANGUAGES

    return [entry for lang in SUPPORTED_LANGUAGES for entry in _built_ins(lang)]


@router.get('/templates', response_model=PaginatedResponse[DocumentTemplateSchema])
async def list_document_templates(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> Any:
    # Without the built-ins `source_outdated` is never computed and comes back
    # False for everything, so an equipment protocol copied from a layout that
    # has since moved on never said so — the one thing a copy cannot know.
    templates = await core_api.templates.list_async(
        db, org_id, module='equipment', built_ins=_built_ins_under_every_name()
    )
    return PaginatedResponse.from_full_list(templates, offset=offset, limit=limit)


@router.get(
    '/templates/placeholders',
    # list-envelope-exception: the placeholder catalogue, a vocabulary in the code
    response_model=list[PlaceholderInfo],
)
async def list_template_placeholders(
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> list[PlaceholderInfo]:
    # The editor's hint: the shared catalogue plus the custom fields this
    # organization's categories actually define.
    from .protocol_service import protocol_placeholders_async

    return await protocol_placeholders_async(db, org_id)


@router.post(
    '/templates/seed-defaults',
    # list-envelope-exception: a bulk result, the templates this request just created
    response_model=list[DocumentTemplateSchema],
    status_code=status.HTTP_201_CREATED,
)
async def seed_default_templates(
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ORG_SETTINGS_WRITE),
    org_id: UUID = Depends(require_org),
) -> list[Any]:
    return await core_api.templates.seed_defaults_async(
        db=db,
        organization_id=org_id,
        module='equipment',
        user_id=current_user.id,
        built_ins=_built_ins(get_current_lang()),
    )


@router.post(
    '/templates/{template_id}/refresh-copy',
    response_model=DocumentTemplateSchema,
    status_code=status.HTTP_201_CREATED,
)
async def refresh_builtin_copy(
    template_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ORG_SETTINGS_WRITE),
    org_id: UUID = Depends(require_org),
) -> Any:
    """Copy the current built-in next to an organization's older copy.

    Alongside, not over: whatever the organization has edited into its own
    protocol stays, the new copy does not become the default, and which of
    the two prints remains a decision somebody makes.
    """
    return await core_api.templates.copy_builtin_alongside_async(
        db=db,
        organization_id=org_id,
        module='equipment',
        user_id=current_user.id,
        template_id=template_id,
        built_ins=_built_ins(get_current_lang()),
    )


@router.get('/templates/{template_id}', response_model=DocumentTemplateSchema)
async def get_document_template(
    template_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> Any:
    tpl = await core_api.templates.get_async(
        db, org_id, template_id, module='equipment'
    )
    if not tpl:
        raise NotFoundException('template', get_current_lang())
    return tpl


@router.post(
    '/templates',
    response_model=DocumentTemplateSchema,
    status_code=status.HTTP_201_CREATED,
)
async def create_document_template(
    data: DocumentTemplateCreate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ORG_SETTINGS_WRITE),
    org_id: UUID = Depends(require_org),
) -> Any:
    if data.module != 'equipment':
        raise catalogue_refusal('invalid_template_module', module='equipment')
    return await core_api.templates.create_async(
        db=db,
        organization_id=org_id,
        module='equipment',
        user_id=current_user.id,
        name=data.name,
        body_html=data.body_html,
        document_type=data.document_type,
        is_default=data.is_default,
    )


@router.put('/templates/{template_id}', response_model=DocumentTemplateSchema)
async def update_document_template(
    template_id: UUID,
    data: DocumentTemplateUpdate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ORG_SETTINGS_WRITE),
    org_id: UUID = Depends(require_org),
) -> Any:
    return await core_api.templates.update_async(
        db=db,
        organization_id=org_id,
        template_id=template_id,
        module='equipment',
        name=data.name,
        body_html=data.body_html,
        document_type=data.document_type,
        is_default=data.is_default,
        user_id=current_user.id,
    )


@router.delete('/templates/{template_id}', status_code=status.HTTP_204_NO_CONTENT)
async def delete_document_template(
    template_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ORG_SETTINGS_WRITE),
    org_id: UUID = Depends(require_org),
) -> None:
    await core_api.templates.delete_async(
        db, org_id, template_id, module='equipment', user_id=current_user.id
    )

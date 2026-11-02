from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts.dtos import UserContextDTO
from app.core.deps import (
    get_async_db,
    get_current_user_context,
    require_org,
    require_permission,
)
from app.core.exceptions import NotFoundException, ServiceRejectionError
from app.core.module_sdk import PaginatedResponse
from app.core.modules import require_module
from app.core.settings_diff import journal_config_change, record_settings
from app.i18n.service import get_current_lang

from . import document_type_config_service as _svc
from . import document_types as dt
from .models.profile import DocumentTypeConfig
from .schemas import (
    DocumentTypeConfigCreate,
    DocumentTypeConfigOut,
)

# The upsert journals the payload's own field names (`keys=set(payload)`),
# so the snapshot-key exporter reads this pair the way it reads a dict
# literal (`AGENTS.md §3`: the declaration sits beside the writer it
# speaks for). The delete endpoint journals the record's columns as they
# stood — a universe the model side of this pair already names.
AUDIT_PAYLOAD_SCHEMA = ('DocumentTypeConfigCreate', 'DocumentTypeConfig')

router = APIRouter(dependencies=[Depends(require_module('warehouse'))])


@router.get(
    '/settings/type-configs', response_model=PaginatedResponse[DocumentTypeConfigOut]
)
async def list_type_configs(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    org_id = require_org(current_user)
    configs = await _svc.list_type_configs(db, org_id)
    return PaginatedResponse.from_full_list(configs, offset=offset, limit=limit)


@router.put(
    '/settings/type-configs/{document_type}', response_model=DocumentTypeConfigOut
)
async def upsert_type_config(
    document_type: str,
    data: DocumentTypeConfigCreate,
    _: None = require_permission('warehouse:manage'),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    org_id = require_org(current_user)
    normalized = dt.normalize(document_type)
    if normalized not in dt.ALL_TYPES:
        raise ServiceRejectionError('document_type_invalid', type=document_type)
    payload = data.model_dump(exclude_unset=True)
    previous: DocumentTypeConfig | None = await _svc.get_type_config(
        db, org_id, normalized
    )
    before = (
        {
            key: value
            for key, value in record_settings(previous).items()
            if key in set(payload)
        }
        if previous is not None
        else {}
    )
    result = await _svc.upsert_type_config(db, org_id, normalized, payload)
    await journal_config_change(
        db,
        org_id,
        current_user.id,
        module='warehouse',
        subject=f'type-config:{normalized}',
        keys=set(payload),
        before=before,
        after=result,
    )
    return result


@router.delete('/settings/type-configs/{document_type}', status_code=204)
async def delete_type_config(
    document_type: str,
    _: None = require_permission('warehouse:manage'),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> None:
    org_id = require_org(current_user)
    normalized = dt.normalize(document_type)
    previous = await _svc.get_type_config(db, org_id, normalized)
    before = record_settings(previous) if previous is not None else {}
    try:
        await _svc.delete_type_config(db, org_id, document_type)
    except ValueError as exc:
        raise NotFoundException('document_type_config', get_current_lang()) from exc
    await journal_config_change(
        db,
        org_id,
        current_user.id,
        module='warehouse',
        subject=f'type-config:{normalized}',
        keys=set(before),
        before=before,
        after=None,
    )

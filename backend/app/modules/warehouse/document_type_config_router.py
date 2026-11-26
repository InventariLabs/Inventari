from typing import Any
from uuid import UUID

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
from app.core.public_api import core_api
from app.core.settings_diff import journal_config_change, record_settings
from app.i18n.service import get_current_lang

from . import document_type_config_service as _svc
from . import document_types as dt
from .models.profile import DocumentTypeConfig
from .schemas import (
    DocumentTypeConfigCreate,
    DocumentTypeConfigOut,
    DocumentTypeConfigUpdate,
)

# The upsert journals the payload's own field names (`keys=set(payload)`),
# so the snapshot-key exporter reads this pair the way it reads a dict
# literal (`AGENTS.md §3`: the declaration sits beside the writer it
# speaks for). The delete endpoint journals the settings the dropped record
# held — the fields the update schema can set, not the row's identity and
# stamps — a universe the model side of this pair names.
AUDIT_PAYLOAD_SCHEMA = ('DocumentTypeConfigCreate', 'DocumentTypeConfig')

router = APIRouter(dependencies=[Depends(require_module('warehouse'))])

#: The settings that point at a storage location. The journal writes the
#: location's name beside each id (AUDIT.md, "A reference is written with
#: its name"), so the Detail column reads a shelf and not eight characters of
#: its id.
_LOCATION_SETTINGS = ('default_source_location_id', 'default_target_location_id')


async def _reading(db: AsyncSession, org_id: UUID, record: Any) -> dict[str, Any]:
    """A type configuration as its journal entry reads it: its settings, and
    the name of each location they point at beside the id."""
    reading = record_settings(record)
    for key in _LOCATION_SETTINGS:
        location_id = getattr(record, key, None)
        if location_id is None:
            continue
        location = await core_api.locations.get_async(db, org_id, location_id)
        if location is not None:
            reading[key.removesuffix('_id') + '_name'] = location.name
    return reading


def _with_names(keys: set[str]) -> set[str]:
    """The keys a journal entry may carry: each location setting also brings
    its name."""
    return keys | {
        key.removesuffix('_id') + '_name' for key in keys if key in _LOCATION_SETTINGS
    }


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
    keys = _with_names(set(payload))
    before = (
        {
            key: value
            for key, value in (await _reading(db, org_id, previous)).items()
            if key in keys
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
        keys=keys,
        before=before,
        after=await _reading(db, org_id, result),
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
    before = await _reading(db, org_id, previous) if previous is not None else {}
    try:
        await _svc.delete_type_config(db, org_id, normalized)
    except ValueError as exc:
        raise NotFoundException('document_type_config', get_current_lang()) from exc
    await journal_config_change(
        db,
        org_id,
        current_user.id,
        module='warehouse',
        subject=f'type-config:{normalized}',
        keys=set(before) & _with_names(set(DocumentTypeConfigUpdate.model_fields)),
        before=before,
        after=None,
    )

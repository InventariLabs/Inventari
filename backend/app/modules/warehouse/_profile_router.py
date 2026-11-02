"""Document profile / presets endpoints — extracted from main router."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts.dtos import UserContextDTO
from app.core.deps import (
    get_async_db,
    get_current_user_context,
    require_org,
    require_permission,
)
from app.core.exceptions import AppException
from app.core.modules import require_module
from app.core.settings_diff import journal_config_change, record_settings
from app.i18n.service import get_current_lang, get_error_message

from . import services
from .models.profile import DocumentProfile
from .schemas import (
    DocumentProfileSchema,
    DocumentProfileUpdate,
    PickOrderStrategySchema,
)

# Both journaling endpoints here cut their key universe from the profile's
# fields — `update_profile` from `data.model_fields_set`, the preset
# endpoint from a preset dict whose keys are profile fields too — so the
# snapshot-key exporter reads this pair the way it reads a dict literal
# (`AGENTS.md §3`: the declaration sits beside the writer it speaks for).
AUDIT_PAYLOAD_SCHEMA = ('DocumentProfileUpdate', 'DocumentProfile')

router = APIRouter(dependencies=[Depends(require_module('warehouse'))])


@router.get('/profile', response_model=DocumentProfileSchema)
async def get_profile(
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> Any:
    return await services.get_or_create_profile(db, org_id)


@router.put('/profile', response_model=DocumentProfileSchema)
async def update_profile(
    data: DocumentProfileUpdate,
    _: None = require_permission('warehouse:manage'),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> Any:
    profile: DocumentProfile = await services.get_or_create_profile(db, org_id)
    keys = set(data.model_fields_set)
    before = {
        key: value for key, value in record_settings(profile).items() if key in keys
    }
    result = await services.update_profile(db, org_id, data)
    await journal_config_change(
        db,
        org_id,
        current_user.id,
        module='warehouse',
        subject='profile',
        keys=keys,
        before=before,
        after=result,
    )
    return result


@router.get(
    # list-envelope-exception: the registered pick orders are a fixed
    # vocabulary of names — a module registers each at import time, the way
    # the preset names above are written into the code — not a growing
    # collection of rows to page.
    '/profile/pick-order-strategies',
    response_model=list[PickOrderStrategySchema],
)
async def list_pick_order_strategies(
    current_user: UserContextDTO = Depends(get_current_user_context),
) -> Any:
    """Every pick order the registry holds, for the warehouse settings' chooser.

    The default is among them — registered the same way as a module's own —
    and each is offered under the label its owning module's catalogue gives
    it (``label_key``). A module switched off for the organization still
    lists; its strategy walks the default until the module is back, which is
    what a saved choice needs it to do.
    """
    from .pick_order_strategies import (
        DEFAULT_PICK_ORDER_STRATEGY,
        pick_order_strategies,
        strategy_label_key,
    )

    return [
        PickOrderStrategySchema(
            name=name,
            module=module,
            label_key=strategy_label_key(module, name),
            is_default=name == DEFAULT_PICK_ORDER_STRATEGY,
        )
        for name, (module, _) in pick_order_strategies().items()
    ]


@router.post('/profile/apply-preset/{preset}', response_model=DocumentProfileSchema)
async def apply_profile_preset(
    preset: str,
    _: None = require_permission('warehouse:manage'),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> Any:
    profile = await services.get_or_create_profile(db, org_id)
    # An unknown preset is the service's 400 refusal; the keys lookup below
    # must not turn that refusal into a 500, so it answers empty for a name
    # nobody declares and journals nothing.
    keys = set(services.PRESETS[preset]) if preset in services.PRESETS else set()
    before = {
        key: value for key, value in record_settings(profile).items() if key in keys
    }
    result = await services.apply_preset(db, org_id, preset)
    await journal_config_change(
        db,
        org_id,
        current_user.id,
        module='warehouse',
        subject=f'profile-preset:{preset}',
        keys=keys,
        before=before,
        after=result,
    )
    return result


@router.get(
    '/profile/presets',
    # list-envelope-exception: the preset names are a vocabulary written into the code
    response_model=list[str],
)
async def list_presets(
    current_user: UserContextDTO = Depends(get_current_user_context),
) -> list[str]:
    return list(services.PRESETS.keys())


@router.get('/profile/presets/{preset_name}', response_model=DocumentProfileUpdate)
async def get_preset_values(
    preset_name: str,
    current_user: UserContextDTO = Depends(get_current_user_context),
) -> DocumentProfileUpdate:
    if preset_name not in services.PRESETS:
        lang = get_current_lang()
        raise AppException(
            status_code=404,
            code='PRESET_NOT_FOUND',
            message=get_error_message(
                'document_preset_unknown',
                lang,
                name=preset_name,
                available=', '.join(services.PRESETS),
            ),
            extra={'lang': lang},
        )
    preset = dict(services.PRESETS[preset_name])
    preset['name'] = preset_name
    return DocumentProfileUpdate.model_validate(preset)

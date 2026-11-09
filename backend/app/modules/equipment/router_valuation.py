from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserContextDTO
from app.core.deps import get_async_db, get_current_user_context, require_org
from app.core.exceptions import (
    ForbiddenException,
    NotFoundException,
)
from app.i18n.service import get_current_lang, get_error_message

from .schemas import (
    AssetValuation,
    FleetValuation,
)

router = APIRouter()

#: Who may read the fleet's purchase and book totals: the overview shows them
#: to administrators and managers only, because they are the organization's
#: finances, and the API holds the same line.
_FINANCE_ROLES = frozenset({'admin', 'manager'})


def _require_finance_reader(
    current_user: UserContextDTO = Depends(get_current_user_context),
) -> None:
    if current_user.is_superuser or current_user.role in _FINANCE_ROLES:
        return
    raise ForbiddenException(
        get_error_message('insufficient_permissions', get_current_lang())
    )


@router.get(
    '/valuation',
    response_model=FleetValuation,
    dependencies=[Depends(_require_finance_reader)],
)
async def fleet_valuation(
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    org_id = require_org(current_user)
    from .depreciation_service import get_fleet_valuation_async

    return await get_fleet_valuation_async(db, org_id)


@router.get('/{item_id}/valuation', response_model=AssetValuation)
async def asset_valuation(
    item_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    """One asset's purchase price and book value, for its own card.

    Not held to the finance roles of the fleet total above, deliberately: the
    total is the organization's finances added up, while one asset's price is
    a fact on its card — the Info tab prints it from the record itself to
    whoever reads the register, and the overview says a member still sees the
    value of one asset on its own page. What bounds this read is the asset:
    a record the register does not list is 404 here.
    """
    org_id = require_org(current_user)
    from .depreciation_service import get_asset_valuation_async

    result = await get_asset_valuation_async(db, org_id, item_id)
    if not result:
        raise NotFoundException(resource='item') from None
    return result

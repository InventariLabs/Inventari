from fastapi import APIRouter, Depends, Query

from app.core.deps import get_current_user_context
from app.core.exceptions import NotFoundException
from app.core.product_profiles import ProductProfile, get_all_profiles, get_profile
from app.schemas.pagination import PaginatedResponse

router = APIRouter()


@router.get('', response_model=PaginatedResponse[ProductProfile])
async def list_profiles(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _current_user=Depends(get_current_user_context),
) -> PaginatedResponse[ProductProfile]:
    """Return all available product profiles for onboarding selection."""
    return PaginatedResponse[ProductProfile].from_full_list(
        get_all_profiles(), offset=offset, limit=limit
    )


@router.get('/{profile_id}', response_model=ProductProfile)
async def get_profile_by_id(
    profile_id: str,
    _current_user=Depends(get_current_user_context),
) -> ProductProfile:
    """Return a single product profile by ID."""
    profile = get_profile(profile_id)
    if not profile:
        raise NotFoundException('profile')
    return profile

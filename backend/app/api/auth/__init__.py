from fastapi import APIRouter

from ._profile import router as profile_router
from ._registration import router as registration_router
from ._reset import router as reset_router
from ._tokens import router as tokens_router

router = APIRouter()

router.include_router(registration_router)
router.include_router(tokens_router)
router.include_router(profile_router)
router.include_router(reset_router)

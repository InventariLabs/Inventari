"""The register's one door: put certificates on file.

The document page's "File the certificates" button sends the numbers its
lines carry; the receiving rule lets the receipt be booked once they are here.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserContextDTO
from app.core.module_sdk import (
    get_async_db,
    get_current_user_context,
    require_module,
    require_org,
    require_read_write,
)

from .certificates import file_certificates_async
from .models import NUMBER_MAX_LENGTH

router = APIRouter(
    dependencies=[
        Depends(require_module('lot_certificates')),
        require_read_write('lot_certificates:read', 'lot_certificates:write'),
    ]
)


class FileCertificatesRequest(BaseModel):
    numbers: list[Annotated[str, Field(max_length=NUMBER_MAX_LENGTH)]] = Field(
        min_length=1, max_length=200
    )


class FiledCertificatesResponse(BaseModel):
    #: The numbers this request put on file; the ones already there are not
    #: repeated.
    filed: list[str]


@router.post('/certificates', response_model=FiledCertificatesResponse)
async def file_certificates(
    body: FileCertificatesRequest,
    db: AsyncSession = Depends(get_async_db),
    org_id: UUID = Depends(require_org),
    user: UserContextDTO = Depends(get_current_user_context),
) -> FiledCertificatesResponse:
    filed = await file_certificates_async(db, org_id, body.numbers, user.id)
    await db.commit()
    return FiledCertificatesResponse(filed=filed)

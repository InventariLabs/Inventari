"""Packing a picked dispatch — packages, their contents, the slip and the label.

Every write answers with the whole packing view: the screen that fills a
package needs to see, after each scan, what is still left to pack, and a
second round trip for that would be the common case rather than the rare one.
"""

from __future__ import annotations

import io
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts.dtos import UserContextDTO
from app.core.deps import get_async_db, get_current_user_context, require_org
from app.core.exceptions import map_service_errors
from app.core.modules import require_module
from app.core.utils import build_pdf_response, content_disposition, sanitize_filename

from . import packing_service as svc
from .packing_schemas import (
    PackageCreate,
    PackageLabelPrint,
    PackageLabelQueued,
    PackageLineSet,
    PackageScan,
    PackageUpdate,
    PackingView,
)

router = APIRouter(dependencies=[Depends(require_module('warehouse'))])


async def _view(db: AsyncSession, org_id: UUID, doc_id: UUID) -> PackingView:
    return await svc.view_async(db, org_id, doc_id)


@router.get('/{doc_id}/packages', response_model=PackingView)
@map_service_errors
async def list_packages(
    doc_id: UUID,
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> Any:
    """The dispatch's packages, and what of each line is left to pack."""
    return await _view(db, org_id, doc_id)


@router.post(
    '/{doc_id}/packages',
    response_model=PackingView,
    status_code=status.HTTP_201_CREATED,
)
@map_service_errors
async def create_package(
    doc_id: UUID,
    data: PackageCreate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> Any:
    """Open an empty package under the next number."""
    await svc.create_package_async(
        db, org_id, doc_id, current_user.id, weight_kg=data.weight_kg
    )
    return await _view(db, org_id, doc_id)


@router.post(
    '/{doc_id}/packages/pack-all',
    response_model=PackingView,
    status_code=status.HTTP_201_CREATED,
)
@map_service_errors
async def pack_all(
    doc_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> Any:
    """One package with everything picked and not packed yet."""
    await svc.pack_all_async(db, org_id, doc_id, current_user.id)
    return await _view(db, org_id, doc_id)


@router.patch('/{doc_id}/packages/{package_id}', response_model=PackingView)
@map_service_errors
async def update_package(
    doc_id: UUID,
    package_id: UUID,
    data: PackageUpdate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> Any:
    """Record the package's weight, or clear it with a named null."""
    await svc.update_package_async(
        db,
        org_id,
        doc_id,
        package_id,
        current_user.id,
        data.model_dump(include=data.model_fields_set),
    )
    return await _view(db, org_id, doc_id)


@router.put(
    '/{doc_id}/packages/{package_id}/lines/{line_id}', response_model=PackingView
)
@map_service_errors
async def set_package_line(
    doc_id: UUID,
    package_id: UUID,
    line_id: UUID,
    data: PackageLineSet,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> Any:
    """Set how much of a document line the package holds; zero takes it out."""
    await svc.set_line_async(
        db, org_id, doc_id, package_id, line_id, data.quantity, current_user.id
    )
    return await _view(db, org_id, doc_id)


@router.post('/{doc_id}/packages/{package_id}/scan', response_model=PackingView)
@map_service_errors
async def scan_into_package(
    doc_id: UUID,
    package_id: UUID,
    data: PackageScan,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> Any:
    """Put one more of the scanned product into the package."""
    await svc.scan_into_package_async(
        db, org_id, doc_id, package_id, data.code, data.quantity, current_user.id
    )
    return await _view(db, org_id, doc_id)


@router.delete('/{doc_id}/packages/{package_id}', response_model=PackingView)
@map_service_errors
async def delete_package(
    doc_id: UUID,
    package_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> Any:
    """Remove a package; its contents go back to the unpacked picked goods."""
    await svc.delete_package_async(db, org_id, doc_id, package_id, current_user.id)
    return await _view(db, org_id, doc_id)


@router.get('/{doc_id}/packing-slip', response_class=Response)
@map_service_errors
async def download_packing_slip(
    doc_id: UUID,
    lang: str = Query(default='en', pattern='^[a-z]{2}(-[A-Z]{2})?$'),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> Response:
    """The packing slip of every package of the dispatch, one sheet each."""
    name, pdf = await svc.packing_slip_pdf_async(db, org_id, doc_id, None, lang)
    return build_pdf_response(pdf, sanitize_filename(name, prefix='packing_slip'))


@router.get('/{doc_id}/packages/{package_id}/packing-slip', response_class=Response)
@map_service_errors
async def download_package_packing_slip(
    doc_id: UUID,
    package_id: UUID,
    lang: str = Query(default='en', pattern='^[a-z]{2}(-[A-Z]{2})?$'),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> Response:
    """The packing slip of one package."""
    name, pdf = await svc.packing_slip_pdf_async(db, org_id, doc_id, package_id, lang)
    return build_pdf_response(pdf, sanitize_filename(name, prefix='packing_slip'))


@router.get('/{doc_id}/packages/{package_id}/label', response_class=StreamingResponse)
@map_service_errors
async def download_package_label(
    doc_id: UUID,
    package_id: UUID,
    width: float = Query(50.0, ge=10.0, le=300.0),
    height: float = Query(24.0, ge=5.0, le=300.0),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> StreamingResponse:
    """The package's label as a PNG, drawn by the printing module."""
    filename, png = await svc.package_label_png_async(
        db, org_id, doc_id, package_id, width_mm=width, height_mm=height
    )
    return StreamingResponse(
        io.BytesIO(png),
        media_type='image/png',
        headers={'Content-Disposition': content_disposition(filename)},
    )


@router.post(
    '/{doc_id}/packages/{package_id}/label/print',
    response_model=PackageLabelQueued,
    status_code=status.HTTP_201_CREATED,
)
@map_service_errors
async def print_package_label(
    doc_id: UUID,
    package_id: UUID,
    data: PackageLabelPrint,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> Any:
    """Send the package's label to a printer's queue, as the download draws it."""
    job_id = await svc.print_package_label_async(
        db,
        org_id,
        doc_id,
        package_id,
        current_user.id,
        agent_id=data.agent_id,
        width_mm=data.width_mm,
        height_mm=data.height_mm,
    )
    return PackageLabelQueued(job_id=job_id)

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserContextDTO
from app.core.deps import get_async_db, get_current_user_context, require_org
from app.core.exceptions import map_service_errors
from app.i18n.service import Language, get_lang_from_header

from .schemas import PlaceholderInfo

router = APIRouter()


@router.get('/assignments/{assignment_id}/protocol/html', response_class=HTMLResponse)
@map_service_errors
async def get_protocol_html(
    assignment_id: UUID,
    template_id: UUID | None = Query(None),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    lang: Language = Depends(get_lang_from_header),
    org_id: UUID = Depends(require_org),
) -> HTMLResponse:
    from .protocol_service import render_protocol_html

    html = await render_protocol_html(db, org_id, assignment_id, template_id, lang=lang)
    return HTMLResponse(content=html)


@router.get('/assignments/{assignment_id}/protocol/pdf')
@map_service_errors
async def get_protocol_pdf(
    assignment_id: UUID,
    template_id: UUID | None = Query(None),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    lang: Language = Depends(get_lang_from_header),
    org_id: UUID = Depends(require_org),
) -> Response:
    from .protocol_service import render_protocol_pdf_async

    pdf_bytes = await render_protocol_pdf_async(
        db, org_id, assignment_id, template_id, lang=lang
    )

    filename = f'protocol-{str(assignment_id)[:8]}.pdf'
    return Response(
        content=pdf_bytes,
        media_type='application/pdf',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )


@router.get(
    '/protocol/placeholders',
    # list-envelope-exception: the placeholder catalogue, a vocabulary in the code
    response_model=list[PlaceholderInfo],
    dependencies=[Depends(require_org)],
)
async def get_placeholders(
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> Any:
    # The custom-field half is a value, not a gate: what it lists is what
    # this organization's categories define.
    from .protocol_service import protocol_placeholders_async

    return await protocol_placeholders_async(db, org_id)

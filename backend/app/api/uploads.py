from fastapi import APIRouter, Cookie, Depends, Request, status
from fastapi.responses import JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import API_KEY_HEADER, UserContextDTO
from app.core.contributions import contribution_registry
from app.core.deps import get_async_db, require_org
from app.core.exceptions import catalogue_status_refusal
from app.core.file_storage.service import FileStorageService
from app.core.logging import get_logger
from app.core.uploads.resolvers import CORE_RESOLVERS
from app.core.utils import content_disposition
from app.services.identity_service import (
    _load_user_context,
    get_current_user,
    user_from_refresh_cookie,
)

logger = get_logger(__name__)

router = APIRouter()


def _refused(status_code: int, key: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={'detail': catalogue_status_refusal(key, status_code).detail},
    )


def _forbidden() -> JSONResponse:
    return _refused(403, 'forbidden')


def _not_found() -> JSONResponse:
    return _refused(404, 'not_found')


async def _resolve(db: AsyncSession, file_path: str, org_id):
    """Return OwnedFileMeta for the first resolver that owns ``file_path``.

    Core resolvers are consulted first, then any module-registered
    ``upload_path_resolvers`` contributions.
    """
    resolvers = [*CORE_RESOLVERS, *contribution_registry.get('upload_path_resolvers')]
    for resolver in resolvers:
        meta = await resolver.resolve(db, file_path, org_id)
        if meta is not None:
            return meta
    return None


async def get_media_user_context(
    request: Request,
    refresh_token: str | None = Cookie(None),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> UserContextDTO:
    """Auth for media serving: Bearer header first, refresh cookie fallback.

    Mirrors ``get_current_user_context`` for XHR/fetch calls (which carry the
    Bearer token), and additionally accepts the HttpOnly ``refresh_token``
    cookie for browser-native requests (``<img src>``, attachment download)
    that cannot set the header.
    """
    # 1. Bearer or API-key header — resolve through the standard dependency.
    api_key = request.headers.get(API_KEY_HEADER)
    auth_header = request.headers.get('Authorization') or ''
    token = (
        auth_header.split(' ', 1)[1]
        if auth_header.lower().startswith('bearer ')
        else None
    )
    if api_key or token:
        bearer_user = await get_current_user(
            request=request, token=token, api_key=api_key, db=db
        )
        return await _load_user_context(db, bearer_user)

    # 2. Refresh-token cookie fallback.
    cookie_user = await user_from_refresh_cookie(db, refresh_token)
    if cookie_user is None:
        raise catalogue_status_refusal(
            'not_authenticated',
            status.HTTP_401_UNAUTHORIZED,
            headers={'WWW-Authenticate': 'Bearer'},
        )
    return await _load_user_context(db, cookie_user)


@router.get('/uploads/{filepath:path}', response_model=None)
async def serve_upload(
    filepath: str,
    current_user: UserContextDTO = Depends(get_media_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
):
    """Serve an uploaded file with organization ownership verification.

    Ownership is resolved by the upload path resolvers (core + module
    contributions) — each covers one file family (item covers, attachments,
    recipe covers, equipment attachments, …). File bytes are read through the
    storage abstraction so this works for any configured backend (local or S3).

    Authentication is primarily the ``Authorization: Bearer`` header (XHR/fetch
    calls). Browser-native requests (``<img>``, attachment download) that can't
    set that header fall back to the HttpOnly ``refresh_token`` cookie.
    """
    org_id = require_org(current_user)

    # Path-traversal guard: reject any attempt to escape the uploads namespace.
    if '..' in filepath.split('/'):
        return _forbidden()

    meta = await _resolve(db, filepath, org_id)
    if meta is None:
        return _not_found()

    # Reads go straight to the storage service on the absolute path from the
    # URL; ownership was already verified by the resolvers above.
    service = FileStorageService()
    if not await service.exists(filepath):
        return _not_found()

    content = (await service.get(filepath)).read()
    return Response(
        content=content,
        media_type=meta.content_type or 'application/octet-stream',
        headers={
            'Content-Disposition': content_disposition(meta.display_name, 'inline')
        }
        if meta.display_name
        else None,
    )

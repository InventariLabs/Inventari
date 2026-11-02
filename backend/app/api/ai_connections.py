"""Router for /api/v1/ai-connections.

Thin endpoint handlers — all data access flows through
:mod:`app.core.public_api.core_api.ai_connections`. Per AGENTS.md
§Backend.2 (canonical pattern):

- ``require_org`` (``app.core.deps``) raises 403 if no organisation on
  the user context. Every endpoint that touches per-org data injects it
  via ``org_id: UUID = Depends(require_org)``.
- The five writes carry ``require_permission(ORG_SETTINGS_WRITE)``:
  whose key pays for the org's AI and which provider answers its
  purposes is administration, not ordinary work — tenancy alone left a
  read-only account free to spend it.
- ``HTTPException`` mapping: ValueError -> 400, ``NotFoundException``
  from the public API -> 404, IntegrityError / unique-constraint
  conflict -> 409, ``ConnectionStillBoundError`` -> 409.

Endpoints:

- ``GET    /``                              List connections.
- ``POST   /``                              Create.
- ``GET    /purposes``                      List purposes with binding.
- ``PUT    /bindings``                      Set a purpose->connection binding.
- ``GET    /{id}``                          Read one (404 cross-tenant).
- ``PUT    /{id}``                          Update (PATCH semantics).
- ``DELETE /{id}``                          Delete (409 if bound).

Note: ``/purposes`` and ``/bindings`` are declared BEFORE the
``/{conn_id}`` routes. FastAPI matches in declaration order, so the
parameterised ``PUT /{conn_id}`` would otherwise swallow
``PUT /bindings`` and the ``GET /{conn_id}`` route would shadow
``GET /purposes``. The type hint (``UUID``) does not gate matching —
string parsing happens after the path is matched.

The router is registered in app/main.py with prefix
``/api/v1/ai-connections``.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import (
    AiConnectionCreateDTO,
    AiConnectionDTO,
    AiConnectionUpdateDTO,
    AiPurposeDTO,
    SystemPermission,
)
from app.core.deps import get_async_db, require_org, require_permission
from app.core.exceptions import (
    ConflictException,
    NotFoundException,
    ServiceRejectionError,
    ValidationException,
    catalogue_refusal,
    map_service_errors,
    rejection_code,
)
from app.core.logging import get_logger
from app.core.public_api import core_api
from app.core.public_api.ai_connections import (
    ConnectionStillBoundError,
)
from app.core.public_api.llm import (
    LlmProviderRefusalError,
    LlmTimeoutError,
    LlmTransportError,
    classify_provider_refusal,
)
from app.i18n.service import get_current_lang, get_error_message
from app.schemas.ai_connection import (
    SetBindingRequest,
    TestConnectionRequest,
)
from app.schemas.pagination import PaginatedResponse

router = APIRouter()
logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Static paths (must come BEFORE /{conn_id} — see module docstring)
# ---------------------------------------------------------------------------


@router.get('', response_model=PaginatedResponse[AiConnectionDTO])
async def list_connections(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    org_id: UUID = Depends(require_org),
    db: AsyncSession = Depends(get_async_db, scope='function'),
):
    """List the caller's org connections."""
    connections = await core_api.ai_connections.list_async(db, org_id)
    return PaginatedResponse.from_full_list(connections, offset=offset, limit=limit)


@router.post('', response_model=AiConnectionDTO)
async def create_connection(
    data: AiConnectionCreateDTO,
    org_id: UUID = Depends(require_org),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ORG_SETTINGS_WRITE),
):
    """Create a new connection.

    Returns 409 on the unique-constraint violation
    (uq_ai_connections_org_name). The error wraps the violation
    raised by :class:`AiConnectionService.create` so that callers
    see a domain-shape error, not a raw SQLAlchemy message.
    """
    try:
        return await core_api.ai_connections.create_async(db, org_id, data)
    except IntegrityError as exc:
        # Service has already rolled the transaction back.
        raise ConflictException(
            'AI_CONNECTION_NAME_TAKEN',
            get_error_message(
                'ai_connection_name_taken',
                get_current_lang(),
                name=data.name,
            ),
        ) from exc


@router.get('/purposes', response_model=PaginatedResponse[AiPurposeDTO])
async def list_purposes(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    org_id: UUID = Depends(require_org),
    db: AsyncSession = Depends(get_async_db, scope='function'),
):
    """List every registered purpose with the caller's binding UUID."""
    purposes = await core_api.ai_connections.list_purposes_async(db, org_id)
    return PaginatedResponse.from_full_list(purposes, offset=offset, limit=limit)


@router.put('/bindings')
@map_service_errors
async def set_binding(
    data: SetBindingRequest,
    org_id: UUID = Depends(require_org),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ORG_SETTINGS_WRITE),
):
    """Set a purpose->connection binding on org settings.

    400 when the purpose key is not registered.
    """
    await core_api.ai_connections.set_binding_async(
        db, org_id, data.purpose_key, data.connection_id
    )
    return {'bound': True}


@router.post('/test')
async def test_connection_endpoint(
    data: TestConnectionRequest,
    org_id: UUID = Depends(require_org),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ORG_SETTINGS_WRITE),
):
    """Test a connection: credentials first, then the output contract.

    Accepts either an existing ``connection_id`` (uses the stored cipher)
    OR an inline draft (``provider`` + ``api_key`` + ``api_base_url`` +
    ``model_name`` + ``capabilities``) so the UI can test BEFORE saving.

    400 means the provider never answered — wrong key, wrong URL, unreachable
    host. 200 with ``contract.ok == false`` means it answered and the model
    could not deliver the agreed shape; the two are different problems with
    different fixes, so they get different outcomes. 429 means the
    organization has spent the AI budget this test would draw on — it is a
    billed call, so the ceiling gates it before anything is sent.

    Declared BEFORE ``/{conn_id}`` so the parameterised routes don't
    swallow the literal ``/test`` path.
    """

    if data.connection_id is None and data.provider is None:
        raise catalogue_refusal('ai_connection_target_required', field='connection_id')

    try:
        result = await core_api.ai_connections.test_connection_async(
            db,
            org_id,
            connection_id=data.connection_id,
            provider=data.provider.value if data.provider else None,
            api_key=data.api_key,
            api_base_url=data.api_base_url,
            model_name=data.model_name,
            capabilities=[c.value for c in data.capabilities],
        )
    except HTTPException:
        # Already an answer: the quota gate refuses with its own status and
        # body (429 with the numbers the counter measured). Wrapping it in the
        # 400 below would report a spent budget as a broken connection.
        raise
    except ServiceRejectionError:
        # A keyed refusal (the URL guard's) already names its cause; let it
        # reach the global ValueError handler, which speaks the key in the
        # request language. The technical catch below would prefix it in
        # English and bury the key inside the sentence.
        raise
    except LlmProviderRefusalError as exc:
        # A key, budget, or model name the provider refuses is the most
        # common first-setup state, and this button is where it is found.
        # The named sentence replaces the provider's body, which has no
        # place in the form and nothing the administrator can act on.
        key = classify_provider_refusal(exc.status_code) or 'llm_provider_unreachable'
        # ^ provider_refusal builds this type only for codes the classifier
        # names; the fallback is unreachable, kept so the contract is total.
        lang = get_current_lang()
        if exc.connection_name and exc.model_name:
            detail = get_error_message(
                key, lang, name=exc.connection_name, model=exc.model_name
            )
        else:
            detail = get_error_message(f'{key}_generic', lang)
        # The code is the 503's elsewhere (``app.main``), with or without
        # the connection's name in the sentence.
        raise ValidationException(
            detail, extra={'lang': lang}, code=rejection_code(key)
        ) from exc
    except LlmTransportError as exc:
        # The probe never got through, or got through and the model was still
        # thinking. The two are different errands — an address to check versus
        # a limit to raise — and collapsing them into "check the address and
        # try again" read a local model loading its weights on the first call
        # after a switch as an unreachable provider. Same keys ``app.main``
        # names everywhere else, but a 400: this endpoint's verdict is "the
        # connection did not pass", and the form reads the sentence out of a
        # 4xx (``extractApiError`` keeps 5xx details out of the screen).
        timed_out = isinstance(exc, LlmTimeoutError)
        logger.warning(
            'Connection test: %s: %s',
            'the model ran out of time' if timed_out else 'could not reach the model',
            exc,
        )
        key = 'llm_provider_timeout' if timed_out else 'llm_provider_unreachable'
        lang = get_current_lang()
        if exc.connection_name and exc.model_name:
            detail = get_error_message(
                key, lang, name=exc.connection_name, model=exc.model_name
            )
        else:
            detail = get_error_message(f'{key}_generic', lang)
        raise ValidationException(
            detail, extra={'lang': lang}, code=rejection_code(key)
        ) from exc
    except Exception as exc:
        # An unexpected failure (a bug, not a named refusal) still answers in
        # the reader's language; the exception that caused it goes to the log,
        # where a raw sentence would be actionable and on screen would not.
        logger.warning('Connection test failed: %s', exc, exc_info=True)
        raise catalogue_refusal('llm_connection_test_failed') from exc

    if result.get('error') == 'not_found':
        raise NotFoundException(resource='ai_connection')
    # A model that answered off-contract is a verdict, not an error: the
    # caller needs the detail (what it returned, how many tries) to decide
    # whether to change the model, so it travels as a 200 payload.
    return result


# ---------------------------------------------------------------------------
# Parameterised paths (declared LAST so they don't shadow /bindings etc.)
# ---------------------------------------------------------------------------


@router.get('/{conn_id}', response_model=AiConnectionDTO)
async def get_connection(
    conn_id: UUID,
    org_id: UUID = Depends(require_org),
    db: AsyncSession = Depends(get_async_db, scope='function'),
):
    """Read one — 404 on missing OR cross-tenant. The public API
    refuses to leak existence across orgs, returning None which we
    map to 404."""
    result = await core_api.ai_connections.get_async(db, org_id, conn_id)
    if result is None:
        raise NotFoundException(resource='ai_connection')
    return result


@router.put('/{conn_id}', response_model=AiConnectionDTO)
async def update_connection(
    conn_id: UUID,
    data: AiConnectionUpdateDTO,
    org_id: UUID = Depends(require_org),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ORG_SETTINGS_WRITE),
):
    """PATCH-style update. ``api_key='**********'`` means leave the
    existing cipher alone.

    Returns 409 when the rename collides with another connection in
    the same org (uq_ai_connections_org_name) — same contract as
    create, so the UI gets a domain error instead of a 500."""
    try:
        result = await core_api.ai_connections.update_async(db, org_id, conn_id, data)
    except IntegrityError as exc:
        raise ConflictException(
            'AI_CONNECTION_NAME_TAKEN',
            get_error_message(
                'ai_connection_name_taken',
                get_current_lang(),
                name=data.name,
            ),
        ) from exc
    if result is None:
        raise NotFoundException(resource='ai_connection')
    return result


@router.delete('/{conn_id}')
async def delete_connection(
    conn_id: UUID,
    org_id: UUID = Depends(require_org),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ORG_SETTINGS_WRITE),
):
    """Delete a connection. 409 when the row is still bound to any
    declared purpose (caller must detach the binding first)."""
    try:
        deleted = await core_api.ai_connections.delete_async(db, org_id, conn_id)
    except ConnectionStillBoundError as exc:
        # The core API translated the refusal; the router gives it the
        # stable code a client can branch on.
        raise ConflictException('CONNECTION_STILL_BOUND', str(exc)) from exc
    if not deleted:
        raise NotFoundException(resource='ai_connection')
    return {'deleted': True}

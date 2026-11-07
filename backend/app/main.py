"""FastAPI application factory and module/router wiring.

The startup/shutdown logic lives in :mod:`app._lifespan`; the custom
ASGI middlewares live in :mod:`app._middleware`. This module is
responsible for creating the ``FastAPI`` instance, attaching exception
handlers, configuring CORS/security headers, and including all
v1 routers (core + dynamic modules).
"""

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from sqlalchemy.exc import DBAPIError, IntegrityError

from app._lifespan import lifespan
from app._middleware import (
    ApiKeyBearerDeprecationMiddleware,
    BodySizeLimitMiddleware,
    LanguageMiddleware,
    PerformanceMiddleware,
    RequestIDMiddleware,
)
from app.api.about import router as about_router
from app.api.admin import router as admin_router
from app.api.ai_connections import router as ai_connections_router
from app.api.announcements import router as announcements_router
from app.api.attachments import router as attachments_router
from app.api.audit_log import router as audit_log_router
from app.api.auth import router as auth_router
from app.api.categories import router as categories_router
from app.api.demo import router as demo_router
from app.api.invitations_public import (
    router_public as invitation_public_router,
)
from app.api.item_pagination import router as item_pagination_router
from app.api.items import router as items_router
from app.api.labels import router as labels_router
from app.api.modules import router as modules_router
from app.api.notifications import router as notifications_router
from app.api.onboarding import router as onboarding_router
from app.api.organizations import router as organizations_router
from app.api.partners import router as partners_router
from app.api.profiles import router as profiles_router
from app.api.roles import router as roles_router
from app.api.stock_as_of import router as stock_as_of_router
from app.api.stock_lots import router as stock_lots_router
from app.api.stock_moves import router as stock_moves_router
from app.api.stock_quants import router as stock_quants_router
from app.api.storage_types import router as storage_types_router
from app.api.storages import router as storages_router
from app.api.uoms import router as uoms_router
from app.api.uploads import router as uploads_router
from app.api.users import router as users_router
from app.api.websocket import router as websocket_router
from app.config import settings
from app.core.audit_actor import audit_actor_scope
from app.core.db_retry import TransactionRetryMiddleware, sqlstate_of
from app.core.file_storage.service import FileStorageService
from app.core.label_rendering import LabelRendererUnavailableError
from app.core.limiter import limiter, rate_limit_exceeded_handler
from app.core.limiter_middleware import RouterAwareSlowAPIMiddleware
from app.core.llm.errors import (
    LlmProviderRefusalError,
    LlmTransportError,
    classify_provider_refusal,
)

# Configure logging
from app.core.logging import configure_logging, get_logger
from app.core.module_identity import ModuleIdentityMiddleware, module_scope
from app.core.module_registry import module_registry
from app.core.module_safety import core_api_url_names
from app.core.scan_providers import (
    BarcodeScanProvider,
    LabelPoolScanProvider,
    StorageScanProvider,
)
from app.core.scan_registry import scan_registry
from app.core.security_headers import SecurityHeadersMiddleware
from app.core.version import get_platform_version
from app.core.worker_recycle import CountRequests

configure_logging()

logger = get_logger('app')

# Initialize File Storage Service
try:
    FileStorageService.initialize_from_settings()
    logger.info('✅ File Storage Service initialized')
except (OSError, ValueError) as e:
    logger.error(f'❌ Failed to initialize File Storage Service: {e}')
    if not settings.DEBUG:
        raise


app = FastAPI(
    title='Inventari API',
    description='Home Inventory Management API',
    version=get_platform_version(),
    # Swagger/ReDoc are dev-only. Exposing the full interactive schema on a
    # public deployment is an unnecessary information surface (the API already
    # requires auth). Gated by DEBUG so CI/local keep `/docs`, prod does not.
    docs_url='/docs' if settings.DEBUG else None,
    redoc_url='/redoc' if settings.DEBUG else None,
    openapi_url='/openapi.json' if settings.DEBUG else None,
    lifespan=lifespan,
    # The journal's actor (who a write belongs to when the credential was an
    # API key) is request-scoped state, and this is the one place every
    # request passes through: it starts empty and is dropped with the
    # response, so no request can be credited with another's key.
    dependencies=[Depends(audit_actor_scope)],
)

# Rate Limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)  # type: ignore[arg-type]


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    from app.i18n.service import get_error_message, get_language_from_accept_header

    logger.exception(
        f'Unhandled exception on {request.method} {request.url.path}: {exc}'
    )
    # Read from the request, not the context variable: this handler runs in the
    # outermost middleware, where the language ``LanguageMiddleware`` set deeper
    # in the stack is no longer visible, so a Polish reader got English here.
    lang = get_language_from_accept_header(request.headers.get('accept-language', ''))
    # A 500 answers in the same envelope as every refusal. The sentence is the
    # catalogue's generic one — an exception's own text names tables, columns
    # and library internals, and belongs in the log above, not on a screen.
    return JSONResponse(
        status_code=500,
        content={
            'detail': {
                'code': 'INTERNAL_ERROR',
                'message': get_error_message('internal_error', lang),
            }
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """422s speak the language the request arrived in.

    FastAPI's default handler passes pydantic's own English sentences
    through untouched, so a Polish session read "String should have at
    most 255 characters" for a field it had just filled in. The translated
    catalog covers the constraint types a person can act on; a type it
    does not carry keeps pydantic's wording rather than being dropped.
    Same payload shape as the default — only the sentences change.

    A validator that refuses with ``ServiceRejectionError('<key>')`` is the
    422's counterpart of the 400 handler's keyed path: pydantic carries the
    exception in ``ctx['error']``, the sentence is resolved here with the
    request language, and the entry says which language that was. Any other
    entry makes no language claim.
    """
    from fastapi.encoders import jsonable_encoder

    from app.core.exceptions import ServiceRejectionError
    from app.i18n._validation import translate_validation_error
    from app.i18n.service import get_current_lang

    lang = get_current_lang()
    detail = []
    for error in exc.errors():
        refusal = (error.get('ctx') or {}).get('error')
        keyed = refusal if isinstance(refusal, ServiceRejectionError) else None
        # jsonable_encoder is what the default handler does too: pydantic's
        # `ctx` can carry live objects (a value_error's ValueError), which
        # JSONResponse refuses.
        error = jsonable_encoder(error)
        if keyed is not None:
            error['msg'] = keyed.sentence(lang)
            error['code'] = keyed.code
            error['lang'] = lang
        else:
            error['msg'] = translate_validation_error(error)
        detail.append(error)
    return JSONResponse(status_code=422, content={'detail': detail})


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    """Map service-layer ``ValueError`` to HTTP 400 (AGENTS.md §3).

    Services raise plain ``ValueError`` for business-rule violations; this
    global handler converts them to a 400 response in the same shape as
    ``ValidationException`` (``{'detail': {'code': ..., 'message': ...}}``)
    so routers no longer need to repeat ``except ValueError: raise ...`` blocks.

    The ``code`` says why: a ``ServiceRejectionError`` answers with the upper-cased
    catalogue key it was raised with (``STORAGE_TYPE_IN_USE``), which a client can
    branch on in any language — also when it was raised inside a validator and
    arrives wrapped in pydantic's ``ValidationError`` (``keyed_refusal``).
    ``VALIDATION_ERROR`` remains only for the answers
    that name no catalogue key: a plain ``ValueError`` still waiting for one, and
    the generic sentence of a library's subclass.

    What the reader sees is decided by provenance (the owner's
    decision: 4xx with a generic message, details in the log — never a 500,
    never the library's words). A sentence this codebase wrote — a plain
    ``ValueError``, or a subclass defined under ``app.*`` — reaches the
    reader as-is. A library's subclass is a defect wearing a 400: pydantic's
    ``ValidationError`` subclasses ``ValueError`` and its text names DTOs and
    echoes ``input_value``, so it is answered with a translated generic
    sentence while the traceback goes to the log.

    The ``lang`` field is a claim about the message text, so it is only made
    for text the handler actually produced: a ``ServiceRejectionError`` carries
    the i18n key it was raised with and gets the translated message plus the
    language, and so does the generic sentence. A plain ``ValueError`` speaks
    its own text — an internal sentence this handler never processed — and
    travels without a language claim rather than a false one.

    Everything the handler answers over is logged with its traceback, keyed
    rejections excepted: they are expected refusals, and logging each would
    bury the tracebacks that separate real defects from refusals.

    ``AppException`` subclasses (``ValidationException``, ``NotFoundException``,
    ``ConflictException``, ...) inherit from ``HTTPException``, not ``ValueError``,
    so they are NOT caught here — they keep their own status codes. Routers that
    need to map a ``ValueError`` to a non-400 status (e.g. 404/409) must still
    catch it explicitly. ``PeriodClosedError`` is caught explicitly upstream
    (mapped to 409) and is never reached by this handler.
    """
    from app.core.exceptions import is_reader_facing_value_error, keyed_refusal
    from app.i18n.service import get_current_lang, get_error_message

    lang = get_current_lang()
    keyed = keyed_refusal(exc)
    if keyed is not None:
        detail: dict[str, str] = {
            'code': keyed.code,
            'message': keyed.sentence(lang),
            'lang': lang,
        }
    elif is_reader_facing_value_error(exc):
        logger.warning(
            'ValueError refused %s %s: %s',
            request.method,
            request.url.path,
            exc,
            exc_info=exc,
        )
        detail = {
            'code': 'VALIDATION_ERROR',
            'message': str(exc) or 'invalid input',
        }
    else:
        logger.error(
            'Unhandled %s on %s %s answered with the generic message',
            type(exc).__name__,
            request.method,
            request.url.path,
            exc_info=exc,
        )
        detail = {
            'code': 'VALIDATION_ERROR',
            'message': get_error_message('invalid_input', lang),
            'lang': lang,
        }
    return JSONResponse(status_code=400, content={'detail': detail})


#: What each stock guard is guarding, in words a caller can act on.
_STOCK_GUARD_MESSAGES = {
    'ck_items_quantity_nonneg': 'stock_would_go_negative',
    'ck_svl_remaining_not_negative': 'stock_would_go_negative',
    # Never more promised than stocked, per (product, shelf, batch, owner)
    # grain, checked at commit over the records and the reservation rows
    # (the core baseline migration).
    'ck_stock_holds_within_stock': 'stock_reserved_over_quantity',
}


@app.exception_handler(IntegrityError)
async def integrity_error_handler(request: Request, exc: IntegrityError):
    """Give a stock guard that fires a name, instead of a bare 500.

    The CHECK constraints on the stock tables are the last line between a bug
    and a shelf holding less than nothing. When one fired, nothing recognised
    it: the exception reached the outermost handler and the caller was told
    "Internal Server Error" — true, and useless to the person who hit it and
    to the log alike.

    Here rather than at each call site, for the same reason as the handler
    above it: a violation can come from any write path, and a rule stated in
    one place cannot go missing from the next one.

    Only the guards this dictionary names. A unique-key clash is a different
    bug with a different answer, and dressing it up as a stock conflict would
    be worse than the 500 it gets today.
    """
    from app.i18n.service import get_current_lang, get_error_message

    detail = str(getattr(exc, 'orig', exc))
    key = next(
        (message for name, message in _STOCK_GUARD_MESSAGES.items() if name in detail),
        None,
    )
    if key is None:
        logger.exception('Unhandled integrity error: %s', exc)
        return JSONResponse(
            status_code=500,
            content={
                'detail': {
                    'code': 'INTERNAL_ERROR',
                    'message': get_error_message('internal_error', get_current_lang()),
                }
            },
        )
    lang = get_current_lang()
    logger.warning('[Stock] guard %s refused a write: %s', key, detail)
    return JSONResponse(
        status_code=409,
        content={
            'detail': {
                'code': 'STOCK_STATE_IMPOSSIBLE',
                'message': get_error_message(key, lang),
                'lang': lang,
            }
        },
    )


#: PostgreSQL's ``character_not_in_repertoire``: text with U+0000 in it, which
#: no text column and no text parameter can hold.
_NULL_CHARACTER_IN_TEXT = '22021'


@app.exception_handler(DBAPIError)
async def unstorable_text_handler(request: Request, exc: DBAPIError):
    """Refuse text with a NUL character in words, instead of a 500.

    The database refuses a statement whose text carries U+0000, and any
    request field can carry one — a list's ``?search=%00`` is a hand-edited
    address away, since the screens keep their search there. The stock on a
    date, the stock list, the products and the partners all answered it with
    a 500. Here rather than at each endpoint, as with the stock guards above:
    the database is where every path that sends text meets.

    Every other database error is raised on unchanged, so it ends where it
    ended before: the retry around the request still sees a deadlock, and
    the outermost handler still answers a defect with the generic 500.
    """
    if sqlstate_of(exc) != _NULL_CHARACTER_IN_TEXT:
        raise exc
    from app.i18n.service import get_current_lang, get_error_message

    lang = get_current_lang()
    logger.warning(
        'Text with a null character refused on %s %s', request.method, request.url.path
    )
    return JSONResponse(
        status_code=400,
        content={
            'detail': {
                'code': 'TEXT_HAS_A_NULL_CHARACTER',
                'message': get_error_message('text_has_a_null_character', lang),
                'lang': lang,
            }
        },
    )


@app.exception_handler(LlmTransportError)
async def llm_transport_error_handler(request: Request, exc: LlmTransportError):
    """Map an unreachable model provider to 503, everywhere it can happen.

    Here rather than at each call site for the same reason as the handler
    below: a model is called from image recognition, from recipe import, and
    from whatever module is added next, and ``httpx`` reports "never got
    through" with exception types that inherit from nothing a router thinks to
    catch. Image recognition answered such a failure with a bare 500 in 1.3
    seconds — before the model had been asked anything — and every other
    caller would have done the same.

    Routers that can say something more specific still catch it first; vision
    does, so it can point at the connection by name.
    """
    from app.core.llm.errors import LlmTimeoutError
    from app.i18n.service import get_current_lang, get_error_message

    # A model that ran out of time was reached. Telling its owner otherwise
    # sends them to check an address that answered, when what they need is a
    # longer limit (LLM_LOCAL_REQUEST_TIMEOUT_SECONDS) or a smaller model.
    timed_out = isinstance(exc, LlmTimeoutError)
    key = 'llm_provider_timeout' if timed_out else 'llm_provider_unreachable'
    logger.warning(
        '%s on %s %s: %s',
        'Model provider timed out' if timed_out else 'Model provider unreachable',
        request.method,
        request.url.path,
        exc,
    )
    lang = get_current_lang()
    if exc.connection_name and exc.model_name:
        message = get_error_message(
            key,
            lang,
            name=exc.connection_name,
            model=exc.model_name,
        )
    else:
        message = get_error_message(f'{key}_generic', lang)
    return JSONResponse(
        status_code=503,
        content={
            'detail': {
                'code': 'LLM_PROVIDER_TIMEOUT'
                if timed_out
                else 'LLM_PROVIDER_UNREACHABLE',
                'message': message,
            }
        },
    )


@app.exception_handler(LlmProviderRefusalError)
async def llm_provider_refusal_handler(request: Request, exc: LlmProviderRefusalError):
    """Map a provider's refusal of the request itself to a named 503.

    A key the provider will not accept, a spent plan or balance, a model
    name it does not know — each is a setting an administrator can fix,
    and each used to arrive as HTTP 500 "An internal error occurred"
    while the log knew it was 401. Here, rather than at every call site,
    for the same reason as the handler above: the same refusal can leave
    image recognition, the nutrition scanner, and recipe import, and the
    next caller will be another module.

    The sentence is the one the vision router uses; the code names the
    exact kind so a client can react without reading prose.
    """
    from app.i18n.service import get_current_lang, get_error_message

    key = classify_provider_refusal(exc.status_code) or 'llm_provider_unreachable'
    # ^ provider_refusal builds this type only for codes the classifier
    # names; the fallback is unreachable, kept so the contract is total.
    logger.warning(
        'Model provider refused %s %s (%s): %s',
        request.method,
        request.url.path,
        key,
        exc,
    )
    lang = get_current_lang()
    if exc.connection_name and exc.model_name:
        message = get_error_message(
            key,
            lang,
            name=exc.connection_name,
            model=exc.model_name,
        )
    else:
        message = get_error_message(f'{key}_generic', lang)
    code = {
        'llm_provider_key_rejected': 'LLM_PROVIDER_KEY_REJECTED',
        'llm_provider_limit': 'LLM_PROVIDER_LIMIT',
        'llm_provider_model_unknown': 'LLM_PROVIDER_MODEL_UNKNOWN',
    }.get(key, 'LLM_PROVIDER_UNREACHABLE')
    return JSONResponse(
        status_code=503,
        content={'detail': {'code': code, 'message': message}},
    )


@app.exception_handler(LabelRendererUnavailableError)
async def label_renderer_unavailable_handler(
    request: Request, exc: LabelRendererUnavailableError
):
    """Map a missing label renderer to 503 (``app.core.label_rendering``).

    Rendering lives in the ``printing`` module and reaches Core through a
    registry; when nothing is registered the request cannot be answered at
    all. That is a temporarily absent capability, not a bug in the request,
    so it gets a 503 — and it is handled here rather than in each of the two
    call sites, which is how the registry docstring already describes it.
    """
    logger.warning(
        f'Label rendering unavailable on {request.method} {request.url.path}: {exc}'
    )
    return JSONResponse(
        status_code=503,
        content={
            'detail': {
                'code': 'LABEL_RENDERER_UNAVAILABLE',
                'message': str(exc),
            }
        },
    )


# --- API Versioning (v1) ---
# Built before module discovery so discovery can read the surface the core
# itself occupies: every first path segment mounted here is a name a dropped
# module directory may not take (``core_api_url_names``).
api_v1_router = APIRouter(prefix='/api/v1')

# Include core routers in v1
api_v1_router.include_router(auth_router, prefix='/auth', tags=['Authentication'])
api_v1_router.include_router(modules_router, prefix='/modules', tags=['Modules'])
api_v1_router.include_router(
    storage_types_router, prefix='/location-types', tags=['Location Types']
)
api_v1_router.include_router(storages_router, prefix='/locations', tags=['Locations'])
api_v1_router.include_router(uoms_router, prefix='/uoms', tags=['Units of Measure'])
api_v1_router.include_router(users_router, prefix='/users', tags=['Users'])
api_v1_router.include_router(
    ai_connections_router,
    prefix='/ai-connections',
    tags=['AI Connections'],
)
api_v1_router.include_router(audit_log_router, tags=['Audit Log'])
api_v1_router.include_router(stock_moves_router, tags=['Stock Ledger'])
api_v1_router.include_router(stock_lots_router, tags=['Stock Ledger'])
api_v1_router.include_router(stock_as_of_router, tags=['Stock Ledger'])
api_v1_router.include_router(stock_quants_router, tags=['Stock Ledger'])
api_v1_router.include_router(roles_router, tags=['Roles & Permissions'])
api_v1_router.include_router(item_pagination_router, prefix='/items', tags=['Items'])
api_v1_router.include_router(items_router, prefix='/items', tags=['Items'])
api_v1_router.include_router(
    categories_router, prefix='/categories', tags=['Categories']
)
api_v1_router.include_router(
    organizations_router, prefix='/organizations', tags=['Organizations']
)
api_v1_router.include_router(labels_router, prefix='/labels', tags=['Labels'])
api_v1_router.include_router(admin_router, prefix='/admin', tags=['Admin'])
api_v1_router.include_router(about_router, prefix='/about', tags=['About'])
api_v1_router.include_router(
    announcements_router, prefix='/announcements', tags=['Announcements']
)
api_v1_router.include_router(
    notifications_router, prefix='/notifications', tags=['Notifications']
)
api_v1_router.include_router(attachments_router, prefix='', tags=['Attachments'])
api_v1_router.include_router(partners_router, prefix='/partners', tags=['Partners'])
api_v1_router.include_router(profiles_router, prefix='/profiles', tags=['Profiles'])
api_v1_router.include_router(
    onboarding_router, prefix='/onboarding', tags=['Onboarding']
)
api_v1_router.include_router(demo_router, prefix='/demo', tags=['Demo'])

# Discover modules (always — TESTING mode still needs module imports so
# SQLAlchemy mapper config can resolve cross-module string relationships.
# Heavier lifecycle (on_startup, Redis, seeding) is gated in lifespan.)
module_registry.discover_modules(extra_reserved_names=core_api_url_names(api_v1_router))

# Register core scan providers with explicit priorities
scan_registry.register(StorageScanProvider(), priority=10)
scan_registry.register(LabelPoolScanProvider(), priority=20)
scan_registry.register(BarcodeScanProvider(), priority=100)  # Fallback

# Register dynamic contributions from modules (e.g. OFFScanProvider with priority 50)
for module in module_registry.get_all():
    try:
        with module_scope(module.metadata.name):
            module.register_contributions()
    except Exception as exc:  # one broken module must not crash app startup
        logger.error(
            f'[Startup] Failed to register contributions for '
            f'{module.metadata.name}: {exc}',
            exc_info=True,
        )
        module_registry.mark_degraded(module.metadata.name)

# Middleware
# The first middleware added sits innermost. The body-size gate goes in
# first on purpose: its refusal then flows back out through every layer
# that decorates a response — CORS for allowed origins, the security
# headers, the performance log — so a refused upload reads like any other
# answer instead of a bare connection-level rejection. What the gate exists
# to protect is handlers reading the body, and nothing between it and the
# handlers reads the body.
app.add_middleware(BodySizeLimitMiddleware)

# Tells the worker's memory watch when a request is in flight, so a worker
# that has grown is replaced between requests, never under one.
app.add_middleware(CountRequests)

# Replay for requests the database aborted (SQLSTATE 40001/40P01). Outside
# the body-size gate on purpose: what it buffers has already passed that
# gate, and its own byte cap is far below it — an upload is never buffered
# just so it could be retried. Inside the decorators (CORS, security
# headers, the performance log) on purpose too: a replay re-enters only the
# app, so one request keeps one request id, one rate-limit count and one
# performance record, and the headers a response carries are built once.
app.add_middleware(TransactionRetryMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        settings.FRONTEND_URL,
        'http://localhost:5173',
        'http://localhost:3000',
    ]
    if settings.DEBUG
    else [settings.FRONTEND_URL],
    allow_credentials=True,
    allow_methods=['GET', 'POST', 'PATCH', 'PUT', 'DELETE', 'OPTIONS'],
    allow_headers=['Content-Type', 'Authorization', 'X-API-Key', 'Accept-Language'],
)

# A cookie that can fail any API call — development only, and only when asked
# for twice. An installation with DEBUG off cannot be switched into it.
if settings.QA_FAULT_INJECTION and settings.DEBUG:
    from app.core.qa_fault_injection import FaultInjectionMiddleware

    app.add_middleware(FaultInjectionMiddleware)
    logger.warning('QA fault injection is ON: a qa_fail cookie will fail API requests.')

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(ApiKeyBearerDeprecationMiddleware)
app.add_middleware(PerformanceMiddleware)
app.add_middleware(LanguageMiddleware)
app.add_middleware(RequestIDMiddleware)
# Identity of the module a request is routed to (app.core.module_identity):
# set before routing so every dependency and endpoint of a module's router
# shares it, and reset with the response. Inert for core routes.
app.add_middleware(ModuleIdentityMiddleware)
app.add_middleware(RouterAwareSlowAPIMiddleware)

# Uploads are served ONLY through this router, which verifies organization
# ownership per file (app/api/uploads.py). Never mount StaticFiles on /uploads:
# it would serve every org's files to anyone who guesses a path. The upload
# root is created by the storage provider itself (file_storage/providers/local.py).
app.include_router(uploads_router)

# Register dynamic modules into v1
for module in module_registry.get_all():
    logger.info(f'[Startup] Registering routes for module: {module.metadata.name}...')
    try:
        m_router = module.register_routes()
        prefix = f'/{module.metadata.name.replace("_", "-")}'
        api_v1_router.include_router(
            m_router, prefix=prefix, tags=[module.metadata.display_name]
        )
        logger.info(f'[Startup] Routes registered for: {module.metadata.name}')
    except Exception as exc:  # one module's routes must not stop the others
        logger.error(
            f'[Startup] Failed to register routes for {module.metadata.name}: {exc}',
            exc_info=True,
        )
        module_registry.mark_degraded(module.metadata.name)

# Mount v1 router to app
app.include_router(api_v1_router)

# WebSocket routes (registered on app directly)
app.include_router(websocket_router, prefix='/api/v1')

# Public (unauthenticated) attestation endpoints — registered outside /api/v1/
try:
    from app.modules.equipment.router_public import (
        router_public as attestation_public_router,
    )

    app.include_router(attestation_public_router)
except ImportError:
    pass

# Public (unauthenticated) invitation check — registered outside /api/v1/
app.include_router(invitation_public_router)


# Compatibility / Root endpoints
@app.get('/api/')
async def api_root():
    return {
        'message': 'Inventari API',
        'current_version': 'v1',
        'versions': ['v1'],
        'docs': '/docs',
    }


@app.get('/')
@limiter.exempt
async def health_check_root():
    return {'status': 'healthy', 'version': get_platform_version()}


@app.get('/health')
@limiter.exempt
async def health_check():
    return {'status': 'healthy', 'version': get_platform_version()}


@app.get('/health/ready')
@limiter.exempt
async def readiness_check():
    """Readiness probe: verifies DB and Redis connectivity.

    Returns 503 when a dependency is unreachable so orchestrators
    (docker-compose healthcheck, k8s readinessProbe) stop routing traffic.
    """
    import app.database as database
    from app.core._event_bus import event_bus

    checks: dict[str, str] = {}

    if database.async_engine is not None:
        try:
            from sqlalchemy import text

            async with database.async_engine.connect() as conn:
                await conn.execute(text('SELECT 1'))
            checks['database'] = 'ok'
        except Exception as exc:  # noqa: BLE001 — readiness reports a failed check, it does not raise
            logger.warning('[Readiness] DB check failed: %s', exc)
            checks['database'] = 'error'
    else:
        checks['database'] = 'not_initialized'

    redis_client = event_bus._redis
    if redis_client is not None:
        try:
            await redis_client.ping()
            checks['redis'] = 'ok'
        except Exception as exc:  # noqa: BLE001 — readiness reports a failed check, it does not raise
            logger.warning('[Readiness] Redis check failed: %s', exc)
            checks['redis'] = 'error'
    else:
        checks['redis'] = 'not_connected'

    all_ok = all(status == 'ok' for status in checks.values())
    return JSONResponse(
        status_code=200 if all_ok else 503,
        content={'status': 'ready' if all_ok else 'not_ready', 'checks': checks},
    )

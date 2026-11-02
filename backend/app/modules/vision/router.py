import time
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Request,
    UploadFile,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserContextDTO
from app.core.deps import (
    get_async_db,
    get_current_user_context,
    require_org,
    require_permission,
)
from app.core.exceptions import (
    AppException,
    catalogue_refusal,
    catalogue_status_refusal,
    rejection_code,
)
from app.core.file_signature import validate_signature
from app.core.limiter import limiter
from app.core.logging import get_logger
from app.core.modules import require_module
from app.core.public_api.llm import (
    LlmContractError,
    LlmEmptyAnswerError,
    LlmProviderRefusalError,
    LlmPurposeUnboundError,
    LlmTimeoutError,
    LlmTransportError,
    classify_provider_refusal,
)
from app.core.upload_validation import format_size_limit, read_capped_upload
from app.i18n import Language
from app.i18n.service import get_current_lang, get_error_message

from .schemas import VisionExtractResponse
from .service import VisionService

# Explicit whitelist — blocks image/jpg, image/svg+xml, image/heic etc.
_ALLOWED_IMAGE_MIME_TYPES = frozenset(
    {'image/jpeg', 'image/png', 'image/webp', 'image/gif'}
)

#: What one photograph may weigh. It used to be ``settings.MAX_UPLOAD_SIZE`` —
#: a value sitting close enough to the request ceiling that a body big enough
#: to trip this limit was refused by the middleware first, so the endpoint had
#: no working limit of its own. Ten megabytes is above any phone camera's
#: output and a quarter of the ceiling (pinned by
#: ``test_a_per_file_limit_is_reachable.py``), and the service scales every
#: image to 1200x1200 before a model sees it, so nothing larger carries
#: information that survives the request.
_MAX_IMAGE_BYTES = 10 * 1024 * 1024

logger = get_logger(__name__)

router = APIRouter(dependencies=[Depends(require_module('vision'))])


async def _read_images(images: list[UploadFile], lang: Language) -> list[bytes]:
    """Validate and read the uploaded images into memory."""
    upload_start = time.perf_counter()
    image_bytes_list: list[bytes] = []
    for image in images:
        # Whitelist MIME types — startswith('image/') accepts
        # image/svg+xml (script injection), image/jpg (non-standard),
        # image/heic (unsupported by Pillow), etc.
        if (
            not image.content_type
            or image.content_type not in _ALLOWED_IMAGE_MIME_TYPES
        ):
            raise catalogue_refusal(
                'vision_unsupported_image_type',
                filename=image.filename or '',
                content_type=image.content_type or '',
                accepted=', '.join(sorted(_ALLOWED_IMAGE_MIME_TYPES)),
            )
        # Capped on the copy, not on the wire: Starlette has already
        # spooled the whole multipart body before this handler ran, and
        # `await image.read()` serves bytes from that spool. What this cap
        # bounds is how much lands in memory — per image, and this
        # endpoint takes a list of them. The wire itself is bounded by
        # MAX_REQUEST_BODY_SIZE in BodySizeLimitMiddleware.
        try:
            content = await read_capped_upload(
                image, get_current_lang(), _MAX_IMAGE_BYTES
            )
        except ValueError as exc:
            # Same refusal, same code, as every other image endpoint: a
            # file too large is 413 no matter which door it came through,
            # and the message names the ceiling — this endpoint's own,
            # not the request ceiling the middleware used to own.
            raise AppException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                code='FILE_TOO_LARGE',
                message=get_error_message(
                    'image_too_large',
                    get_current_lang(),
                    limit=format_size_limit(_MAX_IMAGE_BYTES),
                ),
            ) from exc
        # Verify magic bytes match the declared image type
        validate_signature(content, image.content_type)
        image_bytes_list.append(content)

    if not image_bytes_list:
        raise catalogue_refusal('no_valid_images')
    logger.info(
        '[Performance] Reading %d images from request took %.2fs',
        len(image_bytes_list),
        time.perf_counter() - upload_start,
    )
    return image_bytes_list


def _with_connection(
    status_code: int, exc: Exception, key: str, lang: Language
) -> AppException:
    """The refusal naming the connection, or its placeholder-free twin.

    A structural client and the legacy env-var fallback carry no connection
    name, and a reader must never be shown a literal ``{name}``. Either way
    the code is the key's: the twin is a wording, not another reason.
    """
    connection_name = getattr(exc, 'connection_name', None)
    model_name = getattr(exc, 'model_name', None)
    if connection_name and model_name:
        message = get_error_message(key, lang, name=connection_name, model=model_name)
    else:
        message = get_error_message(f'{key}_generic', lang)
    return AppException(
        status_code=status_code,
        code=rejection_code(key),
        message=message,
        extra={'lang': lang},
    )


def _reraise_llm_failure(
    exc: Exception, lang: Language, unusable_key: str
) -> AppException:
    """Turn a failed extraction into an answer the photographer can act on."""
    if isinstance(exc, LlmPurposeUnboundError):
        # Nobody has picked a connection for this yet. An administrator fixes
        # that in a minute; reporting it as a server error sends them to the
        # logs instead of to Settings.
        logger.warning('[Vision] %s', exc)
        return catalogue_status_refusal(
            'vision_ai_not_configured', status.HTTP_503_SERVICE_UNAVAILABLE, lang=lang
        )
    if isinstance(exc, LlmProviderRefusalError):
        # The provider read us fine and refused the key, the budget, or
        # the model name — the three most common first-setup states, all
        # of them settings a person can fix. "An internal error" sent the
        # administrator to the logs while the log said 401.
        key = classify_provider_refusal(exc.status_code) or 'llm_provider_unreachable'
        # ^ provider_refusal builds this type only for codes the classifier
        # names; the fallback is unreachable, kept so the contract is total.
        logger.warning('[Vision] Provider refused the request (%s): %s', key, exc)
        return _with_connection(status.HTTP_503_SERVICE_UNAVAILABLE, exc, key, lang)
    if isinstance(exc, LlmTransportError):
        # We never got through — or we did, and the model is still thinking.
        # Nothing about the photograph would change either, so the answer
        # must not send the reader back to the camera; and the two are not
        # the same errand, so they do not share a message. One is an address,
        # a certificate or a service that is down; the other is a limit
        # (LLM_LOCAL_REQUEST_TIMEOUT_SECONDS) or a model too big for the
        # machine it runs on.
        timed_out = isinstance(exc, LlmTimeoutError)
        key = 'llm_provider_timeout' if timed_out else 'llm_provider_unreachable'
        logger.warning(
            '[Vision] %s: %s',
            'The model ran out of time' if timed_out else 'Could not reach the model',
            exc,
        )
        return _with_connection(status.HTTP_503_SERVICE_UNAVAILABLE, exc, key, lang)
    if isinstance(exc, LlmEmptyAnswerError):
        # The model answered with nothing. "Could not read this label" points
        # at the photograph, and the photograph is not the problem: either the
        # model does not read images at all, or it spent its whole token
        # budget before writing anything.
        logger.warning('[Vision] The model returned no content: %s', exc)
        return _with_connection(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            exc,
            'vision_model_returned_nothing',
            lang,
        )
    if isinstance(exc, LlmContractError):
        # The provider answered; the answer is unusable. That is the model's
        # problem, not the server's — and the parser's own words ("Expecting
        # value: line 1 column 1") mean nothing to whoever took the photo.
        logger.warning('[Vision] Unusable answer from the model: %s', exc)
        return _with_connection(
            status.HTTP_422_UNPROCESSABLE_CONTENT, exc, unusable_key, lang
        )
    # No answer at all: transport, configuration, a broken image.
    logger.exception('[Vision] Extraction failed before an answer arrived')
    return catalogue_status_refusal(
        'internal_error', status.HTTP_500_INTERNAL_SERVER_ERROR, lang=lang
    )


@router.post(
    '/extract',
    response_model=VisionExtractResponse,
    dependencies=[require_permission('vision:extract')],
)
@limiter.limit('20/minute')
async def extract_from_image(
    request: Request,
    images: list[UploadFile] = File(..., description='Product label photos'),
    context_tag: str | None = Form(
        None,
        description=(
            'What the label was printed for (e.g. "equipment"). Decides which '
            'modules contribute extra fields to the reading.'
        ),
    ),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> VisionExtractResponse:
    """Read a label off one or more photographs of the same item."""
    lang = get_current_lang()
    org_id = require_org(current_user)

    image_bytes_list = await _read_images(images, lang)

    try:
        return await VisionService.extract_from_bytes_list(
            image_bytes_list=image_bytes_list,
            db=db,
            organization_id=org_id,
            user_id=current_user.id,
            context_tag=context_tag,
            # A barcode legible on the photograph goes through the same
            # resolvers a scanned one does.
            user=current_user,
        )
    except (
        LlmPurposeUnboundError,
        LlmContractError,
        OSError,
        RuntimeError,
        ValueError,
    ) as exc:
        raise _reraise_llm_failure(exc, lang, 'vision_label_not_understood') from exc


@router.post(
    '/extract-nutrition',
    response_model=dict[str, Any],
    dependencies=[
        Depends(require_module('nutrition')),
        require_permission('vision:extract'),
    ],
)
@limiter.limit('20/minute')
async def extract_nutrition(
    request: Request,
    file: UploadFile = File(..., description='Photo of nutrition table'),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> dict[str, Any]:
    """Read the nutrition module's field group off a single photograph.

    The shape of the answer belongs to the nutrition module, which declares it
    through ``vision_api``; this endpoint only names the module whose group to
    read. It reads a photograph like ``/extract`` does, so it is behind the
    same permission, ``vision:extract``.
    """
    lang = get_current_lang()
    org_id = require_org(current_user)

    image_bytes_list = await _read_images([file], lang)

    try:
        return await VisionService.extract_contributed_fields(
            module='nutrition',
            image_bytes_list=image_bytes_list,
            db=db,
            organization_id=org_id,
            user_id=current_user.id,
            action_type='extract_nutrition',
        )
    except (
        LlmPurposeUnboundError,
        LlmContractError,
        OSError,
        RuntimeError,
        ValueError,
    ) as exc:
        raise _reraise_llm_failure(
            exc, lang, 'vision_nutrition_not_understood'
        ) from exc

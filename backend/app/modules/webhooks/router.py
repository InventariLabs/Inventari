"""Webhooks module API endpoints."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_admin_user
from app.core.contracts import (
    AuditAction,
    AuditTargetType,
    UserContextDTO,
)
from app.core.cursor import decode_cursor, encode_cursor
from app.core.deps import (
    get_async_db,
    get_current_user_context,
    require_org,
)
from app.core.exceptions import AppException, refusal_code, refusal_text
from app.core.modules import require_module
from app.core.public_api import core_api
from app.modules.webhooks.models import WebhookEndpoint
from app.modules.webhooks.schemas import (
    AvailableEventResponse,
    TestWebhookResponse,
    WebhookDeliveryResponse,
    WebhookEndpointCreate,
    WebhookEndpointResponse,
    WebhookEndpointUpdate,
    valid_event_types,
)
from app.modules.webhooks.ssrf_guard import (
    WebhookUrlRejectedError,
    validate_webhook_url,
)
from app.modules.webhooks.webhook_crud_service import (
    CLEAR_SECRET_SENTINEL,
)
from app.modules.webhooks.webhook_crud_service import (
    create_endpoint_async as svc_create_endpoint,
)
from app.modules.webhooks.webhook_crud_service import (
    delete_endpoint_async as svc_delete_endpoint,
)
from app.modules.webhooks.webhook_crud_service import (
    get_webhook_or_404_async as svc_get_webhook_or_404,
)
from app.modules.webhooks.webhook_crud_service import (
    list_deliveries_async as svc_list_deliveries,
)
from app.modules.webhooks.webhook_crud_service import (
    list_endpoints_async as svc_list_endpoints,
)
from app.modules.webhooks.webhook_crud_service import (
    reactivate_endpoint_async as svc_reactivate_endpoint,
)
from app.modules.webhooks.webhook_crud_service import (
    to_response as svc_to_response,
)
from app.modules.webhooks.webhook_crud_service import (
    update_endpoint_async as svc_update_endpoint,
)
from app.modules.webhooks.webhook_service import (
    deliver_test_ping,
    encrypt_secret,
)
from app.schemas.pagination import CursorPaginatedResponse, PaginatedResponse

MASKED_VALUE = core_api.secrets.MASKED


# Guard for the whole module: the built-in admin level or any custom role
# holding admin:access, the same check every org-admin endpoint uses.
#
# Mounted on the router rather than repeated per endpoint, because the reads
# are the half that was missed: the five mutating endpoints each carried a
# guard and the three GETs — the endpoint list, one endpoint, and the delivery
# archive — carried nothing, so any member could read every target URL. That
# address is a credential at most receivers: knowing it is enough to post there
# as this organization. Declared once, an endpoint added later arrives closed.
router = APIRouter(
    tags=['webhooks'],
    dependencies=[
        Depends(require_module('webhooks')),
        Depends(get_current_admin_user),
    ],
)

_EVENT_DESCRIPTIONS: dict[str, str] = {
    'item.created': 'An item was added to inventory',
    'item.updated': 'An item was modified',
    'item.deleted': 'An item was removed',
    'item.moved': 'An item was moved to another location',
    'category.created': 'A category was created',
    'category.updated': 'A category was modified',
    'category.deleted': 'A category was deleted',
    'location.created': 'A location was created',
    'location.updated': 'A location was modified',
    'location.deleted': 'A location was deleted',
    'organization.created': 'An organization was created',
    'organization.updated': 'An organization was updated',
    'user.registered': 'A new user registered',
    'user.joined_organization': 'A user joined the organization',
    'user.left_organization': 'A user left the organization',
    'module.enabled': 'A module was enabled for the organization',
    'module.disabled': 'A module was disabled for the organization',
    'label.scanned': 'A label was scanned',
    # Module-contributed events. They live in the payload registry rather than
    # `SystemEvent`, and were unreachable until the catalog covered both.
    'recipe.created': 'A recipe was created',
    'recipe.meal_plan_generated': 'A meal plan was generated',
    'recipe.picking_completed': 'Ingredient picking for a recipe finished',
    'item.used': 'An item was used up',
    'item.disposed': 'An item was written off',
    'item.deactivated': 'An item was deactivated',
    'item.status_changed': 'An item changed status',
    'item.transferred': 'An item was transferred to another location',
    'label.assigned': 'A label was assigned to an item',
    'label.batch_generated': 'A batch of labels was generated',
    'label.batch_exported': 'A batch of labels was exported for printing',
    'document.confirmed': 'A document was confirmed',
    'document.completed': 'A document was completed',
    'document.cancelled': 'A document was cancelled',
    'document.shipped': 'A dispatch was completed with its carrier and tracking number',
    'equipment.checkout': 'A piece of equipment was handed out',
    'equipment.checkin': 'A piece of equipment was returned',
    'partner.activated': 'A partner was activated',
    'partner.deactivated': 'A partner was deactivated',
    'purchase_order.confirmed': 'A purchase order was confirmed',
    'purchase_order.completed': 'A purchase order was completed',
    'purchase_order.cancelled': 'A purchase order was cancelled',
    'receipt.created_from_po': 'A receipt was created from a purchase order',
}

#: Which module has to be enabled for an event to ever fire. Events absent from
#: this map come from the core and always fire. Subscribing ahead of enabling a
#: module stays possible on purpose — the catalog marks such events rather than
#: hiding them, so a webhook can be prepared before the module goes on.
_EVENT_SOURCE_MODULE: dict[str, str] = {
    'recipe': 'recipes',
    'equipment': 'equipment',
    'partner': 'partners',
    'document': 'warehouse',
    'purchase_order': 'purchase_orders',
    'receipt': 'purchase_orders',
}


def _source_module(event_type: str) -> str | None:
    """The module that emits *event_type*, or ``None`` for a core event."""
    return _EVENT_SOURCE_MODULE.get(event_type.split('.', 1)[0])


async def _module_availability_async(db: AsyncSession, org_id: UUID) -> dict[str, bool]:
    """Whether each event-source module is enabled here.

    The catalog and the endpoint list ask the same question — which modules are
    on — so both read one answer instead of each looping the module set.
    """
    availability: dict[str, bool] = {}
    for module_name in set(_EVENT_SOURCE_MODULE.values()):
        availability[
            module_name
        ] = await core_api.organizations.is_module_enabled_async(
            db, org_id, module_name
        )
    return availability


def _fires_nothing(event_types: list[str], availability: dict[str, bool]) -> bool:
    """Whether an endpoint can never fire because its modules are all off.

    An event fires when it is a core event (no source module) or its source
    module is enabled. The endpoint is only silent when *every* event it
    subscribes to belongs to a module that is currently disabled — one core
    event, or one module still on, keeps it live.
    """
    if not event_types:
        return False
    for event_type in event_types:
        module = _source_module(event_type)
        if module is None or availability.get(module, True):
            return False
    return True


def _has_unknown_events(event_types: list[str]) -> bool:
    """Whether any subscribed name is no longer in the catalogue.

    A name that left the catalogue — ``item.consumed``/``item.discarded``
    were cut before the first release — matches nothing the bus emits, so the
    endpoint holds a subscription that can never fire while the card reads
    active. The rows are not migrated: only development and demo stores
    carry them, and those are reset. Saying the fact here is what
    keeps the death from being silent.
    """
    allowed = valid_event_types()
    return any(event_type not in allowed for event_type in event_types)


def _validate_url_or_422(url: str) -> None:
    """Refuse an unsafe target in the reader's language, with the reason.

    The guard knows *why* it said no (loopback, private range, a name that does
    not resolve, a name that resolves into a private range). That reason used to
    reach the screen as an English sentence — and, before that, did not reach it
    at all, because the form swallowed the rejection.

    The operator's switch is read here, not only at delivery time. Saving used
    to refuse a private address whatever the setting said, so the switch turned
    on a delivery path to an endpoint that could never be created: the whole
    reason it exists — a webhook aimed at Home Assistant on the LAN — stayed
    shut with it on.
    """
    from app.config import settings as app_settings

    allow_private = getattr(app_settings, 'WEBHOOKS_ALLOW_PRIVATE_NETWORKS', False)
    try:
        validate_webhook_url(url, allow_private=allow_private)
    except WebhookUrlRejectedError as exc:
        raise _url_rejected(f'WEBHOOK_URL_{exc.reason.upper()}', str(exc)) from exc
    except ValueError as exc:
        # Malformed URL, a scheme other than http/https, no host name — the
        # guard keys each of them, so the sentence is already in the reader's
        # language and the code says which of the three it was.
        raise _url_rejected(
            refusal_code(exc, 'WEBHOOK_URL_INVALID'), refusal_text(exc)
        ) from exc


def _url_rejected(code: str, message: str) -> AppException:
    """A 422 that says which field it is about, so the form can point at it."""
    return AppException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        code=code,
        message=message,
        field='url',
    )


@router.get(
    '/events',
    # list-envelope-exception: a vocabulary, the event types a subscription can name
    response_model=list[AvailableEventResponse],
)
async def list_available_events(
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> list[AvailableEventResponse]:
    # Same union the create/update validators accept — a catalog narrower than
    # the validator means the API takes a subscription the UI never offers.
    org_id = require_org(current_user)
    availability = await _module_availability_async(db, org_id)

    return [
        AvailableEventResponse(
            event_type=name,
            description=_EVENT_DESCRIPTIONS.get(name, name),
            source_module=_source_module(name),
            available=availability.get(_source_module(name) or '', True),
        )
        for name in sorted(valid_event_types())
    ]


async def _flagged_response_async(
    db: AsyncSession, org_id: UUID, endpoint: WebhookEndpoint
) -> WebhookEndpointResponse:
    """The endpoint as a response, carrying whether it can never fire.

    The silence is a fact about the module switches right now, not about the
    endpoint's own rows, so it is computed here — one availability read per
    response — instead of stored where it could go stale the moment somebody
    flips a module.
    """
    availability = await _module_availability_async(db, org_id)
    return svc_to_response(
        endpoint,
        events_all_module_disabled=_fires_nothing(
            endpoint.event_types or [], availability
        ),
        events_unknown=_has_unknown_events(endpoint.event_types or []),
    )


@router.get('/endpoints', response_model=PaginatedResponse[WebhookEndpointResponse])
async def list_endpoints(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> PaginatedResponse[WebhookEndpointResponse]:
    org_id = require_org(current_user)
    endpoints = await svc_list_endpoints(org_id, db)
    availability = await _module_availability_async(db, org_id)
    responses = [
        svc_to_response(
            ep,
            events_all_module_disabled=_fires_nothing(
                ep.event_types or [], availability
            ),
            events_unknown=_has_unknown_events(ep.event_types or []),
        )
        for ep in endpoints
    ]
    return PaginatedResponse.from_full_list(responses, offset=offset, limit=limit)


def _endpoint_snapshot(endpoint: WebhookEndpoint) -> dict[str, Any]:
    """What the journal keeps about an endpoint after the row is gone.

    Name and destination, never the signing secret: the entry says which
    channel was opened or closed and where it pointed, which is the question
    asked months later, and the delivery history that would have answered it
    is cascaded away with the endpoint. A creation also names the events the
    channel subscribes to — the breadth of what leaves by it is part of what
    was opened.
    """
    snapshot: dict[str, Any] = {'name': endpoint.name, 'url': str(endpoint.url)}
    if endpoint.event_types is not None:
        snapshot['event_types'] = sorted(endpoint.event_types)
    return snapshot


def _journal_fields(endpoint: WebhookEndpoint) -> dict[str, Any]:
    """The fields an edit can move, read before the write and after it.

    The reader walks the two dictionaries and drops every leaf that did not
    move, so this is the whole surface an edit's entry can speak about: the
    name, the destination, the method, the subscribed events, whether the
    channel is on and its delivery limits (retries, timeout, backoff). The
    secret is not a field here — it has no value it may show, only presence,
    which the update entry carries beside these.
    """
    return {
        'name': endpoint.name,
        'url': str(endpoint.url),
        'http_method': endpoint.http_method,
        'event_types': sorted(endpoint.event_types or []),
        'is_active': endpoint.is_active,
        'max_retries': endpoint.max_retries,
        'timeout_seconds': endpoint.timeout_seconds,
        'retry_backoff_seconds': endpoint.retry_backoff_seconds,
    }


# The pair this module's journal keys come from: the update payload and the
# endpoint row share these fields, so every key the journal can write is one
# the schema and the model share. The snapshot-key exporter reads this
# declaration; a reader then meets the same words the settings screen uses.
AUDIT_PAYLOAD_SCHEMA = ('WebhookEndpointUpdate', 'WebhookEndpoint')


@router.post(
    '/endpoints',
    response_model=WebhookEndpointResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_endpoint(
    body: WebhookEndpointCreate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> WebhookEndpointResponse:
    org_id = require_org(current_user)

    url_str = str(body.url)
    _validate_url_or_422(url_str)

    encrypted_secret = encrypt_secret(body.secret) if body.secret else None

    endpoint = await svc_create_endpoint(
        db,
        organization_id=org_id,
        name=body.name,
        url=url_str,
        secret=encrypted_secret,
        http_method=body.http_method,
        event_types=body.event_types,
        max_retries=body.max_retries,
        retry_backoff_seconds=body.retry_backoff_seconds,
        timeout_seconds=body.timeout_seconds,
        is_active=body.is_active,
    )
    # Opening a channel that data leaves by is an administrative act, and
    # this module wrote nothing at all: four endpoints created, three
    # deleted, and the organization journal held a single line about the
    # module being switched on.
    await core_api.audit_log.log_action_async(
        db,
        organization_id=org_id,
        user_id=current_user.id,
        action=AuditAction.CREATE,
        target_type=AuditTargetType.WEBHOOK_ENDPOINT,
        target_id=endpoint.id,
        snapshot=_endpoint_snapshot(endpoint),
    )
    return await _flagged_response_async(db, org_id, endpoint)


@router.get('/endpoints/{webhook_id}', response_model=WebhookEndpointResponse)
async def get_endpoint(
    webhook_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> WebhookEndpointResponse:
    org_id = require_org(current_user)
    endpoint = await svc_get_webhook_or_404(webhook_id, org_id, db)
    return await _flagged_response_async(db, org_id, endpoint)


@router.put('/endpoints/{webhook_id}', response_model=WebhookEndpointResponse)
async def update_endpoint(
    webhook_id: UUID,
    body: WebhookEndpointUpdate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> WebhookEndpointResponse:
    org_id = require_org(current_user)
    endpoint = await svc_get_webhook_or_404(webhook_id, org_id, db)
    before = _journal_fields(endpoint)
    had_secret = endpoint.secret is not None

    url_val: str | None = None
    if body.url is not None:
        url_val = str(body.url)
        _validate_url_or_422(url_val)

    # Secret update semantics:
    #   body.secret is None          -> no change (signal: don't touch)
    #   body.secret == MASKED_VALUE  -> no change (echoed back from GET response)
    #   body.secret == ""            -> CLEAR existing secret
    #   body.secret == CLEAR_SENTINEL -> explicit clear (alternative to "")
    #   any other string            -> replace with new encrypted secret
    if body.secret is None or body.secret == MASKED_VALUE:
        secret_val: str | None = None  # sentinel: service treats None as "no change"
    elif body.secret == '' or body.secret == CLEAR_SECRET_SENTINEL:
        secret_val = CLEAR_SECRET_SENTINEL  # signal to service to clear
    else:
        secret_val = encrypt_secret(body.secret)

    updated = await svc_update_endpoint(
        db,
        endpoint,
        name=body.name,
        url=url_val,
        secret=secret_val,
        http_method=body.http_method,
        event_types=body.event_types,
        max_retries=body.max_retries,
        retry_backoff_seconds=body.retry_backoff_seconds,
        timeout_seconds=body.timeout_seconds,
        is_active=body.is_active,
    )
    # What the journal says an edit did: the fields that moved, before and
    # after, and nothing else. The reader drops unchanged leaves on its own,
    # but the write narrows to the difference anyway — an entry whose two
    # sides agree reads as "Update" over a channel that may now carry more
    # events or a different signature, with nothing on the row saying so.
    after = _journal_fields(updated)
    moved = [key for key in before if before[key] != after[key]]
    snapshot: dict[str, Any] = {
        'name': updated.name,
        'url': str(updated.url),
        'before': {key: before[key] for key in moved},
        'after': {key: after[key] for key in moved},
    }
    # The secret has no value it may show, only presence. A turn-over leaves
    # presence unchanged, so it is said by the fields line instead — the
    # fact that the credential changed, never what it changed to.
    secret_touched = body.secret is not None and body.secret != MASKED_VALUE
    if secret_touched:
        snapshot['fields'] = ['secret']
        has_secret = updated.secret is not None
        if had_secret != has_secret:
            snapshot['before']['secret'] = 'set' if had_secret else 'absent'
            snapshot['after']['secret'] = 'set' if has_secret else 'absent'
    await core_api.audit_log.log_action_async(
        db,
        organization_id=org_id,
        user_id=current_user.id,
        action=AuditAction.UPDATE,
        target_type=AuditTargetType.WEBHOOK_ENDPOINT,
        target_id=updated.id,
        snapshot=snapshot,
    )
    return await _flagged_response_async(db, org_id, updated)


@router.delete('/endpoints/{webhook_id}', status_code=status.HTTP_204_NO_CONTENT)
async def delete_endpoint(
    webhook_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> None:
    org_id = require_org(current_user)
    endpoint = await svc_get_webhook_or_404(webhook_id, org_id, db)
    # Read the snapshot while the row is still there — after the delete the
    # name and the destination exist nowhere else.
    snapshot = _endpoint_snapshot(endpoint)
    endpoint_id = endpoint.id
    await svc_delete_endpoint(db, endpoint)
    await core_api.audit_log.log_action_async(
        db,
        organization_id=org_id,
        user_id=current_user.id,
        action=AuditAction.HARD_DELETE,
        target_type=AuditTargetType.WEBHOOK_ENDPOINT,
        target_id=endpoint_id,
        snapshot=snapshot,
    )


@router.post('/endpoints/{webhook_id}/test', response_model=TestWebhookResponse)
async def test_endpoint(
    webhook_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> TestWebhookResponse:
    org_id = require_org(current_user)
    endpoint = await svc_get_webhook_or_404(webhook_id, org_id, db)

    is_success, status_code, error_message, delivery_id = await deliver_test_ping(
        db, endpoint, str(org_id)
    )
    return TestWebhookResponse(
        success=is_success,
        status_code=status_code,
        error=error_message,
        delivery_id=delivery_id,
    )


@router.post(
    '/endpoints/{webhook_id}/reactivate', response_model=WebhookEndpointResponse
)
async def reactivate_endpoint(
    webhook_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> WebhookEndpointResponse:
    org_id = require_org(current_user)
    endpoint = await svc_get_webhook_or_404(webhook_id, org_id, db)
    # The breaker's mark is the only honest source for the sentence: the
    # system sets it when it cuts the channel off, and any manual on/off
    # decision clears it. Reading it must happen before the service does —
    # reactivation is one of those decisions and clears it too.
    was_cut_by_breaker = endpoint.auto_disabled_at is not None
    reactivated = await svc_reactivate_endpoint(db, endpoint)
    # The other half of the breaker: it switched the channel off by itself,
    # a person switched it back on. Both belong in the journal, or the gap
    # between them reads as nothing having happened. A channel that was off
    # by somebody's toggle has no breaker to answer for, and its row stays
    # the person's plain update.
    await core_api.audit_log.log_action_async(
        db,
        organization_id=org_id,
        user_id=current_user.id,
        action=AuditAction.UPDATE,
        target_type=AuditTargetType.WEBHOOK_ENDPOINT,
        target_id=reactivated.id,
        snapshot=_endpoint_snapshot(reactivated),
        meta_data=(
            {'reactivated_after_circuit_breaker': True} if was_cut_by_breaker else None
        ),
    )
    return await _flagged_response_async(db, org_id, reactivated)


@router.get(
    '/endpoints/{webhook_id}/deliveries',
    response_model=CursorPaginatedResponse[WebhookDeliveryResponse],
)
async def list_deliveries(
    webhook_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = Query(
        None, description='Opaque cursor from previous response'
    ),
) -> CursorPaginatedResponse[WebhookDeliveryResponse]:
    # Payloads included, and not filtered by the reader's module permissions —
    # deliberately. The archive holds what a webhook administrator chose to
    # subscribe to, and that same person can point any subscribed event at a URL
    # they control, so hiding `document.completed` here from someone who may not
    # read documents protects nothing the create path does not already hand
    # over. The gate that decides the exposure is the one on administering
    # webhooks at all, which now covers this too. A per-module filter would also
    # contradict the catalog's rule that subscribing ahead of enabling a module
    # is allowed: the endpoint would list a subscription whose history was
    # invisible.
    org_id = require_org(current_user)
    await svc_get_webhook_or_404(webhook_id, org_id, db)

    cursor_ts = None
    if cursor:
        _, cursor_ts = decode_cursor(cursor)

    logs = await svc_list_deliveries(db, webhook_id, org_id, limit, cursor_ts=cursor_ts)
    return CursorPaginatedResponse.from_cursor_page(
        logs,
        limit,
        lambda last: encode_cursor(last.id, last.created_at),
        transform=WebhookDeliveryResponse.model_validate,
    )

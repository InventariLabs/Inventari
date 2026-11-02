"""CRUD operations for webhook endpoints.

All DB write logic is isolated here so the router stays thin
(HTTP concerns only: deps, status codes, response_model).
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db_utils import get_org_owned_or_404_async
from app.modules.webhooks.models import WebhookDeliveryLog, WebhookEndpoint
from app.modules.webhooks.schemas import WebhookEndpointResponse

# Sentinel value the client can send to clear an existing secret
CLEAR_SECRET_SENTINEL = '__CLEAR__'


def _org_uuid(organization_id: str | UUID) -> UUID:
    if isinstance(organization_id, UUID):
        return organization_id
    return UUID(str(organization_id))


def to_response(
    endpoint: WebhookEndpoint,
    *,
    events_all_module_disabled: bool = False,
    events_unknown: bool = False,
) -> WebhookEndpointResponse:
    return WebhookEndpointResponse(
        id=endpoint.id,
        name=endpoint.name,
        url=str(endpoint.url),
        has_secret=bool(endpoint.secret),
        http_method=endpoint.http_method,
        event_types=endpoint.event_types or [],
        max_retries=endpoint.max_retries,
        retry_backoff_seconds=endpoint.retry_backoff_seconds,
        timeout_seconds=endpoint.timeout_seconds,
        is_active=endpoint.is_active,
        last_triggered_at=endpoint.last_triggered_at,
        last_status_code=endpoint.last_status_code,
        consecutive_failures=endpoint.consecutive_failures,
        auto_disabled_at=endpoint.auto_disabled_at,
        events_all_module_disabled=events_all_module_disabled,
        events_unknown=events_unknown,
        created_at=endpoint.created_at,
        updated_at=endpoint.updated_at,
    )


async def get_webhook_or_404_async(
    webhook_id: UUID,
    organization_id: str | UUID,
    db: AsyncSession,
) -> WebhookEndpoint:
    return await get_org_owned_or_404_async(
        db, WebhookEndpoint, webhook_id, _org_uuid(organization_id), resource='webhook'
    )


async def list_endpoints_async(
    organization_id: str | UUID,
    db: AsyncSession,
) -> list[WebhookEndpoint]:
    stmt = (
        select(WebhookEndpoint)
        .where(WebhookEndpoint.organization_id == _org_uuid(organization_id))
        .order_by(WebhookEndpoint.created_at.desc(), WebhookEndpoint.id)
    )
    return list((await db.execute(stmt)).scalars().all())


async def create_endpoint_async(
    db: AsyncSession,
    *,
    organization_id: str | UUID,
    name: str,
    url: str,
    secret: str | None,
    http_method: str,
    event_types: list[str],
    max_retries: int,
    retry_backoff_seconds: int,
    timeout_seconds: int,
    is_active: bool,
) -> WebhookEndpoint:
    endpoint = WebhookEndpoint(
        organization_id=_org_uuid(organization_id),
        name=name,
        url=url,
        secret=secret,
        http_method=http_method,
        event_types=event_types,
        max_retries=max_retries,
        retry_backoff_seconds=retry_backoff_seconds,
        timeout_seconds=timeout_seconds,
        is_active=is_active,
    )
    db.add(endpoint)
    await db.flush()
    await db.refresh(endpoint)
    return endpoint


async def update_endpoint_async(
    db: AsyncSession,
    endpoint: WebhookEndpoint,
    *,
    name: str | None = None,
    url: str | None = None,
    secret: str | None = None,
    http_method: str | None = None,
    event_types: list[str] | None = None,
    max_retries: int | None = None,
    retry_backoff_seconds: int | None = None,
    timeout_seconds: int | None = None,
    is_active: bool | None = None,
) -> WebhookEndpoint:
    if name is not None:
        endpoint.name = name
    if url is not None:
        # Reset consecutive_failures when URL changes
        if url != str(endpoint.url):
            endpoint.consecutive_failures = 0
            endpoint.auto_disabled_at = None
        endpoint.url = url
    # secret semantics:
    #   secret is None                  -> no change
    #   secret == CLEAR_SECRET_SENTINEL -> clear existing secret
    #   any other non-None string       -> replace with this (already encrypted) value
    if secret == CLEAR_SECRET_SENTINEL:
        endpoint.secret = None
    elif secret is not None:
        endpoint.secret = secret
    if http_method is not None:
        endpoint.http_method = http_method
    if event_types is not None:
        endpoint.event_types = event_types
    if max_retries is not None:
        endpoint.max_retries = max_retries
    if retry_backoff_seconds is not None:
        endpoint.retry_backoff_seconds = retry_backoff_seconds
    if timeout_seconds is not None:
        endpoint.timeout_seconds = timeout_seconds
    if is_active is not None:
        # The edit form sends is_active on every save. Only a value that
        # moves is somebody's decision, ending the breaker as the reason
        # this endpoint is on or off; the same value echoed back must not
        # erase the cut-off the breaker's once-only journal entry rests on.
        if is_active != endpoint.is_active:
            endpoint.auto_disabled_at = None
        endpoint.is_active = is_active

    await db.flush()
    await db.refresh(endpoint)
    return endpoint


async def delete_endpoint_async(db: AsyncSession, endpoint: WebhookEndpoint) -> None:
    await db.delete(endpoint)
    await db.flush()


async def reactivate_endpoint_async(
    db: AsyncSession, endpoint: WebhookEndpoint
) -> WebhookEndpoint:
    endpoint.is_active = True
    endpoint.consecutive_failures = 0
    endpoint.auto_disabled_at = None
    await db.flush()
    await db.refresh(endpoint)
    return endpoint


async def list_deliveries_async(
    db: AsyncSession,
    webhook_endpoint_id: UUID,
    org_id: UUID,
    limit: int,
    cursor_ts: datetime | None = None,
) -> list[WebhookDeliveryLog]:
    stmt = (
        select(WebhookDeliveryLog)
        .join(
            WebhookEndpoint,
            WebhookDeliveryLog.webhook_endpoint_id == WebhookEndpoint.id,
        )
        .where(
            WebhookDeliveryLog.webhook_endpoint_id == webhook_endpoint_id,
            WebhookEndpoint.organization_id == org_id,
        )
        .order_by(WebhookDeliveryLog.created_at.desc())
    )
    if cursor_ts is not None:
        stmt = stmt.where(WebhookDeliveryLog.created_at < cursor_ts)
    return list((await db.execute(stmt.limit(limit + 1))).scalars().all())

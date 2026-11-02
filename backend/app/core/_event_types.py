from enum import StrEnum
from typing import Any

from app.core.contracts.events import EventPayload, TenantEventPayload
from app.core.logging import get_logger

__all__ = [
    'EventPayload',
    'SystemEvent',
    'TenantEventPayload',
]

logger = get_logger(__name__)


def _sa_json_default(obj: Any) -> Any:
    """JSON fallback for event payloads written to Redis."""
    try:
        from sqlalchemy import inspect as sa_inspect
        from sqlalchemy.exc import NoInspectionAvailable

        try:
            state = sa_inspect(obj)
            return {col.key: getattr(obj, col.key) for col in state.mapper.column_attrs}
        except NoInspectionAvailable:
            pass
    except ImportError:
        pass
    return str(obj)


class SystemEvent(StrEnum):
    """Standard system events that modules can subscribe to.

    This table lists what CORE ships. A module's own events are not here —
    ``equipment.*``, ``document.*``, ``purchase_order.*`` and
    ``receipt.created_from_po`` left before the repository went public and
    now live only in ``app.modules.<module>.events``. Nothing about that
    move touched the wire: those enums are ``StrEnum`` carrying the same
    strings, and each module registers its payload at install. A
    cross-module subscriber names the event by its string, never by
    importing another module's enum.

    No deprecated members today. The two neutral-vocabulary aliases this
    enum used to carry — ``ITEM_CONSUMED`` / ``ITEM_DISCARDED``, re-emitted
    beside ``ITEM_USED`` / ``ITEM_DISPOSED`` by a shim in
    ``services/items/move_service`` — left before the repository went
    public, together with the entries that named them in
    ``app.core._event_deprecations``.
    """

    ITEM_CREATED = 'item.created'
    ITEM_UPDATED = 'item.updated'
    ITEM_DELETED = 'item.deleted'
    ITEM_MOVED = 'item.moved'
    ITEM_USED = 'item.used'
    ITEM_DISPOSED = 'item.disposed'
    ITEM_TRANSFERRED = 'item.transferred'
    ITEM_DEACTIVATED = 'item.deactivated'
    ITEM_STATUS_CHANGED = 'item.status_changed'

    CATEGORY_CREATED = 'category.created'
    CATEGORY_UPDATED = 'category.updated'
    CATEGORY_DELETED = 'category.deleted'

    STORAGE_CREATED = 'location.created'
    STORAGE_UPDATED = 'location.updated'
    STORAGE_DELETED = 'location.deleted'

    ORGANIZATION_CREATED = 'organization.created'
    ORGANIZATION_UPDATED = 'organization.updated'

    USER_REGISTERED = 'user.registered'
    USER_JOINED_ORG = 'user.joined_organization'
    USER_LEFT_ORG = 'user.left_organization'

    MODULE_ENABLED = 'module.enabled'
    MODULE_DISABLED = 'module.disabled'

    LABEL_SCANNED = 'label.scanned'
    LABEL_ASSIGNED = 'label.assigned'
    LABEL_BATCH_GENERATED = 'label.batch_generated'
    LABEL_BATCH_EXPORTED = 'label.batch_exported'

    PARTNER_ACTIVATED = 'partner.activated'
    PARTNER_DEACTIVATED = 'partner.deactivated'

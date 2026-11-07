"""Registry mapping event names to their payload contract types.

Keys are plain strings (not ``SystemEvent`` members) to keep this module
free of any dependency on ``app.core._event_types`` — the dependency must
point the other way (event bus -> contracts).

Events without a registered type are tolerated (fail-open): validation is
opt-in per event and unknown/custom module events pass through with the
permissive base payload.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from app.core.module_identity import current_module, event_registration_refusal
from app.core.operator_error import OperatorError

from ._base import EventPayload, EventValidationError, TenantEventPayload
from ._payloads import (
    CategoryCreatedPayload,
    CategoryDeletedPayload,
    CategoryUpdatedPayload,
    DocumentCancelledPayload,
    DocumentCompletedPayload,
    DocumentConfirmedPayload,
    DocumentShippedPayload,
    EquipmentCheckinPayload,
    EquipmentCheckoutPayload,
    ItemCreatedPayload,
    ItemDeletedPayload,
    ItemMovedPayload,
    ItemQuantityEventPayload,
    ItemUpdatedPayload,
    LabelBatchExportedPayload,
    LabelBatchGeneratedPayload,
    ModuleDisabledPayload,
    ModuleEnabledPayload,
    PartnerActivatedPayload,
    PartnerDeactivatedPayload,
    PurchaseOrderCancelledPayload,
    PurchaseOrderCompletedPayload,
    PurchaseOrderConfirmedPayload,
    ReceiptCreatedFromPOPayload,
    RecipeCreatedPayload,
    RecipeMealPlanGeneratedPayload,
    RecipePickingCompletedPayload,
    StorageCreatedPayload,
    StorageDeletedPayload,
    StorageUpdatedPayload,
    UserJoinedOrgPayload,
    UserLeftOrgPayload,
)

EVENT_PAYLOAD_TYPES: dict[str, type[EventPayload]] = {
    'item.created': ItemCreatedPayload,
    'item.updated': ItemUpdatedPayload,
    'item.deleted': ItemDeletedPayload,
    'item.moved': ItemMovedPayload,
    'item.used': ItemQuantityEventPayload,
    'item.disposed': ItemQuantityEventPayload,
    # Defined in SystemEvent but never emitted — base contract only.
    'item.transferred': TenantEventPayload,
    'item.deactivated': TenantEventPayload,
    'item.status_changed': TenantEventPayload,
    'category.created': CategoryCreatedPayload,
    'category.updated': CategoryUpdatedPayload,
    'category.deleted': CategoryDeletedPayload,
    'location.created': StorageCreatedPayload,
    'location.updated': StorageUpdatedPayload,
    'location.deleted': StorageDeletedPayload,
    'organization.created': TenantEventPayload,
    'organization.updated': TenantEventPayload,
    'user.registered': TenantEventPayload,
    'user.joined_organization': UserJoinedOrgPayload,
    'user.left_organization': UserLeftOrgPayload,
    'module.enabled': ModuleEnabledPayload,
    'module.disabled': ModuleDisabledPayload,
    'label.scanned': TenantEventPayload,
    'label.assigned': TenantEventPayload,
    'label.batch_generated': LabelBatchGeneratedPayload,
    'label.batch_exported': LabelBatchExportedPayload,
    'equipment.checkout': EquipmentCheckoutPayload,
    'equipment.checkin': EquipmentCheckinPayload,
    'partner.activated': PartnerActivatedPayload,
    'partner.deactivated': PartnerDeactivatedPayload,
    'document.confirmed': DocumentConfirmedPayload,
    'document.completed': DocumentCompletedPayload,
    'document.cancelled': DocumentCancelledPayload,
    'document.shipped': DocumentShippedPayload,
    'purchase_order.confirmed': PurchaseOrderConfirmedPayload,
    'purchase_order.completed': PurchaseOrderCompletedPayload,
    'purchase_order.cancelled': PurchaseOrderCancelledPayload,
    'receipt.created_from_po': ReceiptCreatedFromPOPayload,
    'recipe.created': RecipeCreatedPayload,
    'recipe.picking_completed': RecipePickingCompletedPayload,
    'recipe.meal_plan_generated': RecipeMealPlanGeneratedPayload,
}


#: Payload types registered at runtime by modules, via ``register_payload``.
#: Kept apart from ``EVENT_PAYLOAD_TYPES`` so that a module can never shadow a
#: core event, and so that the static table stays readable as the core contract.
_RUNTIME_PAYLOAD_TYPES: dict[str, type[EventPayload]] = {}

#: Who registered each runtime payload. The owner is recorded rather than
#: derived from the name's prefix because a module's namespace and its name
#: can differ (``recipes`` owns ``recipe.created``), and because ownership is
#: a fact the registrar stated, not a spelling to re-parse at emission time.
_RUNTIME_PAYLOAD_OWNERS: dict[str, str] = {}

_EVENT_NAME_RE = re.compile(r'^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$')


def event_owner(event_name: str) -> str | None:
    """The module that registered *event_name* at runtime, if any."""
    return _RUNTIME_PAYLOAD_OWNERS.get(str(event_name))


def is_core_event(event_name: str) -> bool:
    """Whether *event_name* belongs to the core contract table."""
    return str(event_name) in EVENT_PAYLOAD_TYPES


def register_payload(event_name: str, model: type[EventPayload]) -> None:
    """Register *model* as the payload contract for *event_name*.

    Modules call this from ``on_startup``. The name must be namespaced as
    ``<module>.<event>`` — an unnamespaced name would sit in the same flat
    space as core events and collide the moment core grows one.

    Raises ``ValueError`` on a malformed name, on a name outside the
    caller's own namespace, on redefining a core-owned name with a
    different model, or on re-registering the same name with a different
    model. Re-registering the identical model is a no-op, so a module
    surviving a reload does not explode; re-declaring a core-owned name
    with the very class from the core table is tolerated while the class
    still lives in core (the module claims ownership ahead of the planned
    move).
    """
    name = str(event_name)
    if not _EVENT_NAME_RE.match(name):
        raise OperatorError(
            f'Event name {name!r} must be namespaced as <module>.<event>, '
            'lowercase, e.g. "warranty.expired".'
        )
    if not isinstance(model, type) or not issubclass(model, EventPayload):
        raise OperatorError(f'Payload for {name!r} must be an EventPayload subclass.')
    if name in EVENT_PAYLOAD_TYPES:
        if EVENT_PAYLOAD_TYPES[name] is model:
            # The module re-declares its own event with the very class that
            # still lives in the core table (the move to the module is
            # planned). An ownership claim, not a shadowing attempt — tolerate
            # it as a no-op and keep the core table as the single source.
            return
        raise OperatorError(
            f'{name!r} is a core event; its payload is owned by the core contract '
            'and cannot be redefined by a module.'
        )

    # A new runtime registration is an ownership claim. A module may only
    # claim a namespace no other loaded module answers to: without this,
    # module foo could register ``bar.something`` and every subscriber would
    # read it as bar's event, while the failure carried no trace of foo. The
    # check runs here and not only in ``core_api.events`` because the
    # registry is the seam both the public API and the module context
    # funnel through.
    from app.core.module_registry import module_registry

    known_modules = {module.metadata.name for module in module_registry.get_all()}
    refusal = event_registration_refusal(name, known_modules=known_modules)
    if refusal is not None:
        raise OperatorError(refusal)

    existing = _RUNTIME_PAYLOAD_TYPES.get(name)
    if existing is not None and existing is not model:
        raise OperatorError(
            f'{name!r} is already registered by {existing.__name__}; '
            f'refusing to replace it with {model.__name__}.'
        )
    _RUNTIME_PAYLOAD_TYPES[name] = model
    caller = current_module()
    if caller is not None:
        _RUNTIME_PAYLOAD_OWNERS[name] = caller


def registered_payloads() -> Mapping[str, type[EventPayload]]:
    """Every known payload contract: core table first, then runtime registrations."""
    return {**EVENT_PAYLOAD_TYPES, **_RUNTIME_PAYLOAD_TYPES}


def get_payload_type(event_name: str) -> type[EventPayload] | None:
    """Return the registered payload type for *event_name*, or ``None``."""
    name = str(event_name)
    return EVENT_PAYLOAD_TYPES.get(name) or _RUNTIME_PAYLOAD_TYPES.get(name)


def validate_event_payload(
    event_name: str, data: Mapping[str, Any] | EventPayload
) -> EventPayload:
    """Validate *data* against the payload type registered for *event_name*.

    Registered events: returns an instance of the registered payload type;
    a :class:`ValidationError` is wrapped in :class:`EventValidationError`.
    Unregistered events: fail-open — returns the permissive base payload
    (tenant variant when ``organization_id`` is present).
    """
    payload_type = get_payload_type(event_name)
    if payload_type is None:
        if isinstance(data, EventPayload):
            return data
        cls = TenantEventPayload if 'organization_id' in data else EventPayload
        return cls.model_validate(data)
    try:
        return payload_type.model_validate(data)
    except ValidationError as exc:
        raise EventValidationError(str(event_name), exc) from exc

"""Per-event payload contracts.

One Pydantic model per emitted event. Fields declared here are the stable,
typed part of the contract; ``extra='allow'`` (inherited) tolerates
transitional extras such as ORM objects attached by legacy emitters —
those extras are NOT part of the contract and must not be relied on by
subscribers.

Fields typed ``Any`` marked "transitional" carry an ORM object (or a
``jsonable_encoder`` dict of one) until the emitter migrates to a DTO.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from ._base import EventPayload, TenantEventPayload

# ── Items ────────────────────────────────────────────────────────────────────


class ItemCreatedPayload(TenantEventPayload):
    item: Any = None  # transitional: ORM Item
    user_id: str | None = None  # the actor, one key on every item event


class ItemUpdatedPayload(TenantEventPayload):
    item: Any = None  # transitional: ORM Item
    changes: dict[str, Any] = Field(default_factory=dict)
    user_id: str | None = None


class ItemDeletedPayload(TenantEventPayload):
    item_id: str
    user_id: str | None = None


class ItemMovedPayload(TenantEventPayload):
    item: Any = None  # transitional: ORM Item
    changes: dict[str, Any] = Field(default_factory=dict)
    user_id: str | None = None


class ItemQuantityEventPayload(TenantEventPayload):
    """Shared shape for item.used / item.disposed."""

    item: Any = None  # transitional: jsonable_encoder dict of ORM Item
    quantity: float
    user_id: str


# ── Categories & locations ────────────────────────────────────────────────────


class CategoryCreatedPayload(TenantEventPayload):
    category_id: str


class CategoryUpdatedPayload(TenantEventPayload):
    category_id: str


class CategoryDeletedPayload(TenantEventPayload):
    category_id: str


class StorageCreatedPayload(TenantEventPayload):
    location_id: str


class StorageUpdatedPayload(TenantEventPayload):
    location_id: str
    changes: dict[str, Any] = Field(default_factory=dict)


class StorageDeletedPayload(TenantEventPayload):
    location_id: str


# ── Users & modules ──────────────────────────────────────────────────────────


class UserJoinedOrgPayload(TenantEventPayload):
    user: Any = None  # the member: id, email, full_name, role


class UserLeftOrgPayload(TenantEventPayload):
    user: Any = None  # the member: id, email, full_name, role


class ModuleEnabledPayload(TenantEventPayload):
    module_name: str


class ModuleDisabledPayload(TenantEventPayload):
    module_name: str


# ── Labels ───────────────────────────────────────────────────────────────────


class LabelBatchGeneratedPayload(TenantEventPayload):
    count: int
    label_ids: list[str] = Field(default_factory=list)
    label_type: str | None = None
    prefix: str | None = None
    created_by: str | None = None


class LabelBatchExportedPayload(TenantEventPayload):
    count: int
    label_ids: list[str] = Field(default_factory=list)
    width_mm: float | None = None
    height_mm: float | None = None


# ── Equipment module ─────────────────────────────────────────────────────────
# Module-owned contracts. They live in core until the planned move; each
# module re-declares them via ``register_payload`` in ``on_startup``.


class EquipmentCheckoutPayload(TenantEventPayload):
    """Module-owned (equipment) — lives here until the planned move."""

    assignment_id: str
    item_id: str
    item_name: str = ''
    assigned_to_name: str = ''
    user_id: str | None = None


class EquipmentCheckinPayload(TenantEventPayload):
    """Module-owned (equipment) — lives here until the planned move."""

    assignment_id: str
    item_id: str
    item_name: str = ''
    assigned_to_name: str = ''
    checkin_condition: str | None = None
    new_status: str | None = None
    user_id: str | None = None


# ── Partners ─────────────────────────────────────────────────────────────────


class PartnerActivatedPayload(TenantEventPayload):
    partner_id: str


class PartnerDeactivatedPayload(TenantEventPayload):
    partner_id: str


# ── Documents module ─────────────────────────────────────────────────────────


class DocumentConfirmedPayload(TenantEventPayload):
    """Module-owned (documents) — lives here until the planned move.

    Each line says what it is about — ``product_id``, ``product_code``,
    ``lot_id`` and ``lot_number`` (where the line names a batch, the id once
    the batch exists), ``source_location_id`` and ``source_location_code``,
    ``target_location_id`` and ``target_location_code``, ``unit`` — beside
    ``expected_quantity`` and ``done_quantity``. A dispatch or a scrap that
    named no batch is reported once per batch its draw took.
    """

    document_id: str
    document_type: str
    lines: list[dict[str, Any]] = Field(default_factory=list)


class DocumentCompletedPayload(TenantEventPayload):
    """Module-owned (documents) — lives here until the planned move."""

    document_id: str
    document_type: str
    lines: list[dict[str, Any]] = Field(default_factory=list)


class DocumentCancelledPayload(TenantEventPayload):
    """Module-owned (documents) — lives here until the planned move."""

    document_id: str
    document_type: str
    lines: list[dict[str, Any]] = Field(default_factory=list)


class DocumentShippedPayload(TenantEventPayload):
    """Module-owned (documents) — lives here until the planned move.

    A topic of its own rather than keys in ``document.completed``: that one
    fires for every document type and names no document number, and a
    receiver that books shipments would have to listen to every receipt and
    stock take to find the dispatches among them.
    """

    document_id: str
    document_number: str
    document_type: str
    carrier: str
    tracking_number: str | None = None
    tracking_url: str | None = None
    package_count: int = 0
    shipped_at: str
    #: The dispatch's lines, shaped as in ``document.completed``.
    lines: list[dict[str, Any]] = Field(default_factory=list)


# ── Purchase orders module ───────────────────────────────────────────────────


class PurchaseOrderConfirmedPayload(TenantEventPayload):
    """Module-owned (purchase_orders) — lives here until the planned move."""

    po_id: str
    po_number: str


class PurchaseOrderCompletedPayload(TenantEventPayload):
    """Module-owned (purchase_orders) — lives here until the planned move."""

    po_id: str
    po_number: str


class PurchaseOrderCancelledPayload(TenantEventPayload):
    """Module-owned (purchase_orders) — lives here until the planned move."""

    po_id: str
    po_number: str


class ReceiptCreatedFromPOPayload(TenantEventPayload):
    """Module-owned (purchase_orders) — lives here until the planned move."""

    receipt_id: str
    receipt_number: str
    po_id: str
    po_number: str


# ── Recipes module ───────────────────────────────────────────────────────────


class RecipeCreatedPayload(TenantEventPayload):
    """Module-owned (recipes) — lives here until the planned move."""

    recipe_id: str
    name: str


class RecipePickingCompletedPayload(TenantEventPayload):
    """Module-owned (recipes) — lives here until the planned move."""

    session_id: str
    recipe_id: str
    servings: int
    items_consumed: list[dict[str, Any]] = Field(default_factory=list)


class RecipeMealPlanGeneratedPayload(TenantEventPayload):
    """Module-owned (recipes) — lives here until the planned move."""

    plan_id: str
    shopping_list_id: str
    to_buy_count: int


__all__ = [
    'CategoryCreatedPayload',
    'CategoryDeletedPayload',
    'CategoryUpdatedPayload',
    'DocumentCancelledPayload',
    'DocumentCompletedPayload',
    'EquipmentCheckinPayload',
    'EquipmentCheckoutPayload',
    'EventPayload',
    'ItemCreatedPayload',
    'ItemDeletedPayload',
    'ItemMovedPayload',
    'ItemQuantityEventPayload',
    'ItemUpdatedPayload',
    'LabelBatchExportedPayload',
    'LabelBatchGeneratedPayload',
    'ModuleDisabledPayload',
    'ModuleEnabledPayload',
    'PartnerActivatedPayload',
    'PartnerDeactivatedPayload',
    'PurchaseOrderCancelledPayload',
    'PurchaseOrderCompletedPayload',
    'PurchaseOrderConfirmedPayload',
    'ReceiptCreatedFromPOPayload',
    'RecipeCreatedPayload',
    'RecipeMealPlanGeneratedPayload',
    'RecipePickingCompletedPayload',
    'StorageCreatedPayload',
    'StorageDeletedPayload',
    'StorageUpdatedPayload',
    'UserJoinedOrgPayload',
    'UserLeftOrgPayload',
]

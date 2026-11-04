# CoreAPI Reference

The **CoreAPI** (`app.core.public_api.core_api`) is a facade that exposes stable, module-safe methods for interacting with Core data. Modules must use CoreAPI instead of importing Core models or services directly.

**Location:** `backend/app/core/public_api/`

---

## Namespaces (33)

| Namespace | Class | Description |
|---|---|---|
| `core_api.ai_connections` | `CoreAIConnectionsAPI` | Public API used by the /api/v1/ai-connections router. |
| `core_api.ai_usage` | `CoreAIUsageAPI` | Public Core API for AI usage rate-limiting, cost estimation, and logging. |
| `core_api.admin` | `CoreAdminAPI` | Public Core API namespace for superadmin analytics. |
| `core_api.announcements` | `CoreAnnouncementsAPI` | Public Core API for module-safe announcement reads and writes. |
| `core_api.audit_log` | `CoreAuditLogAPI` | Public Core API for module-safe audit-trail reads + writes. |
| `core_api.items` | `CoreItemsAPI` | Public Core API for modules that need read and write access to items. |
| `core_api.item_history` | `CoreItemHistoryAPI` | Public Core API for item history write access. |
| `core_api.attachments` | `CoreAttachmentsAPI` | Public Core API for module-safe ItemAttachment access. |
| `core_api.labels` | `CoreLabelsAPI` | Public Core API for module-safe LabelPool reads and writes. |
| `core_api.llm` | `CoreLlmAPI` | Public Core API for LLM purposes and client resolution. |
| `core_api.organizations` | `CoreOrganizationsAPI` | Public Core API for module-safe organization access. |
| `core_api.roles` | `CoreRolesAPI` | Public Core API for module-safe role queries. |
| `core_api.scheduler` | `CoreSchedulerAPI` | Public Core API for periodic task registration. |
| `core_api.locations` | `CoreStoragesAPI` | Public Core API for module-safe location access. |
| `core_api.location_types` | `CoreStorageTypesAPI` | Public Core API for module-safe location type reads and writes. |
| `core_api.settings` | `CoreSettingsAPI` | Public Core API for module settings with namespace-per-module isolation. |
| `core_api.categories` | `CoreCategoriesAPI` | Public Core API for module-safe category reads and writes. |
| `core_api.email` | `CoreEmailAPI` | Public Core API for sending transactional email from modules. |
| `core_api.events` | `CoreEventsAPI` | Public Core API for validated event emission and subscription. |
| `core_api.notifications` | `CoreNotificationsAPI` | Public Core API for creating in-app notifications from modules. |
| `core_api.users` | `CoreUsersAPI` | Public Core API for module-safe user access. |
| `core_api.file_storage` | `CoreFileStorageAPI` | Public Core API for modules to use the configured file storage. |
| `core_api.secrets` | `CoreSecretsAPI` | Basic encryption helpers for module use. |
| `core_api.uoms` | `CoreUomsAPI` | Public Core API for module-safe UOM reads. |
| `core_api.product_templates` | `CoreProductTemplatesAPI` | Read and write access to ProductTemplate records for use by modules. |
| `core_api.queries` | `CoreQueriesAPI` | Public Core API namespace for analytics read-models. |
| `core_api.partners` | `CorePartnersAPI` | Public Core API for modules needing read/write access to Partners. |
| `core_api.pdf` | `CorePdfAPI` | Public Core API for PDF generation and template rendering. |
| `core_api.periods` | `CorePeriodsAPI` | Public Core API namespace for inventory period guards. |
| `core_api.stock` | `CoreStockAPI` | Public Core API for WMS stock operations. |
| `core_api.stock_moves` | `CoreStockMovesAPI` | Public Core API namespace for StockMove records. |
| `core_api.templates` | `CoreTemplatesAPI` | Public Core API for document template CRUD. |
| `core_api.valuation` | `CoreValuationAPI` | Public Core API for inventory valuation operations. |

---

## Method Reference

### `core_api.ai_connections` — `CoreAIConnectionsAPI`

| Method | Signature | R/W | Description |
|---|---|---|---|
| `create_async` | `(db: AsyncSession, org_id: uuid.UUID, data: AiConnectionCreateDTO) -> AiConnectionDTO` | WRITE | — |
| `delete_async` | `(db: AsyncSession, org_id: uuid.UUID, conn_id: uuid.UUID) -> bool` | WRITE | Delete a connection. Refuses with |
| `get_async` | `(db: AsyncSession, org_id: uuid.UUID, conn_id: uuid.UUID) -> AiConnectionDTO \| None` | READ | — |
| `list_async` | `(db: AsyncSession, org_id: uuid.UUID) -> list[AiConnectionDTO]` | READ | — |
| `list_purposes_async` | `(db: AsyncSession, org_id: uuid.UUID) -> list[AiPurposeDTO]` | READ | All registered purposes, with the choice and the verdict apart. |
| `set_binding_async` | `(db: AsyncSession, org_id: uuid.UUID, purpose_key: str, connection_id: uuid.UUID \| None) -> None` | WRITE | Set *purpose_key* -> *connection_id* for *org_id*. |
| `test_connection_async` | `(db: AsyncSession, org_id: uuid.UUID, *, connection_id: uuid.UUID \| None=None, provider: str \| None=None, api_key: str \| None=None, api_base_url: str \| None=None, model_name: str \| None=None, capabilities: list[str] \| None=None) -> dict[str, Any]` | READ | Validate credentials, then check the model against the contract. |
| `update_async` | `(db: AsyncSession, org_id: uuid.UUID, conn_id: uuid.UUID, data: AiConnectionUpdateDTO) -> AiConnectionDTO \| None` | WRITE | — |

---

### `core_api.ai_usage` — `CoreAIUsageAPI`

| Method | Signature | R/W | Description |
|---|---|---|---|
| `check_limit_async` | `(db: AsyncSession, organization_id: UUID, action_type: str) -> None` | READ | Async: raise AIUsageLimitExceededError if the org has exceeded its limits. |
| `count_usage_async` | `(db: AsyncSession, organization_id: UUID, *, since: datetime, action_type: str \| None=None) -> int` | READ | Count AI usage records for an organization since a given timestamp. |
| `enforce_limit_async` | `(db: AsyncSession, organization_id: UUID, action_type: str) -> None` | READ | Gate a billable AI call: over the ceiling it refuses, an outage it ignores. |
| `estimate_cost_async` | `(db: AsyncSession, model_name: str, prompt_tokens: int, completion_tokens: int, cache_read_tokens: int=0) -> tuple[float, bool]` | READ | Async: return (estimated_cost_usd, is_estimated) for the given model and token counts. |
| `get_global_stats_async` | `(db: AsyncSession, *, user: UserContextDTO, days: int=30) -> GlobalAIUsageStatsDTO` | READ | Global AI usage stats: requests, cost, top orgs, by model, daily chart. |
| `get_org_stats_async` | `(db: AsyncSession, organization_id: UUID, *, days: int=30) -> OrgAIUsageStatsDTO` | READ | Per-org AI usage breakdown with current month usage vs limits. |
| `log_llm_usage_async` | `(db: AsyncSession, user_id: UUID \| str \| None, organization_id: UUID \| str \| None, response: Any, action_type: str, client: Any \| None=None) -> None` | WRITE | Best-effort LLM usage logging shared by vision/recipes. |
| `log_usage_async` | `(db: AsyncSession, user_id: UUID \| None, organization_id: UUID, model_name: str, provider: str, action_type: str, prompt_tokens: int=0, completion_tokens: int=0, total_tokens: int=0, estimated_cost_usd: float=0.0, cost_is_estimated: bool=False) -> None` | WRITE | Async: log AI usage record to the database. |

---

### `core_api.admin` — `CoreAdminAPI`

| Method | Signature | R/W | Description |
|---|---|---|---|
| `get_global_stats_async` | `(db: AsyncSession, *, user: UserContextDTO) -> GlobalAdminStatsDTO` | READ | Global system stats: totals, DAU/WAU, LLM cost, scans. |
| `list_org_metrics_async` | `(db: AsyncSession, *, user: UserContextDTO) -> list[AdminOrgMetricsDTO]` | READ | List all organizations with SaaS metrics (members/items/storage/value/activity). |

---

### `core_api.announcements` — `CoreAnnouncementsAPI`

| Method | Signature | R/W | Description |
|---|---|---|---|
| `create_async` | `(db: AsyncSession, announcement_in: AnnouncementCreateDTO, user: UserContextDTO) -> AnnouncementDTO` | WRITE | Create a new global announcement. Returns the AnnouncementDTO. |
| `delete_async` | `(db: AsyncSession, announcement_id: UUID) -> bool` | WRITE | Delete an announcement by ID. Returns ``True`` if deleted, ``False`` if not found. |
| `get_by_id_async` | `(db: AsyncSession, announcement_id: UUID) -> AnnouncementDTO \| None` | READ | Return a single announcement by ID, or ``None``. |
| `list_active_async` | `(db: AsyncSession) -> list[AnnouncementDTO]` | READ | Return currently active announcements (now within active window). |
| `list_all_async` | `(db: AsyncSession) -> list[AnnouncementDTO]` | READ | Return all announcements (active, expired, future) ordered newest first. |

---

### `core_api.audit_log` — `CoreAuditLogAPI`

| Method | Signature | R/W | Description |
|---|---|---|---|
| `list_for_org_async` | `(db: AsyncSession, organization_id: UUID, *, target_type: str \| None=None, target_id: UUID \| None=None, user_id: UUID \| None=None, actor: str \| None=None, since: datetime \| None=None, until: datetime \| None=None, limit: int=500, offset: int=0, after: tuple[datetime, UUID] \| None=None, known_total: int \| None=None) -> tuple[list[AuditLogDTO], int]` | READ | Return audit entries for one organization, newest first. |
| `list_for_target_async` | `(db: AsyncSession, organization_id: UUID, target_type: str, target_id: UUID, *, limit: int=200) -> list[AuditLogDTO]` | READ | Return audit entries for one (target_type, target_id), newest first. |
| `list_target_types_async` | `(db: AsyncSession, organization_id: UUID) -> list[str]` | READ | The distinct target types this organization's log actually holds. |
| `log_action_async` | `(db: AsyncSession, *, organization_id: UUID, user_id: UUID \| None, action: AuditAction, target_type: str, target_id: UUID, snapshot: dict[str, Any] \| None=None, reason: str \| None=None, meta_data: dict[str, Any] \| None=None) -> None` | WRITE | Module-safe write surface for audit entries. |

---

### `core_api.items` — `CoreItemsAPI`

| Method | Signature | R/W | Description |
|---|---|---|---|
| `bind_template_async` | `(db: AsyncSession, organization_id: UUID, item_id: UUID, template_id: UUID, *, user_id: UUID \| None=None, source_document_id: UUID \| None=None, unit_confirmed_over_template: bool=False) -> ItemDTO \| None` | WRITE | Point a record at its product card — the link, and the paper behind it. |
| `count_async` | `(db: AsyncSession, organization_id: UUID, *, is_deleted: bool=False, category_id: UUID \| None=None, context_tag: str \| None=None) -> int` | READ | — |
| `create_async` | `(db: AsyncSession, organization_id: UUID, data: ItemCreateDTO, user: UserContextDTO, *, source_document_id: UUID \| None=None, history_changes: dict[str, Any] \| None=None, post_the_change: bool=True, unit_confirmed_over_template: bool=False) -> ItemDTO` | WRITE | Create an item through the standard service pipeline. |
| `distinct_uom_ids_for_template_async` | `(db: AsyncSession, organization_id: UUID, *, template_id: UUID) -> list[UUID \| None]` | READ | Every distinct unit the items of one product carry. |
| `existing_ids_async` | `(db: AsyncSession, organization_id: UUID, item_ids: set[UUID]) -> set[UUID]` | WRITE | Return the subset of *item_ids* that exist for *organization_id* — one query. |
| `find_by_barcode_async` | `(db: AsyncSession, organization_id: UUID, barcode: str, *, quantity_positive: bool=True, for_update: bool=False) -> ItemDTO \| None` | READ | Return the first item with *barcode* in *organization_id*. |
| `find_stock_row_async` | `(db: AsyncSession, organization_id: UUID, *, barcode: str \| None=None, template_id: UUID \| None=None, expiry_date: date \| None=None, storage_location_id: UUID \| None=None, lot_id: UUID \| None=None, owner_id: UUID \| None=None, for_update: bool=False) -> ItemDTO \| None` | WRITE | Return the record a delivery to this place tops up. |
| `get_any_async` | `(db: AsyncSession, organization_id: UUID, item_id: UUID) -> ItemDTO \| None` | READ | Get item including soft-deleted ones (for protocol rendering). |
| `get_async` | `(db: AsyncSession, organization_id: UUID, item_id: UUID) -> ItemDTO \| None` | READ | — |
| `get_for_update_async` | `(db: AsyncSession, organization_id: UUID, item_id: UUID) -> ItemDTO \| None` | WRITE | Return a single item with row-level lock (SELECT ... FOR NO KEY UPDATE). |
| `has_active_barcode_async` | `(db: AsyncSession, organization_id: UUID, barcode: str) -> bool` | READ | — |
| `inherited_category_async` | `(db: AsyncSession, organization_id: UUID, *, source_category_id: UUID \| None=None, template_id: UUID \| None=None) -> UUID \| None` | READ | The category a new record of this product is filed under. |
| `latest_purchase_prices_async` | `(db: AsyncSession, organization_id: UUID, template_ids: list[UUID]) -> dict[UUID, Decimal]` | READ | The newest recorded purchase price of each product that has one. |
| `list_async` | `(db: AsyncSession, organization_id: UUID, *, storage_location_id: UUID \| None=None, template_id: UUID \| None=None, storage_usage: str \| None=None, category_id: UUID \| None=None, context_tag: str \| None=None, limit: int=100, offset: int=0) -> list[ItemDTO]` | READ | List items using an AsyncSession. |
| `list_by_expiry_async` | `(db: AsyncSession, organization_id: UUID, *, template_ids: list[UUID] \| None=None, location_id: UUID \| None=None, storage_usage: str \| None=None, order: str='asc', limit: int=500) -> list[ItemDTO]` | READ | List active items sorted by ``expiry_date`` (FEFO picking order). |
| `list_existing_serials_async` | `(db: AsyncSession, organization_id: UUID, serial_numbers: set[str]) -> set[str]` | READ | — |
| `list_expiring_by_template_async` | `(db: AsyncSession, organization_id: UUID, *, template_ids: set[UUID], expiry_after: date, expiry_before: date) -> dict[UUID, list[ItemDTO]]` | READ | Load items expiring within a date range, grouped by template_id. |
| `list_with_template_async` | `(db: AsyncSession, organization_id: UUID, template_ids: list[UUID]) -> dict[UUID, list[ItemDTO]]` | READ | Batch-load active items grouped by template_id. |
| `lock_records_async` | `(db: AsyncSession, organization_id: UUID, item_ids: Iterable[UUID]) -> None` | WRITE | Take the row locks of *item_ids* in one statement. |
| `open_to_take_part_async` | `(db: AsyncSession, organization_id: UUID, item_id: UUID, *, user_id: UUID) -> ItemDTO \| None` | WRITE | Open the package a part is about to be taken from (writes the opening). |
| `post_opening_balance_async` | `(db: AsyncSession, organization_id: UUID, item_id: UUID, *, template_id: UUID, holding: Decimal, user_id: UUID \| None, location_id: UUID \| None=None) -> None` | WRITE | Post what a record held before it had a card as its opening balance. |
| `purge_async` | `(db: AsyncSession, organization_id: UUID, item_id: UUID, user: UserContextDTO, reason: str \| None=None) -> bool` | WRITE | — |
| `search_cursor_paginated_async` | `(db: AsyncSession, organization_id: UUID, *, storage_ids: list[UUID] \| None=None, storage_id: UUID \| None=None, search: str \| None=None, quantity_above: Decimal \| None=None, cursor_ts: datetime \| None=None, cursor_id: UUID \| None=None, limit: int=50) -> CursorPaginatedDTO[ItemDTO]` | READ | Cursor-paginated items list using keyset pagination on created_at. |
| `search_stock_summary_async` | `(db: AsyncSession, organization_id: UUID, *, storage_ids: list[UUID] \| None=None, search: str \| None=None, quantity_above: Decimal \| None=None, limit: int=50) -> list[tuple[ItemDTO, Decimal, bool]]` | READ | Stock rows for a picker: distinguishable ones individually, |
| `soft_delete_async` | `(db: AsyncSession, organization_id: UUID, item_id: UUID, user: UserContextDTO, reason: str \| None=None, notes: str \| None=None) -> bool` | WRITE | — |
| `transfer_async` | `(db: AsyncSession, organization_id: UUID, item_id: UUID, to_storage_location_id: UUID, *, user_id: UUID, source_document_id: UUID \| None=None, notes: str \| None=None, history_changes: dict[str, Any] \| None=None, history_action: ItemAction=<ItemAction.MOVED: 'MOVED'>, post_the_change: bool=True) -> ItemDTO \| None` | WRITE | — |
| `update_async` | `(db: AsyncSession, organization_id: UUID, item_id: UUID, data: ItemUpdateDTO, user: UserContextDTO) -> ItemDTO \| None` | WRITE | — |
| `update_meta_data_async` | `(db: AsyncSession, organization_id: UUID, item_id: UUID, namespace: str, data: dict[str, Any]) -> ItemDTO \| None` | WRITE | Update item meta_data in a namespaced way. |
| `update_quantity_async` | `(db: AsyncSession, organization_id: UUID, item_id: UUID, quantity: Decimal, *, user_id: UUID, source_document_id: UUID \| None=None, history_changes: dict[str, Any] \| None=None, sync_valuation: bool=True, post_the_change: bool=True, lot_id: UUID \| None=None, move_reference_type: str='item', move_reference_id: UUID \| None=None) -> ItemDTO \| None` | WRITE | Set an item's quantity and post the change to the ledger. |

---

### `core_api.item_history` — `CoreItemHistoryAPI`

| Method | Signature | R/W | Description |
|---|---|---|---|
| `list_for_item_async` | `(db: AsyncSession, item_id: UUID, organization_id: UUID, *, limit: int=50, actions: Sequence[str] \| None=None) -> list[ItemHistoryDTO]` | READ | Newest-first history of one item, as the entry DTO. |
| `log_async` | `(db: AsyncSession, item_id: UUID, organization_id: UUID, user_id: UUID, action: str, changes: dict[str, Any]) -> None` | WRITE | Create an ItemHistory record. Calls db.flush() — caller commits. |

---

### `core_api.attachments` — `CoreAttachmentsAPI`

| Method | Signature | R/W | Description |
|---|---|---|---|
| `find_by_file_path_async` | `(db: AsyncSession, file_path: str, organization_id: UUID) -> ItemAttachmentDTO \| None` | READ | Find an ItemAttachment DTO by its stored file_path. |
| `get_attachment_with_item_async` | `(db: AsyncSession, attachment_id: UUID, organization_id: UUID) -> ItemAttachmentDTO \| None` | READ | Return an ItemAttachment DTO with eager-loaded item.storage_location, or None. |
| `get_item_with_storage_async` | `(db: AsyncSession, item_id: UUID, organization_id: UUID) -> ItemDTO \| None` | READ | Return an Item DTO with eager-loaded storage_location, or None. |

---

### `core_api.labels` — `CoreLabelsAPI`

| Method | Signature | R/W | Description |
|---|---|---|---|
| `assign_to_existing_item_async` | `(db: AsyncSession, short_code: str, item_id: UUID, organization_id: UUID, *, user_id: UUID \| None=None) -> LabelPoolDTO \| None` | WRITE | Assign a label to an existing item (returns refreshed DTO, ``None`` when not found). |
| `caption` | `(label: LabelPoolDTO) -> str \| None` | READ | The text printed under a label's QR code when nobody typed one. |
| `create_from_codes_async` | `(db: AsyncSession, codes: list[LabelCodeItemDTO], user: UserContextDTO, *, label_type: str='GENERIC', context_tag: str \| None=None) -> list[LabelPoolDTO]` | WRITE | Create labels with explicit short_codes (org-scoped). |
| `delete_async` | `(db: AsyncSession, label_id: UUID, organization_id: UUID, *, user_id: UUID \| None=None) -> bool` | WRITE | Delete a label scoped to *organization_id*. Returns ``False`` when not found. |
| `generate_pool_async` | `(db: AsyncSession, request: LabelPoolCreateDTO, user: UserContextDTO) -> list[LabelPoolDTO]` | WRITE | Generate a pool of N unique labels. |
| `get_by_id_async` | `(db: AsyncSession, label_id: UUID, organization_id: UUID) -> LabelPoolDTO \| None` | READ | Return a single label by ID scoped to *organization_id*, or ``None``. |
| `get_by_short_code_async` | `(db: AsyncSession, short_code: str, organization_id: UUID) -> LabelPoolDTO \| None` | READ | Return a single label by short_code scoped to *organization_id*, or ``None``. |
| `get_pool_stats_async` | `(db: AsyncSession, organization_id: UUID) -> dict[str, Any]` | READ | Return pool stats: total / assigned counts. |
| `list_by_short_codes_async` | `(db: AsyncSession, short_codes: list[str], organization_id: UUID) -> list[LabelPoolDTO]` | READ | Return labels whose short_code is in *short_codes* scoped to *organization_id*. |
| `list_for_org_async` | `(db: AsyncSession, organization_id: UUID, *, unassigned_only: bool=False) -> list[LabelPoolDTO]` | READ | List labels for *organization_id*, optionally filtered to unassigned. |
| `list_for_org_with_relations_async` | `(db: AsyncSession, organization_id: UUID, *, unassigned_only: bool=False, label_type: str \| None=None, status: str \| None=None, offset: int=0, limit: int \| None=None) -> tuple[list[LabelPoolDTO], int]` | READ | List labels for *organization_id* with eager-loaded assigned_item. |
| `list_in_ids_async` | `(db: AsyncSession, label_ids: list[UUID], organization_id: UUID) -> list[LabelPoolDTO]` | READ | Return labels whose IDs are in *label_ids* scoped to *organization_id*. |
| `list_unprinted_unassigned_async` | `(db: AsyncSession, organization_id: UUID, *, limit: int, exclude_ids: list[UUID] \| None=None) -> list[LabelPoolDTO]` | WRITE | List unprinted + unassigned labels for *organization_id*. |
| `mark_as_printed_by_ids_async` | `(db: AsyncSession, label_ids: list[UUID], organization_id: UUID) -> None` | WRITE | Mark labels as printed by their IDs (scoped to *organization_id*). |
| `unassign_async` | `(db: AsyncSession, short_code: str, organization_id: UUID, *, user_id: UUID \| None=None) -> LabelPoolDTO \| None` | WRITE | Unassign a label by short_code (returns refreshed DTO, ``None`` when not found). |

---

### `core_api.llm` — `CoreLlmAPI`

| Method | Signature | R/W | Description |
|---|---|---|---|
| `connection_for_purpose_async` | `(db: AsyncSession, organization_id: UUID, purpose_key: str) -> Any \| None` | READ | Resolve the bound connection **row** for *purpose_key*. |
| `extract_from_images_async` | `(db: AsyncSession, organization_id: UUID, *, purpose_key: str, schema: type[T], instructions: str, images: Sequence[bytes], action_type: str, user_id: UUID \| str \| None=None, temperature: float=0.2, max_tokens: int=8000, disable_reasoning: bool=True) -> T` | READ | Read *schema* out of *images*, and account for what it cost. |
| `get_client_for_purpose_async` | `(db: AsyncSession, organization_id: UUID, purpose_key: str) -> LlmClient \| None` | READ | Resolve the LLM client bound to *purpose_key* for the organization. |
| `register_purpose` | `(key: str, capability: LlmCapability, label_key: str, description_key: str, owner_module: str, probe: AiContractProbe \| None=None) -> None` | READ | Register an AI purpose (idempotent; conflict raises ValueError). |

---

### `core_api.organizations` — `CoreOrganizationsAPI`

| Method | Signature | R/W | Description |
|---|---|---|---|
| `apply_onboarding_profile_async` | `(db: AsyncSession, organization: OrganizationDTO, profile_id: str, user: UserContextDTO \| None=None, currency: str \| None=None, modules: list[str] \| None=None, timezone: str \| None=None, organization_name: str \| None=None, country: str \| None=None, use_country_preset: bool=False) -> OrganizationDTO` | WRITE | Apply a product profile to *organization* (idempotent onboarding). |
| `get_async` | `(db: AsyncSession, organization_id: UUID) -> OrganizationDTO \| None` | READ | — |
| `get_name_async` | `(db: AsyncSession, organization_id: UUID) -> str \| None` | READ | Async: return the organization name, or ``None`` if not found. |
| `get_settings_async` | `(db: AsyncSession, organization_id: UUID) -> dict[str, Any] \| None` | WRITE | — |
| `is_module_enabled_async` | `(db: AsyncSession, organization_id: UUID, module_name: str) -> bool` | READ | — |
| `list_all_async` | `(db: AsyncSession) -> list[OrganizationDTO]` | READ | Async: list all organizations (superadmin only). |
| `list_missing_short_id_async` | `(db: AsyncSession) -> list[OrganizationDTO]` | READ | List organizations without a short_id (startup repair). |
| `timezone_async` | `(db: AsyncSession, organization_id: UUID) -> tzinfo` | READ | The organization's own clock. |
| `today_async` | `(db: AsyncSession, organization_id: UUID) -> date` | READ | What day it is where this organization is. |
| `toggle_module_async` | `(db: AsyncSession, organization: OrganizationDTO, module_name: str, enabled: bool, user: UserContextDTO) -> list[str]` | WRITE | Toggle a module on/off for *organization*. Returns the new enabled list. |
| `update_async` | `(db: AsyncSession, organization_id: UUID, **fields: Any) -> OrganizationDTO \| None` | WRITE | Update organization fields. |
| `window_start_async` | `(db: AsyncSession, organization_id: UUID, days: int) -> datetime` | READ | The instant *days* local days ago began, as a point in time. |

---

### `core_api.roles` — `CoreRolesAPI`

| Method | Signature | R/W | Description |
|---|---|---|---|
| `administrators_async` | `(db: AsyncSession, *, organization_id: UUID) -> set[UUID]` | READ | Everybody who administers this organisation, by authority. |
| `assign_async` | `(db: AsyncSession, organization_id: UUID, user_id: UUID, role_id: UUID, actor_user_id: UUID) -> bool` | WRITE | Link a user to a role. Idempotent. |
| `check_user_permission_async` | `(db: AsyncSession, *, user_id: UUID, organization_id: UUID, permission: str) -> bool` | READ | Fresh DB lookup: does *user_id* hold *permission* in this org? |
| `create_async` | `(db: AsyncSession, *, organization_id: UUID, name: str, permissions: list[str]) -> RoleDTO` | WRITE | Create a new org-scoped role. |
| `delete_async` | `(db: AsyncSession, *, organization_id: UUID, role_id: UUID) -> None` | WRITE | Delete an org role, refusing while somebody still holds it. |
| `has_holder_async` | `(db: AsyncSession, *, organization_id: UUID, permission: str) -> bool` | READ | Whether anybody in this organisation holds *permission*. |
| `holders_async` | `(db: AsyncSession, *, organization_id: UUID, role_id: UUID) -> list[RoleHolderDTO]` | READ | Everyone in the organisation who currently holds the role. |
| `holders_of_permission_async` | `(db: AsyncSession, *, organization_id: UUID, permission: str) -> set[UUID]` | READ | Everybody in this organisation who currently holds *permission*. |
| `list_for_org_async` | `(db: AsyncSession, organization_id: UUID) -> list[RoleDTO]` | READ | Return every role available in an organisation (admin tooling). |
| `list_for_user_async` | `(db: AsyncSession, organization_id: UUID, user_id: UUID) -> list[RoleDTO]` | READ | Return the roles this user holds in the given org. |
| `org_role_map_async` | `(db: AsyncSession, *, organization_id: UUID, user_ids: list[UUID]) -> dict[UUID, RoleDTO]` | READ | The org-scoped custom role each given user holds, keyed by user id. |
| `permissions_for_users_async` | `(db: AsyncSession, *, organization_id: UUID, user_ids: list[UUID]) -> dict[UUID, set[str]]` | READ | Every permission each of these people holds, in two queries. |
| `rename_async` | `(db: AsyncSession, *, organization_id: UUID, role_id: UUID, name: str) -> RoleDTO` | READ | Give an existing org role a new name. |
| `role_ids_for_user_async` | `(db: AsyncSession, organization_id: UUID, user_id: UUID) -> set[UUID]` | READ | Every role this user holds here, the built-in level included. |
| `update_permissions_async` | `(db: AsyncSession, *, organization_id: UUID, role_id: UUID, permissions: list[str]) -> RoleDTO` | WRITE | Replace the permission set on an existing role. |

---

### `core_api.scheduler` — `CoreSchedulerAPI`

| Method | Signature | R/W | Description |
|---|---|---|---|
| `register_task` | `(name: str, interval: timedelta, handler: Callable[[], Any], *, module_name: str, is_persistent: bool=False) -> None` | READ | Register a periodic task under ``<module_name>.<name>``. |
| `unregister_task` | `(name: str, *, module_name: str) -> bool` | READ | Unregister a periodic task. Returns True when the task existed. |

---

### `core_api.locations` — `CoreStoragesAPI`

| Method | Signature | R/W | Description |
|---|---|---|---|
| `count_expiring_soon_async` | `(db: AsyncSession, organization_id: UUID, storage_id: UUID, *, days: int=7) -> int` | READ | Count non-deleted items in *storage_id* expiring within *days*. |
| `count_items_in_location_async` | `(db: AsyncSession, organization_id: UUID, storage_id: UUID) -> int` | READ | Count non-deleted items in *storage_id*. |
| `count_items_in_subtree_async` | `(db: AsyncSession, organization_id: UUID, storage_id: UUID) -> int` | READ | Count non-deleted items in *storage_id* and all its descendants. |
| `create_async` | `(db: AsyncSession, organization_id: UUID, *, name: str, user_id: UUID, description: str \| None=None, behavior_mode: str \| None=None, context_tag: str \| None=None, usage: str \| None=None, parent_id: UUID \| None=None) -> StorageDTO` | WRITE | Create a storage location. Runs interceptors and emits events. |
| `descendant_ids_async` | `(db: AsyncSession, organization_id: UUID, storage_id: UUID) -> list[UUID]` | READ | All storage ids below *storage_id* (excludes the node itself). |
| `find_by_context_tag_async` | `(db: AsyncSession, organization_id: UUID, context_tag: str) -> StorageDTO \| None` | READ | — |
| `find_by_scanned_code_async` | `(db: AsyncSession, organization_id: UUID, code: str) -> StorageDTO \| None` | READ | The location a scanned code names (its own code or its label's), or ``None``. |
| `get_async` | `(db: AsyncSession, organization_id: UUID, storage_id: UUID) -> StorageDTO \| None` | READ | — |
| `get_with_type_async` | `(db: AsyncSession, organization_id: UUID, storage_id: UUID) -> StorageDTO \| None` | READ | Return a storage location with eager-loaded storage_type, or ``None``. |
| `item_counts_by_location_async` | `(db: AsyncSession, organization_id: UUID, storage_ids: list[UUID]) -> dict[UUID, int]` | READ | Return {storage_id: count} for non-deleted items in those storages. |
| `label_caption` | `(storage: StorageDTO) -> str \| None` | READ | The text under the QR code of this location's label. |
| `list_async` | `(db: AsyncSession, organization_id: UUID, *, context_tag: str \| None=None, usage: str \| None=None, limit: int=200, offset: int=0) -> list[StorageDTO]` | READ | — |
| `list_by_ids_async` | `(db: AsyncSession, organization_id: UUID, storage_ids: Iterable[UUID]) -> list[StorageDTO]` | READ | The named locations that exist and are not archived, ordered by name. |
| `list_holding_stock_with_ancestors_async` | `(db: AsyncSession, organization_id: UUID, *, usage: str='internal') -> list[StorageDTO]` | READ | The locations of *usage* holding a live record, with the chains above them. |
| `list_items_in_location_async` | `(db: AsyncSession, organization_id: UUID, storage_id: UUID, *, include_inside: bool=False, limit: int \| None=None, offset: int=0) -> list[ItemDTO]` | READ | List non-deleted items in *storage_id* ordered by expiry ascending. |
| `list_storage_ids_async` | `(db: AsyncSession, organization_id: UUID) -> list[UUID]` | READ | Return just the IDs of storage locations for *organization_id*. |
| `scannable_code_async` | `(db: AsyncSession, organization_id: UUID, storage_id: UUID) -> str \| None` | READ | The code that names *storage_id* when scanned — its own, or its label's. |
| `subtree_and_ancestors_async` | `(db: AsyncSession, organization_id: UUID, storage_id: UUID) -> tuple[list[StorageDTO], list[StorageDTO]]` | READ | ``(subtree, ancestors)`` of a location, without reading the rest of the tree. |

---

### `core_api.location_types` — `CoreStorageTypesAPI`

| Method | Signature | R/W | Description |
|---|---|---|---|
| `create_async` | `(db: AsyncSession, storage_type_in: StorageTypeCreateDTO, user: UserContextDTO, lang: str \| None=None) -> StorageTypeDTO` | WRITE | Create a new storage type. Returns the StorageTypeDTO. |
| `delete_async` | `(db: AsyncSession, storage_type_id: UUID, user: UserContextDTO) -> bool` | WRITE | Delete a storage type. Returns ``True`` if deleted, ``False`` if not found. |
| `get_by_id_async` | `(db: AsyncSession, storage_type_id: UUID, organization_id: UUID, *, include_global: bool=False) -> StorageTypeDTO \| None` | READ | Return a single storage type by ID, or ``None``. |
| `list_for_org_async` | `(db: AsyncSession, organization_id: UUID) -> list[StorageTypeDTO]` | READ | Return the storage types *organization_id* owns, in a stable order. |
| `update_async` | `(db: AsyncSession, storage_type_id: UUID, storage_type_in: StorageTypeUpdateDTO, user: UserContextDTO, lang: str \| None=None) -> StorageTypeDTO \| None` | WRITE | Update a storage type (handles system forking). Returns updated DTO or None. |

---

### `core_api.settings` — `CoreSettingsAPI`

| Method | Signature | R/W | Description |
|---|---|---|---|
| `encrypt_secret` | `(module_name: str, value: str) -> str` | WRITE | Return *value* at rest, bound to *module_name*. |
| `get_async` | `(db: AsyncSession, organization_id: UUID, module_name: str, key: str \| None=None, default: JSONValue=None) -> JSONValue` | READ | Async: read a module setting. Secret fields are masked. |
| `get_decrypted_async` | `(db: AsyncSession, organization_id: UUID, module_name: str, key: str \| None=None, default: JSONValue=None) -> JSONValue` | READ | Async: the plaintext value of one secret field for *module_name*. |
| `get_default_org_limits_async` | `(db: AsyncSession) -> dict[str, Any]` | READ | Async: return default AI/item/member limits for new organizations. |
| `get_org_limits_async` | `(db: AsyncSession, organization_id: UUID) -> dict[str, Any]` | READ | Async: return effective AI limits for *organization_id*. |
| `get_schema_version_async` | `(db: AsyncSession, organization_id: UUID, module_name: str) -> int` | READ | Async: the settings-schema version this organization's blob carries. |
| `list_system_settings_async` | `(db: AsyncSession) -> list[dict[str, Any]]` | WRITE | Return all global system settings rows (model pricing, default limits). |
| `migrate_settings_async` | `(db: AsyncSession, module_name: str, migrate: Callable[..., Any]) -> int` | WRITE | Async: rewrite every organization's settings blob for *module_name*. |
| `set_bulk_async` | `(db: AsyncSession, organization_id: UUID, module_name: str, values: JSONObject) -> None` | WRITE | Async: set multiple module settings at once (shallow merge). |
| `set_system_setting_async` | `(db: AsyncSession, key: str, value: JSONValue, updated_by: UUID \| None=None) -> tuple[str, JSONValue, datetime \| None]` | WRITE | Upsert a global system setting; invalidates the in-process cache. |

---

### `core_api.categories` — `CoreCategoriesAPI`

| Method | Signature | R/W | Description |
|---|---|---|---|
| `create_async` | `(db: AsyncSession, category_in: CategoryCreateDTO, user: UserContextDTO) -> CategoryDTO` | WRITE | Create a new category. Returns the created CategoryDTO. |
| `delete_async` | `(db: AsyncSession, organization_id: UUID, category_id: UUID, user: UserContextDTO) -> bool` | WRITE | Delete a category by ID. Returns ``True`` if deleted, ``False`` if not found. |
| `existing_ids_async` | `(db: AsyncSession, organization_id: UUID, category_ids: set[UUID]) -> set[UUID]` | WRITE | Return the subset of *category_ids* visible to *organization_id* — one query. |
| `get_by_id_async` | `(db: AsyncSession, organization_id: UUID, category_id: UUID) -> CategoryDTO \| None` | READ | Return a single category visible to *organization_id*, or ``None``. |
| `list_async` | `(db: AsyncSession, organization_id: UUID) -> list[CategoryDTO]` | READ | Return all active categories using an AsyncSession. |
| `list_with_filters_async` | `(db: AsyncSession, organization_id: UUID, *, include_inactive: bool=False, claimed_tags: set[str] \| None=None, with_counts: bool=False) -> list[CategoryDTO]` | READ | List categories visible to *organization_id* with optional filters. |
| `rename_group_async` | `(db: AsyncSession, organization_id: UUID, *, current_name: str, new_name: str \| None, category_ids: list[UUID] \| None=None, user: UserContextDTO) -> list[UUID]` | READ | Rename a category group, or take it off the categories that carry it. |
| `update_async` | `(db: AsyncSession, organization_id: UUID, category_id: UUID, category_in: CategoryUpdateDTO, user: UserContextDTO) -> CategoryDTO \| None` | WRITE | Update a category by ID. Returns the updated CategoryDTO or ``None``. |

---

### `core_api.email` — `CoreEmailAPI`

| Method | Signature | R/W | Description |
|---|---|---|---|
| `is_configured` | `() -> bool` | READ | Whether a message sent through ``send_async`` could leave at all. |
| `render_button` | `(url: str, label: str) -> str` | READ | The one centred call to action these emails carry. |
| `render_fallback_link` | `(intro: str, url: str) -> str` | READ | The address spelled out, for a client that shows no button. |
| `render_shell` | `(heading: str, body_html: str, footer: str) -> str` | READ | The card every transactional email arrives in. |
| `send_async` | `(to_email: str, subject: str, html_content: str, smtp_config: dict[str, Any] \| None=None, *, organization_id: UUID) -> bool` | WRITE | Send an HTML email asynchronously (SMTP I/O offloaded to a thread). |
| `send_with_attachment_async` | `(to_email: str, subject: str, html_content: str, attachment_bytes: bytes, attachment_filename: str, smtp_config: dict[str, Any] \| None=None, *, organization_id: UUID) -> bool` | WRITE | Send an HTML email with an attachment via the durable queue. |

---

### `core_api.events` — `CoreEventsAPI`

| Method | Signature | R/W | Description |
|---|---|---|---|
| `emit_async` | `(event: SystemEvent \| str, payload: Mapping[str, Any] \| EventPayload) -> None` | READ | Emit an event after validating its payload against the registry. |
| `emit_transactional_async` | `(db: AsyncSession, event: SystemEvent \| str, payload: Mapping[str, Any] \| EventPayload) -> None` | READ | Outbox-backed emit riding the caller's transaction. |
| `flush_pending_async` | `(db: AsyncSession) -> None` | READ | Dispatch TESTING-buffered transactional events after ``db.commit()``. |
| `register_payload` | `(event_name: str, model: type[EventPayload]) -> None` | READ | Declare the payload contract for one of this module's events. |
| `registered_events` | `() -> dict[str, str]` | READ | Return ``{event_name: payload_type_name}`` for the event catalog. |
| `subscribe` | `(event: SystemEvent \| str, handler: Callable[[EventPayload], Any], *, org_filter: UUID \| str \| None=None) -> None` | READ | Subscribe to an event with payload coercion and optional org filter. |

---

### `core_api.notifications` — `CoreNotificationsAPI`

| Method | Signature | R/W | Description |
|---|---|---|---|
| `create_async` | `(db: AsyncSession, user_id: UUID, title: LocalizedText, content: LocalizedText, notification_type: str='info', link: str \| None=None, meta_data: dict[str, Any] \| None=None) -> NotificationDTO \| None` | WRITE | Persist a new in-app notification row. |
| `delete_async` | `(db: AsyncSession, notification_id: UUID, user_id: UUID) -> bool` | WRITE | Delete a notification. Returns ``True`` if deleted, ``False`` if not found. |
| `exists_unread_by_meta_async` | `(db: AsyncSession, organization_id: UUID, key: NotificationDedupKey, since: datetime) -> bool` | READ | Deduplication probe for periodic alert workers. |
| `get_by_id_for_user_async` | `(db: AsyncSession, notification_id: UUID, user_id: UUID) -> NotificationDTO \| None` | READ | Return a single notification by ID, scoped to *user_id*. |
| `list_for_user_async` | `(db: AsyncSession, user_id: UUID, *, unread_only: bool=False, skip: int=0, limit: int=50) -> list[NotificationDTO]` | READ | Return notifications for *user_id* ordered newest first. |
| `localize` | `(table: Mapping[str, str], /, **values: object) -> dict[str, str]` | READ | Fill one format string per language. |
| `mark_all_read_async` | `(db: AsyncSession, user_id: UUID) -> None` | WRITE | Mark all notifications as read for *user_id*. |
| `mark_read_by_meta_async` | `(db: AsyncSession, organization_id: UUID, ref_key: str, ref_id: str) -> int` | WRITE | Mark the org's unread notifications about one record as read. |
| `notify_org_admins_async` | `(db: AsyncSession, organization_id: UUID, title: LocalizedText, content: LocalizedText, notification_type: str='info', link: str \| None=None, meta_data: dict[str, Any] \| None=None) -> list[NotificationDTO]` | WRITE | Notify every member who administers *organization_id*. |
| `publish_async` | `(db: AsyncSession, notifications: NotificationDTO \| list[NotificationDTO] \| None) -> None` | READ | Publish already-committed notifications to the WS hub via Redis. |
| `update_read_status_async` | `(db: AsyncSession, notification_id: UUID, user_id: UUID, is_read: bool) -> NotificationDTO \| None` | WRITE | Update a notification's read status. Returns the updated DTO or None. |

---

### `core_api.users` — `CoreUsersAPI`

| Method | Signature | R/W | Description |
|---|---|---|---|
| `activate_or_deactivate_async` | `(db: AsyncSession, organization_id: UUID \| None, user_id: UUID, *, actor_user_id: UUID \| None=None) -> UserDTO \| None` | WRITE | Toggle a user's ``is_active`` flag. Returns updated user, or None. |
| `block_async` | `(db: AsyncSession, organization_id: UUID \| None, user_id: UUID, reason: str \| None, *, actor_user_id: UUID \| None=None) -> UserDTO \| None` | WRITE | Block a user with optional reason. Returns updated user, or None. |
| `count_async` | `(db: AsyncSession, organization_id: UUID) -> int` | READ | Async: count users in an organization (used by list_all_organizations). |
| `get_async` | `(db: AsyncSession, organization_id: UUID \| None, user_id: UUID) -> UserProfileDTO \| None` | READ | Load a user profile, scoped to *organization_id*. |
| `get_by_email_async` | `(db: AsyncSession, organization_id: UUID \| None, email: str) -> UserDTO \| None` | READ | Get a user DTO by email, scoped to *organization_id*. |
| `get_by_id_in_org_async` | `(db: AsyncSession, user_id: UUID, organization_id: UUID) -> UserDTO \| None` | READ | Async: get a User DTO by id within a specific organization, or None. |
| `get_by_ids_async` | `(db: AsyncSession, organization_id: UUID \| None, user_ids: list[UUID]) -> list[UserProfileDTO]` | READ | Batch-load user profiles by id list (single IN-query). |
| `get_first_system_user_async` | `(db: AsyncSession) -> UserDTO \| None` | READ | Return the oldest user across ALL organizations (org-less global read). |
| `get_full_async` | `(db: AsyncSession, organization_id: UUID \| None, user_id: UUID) -> UserDTO \| None` | READ | — |
| `list_all_async` | `(db: AsyncSession) -> list[UserDTO]` | READ | List all users (superuser view) with organization eagerly loaded. |
| `list_org_members_async` | `(db: AsyncSession, organization_id: UUID, offset: int=0, limit: int \| None=None, search: str \| None=None) -> list[UserDTO]` | READ | ``offset``/``limit``/``search`` are passed through to |
| `promote_superuser_async` | `(db: AsyncSession, user_id: UUID) -> UserDTO \| None` | WRITE | Promote a user to superuser (startup repair only). |
| `unblock_async` | `(db: AsyncSession, organization_id: UUID \| None, user_id: UUID, *, actor_user_id: UUID \| None=None) -> UserDTO \| None` | WRITE | Unblock a user. Returns updated user, or None. |

---

### `core_api.file_storage` — `CoreFileStorageAPI`

| Method | Signature | R/W | Description |
|---|---|---|---|
| `delete_for_org_async` | `(organization_id: UUID, module_name: str, file_path: str) -> None` | WRITE | Delete a file previously saved via :meth:`save_for_org_async`. |
| `exists_for_org_async` | `(organization_id: UUID, module_name: str, file_path: str) -> bool` | READ | Check whether a file saved via :meth:`save_for_org_async` exists. |
| `get_for_org_async` | `(organization_id: UUID, module_name: str, file_path: str) -> bytes` | READ | Retrieve a file previously saved via :meth:`save_for_org_async`. |
| `get_url_for_org_async` | `(organization_id: UUID, module_name: str, file_path: str, expires_in: int \| None=None) -> str` | READ | Get a URL for a file saved via :meth:`save_for_org_async`. |
| `save_for_org_async` | `(organization_id: UUID, module_name: str, file_path: str, content: bytes, content_type: str='application/octet-stream') -> str` | WRITE | Save *content* under an enforced ``<org>/<module>/`` prefix. |

---

### `core_api.secrets` — `CoreSecretsAPI`

| Method | Signature | R/W | Description |
|---|---|---|---|
| `decrypt_for_module` | `(module_name: <class 'str'>, value: <class 'str'>) -> <class 'str'>` | READ | Decrypt *value* written by :meth:`encrypt_for_module`. |
| `encrypt_for_module` | `(module_name: <class 'str'>, value: <class 'str'>) -> <class 'str'>` | WRITE | Encrypt *value* cryptographically bound to *module_name*. |

---

### `core_api.uoms` — `CoreUomsAPI`

| Method | Signature | R/W | Description |
|---|---|---|---|
| `convert_quantity` | `(qty: Decimal, source: UomDTO \| None, target: UomDTO \| None) -> tuple[Decimal, bool]` | READ | Convert *qty* from *source* to *target* UoM (factor-ratio, same category). |
| `existing_ids_async` | `(db: AsyncSession, uom_ids: set[UUID], organization_id: UUID) -> set[UUID]` | READ | Return the subset of *uom_ids* that exist for *organization_id* — one query. |
| `get_async` | `(db: AsyncSession, uom_id: UUID, organization_id: UUID) -> UomDTO \| None` | READ | Return the UOM row for *uom_id*, or ``None``. |
| `get_by_symbol_async` | `(db: AsyncSession, symbol: str, organization_id: UUID, *, include_global: bool=False) -> UomDTO \| None` | READ | Async: return the UOM DTO whose ``symbol`` matches *symbol* exactly, or ``None``. |
| `list_categories_for_org_async` | `(db: AsyncSession, organization_id: UUID) -> list[UomCategoryDTO]` | READ | Return all UOM categories visible to *organization_id* (system + org-specific). |
| `list_for_org_async` | `(db: AsyncSession, organization_id: UUID) -> list[UomDTO]` | READ | Return all UOM rows visible to *organization_id* (system + org-specific). |
| `quantity_step` | `(uom: UomDTO \| None) -> Decimal` | READ | The step quantities in *uom* are counted in — its own ``rounding``, |
| `quantize` | `(qty: Decimal, uom: UomDTO \| None) -> Decimal` | READ | *qty* on the nearest step of *uom* — the rounding a measurement takes. |
| `round_up` | `(qty: Decimal, uom: UomDTO \| None) -> Decimal` | READ | *qty* on the next step of *uom* at or above it — the rounding a |
| `to_canonical_measure_async` | `(db: AsyncSession, qty: Decimal, uom: UomDTO \| None) -> tuple[Decimal, str] \| None` | READ | Express *qty* in the reference unit of *uom*'s category. |
| `to_stock_uom_async` | `(db: AsyncSession, organization_id: UUID, product_template_id: UUID \| None, quantity: Decimal, uom_id: UUID \| None) -> Decimal` | READ | Express *quantity*, stated in *uom_id*, in the product's stock unit. |
| `validate_quantity_precision_async` | `(db: AsyncSession, uom_id: UUID, quantity: Decimal, organization_id: UUID) -> None` | READ | Async: raise ValueError if quantity violates the precision rules of the given UoM. |

---

### `core_api.product_templates` — `CoreProductTemplatesAPI`

| Method | Signature | R/W | Description |
|---|---|---|---|
| `count_for_org_async` | `(db: AsyncSession, org_id: UUID) -> int` | READ | Count templates the org can pick from (org-scoped + global). |
| `create_async` | `(db: AsyncSession, org_id: UUID, name: str, brand: str \| None=None, barcode: str \| None=None, sku: str \| None=None, description: str \| None=None, image_url: str \| None=None, meta_data: dict[str, Any] \| None=None, user_id: UUID \| None=None) -> ProductTemplateDTO` | WRITE | — |
| `create_stub_async` | `(db: AsyncSession, org_id: UUID, name: str, barcode: str \| None=None, user_id: UUID \| None=None) -> ProductTemplateDTO` | WRITE | — |
| `delete_async` | `(db: AsyncSession, template_id: UUID, org_id: UUID, user_id: UUID \| None=None) -> None` | WRITE | — |
| `exists_for_org_async` | `(db: AsyncSession, org_id: UUID, template_id: UUID) -> bool` | READ | — |
| `get_async` | `(db: AsyncSession, org_id: UUID, template_id: UUID) -> ProductTemplateDTO \| None` | READ | — |
| `get_many_async` | `(db: AsyncSession, org_id: UUID, template_ids: list[UUID]) -> dict[UUID, ProductTemplateDTO]` | READ | Batch twin of ``get_async``: id -> template, missing ids absent. |
| `get_with_uom_async` | `(db: AsyncSession, org_id: UUID, template_id: UUID) -> ProductTemplateDTO \| None` | READ | Return a template with ``weight_uom`` eagerly loaded. |
| `list_for_org_async` | `(db: AsyncSession, org_id: UUID, limit: int=200) -> list[ProductTemplateDTO]` | READ | — |
| `list_for_org_with_recipe_usage_async` | `(db: AsyncSession, org_id: UUID, limit: int=200) -> list[ProductTemplateDTO]` | READ | List templates with recipe-ingredient usage count, ordered by usage. |
| `lookup_by_barcode_async` | `(db: AsyncSession, org_id: UUID, barcode: str) -> ProductTemplateDTO \| None` | READ | — |
| `lookup_by_identity_async` | `(db: AsyncSession, org_id: UUID, *, name: str, brand: str \| None=None, barcode: str \| None=None) -> ProductTemplateDTO \| None` | READ | The card a record of this name, brand and code belongs to, if one does. |
| `lookup_by_sku_async` | `(db: AsyncSession, org_id: UUID, sku: str) -> ProductTemplateDTO \| None` | READ | Async: find a template by SKU, scoped to org + global templates. |
| `names_and_units_async` | `(db: AsyncSession, org_id: UUID, template_ids: Iterable[UUID]) -> dict[UUID, tuple[str, str \| None]]` | READ | id -> (name, unit symbol) for many templates, missing ids absent. |
| `resolve_default_async` | `(db: AsyncSession, org_id: UUID, *, name: str, brand: str \| None=None, barcode: str \| None=None, uom_id: UUID \| None=None) -> ProductTemplateDTO` | READ | The card this product belongs to, minting one when none matches. |
| `search_fuzzy_async` | `(db: AsyncSession, org_id: UUID, query: str, limit: int=10) -> list[ProductTemplateDTO]` | READ | ILIKE search across org + global templates, name-only. |
| `search_fuzzy_many_async` | `(db: AsyncSession, org_id: UUID, queries: list[str]) -> dict[str, list[ProductTemplateCandidateDTO]]` | READ | Batch name-fragment search: fragment -> the templates containing it. |
| `search_ranked_async` | `(db: AsyncSession, org_id: UUID, query: str, limit: int=10) -> list[ProductTemplateDTO]` | READ | Search templates with priority ranking: exact barcode > exact SKU > ILIKE name. |
| `update_async` | `(db: AsyncSession, template_id: UUID, org_id: UUID, name: str \| None=None, brand: str \| None=None, barcode: str \| None=None, description: str \| None=None, image_url: str \| None=None, meta_data: dict[str, Any] \| None=None, user_id: UUID \| None=None) -> ProductTemplateDTO` | WRITE | — |

---

### `core_api.queries` — `CoreQueriesAPI`

| Method | Signature | R/W | Description |
|---|---|---|---|
| `count_low_stock_products_async` | `(db: AsyncSession, organization_id: UUID, exclude_module_contexts: bool=False) -> int` | READ | How many products :meth:`get_low_stock_products_async` pages through. |
| `get_consumption_stats_async` | `(db: AsyncSession, organization_id: UUID, *, days: int=30) -> ConsumptionStatsDTO` | READ | Usage and disposal aggregates over a time window. |
| `get_cost_summary_async` | `(db: AsyncSession, organization_id: UUID, *, period: str='month') -> CostSummaryDTO` | READ | Cost analysis: spent, wasted, trends, savings opportunities. |
| `get_expense_forecast_async` | `(db: AsyncSession, organization_id: UUID, *, period: str='month') -> ExpenseForecastDTO` | READ | Predicted future spending derived from historical purchase trends. |
| `get_expiry_forecast_async` | `(db: AsyncSession, organization_id: UUID) -> list[ExpiryBucketDTO]` | READ | Six time-bucketed expiry counts for an organization. |
| `get_low_stock_products_async` | `(db: AsyncSession, organization_id: UUID, limit: int=100, exclude_module_contexts: bool=False, offset: int=0) -> list[LowStockProductDTO]` | READ | The products the overview's ``low_stock`` number counts, emptiest first. |
| `get_overview_async` | `(db: AsyncSession, organization_id: UUID) -> OverviewDTO` | READ | High-level inventory health snapshot for an organization. |
| `get_partner_display_names_async` | `(db: AsyncSession, organization_id: UUID, partner_ids: Iterable[UUID]) -> dict[UUID, str]` | READ | The display name of each partner these ids name, asked in one read. |
| `get_recent_activity_async` | `(db: AsyncSession, organization_id: UUID, *, limit: int=10) -> list[ActivityDTO]` | READ | Recent ItemHistory entries with item and user names. |
| `get_reconciliation_async` | `(db: AsyncSession, organization_id: UUID) -> ReconciliationDTO` | READ | The shelf against the movement ledger and against the cost layers. |
| `get_reconciliation_previous_async` | `(db: AsyncSession, organization_id: UUID) -> PreviousMeasurementDTO \| None` | READ | What the previous scheduled reconciliation pass measured. |
| `get_reservations_held_by_documents_async` | `(db: AsyncSession, organization_id: UUID, document_ids: Iterable[UUID]) -> list[DocumentReservationHoldDTO]` | READ | Reservations held by each of these documents, per product and shelf. |
| `get_rotation_analysis_async` | `(db: AsyncSession, organization_id: UUID) -> RotationAnalysisDTO` | READ | Inventory rotation metrics: age, slow movers, dead stock. |
| `get_stats_by_category_async` | `(db: AsyncSession, organization_id: UUID) -> list[CategoryStatsDTO]` | READ | Item counts and stock value aggregated per category. |
| `get_stats_by_storage_async` | `(db: AsyncSession, organization_id: UUID) -> list[StorageStatsDTO]` | READ | Item counts and expiry aggregates per storage location. |
| `get_storage_display_names_async` | `(db: AsyncSession, organization_id: UUID, storage_ids: Iterable[UUID]) -> dict[UUID, str]` | READ | The name of each shelf these ids name, asked in one read. |

---

### `core_api.partners` — `CorePartnersAPI`

| Method | Signature | R/W | Description |
|---|---|---|---|
| `activate_async` | `(db: AsyncSession, organization_id: uuid.UUID, partner_id: uuid.UUID, *, user_id: uuid.UUID \| None=None) -> PartnerDTO \| None` | WRITE | Reactivate a previously deactivated partner. Returns None if not found. |
| `create_async` | `(db: AsyncSession, organization_id: uuid.UUID, data: PartnerCreateDTO, user: UserContextDTO) -> PartnerDTO` | WRITE | Create a partner through the standard service pipeline. |
| `deactivate_async` | `(db: AsyncSession, organization_id: uuid.UUID, partner_id: uuid.UUID, *, user_id: uuid.UUID \| None=None) -> PartnerDTO \| None` | WRITE | Soft-deactivate a partner (sets is_active=False). Returns None if not found. |
| `get_async` | `(db: AsyncSession, org_id: uuid.UUID, partner_id: uuid.UUID) -> PartnerDTO \| None` | READ | — |
| `ids_named_like_async` | `(db: AsyncSession, org_id: uuid.UUID, term: str) -> list[uuid.UUID]` | READ | Ids of the partners whose name contains *term*, for one query. |
| `list_async` | `(db: AsyncSession, org_id: uuid.UUID, partner_type: str \| None=None, is_active: bool=True, limit: int=1000) -> list[PartnerDTO]` | READ | Async: list partners for *org_id* with optional filters. |
| `list_by_email_async` | `(db: AsyncSession, org_id: uuid.UUID, email: str) -> list[PartnerDTO]` | READ | — |
| `update_async` | `(db: AsyncSession, organization_id: uuid.UUID, partner_id: uuid.UUID, data: PartnerUpdateDTO, *, user_id: uuid.UUID \| None=None) -> PartnerDTO \| None` | WRITE | Partial update (PATCH-style). Returns None if partner not found. |

---

### `core_api.pdf` — `CorePdfAPI`

| Method | Signature | R/W | Description |
|---|---|---|---|
| `common_labels` | `(lang: str) -> dict[str, str]` | READ | Shared PDF labels (i18n-lite): 5 languages, English fallback. |
| `format_partner_address` | `(address: dict[str, Any] \| None, lang: str='en') -> str \| None` | READ | Format a partner address dict as a single-line string. |
| `generate_code128_base64` | `(value: str) -> str` | WRITE | Code128 barcode as a data-URI image at the standard print geometry. |
| `generate_qr_base64` | `(value: str) -> str` | WRITE | QR code as a data-URI PNG at the standard print geometry. |
| `get_doc_status_map` | `(lang: str) -> dict[str, str]` | READ | Document status code -> localized label map. |
| `printed_codes` | `(number: str) -> dict[str, Any]` | READ | The code images a printout carries, and the size to print them at. |
| `register_pdf_filters` | `(env: Any) -> None` | READ | Register standard Jinja2 filters (format_date, format_qty, etc.). |
| `render_html` | `(template_html: str \| None, context: dict[str, Any], *, templates_dir: Path \| None=None) -> str` | READ | Render a template string with the sandboxed Jinja2 engine. |
| `render_pdf` | `(html: str) -> bytes` | READ | Convert rendered HTML to PDF bytes (WeasyPrint). |
| `sanitize_html` | `(body_html: str) -> str` | READ | Strip dangerous tags/attributes from user-authored HTML (nh3). |

---

### `core_api.periods` — `CorePeriodsAPI`

| Method | Signature | R/W | Description |
|---|---|---|---|
| `check_not_closed_async` | `(db: AsyncSession, organization_id: UUID, doc_date: date) -> None` | READ | Raise ``PeriodClosedError`` if the given date falls in a closed period. |

---

### `core_api.stock` — `CoreStockAPI`

| Method | Signature | R/W | Description |
|---|---|---|---|
| `ask_what_each_grain_has_free_once_async` | `(db: AsyncSession, organization_id: UUID) -> AsyncIterator[None]` | WRITE | A block in which ``post_movement_async`` writes and asks its shortage question once, at the end. |
| `find_best_pick_group_for_picking_async` | `(db: AsyncSession, organization_id: UUID, product_template_id: UUID, storage_location_id: UUID \| None=None, owner_id: UUID \| None=None, *, except_document_id: UUID \| None=None) -> PickGroupDTO \| None` | READ | The group and lot to plan a picking line from, in the product's removal order. |
| `get_lot_detail_async` | `(db: AsyncSession, organization_id: UUID, lot_id: UUID) -> StockLotDetailDTO \| None` | READ | — |
| `get_or_create_lot_async` | `(db: AsyncSession, organization_id: UUID, product_template_id: UUID, name: str, is_serial: bool=False, expiry_date: date \| None=None, production_date: date \| None=None, use_by_date: date \| None=None) -> UUID` | WRITE | — |
| `held_quantity_async` | `(db: AsyncSession, organization_id: UUID, product_template_id: UUID, location_id: UUID \| None, *, document_ids: Sequence[UUID] \| None=None) -> Decimal` | READ | How much of this product on this shelf the named documents hold. |
| `list_lot_rows_async` | `(db: AsyncSession, organization_id: UUID, *, product_template_id: UUID \| None=None, status: str \| None=None, limit: int=200, offset: int=0) -> tuple[list[StockLotDetailDTO], int]` | READ | — |
| `list_lots_async` | `(db: AsyncSession, organization_id: UUID, product_template_id: UUID \| None=None) -> list[StockLotDTO]` | READ | — |
| `list_quant_rows_async` | `(db: AsyncSession, organization_id: UUID, *, product_template_id: UUID \| None=None, location_id: UUID \| None=None, lot_id: UUID \| None=None, include_empty: bool=False, search: str \| None=None, limit: int=200, offset: int=0, count_cap: int \| None=None) -> tuple[list[StockQuantRowDTO], int]` | READ | A page of the stock list, and its count (stopped at ``count_cap``). |
| `list_quants_async` | `(db: AsyncSession, organization_id: UUID, product_template_id: UUID \| None=None, storage_location_id: UUID \| None=None, product_template_ids: list[UUID] \| None=None, storage_location_ids: list[UUID] \| None=None) -> list[StockQuantDTO]` | READ | — |
| `lock_async` | `(db: AsyncSession, organization_id: UUID, *, keys: Iterable[tuple[UUID, UUID \| None]]=(), reserved_for_document_id: UUID \| None=None) -> None` | WRITE | Lock every group of stock an operation will write, before the first write. |
| `plan_draw_async` | `(db: AsyncSession, organization_id: UUID, product_template_id: UUID, storage_location_id: UUID \| None, quantity: Decimal \| None, *, removal_strategy: str \| None=None, owner_id: UUID \| None=None, any_owner: bool=False, lot_id: UUID \| None=None, require_active_lot: bool=True, by_record: bool=False, except_document_id: UUID \| None=None, among_shelves: Sequence[UUID] \| None=None) -> list[QuantConsumptionDTO]` | READ | Plan the draw ``take_from_the_records_async`` would make, read-only. |
| `post_movement_async` | `(db: AsyncSession, organization_id: UUID, product_template_id: UUID, quantity: Decimal, *, from_location_id: UUID \| None=None, to_location_id: UUID \| None=None, lot_id: UUID \| None=None, owner_id: UUID \| None=None, require_active_lot: bool=True, reference_type: str, reference_id: UUID, created_by: UUID \| None=None, records: Sequence[RecordPostDTO]=()) -> list[QuantConsumptionDTO]` | WRITE | State the records a movement is and write the movement, together. |
| `posting_scope_async` | `(db: AsyncSession) -> AsyncIterator[None]` | WRITE | The scope an operation that posts many lines runs in. |
| `quantities_by_shelf_async` | `(db: AsyncSession, organization_id: UUID, storage_location_ids: list[UUID] \| None=None) -> dict[UUID, dict[UUID, Decimal]]` | READ | Shelf -> product -> quantity, batches and owners summed together. |
| `quarantine_lot_async` | `(db: AsyncSession, organization_id: UUID, lot_id: UUID, reason: str \| None=None, *, user_id: UUID \| None=None) -> StockLotDTO \| None` | READ | Set a lot's status to QUARANTINED — blocks consumption/reservation. |
| `release_for_document_async` | `(db: AsyncSession, organization_id: UUID, document_id: UUID) -> None` | WRITE | Release all reservations for a specific document. |
| `release_lot_async` | `(db: AsyncSession, organization_id: UUID, lot_id: UUID, *, user_id: UUID \| None=None) -> StockLotDTO \| None` | WRITE | Release a quarantined/held lot back to ACTIVE status. |
| `release_unbacked_async` | `(db: AsyncSession, organization_id: UUID, product_template_id: UUID, location_id: UUID \| None, leaving_quantity: Decimal, *, document_ids: Sequence[UUID] \| None=None) -> Decimal` | WRITE | Release only the hold the remaining stock can no longer cover. |
| `reserve_for_document_async` | `(db: AsyncSession, organization_id: UUID, product_template_id: UUID, location_id: UUID \| None, needed_qty: Decimal, removal_strategy: str='FIFO', *, document_id: UUID, document_line_id: UUID \| None=None, lot_id: UUID \| None=None, require_active_lot: bool=True) -> ReservationResultDTO` | WRITE | Atomically reserve stock for one document, under the groups' anchors. |
| `resolve_removal_strategy` | `(template: object \| None, override: str \| None=None) -> str` | READ | Pick FIFO/FEFO for a (template, override) pair. |
| `set_lot_status_async` | `(db: AsyncSession, organization_id: UUID, lot_id: UUID, status: str, reason: str \| None=None, user_id: UUID \| None=None) -> StockLotDTO \| None` | WRITE | — |
| `shelf_contents_async` | `(db: AsyncSession, organization_id: UUID, product_template_ids: Collection[UUID]=()) -> list[ShelfContentsDTO]` | READ | What stands on every shelf, told in one row per shelf. |
| `take_from_the_records_async` | `(db: AsyncSession, organization_id: UUID, product_template_id: UUID, storage_location_id: UUID \| None, quantity: Decimal, lot_id: UUID \| None=None, owner_id: UUID \| None=None, *, require_active_lot: bool=True, any_owner: bool=False, removal_strategy: str \| None=None, user_id: UUID \| None=None, source_document_id: UUID \| None=None, history_changes: dict[str, Any] \| None=None, reference_type: str \| None=None, reference_id: UUID \| None=None) -> list[QuantConsumptionDTO]` | WRITE | Take ``quantity`` off the records the draw plan names, one write each. |

---

### `core_api.stock_moves` — `CoreStockMovesAPI`

| Method | Signature | R/W | Description |
|---|---|---|---|
| `aggregate_aging_buckets_async` | `(db: AsyncSession, organization_id: UUID, product_template_id: UUID, *, as_of: datetime \| None=None) -> list[StockAgeBucketDTO]` | READ | — |
| `any_departure_async` | `(db: AsyncSession, organization_id: UUID, *, product_template_id: UUID, from_location_id: UUID, lot_id: UUID \| None, owner_id: UUID \| None, since: datetime, excluded_reference_ids: Sequence[UUID]=()) -> bool` | READ | Whether stock left one group after *since*, other than these moves. |
| `any_departure_from_groups_async` | `(db: AsyncSession, organization_id: UUID, groups: Sequence[StockMovePostedGroupDTO], *, excluded_reference_ids: Sequence[UUID]=()) -> bool` | READ | ``any_departure_async`` for many posted groups, asked in one statement. |
| `count_by_reference_async` | `(db: AsyncSession, organization_id: UUID, reference_type: str, reference_id: UUID) -> int` | READ | — |
| `create_async` | `(db: AsyncSession, *, organization_id: UUID, product_template_id: UUID, quantity: Decimal, from_location_id: UUID \| None=None, to_location_id: UUID \| None=None, lot_id: UUID \| None=None, owner_id: UUID \| None=None, state: str='done', reference_type: str \| None=None, reference_id: UUID \| None=None, created_by: UUID \| None=None, completed_at: datetime \| None=None) -> StockMoveDTO` | WRITE | Create one movement; ``owner_id`` says whose goods moved. |
| `get_async` | `(db: AsyncSession, organization_id: UUID, move_id: UUID) -> StockMoveDTO \| None` | READ | — |
| `list_by_reference_async` | `(db: AsyncSession, organization_id: UUID, reference_type: str, reference_id: UUID, *, limit: int=200, offset: int=0) -> list[StockMoveDTO]` | READ | — |
| `list_by_template_async` | `(db: AsyncSession, organization_id: UUID, product_template_id: UUID, *, limit: int=200, state: str \| None=None, since: datetime \| None=None) -> list[StockMoveDTO]` | READ | — |
| `list_for_org_async` | `(db: AsyncSession, organization_id: UUID, *, product_template_id: UUID \| None=None, location_id: UUID \| None=None, lot_id: UUID \| None=None, reference_type: str \| None=None, reference_id: UUID \| None=None, user_id: UUID \| None=None, direction: str \| None=None, state: str \| None=None, since: datetime \| None=None, until: datetime \| None=None, limit: int=200, offset: int=0, after: tuple[datetime, UUID] \| None=None, known_total: int \| None=None) -> tuple[list[StockMoveDTO], int]` | READ | One page of the movement ledger with the full count beside it. |
| `list_receipts_for_aging_async` | `(db: AsyncSession, organization_id: UUID, product_template_id: UUID, *, as_of: datetime \| None=None, limit: int=1000) -> list[StockAgeEntryDTO]` | READ | — |
| `list_recent_async` | `(db: AsyncSession, organization_id: UUID, *, limit: int=200) -> list[StockMoveDTO]` | READ | — |
| `list_rows_for_org_async` | `(db: AsyncSession, organization_id: UUID, *, product_template_id: UUID \| None=None, location_id: UUID \| None=None, lot_id: UUID \| None=None, reference_type: str \| None=None, reference_id: UUID \| None=None, user_id: UUID \| None=None, direction: str \| None=None, state: str \| None=None, since: datetime \| None=None, until: datetime \| None=None, exclude_module_contexts: bool=False, limit: int=200, offset: int=0, after: tuple[datetime, UUID] \| None=None, known_total: int \| None=None, count_up_to: int \| None=None) -> tuple[list[StockMoveRowDTO], int]` | READ | The same page as :meth:`list_for_org_async`, read as sentences. |
| `posted_groups_async` | `(db: AsyncSession, organization_id: UUID, reference_type: str, reference_id: UUID) -> list[StockMovePostedGroupDTO]` | WRITE | Every group of stock one source filled, and when it last filled it. |

---

### `core_api.templates` — `CoreTemplatesAPI`

| Method | Signature | R/W | Description |
|---|---|---|---|
| `copy_builtin_alongside_async` | `(db: AsyncSession, organization_id: UUID, module: str, user_id: UUID, template_id: UUID, built_ins: list[tuple[str, str, str]]) -> DocumentTemplateSchema` | READ | Copy the current built-in next to the organization's own copy. |
| `create_async` | `(db: AsyncSession, organization_id: UUID, module: str, user_id: UUID, name: str, body_html: str, document_type: str='DEFAULT', is_default: bool=False, partials: dict[str, str] \| None=None) -> DocumentTemplateSchema` | WRITE | — |
| `delete_async` | `(db: AsyncSession, organization_id: UUID, template_id: UUID, module: str, user_id: UUID \| None=None) -> None` | WRITE | Raises ``NotFoundException`` when the template does not exist. |
| `get_async` | `(db: AsyncSession, organization_id: UUID, template_id: UUID, module: str) -> DocumentTemplateSchema \| None` | READ | — |
| `get_default_async` | `(db: AsyncSession, organization_id: UUID, module: str, document_type: str) -> DocumentTemplateSchema \| None` | READ | Get the default template for ``(module, document_type)``. |
| `list_async` | `(db: AsyncSession, organization_id: UUID, module: str, built_ins: list[tuple[str, str, str]] \| None=None) -> list[DocumentTemplateSchema]` | READ | The organization's own templates. |
| `seed_defaults_async` | `(db: AsyncSession, organization_id: UUID, module: str, user_id: UUID, built_ins: list[tuple[str, str, str]], partials: dict[str, str] \| None=None) -> list[DocumentTemplateSchema]` | READ | Seed built-in templates; existing names are skipped (idempotent). |
| `update_async` | `(db: AsyncSession, organization_id: UUID, template_id: UUID, module: str, *, name: str \| None=None, body_html: str \| None=None, document_type: str \| None=None, is_default: bool \| None=None, partials: dict[str, str] \| None=None, user_id: UUID \| None=None) -> DocumentTemplateSchema` | WRITE | Raises ``NotFoundException`` when the template does not exist. |

---

### `core_api.valuation` — `CoreValuationAPI`

| Method | Signature | R/W | Description |
|---|---|---|---|
| `estimate_unit_cost_async` | `(db: AsyncSession, organization_id: UUID, product_template_ids: list[UUID]) -> dict[UUID, UnitCostEstimate]` | READ | Estimate stock-unit costs: priced layers, supplier offers, unknown. |
| `get_current_rate_async` | `(db: AsyncSession, organization_id: UUID, product_template_id: UUID) -> Decimal \| None` | READ | Return the template's layer-average valuation rate, or None. |
| `get_rates_batch_async` | `(db: AsyncSession, organization_id: UUID, product_template_ids: list[UUID]) -> dict[UUID, Decimal \| None]` | READ | Return ``{template_id: layer-average valuation rate}`` for *product_template_ids*. |
| `lock_open_layers_async` | `(db: AsyncSession, organization_id: UUID, product_template_ids: Iterable[UUID]) -> None` | READ | Lock and read the cost layers of these products in one statement. |
| `record_delivery_async` | `(db: AsyncSession, organization_id: UUID, product_template_id: UUID, quantity: Decimal, document_line_id: UUID \| None=None, reason: str \| None=None, item_id: UUID \| None=None, reverses_line_id: UUID \| None=None) -> Decimal \| None` | WRITE | Take stock off the receipt layers and post what it was worth. |
| `record_receipt_async` | `(db: AsyncSession, organization_id: UUID, product_template_id: UUID, quantity: Decimal, unit_cost: Decimal \| None, document_line_id: UUID \| None=None, currency: str \| None=None, document_date: date \| None=None, reverses_line_id: UUID \| None=None) -> None` | WRITE | Record a receipt into the cost history. |
| `record_unpriced_receipt_async` | `(db: AsyncSession, organization_id: UUID, product_template_id: UUID, quantity: Decimal) -> None` | WRITE | Record stock arriving with nobody having named a price. |

---

## Statistics

- **Total methods:** 310
- **Namespaces:** 33
- **Documented methods:** 310 (100%)
- **READ methods:** 214 (69%)
- **WRITE methods:** 96 (31%)


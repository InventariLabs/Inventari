"""Vulture whitelist — names that ARE used but invisible to static analysis.

Vulture scans this file (it is listed in ``[tool.vulture] paths``), and every
name loaded here counts as "used". Add an entry ONLY when a grep proves real
usage that vulture cannot see (framework indirection, excluded DTO/schema/
model files, dynamic dispatch, DB-stored string values). Group by cause,
one line per name. The file is parsed, never executed.

Bare expressions are intentional — ruff B018 is suppressed per line.
"""

from typing import Any

from app.api.onboarding import ProfileSwitchResponse
from app.api.organizations import InvitationSummary
from app.cli.commands_shell import shell_command
from app.config import settings
from app.core._event_bus import EventBus
from app.core._event_deprecations import get_deprecation
from app.core._event_types import SystemEvent
from app.core._interceptor_base import (
    CategoryInterceptor,
    ItemInterceptor,
    StorageInterceptor,
)
from app.core._interceptor_pipeline import InterceptorPipeline
from app.core._registry_class import ModuleRegistry
from app.core.api_key_auth import clear_api_key_resolver
from app.core.architecture_lint._quality_checks_tenancy import (
    _collect_public_api_missing_org_keys,
)
from app.core.barcode import validate_checksum
from app.core.context import ModuleContext
from app.core.contracts import CategoryDTO, StockLotDetailDTO
from app.core.contributions import QuotaProvider
from app.core.db_isolation import (
    controller_run_id,
    drop_run_databases,
    isolated_db_url,
    run_scoped_db_name,
)
from app.core.label_rendering import clear_label_renderers
from app.core.limiter_middleware import RouterAwareSlowAPIMiddleware
from app.core.migration_helpers import (
    convert_naive_timestamps_to_utc,
    create_index_if_absent,
    create_table_if_absent,
)
from app.core.module_manifest_schema import ManifestCapability, ModuleManifest
from app.core.period_guard import clear_period_guard
from app.core.product_profiles import ProductProfile
from app.core.public_api import core_api
from app.core.template_ranking import clear_template_ranker
from app.i18n.service import get_module_error_message
from app.models.email_job import EmailJob
from app.models.label_pool import LabelPool
from app.models.organization import OrganizationInvitation
from app.models.user import RegistrationRequest
from app.modules.approvals.models import ApprovalRequest
from app.modules.approvals.target_types import TargetType
from app.modules.equipment.models import AuditCampaign, AuditResponse
from app.modules.equipment.module import EquipmentModule
from app.modules.maker.maker_api import maker_api
from app.modules.purchase_orders.models import PurchaseOrder
from app.modules.purchase_orders.module import PurchaseOrdersModule
from app.modules.purchase_orders.purchase_orders_api import purchase_orders_api
from app.modules.recipes._allergens import ALLERGEN_SET
from app.modules.recipes.ingredient_parser_llm import IngredientParseOutcome
from app.modules.recipes.module import RecipesModule
from app.modules.shopping_lists.models import ShoppingList
from app.modules.stock_takes.models import CycleCountSchedule, StockTakeCount
from app.modules.stock_takes.schemas import StockTakeWithDetails
from app.modules.vision.service import VisionService
from app.modules.warehouse.document_pdf_service import IssuerContext
from app.modules.warehouse.models.document import Document, DocumentLine
from app.modules.warehouse.models.profile import DocumentProfile
from app.modules.warehouse.putaway_schemas import (
    PutawayCapacityOut,
    PutawayRuleOut,
)
from app.modules.warehouse.schemas import DocumentSchema
from app.modules.webhooks.module import WebhooksModule
from app.schemas.organization import Organization
from app.schemas.partner import PartnerListItem
from app.services._stock_reservation import list_reservations_async
from app.services.category_emoji import resolve_category_emoji
from app.services.gdpr_service import anonymize_user_async
from app.services.profile_switch_planner import ProfileSwitchPlan

# --- Used as types/keys in files excluded from the scan (*schemas*.py) ------
# TargetType: Pydantic field type in approvals/schemas.py; members are used
# as string literals ('document', 'purchase_order', 'equipment_checkout')
# across modules. EQUIPMENT_CHECKOUT belonged in this list from the start and
# was missing from it until 2026-09-21: vulture matches bare names, so the
# unrelated SystemEvent.EQUIPMENT_CHECKOUT entry further down was covering it
# by coincidence. That alias left with the vertical events; this did not.
TargetType  # noqa: B018
TargetType.DOCUMENT  # noqa: B018
TargetType.EQUIPMENT_CHECKOUT  # noqa: B018
TargetType.PURCHASE_ORDER  # noqa: B018
# Used by the allergen validator in recipes/_schemas_recipe.py (excluded).
ALLERGEN_SET  # noqa: B018

# --- Callers living in paths the scan excludes ------------------------------
# Module migrations (*/migrations/* is excluded) build their tables through
# these helpers — see api_keys, purchase_orders and webhooks 001_initial.
create_table_if_absent  # noqa: B018
create_index_if_absent  # noqa: B018
# The archived core tzaware01 and one revision in each module chain convert their naive
# timestamp columns through it.
convert_naive_timestamps_to_utc  # noqa: B018
# Baseline builder for the tenancy lint, called from
# tests/unit/test_architecture_lint_tenancy.py (*/tests/* is excluded).
_collect_public_api_missing_org_keys  # noqa: B018
# Scratch-database context manager for the migration tests; every caller is a
# fixture under */tests/*, which the scan excludes.
isolated_db_url  # noqa: B018
# The run-scoped database helpers are consumed by backend/conftest.py, which
# vulture does not scan: the controller mints the run id and names its
# databases with it (run_scoped_db_name), and the controller's sessionfinish
# drops the run's databases through drop_run_databases.
controller_run_id  # noqa: B018
run_scoped_db_name  # noqa: B018
drop_run_databases  # noqa: B018
# Registry resets, the only way to reach the unregistered branch of each
# inverted dependency. Used by tests/unit/test_core_registries.py and
# tests/unit/test_core_isolation_lint.py.
clear_label_renderers  # noqa: B018
clear_template_ranker  # noqa: B018
clear_api_key_resolver  # noqa: B018
# Same registry-reset role for the period guards; the caller is the
# autouse fixture in tests/unit/test_core_isolation_lint.py.
clear_period_guard  # noqa: B018
# Undoing a registration is public by design (see the method's docstring:
# tests used to reach into _item_interceptors to take a blocker back out).
# Both callers are teardowns — equipment/tests/integration/test_bulk_purge.py
# and tests/integration/test_purge_blockers.py, under the excluded */tests/*.
# NB: the import above must come from the defining module (_interceptor_pipeline),
# not the app.core.interceptors re-export — vulture only credits an
# Attribute.attribute usage when the name resolves to its definition, and a
# re-export chain leaves the reference unresolvable (gate went red exactly this
# way in 2026-08).
InterceptorPipeline.unregister_item_interceptor  # noqa: B018

# --- Test-only usages: every caller lives under */tests/*, which the scan ----
# excludes. Each name verified by grep 2026-08-19 ( triage) — no
# production caller exists, but the tests pin real subsystem behavior:
# event-bus introspection, registry reset/surface, barcode checksums,
# cache invalidation, permission checks, the field preset registry, the
# reservations listing, the vision service entry and DTO fields.
EventBus.is_connected  # noqa: B018
EventBus.is_listening  # noqa: B018
get_deprecation  # noqa: B018
ModuleRegistry.get_rejected_modules  # noqa: B018
validate_checksum  # noqa: B018
resolve_category_emoji  # noqa: B018
list_reservations_async  # noqa: B018
VisionService.extract_from_base64_list  # noqa: B018
IngredientParseOutcome.fallback_reason  # noqa: B018
# Declared on the manifest, pinned by test_manifest_settings_schema.py
# against the live get_settings_schema implementation.
ModuleManifest.has_settings_schema  # noqa: B018

# --- Framework hooks ---------------------------------------------------------
# Starlette calls dispatch() on every request; the override exists precisely
# because the parent's handler lookup cannot be replaced any other way.
RouterAwareSlowAPIMiddleware.dispatch  # noqa: B018
# openpyxl reads both attributes back when it writes the sheet: data_type
# selects the inlineStr encoding and quotePrefix records the literal-text
# style. Set in export_hygiene.defuse_worksheet, round-trip pinned by
# tests/unit/test_export_hygiene.py — a path the scan excludes. Typed Any
# because quotePrefix is an instance attribute openpyxl adds, not a
# descriptor on Cell.
_openpyxl_cell: Any = None
_openpyxl_cell.data_type  # noqa: B018
_openpyxl_cell.quotePrefix  # noqa: B018

# --- Interceptor hooks: dispatched dynamically by _interceptor_pipeline.py --
# via getattr(interceptor, method_name); base defaults exist to be overridden.
ItemInterceptor.before_create  # noqa: B018
ItemInterceptor.before_update  # noqa: B018
ItemInterceptor.before_delete  # noqa: B018
ItemInterceptor.after_create  # noqa: B018
ItemInterceptor.after_update  # noqa: B018
ItemInterceptor.after_delete  # noqa: B018
ItemInterceptor.before_consume  # noqa: B018
ItemInterceptor.after_consume  # noqa: B018
ItemInterceptor.before_discard  # noqa: B018
ItemInterceptor.after_discard  # noqa: B018
ItemInterceptor.before_purge  # noqa: B018
StorageInterceptor.before_create  # noqa: B018
StorageInterceptor.before_update  # noqa: B018
StorageInterceptor.before_delete  # noqa: B018
StorageInterceptor.after_create  # noqa: B018
StorageInterceptor.after_update  # noqa: B018
StorageInterceptor.after_delete  # noqa: B018
CategoryInterceptor.before_create  # noqa: B018
CategoryInterceptor.before_update  # noqa: B018
CategoryInterceptor.before_delete  # noqa: B018
CategoryInterceptor.after_create  # noqa: B018
CategoryInterceptor.after_update  # noqa: B018
CategoryInterceptor.after_delete  # noqa: B018

# --- SystemEvent catalog: consumers reference events by string value --------
# (webhook subscriptions store event_types as list[str] in the DB, frontend
# listens by name). Unused-in-code members are reserved, documented names.
SystemEvent.ITEM_TRANSFERRED  # noqa: B018
SystemEvent.ITEM_DEACTIVATED  # noqa: B018
SystemEvent.ITEM_STATUS_CHANGED  # noqa: B018
SystemEvent.ORGANIZATION_CREATED  # noqa: B018
SystemEvent.ORGANIZATION_UPDATED  # noqa: B018
SystemEvent.USER_REGISTERED  # noqa: B018
SystemEvent.LABEL_SCANNED  # noqa: B018
SystemEvent.LABEL_ASSIGNED  # noqa: B018

# --- CoreAPI documented contract (docs/subsystems/CORE_API.md, drift-pinned -
# by test_core_api_docs_drift.py; reserved for cloud-module consumption).
# The reservation is real: the cloud/SaaS module is developed outside this
# repository and imports these methods through ``core_api`` (see
# app/core/public_api/admin.py), so a grep of this tree finding no caller does
# not make a method here dead — for the methods the cloud module calls
# (verified against it); the ones it does not call sit in the reserved section. Removing one takes the owner's word that the
# cloud module no longer uses it, not a repo-wide search.
core_api.admin.get_global_stats_async  # noqa: B018
core_api.ai_usage.get_global_stats_async  # noqa: B018
core_api.ai_usage.get_org_stats_async  # noqa: B018
core_api.settings.list_system_settings_async  # noqa: B018
core_api.settings.set_system_setting_async  # noqa: B018
# Org-scoped file-storage and secrets helpers for module consumers; the
# contract is documented, the callers may live in community modules
# ( triage 2026-08-19).
core_api.file_storage.save_for_org_async  # noqa: B018
core_api.file_storage.get_for_org_async  # noqa: B018
core_api.file_storage.get_url_for_org_async  # noqa: B018
core_api.file_storage.delete_for_org_async  # noqa: B018
core_api.file_storage.exists_for_org_async  # noqa: B018
core_api.secrets.encrypt_for_module  # noqa: B018
core_api.secrets.decrypt_for_module  # noqa: B018

# --- Callers the scan reaches, kept for a documented reason ------------------
# Permission catalog handed to admins by GET /auth/me, which lives in a file
# the scan reaches — kept because the registry is also the documented lookup
# for module-declared keys (backend/AGENTS.md §4 "Module Extensibility Patterns").
ModuleRegistry.get_all_permissions  # noqa: B018
# Registered as a click command in manage.py: app.command(name='shell').
shell_command  # noqa: B018

# --- begin reserved surface -------------------------------------------------
# Everything above says "the caller exists, the scanner cannot see it" — a
# claim a grep settles. Everything here says something else: "there is no
# caller, and there is not meant to be one yet". That cannot be grepped, so
# each line carries an owner and a date, checked by the architecture lint. A
# silenced name with no caller and no deadline is how a dead API goes on
# being reported as alive.
#
# Format: <name>, then the B018 suppression comment, then
# "# owner=<who> expires=<YYYY-MM-DD> <reason>" as the lines below show.
maker_api  # noqa: B018  # owner=core expires=2027-02-28 Module extension surface (AGENTS.md, Cross-Module API Contracts); no in-repo caller outside the maker module itself.
maker_api.list_bom_lines_async  # noqa: B018  # owner=core expires=2027-02-28 As maker_api above.
maker_api.explode_bom_async  # noqa: B018  # owner=core expires=2027-02-28 As maker_api above.
maker_api.compute_total_cost_async  # noqa: B018  # owner=core expires=2027-02-28 As maker_api above.
maker_api.compute_unit_cost_async  # noqa: B018  # owner=core expires=2027-02-28 As maker_api above.
maker_api.get_breakdown_async  # noqa: B018  # owner=core expires=2027-02-28 As maker_api above.
maker_api.complete_production_async  # noqa: B018  # owner=core expires=2027-02-28 As maker_api above.
purchase_orders_api.list_reorder_rules_async  # noqa: B018  # owner=core expires=2027-02-28 Module extension surface; no in-repo caller.
purchase_orders_api.create_reorder_rule_async  # noqa: B018  # owner=core expires=2027-02-28 Module extension surface; no in-repo caller.
purchase_orders_api.list_pricelist_for_partner_async  # noqa: B018  # owner=core expires=2027-02-28 Module extension surface; no in-repo caller.
purchase_orders_api.list_supplier_prices_for_template_async  # noqa: B018  # owner=core expires=2027-02-28 Module extension surface; no in-repo caller.
get_module_error_message  # noqa: B018  # owner=core expires=2027-02-28 Module-facing i18n API documented in MODULES_GUIDE.md; no in-repo caller.
anonymize_user_async  # noqa: B018  # owner=core expires=2027-02-28 Entry point of the manual GDPR erasure procedure (docs/GDPR_MANUAL_PROCEDURE.md); called by hand, never by code.
core_api.events.registered_events  # noqa: B018  # owner=core expires=2027-02-28 CoreAPI contract method; no in-repo caller and none in the cloud module either.
core_api.partners.deactivate_async  # noqa: B018  # owner=core expires=2027-02-28 CoreAPI contract method; no in-repo caller and none in the cloud module either.
core_api.partners.activate_async  # noqa: B018  # owner=core expires=2027-02-28 CoreAPI contract method; no in-repo caller and none in the cloud module either.
core_api.pdf.render_pdf  # noqa: B018  # owner=core expires=2027-02-28 CoreAPI contract method; no in-repo caller and none in the cloud module either.
core_api.queries.get_partner_display_names_async  # noqa: B018  # owner=core expires=2027-01-31 CoreAPI contract method; its consumers are the warehouse register/todo services, which join core tables today and move onto this read next — until then no in-repo caller.
core_api.queries.get_reservations_held_by_documents_async  # noqa: B018  # owner=core expires=2027-01-31 As get_partner_display_names_async above.
core_api.scheduler.unregister_task  # noqa: B018  # owner=core expires=2027-02-28 CoreAPI contract method; no in-repo caller and none in the cloud module either.
core_api.settings.get_schema_version_async  # noqa: B018  # owner=core expires=2027-04-30 Reads the settings shape stamp for a module's per-organization migration pass (MODULE_ADVANCED_GUIDE.md); the caller is module code outside this tree.
ModuleContext.migrate_settings  # noqa: B018  # owner=core expires=2027-04-30 The upgrade context's per-organization settings pass (MODULE_ADVANCED_GUIDE.md); called from a module's on_upgrade_async, so no in-repo caller until a module changes its settings shape.
# --- end reserved surface ---------------------------------------------------

# --- Module classes: auto-discovered by the registry scan --------------------
# (issubclass(attr, BaseModule) in app/core/_registry_class.py).
EquipmentModule  # noqa: B018
PurchaseOrdersModule  # noqa: B018
RecipesModule  # noqa: B018
WebhooksModule  # noqa: B018
# Contribution registry: providers dispatched dynamically by check_quota().
QuotaProvider  # noqa: B018
QuotaProvider.get_limit_value  # noqa: B018

# --- Settings/manifest/tracking vocabulary -----------------------------------
# Env-var schema fields read via os.getenv() in the logging bootstrap
# (app/core/logging.py) to avoid an import cycle; removal would also trip
# SettingsConfigDict extra='forbid' for .env files carrying these vars.
settings.LOG_LEVEL  # noqa: B018
settings.LOG_DIR  # noqa: B018
# Read by the inline Python in entrypoint.sh, which holds the migration
# advisory lock. The scan only reads .py files, so the shell script is
# invisible to it — the property must not be "cleaned up".
settings.migration_database_url  # noqa: B018
# ManifestCapability members are matched by VALUE when pydantic parses
# manifest.json, never referenced by member name. The enum itself is no longer
# listed here: `ModuleManifest.capabilities` is typed `list[ManifestCapability]`,
# so the type has a real consumer now.
ManifestCapability.NETWORK  # noqa: B018
ManifestCapability.FILESYSTEM  # noqa: B018
ManifestCapability.PROCESS  # noqa: B018
ManifestCapability.DATABASE  # noqa: B018
# previous_version / upgraded_at / installed_at are
# written by `module upgrade` (app/cli/_module_upgrade.py) and read back by
# `module list` and its --json export (app/cli/commands_module.py) — all
# through string keys, which is what vulture cannot follow. ModuleTrackingEntry
# is a TypedDict (total=False), so its keys are pinned in ignore_names, not
# here: a TypedDict key is not an attribute, and mypy rightly refuses to read
# it as one. `inventari_min_version` needs no pin of either kind: the manifest
# validator reads it as an attribute (app/core/module_validator.py).

# --- ProductProfile fields: serialized via GET /api/v1/profiles, consumed by -
# frontend (useProfileTheme, AppShell, useProfileCategories);
# theme_id pinned by the OpenAPI contract.
ProductProfile.theme_id  # noqa: B018
ProductProfile.launcher_categories  # noqa: B018
ProductProfile.theme  # noqa: B018
ProductProfile.branding  # noqa: B018

# --- Profile-switch DTO fields: populated by profile_switch_planner and -----
# serialized into API responses (names shared by ProfileSwitchPlan and
# ProfileSwitchDiffResponse; vulture tracks attribute names globally).
ProfileSwitchPlan.to_profile_id  # noqa: B018
ProfileSwitchPlan.disable  # noqa: B018
ProfileSwitchPlan.cascade_disable  # noqa: B018
ProfileSwitchPlan.module_config_overwrite  # noqa: B018
ProfileSwitchResponse.applied  # noqa: B018

# --- ORM attribute writes: columns read via the ORM / Pydantic ---------------
# from_attributes / Jinja templates, i.e. written in services but "read"
# only in files excluded from the scan (models, schemas, contracts).
ApprovalRequest.cancelled_at  # noqa: B018
AuditCampaign.launched_at  # noqa: B018
AuditResponse.email_sent_at  # noqa: B018
AuditResponse.responded_at  # noqa: B018
AuditResponse.response_ip  # noqa: B018
AuditResponse.response_user_agent  # noqa: B018
AuditResponse.dispute_reason  # noqa: B018
CycleCountSchedule.last_run_at  # noqa: B018
Document.confirmed_by  # noqa: B018
Document.confirmed_at  # noqa: B018
DocumentProfile.default_unit  # noqa: B018
DocumentProfile.visible_line_fields  # noqa: B018
EmailJob.sent_at  # noqa: B018
EmailJob.last_error  # noqa: B018
LabelPool.assigned_at  # noqa: B018
LabelPool.is_item_deleted  # noqa: B018
LabelPool.assigned_item_name  # noqa: B018
LabelPool.assigned_item_quantity  # noqa: B018
LabelPool.assigned_item_unit  # noqa: B018
LabelPool.assigned_item_context_tag  # noqa: B018
CategoryDTO.is_module_owned  # noqa: B018 — read by the frontend, not the backend
PurchaseOrder.confirmed_by  # noqa: B018
PurchaseOrder.confirmed_at  # noqa: B018
PurchaseOrder.cancelled_at  # noqa: B018
ShoppingList.archived_at  # noqa: B018
RegistrationRequest.approved_by_id  # noqa: B018
RegistrationRequest.rejected_at  # noqa: B018
# Transient enrichment attributes set on rows and consumed by DTOs/frontend.
DocumentSchema.generated_backorder_id  # noqa: B018
DocumentSchema.generated_backorder_number  # noqa: B018
DocumentSchema.return_of_id  # noqa: B018
DocumentSchema.corrects_document_type  # noqa: B018
# Response-DTO fields assigned in routers, read via serialization.
DocumentSchema.approval  # noqa: B018
InvitationSummary.used_at  # noqa: B018
InvitationSummary.used_by_user_id  # noqa: B018
# Written by partner_service and read by the client through the response
# model; vulture sees only the assignment.
PartnerListItem.turnover_currency  # noqa: B018
Organization.can_send_email  # noqa: B018
Organization.member_count  # noqa: B018
PutawayRuleOut.product_template_name  # noqa: B018
StockTakeWithDetails.location_type_name  # noqa: B018
# Written when an invitation is redeemed, read back through InvitationSummary —
# models are excluded from the scan, so the assignment looks like the only use.
OrganizationInvitation.used_at  # noqa: B018
OrganizationInvitation.used_by_user_id  # noqa: B018
# Read by the frontend partner list/sheet; Python only writes it.
PartnerListItem.turnover_currency  # noqa: B018
# The issuer's logo is written here and read by the Jinja layout
# (`{{ issuer.logo }}`), which vulture does not parse — the same class of
# false positive as a response-DTO field.
IssuerContext.logo  # noqa: B018
# The receipt executor writes where the goods actually landed; it is read
# through DocumentLineSchema and rendered on the document, so vulture —
# which skips the models — sees only the assignment.
DocumentLine.executed_location_id  # noqa: B018
# A recount corrects the pass it belongs to, so who counted it and when are
# written on the existing row. Both are read back through StockTakeCountRead
# on the counting screen and the report; models are excluded from the scan,
# so the assignment looks like the only use.
StockTakeCount.counted_by  # noqa: B018
StockTakeCount.counted_at  # noqa: B018
# The lot trail names the batch's decisions; the service writes the entries
# and the reader is the GET /stock-lots response (frontend renders them) —
# vulture sees only the assignment, since the DTO file is excluded.
StockLotDetailDTO.status_history  # noqa: B018
# The capacity row names the unit its limit is counted in: the router writes
# product_unit_symbol onto PutawayCapacityOut and the only reader is the
# documents location card (frontend), which the scan does not follow.
PutawayCapacityOut.product_unit_symbol  # noqa: B018

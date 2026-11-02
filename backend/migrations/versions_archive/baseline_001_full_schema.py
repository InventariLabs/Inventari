"""baseline — full schema snapshot.

This migration replaces 155 historical migrations with a single
baseline that represents the current schema state (2026-06-10).
On existing databases: stamp head, do NOT run upgrade.
On fresh databases: upgrade head to create all tables.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'baseline_001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "announcements",
        sa.Column("id", postgresql.UUID(), primary_key=True, nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("active_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("active_until", sa.DateTime(timezone=True)),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", postgresql.UUID()),
    )

    op.create_table(
        "module_installations",
        sa.Column("id", postgresql.UUID(), primary_key=True, nullable=False),
        sa.Column("module_name", sa.String(100), nullable=False),
        sa.Column("installed_version", sa.String(50), nullable=False),
        sa.Column("installed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_index("ix_module_installations_module_name", "module_installations", ["module_name"], unique=True)

    op.create_table(
        "organizations",
        sa.Column("id", postgresql.UUID(), primary_key=True, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", postgresql.UUID()),
        sa.Column("enabled_modules", postgresql.JSON(), nullable=False),
        sa.Column("allowed_modules", postgresql.JSON()),
        sa.Column("settings", postgresql.JSON(), nullable=False),
        sa.Column("short_id", sa.String(20)),
        sa.Column("active_profile_id", sa.String(50)),
        sa.Column("onboarding_completed", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("currency", sa.String(3), nullable=False, server_default=sa.text("'USD'")),
        sa.Column("timezone", sa.String(50), nullable=False, server_default=sa.text("'UTC'")),
        sa.Column("tax_id", sa.String(50)),
        sa.Column("country", sa.String(2)),
    )

    op.create_index("ix_organizations_short_id", "organizations", ["short_id"], unique=True)

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(), primary_key=True, nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("preferred_language", sa.String(10), nullable=False, server_default=sa.text("'en'")),
        sa.Column("role", sa.String(50), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_superuser", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_blocked", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("blocked_at", sa.DateTime(timezone=True)),
        sa.Column("blocking_reason", sa.String(500)),
        sa.Column("failed_login_count", sa.BigInteger(), server_default=sa.text("0")),
        sa.Column("locked_until", sa.DateTime(timezone=True)),
        sa.Column("organization_id", postgresql.UUID()),
    )

    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_is_superuser", "users", ["is_superuser"])
    op.create_index("ix_users_organization_id", "users", ["organization_id"])

    op.create_table(
        "ai_usage_logs",
        sa.Column("id", postgresql.UUID(), primary_key=True, nullable=False),
        sa.Column("user_id", postgresql.UUID()),
        sa.Column("organization_id", postgresql.UUID(), nullable=False),
        sa.Column("model_name", sa.String(255), nullable=False),
        sa.Column("provider", sa.String(100)),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("estimated_cost_usd", sa.Float()),
        sa.Column("cost_is_estimated", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("action_type", sa.String(100)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_index("ix_ai_usage_logs_user_id", "ai_usage_logs", ["user_id"])
    op.create_index("ix_ai_usage_logs_organization_id", "ai_usage_logs", ["organization_id"])
    op.create_index("ix_ai_usage_logs_created_at", "ai_usage_logs", ["created_at"])

    # NOTE: api_keys moved to api_keys module migration (001_initial).
    # NOTE: approval_workflows moved to approvals module migration (001_initial).
    # NOTE: audit_campaigns, audit_responses, equipment_assignments,
    #       equipment_attachments, equipment_document_templates,
    #       equipment_maintenance_logs moved to equipment module migration
    #       (001_initial).
    # NOTE: inventory_periods, tax_rates, document_profiles, document_type_configs,
    #       documents, document_lines, document_relations, wms_pick_sessions,
    #       wms_pick_lines moved to documents module migration (001_initial).

    op.create_table(
        "audit_log",
        sa.Column("id", postgresql.UUID(), primary_key=True, nullable=False),
        sa.Column("organization_id", postgresql.UUID(), nullable=False),
        sa.Column("user_id", postgresql.UUID()),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("target_type", sa.String(50), nullable=False),
        sa.Column("target_id", postgresql.UUID(), nullable=False),
        sa.Column("snapshot", postgresql.JSON()),
        sa.Column("reason", sa.String(500)),
        sa.Column("meta_data", postgresql.JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_index("ix_audit_log_user_id", "audit_log", ["user_id"])
    op.create_index("ix_audit_log_organization_id", "audit_log", ["organization_id"])
    op.create_index("ix_audit_log_target", "audit_log", ["target_type", "target_id"])
    op.create_index("ix_audit_log_created_at", "audit_log", ["created_at"])

    op.create_table(
        "categories",
        sa.Column("id", postgresql.UUID(), primary_key=True, nullable=False),
        sa.Column("organization_id", postgresql.UUID()),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("code", sa.String(100)),
        sa.Column("category_type", sa.String(50)),
        sa.Column("context_tag", sa.String(100)),
        sa.Column("icon", sa.String(100)),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("meta_data", postgresql.JSONB()),
        sa.Column("module_name", sa.String(50)),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("field_definitions", postgresql.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )

    op.create_index("ix_categories_context_tag", "categories", ["context_tag"])
    op.create_index("ix_categories_code", "categories", ["code"])
    op.create_index("ix_categories_module_name", "categories", ["module_name"])
    op.create_index("ix_categories_is_active", "categories", ["is_active"])
    op.create_index("ix_categories_organization_id", "categories", ["organization_id"])

    # NOTE: cycle_count_schedules, stock_takes, stock_take_items are now created by
    # the stock_takes module migration (001_initial.py).

    op.create_table(
        "document_templates",
        sa.Column("id", postgresql.UUID(), primary_key=True, nullable=False),
        sa.Column("organization_id", postgresql.UUID(), nullable=False),
        sa.Column("module", sa.String(50), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("document_type", sa.String(50), nullable=False),
        sa.Column("body_html", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("created_by", postgresql.UUID()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )

    op.create_index("ix_doc_templates_org_module", "document_templates", ["organization_id", "module"])
    op.create_index("ix_document_templates_module", "document_templates", ["module"])
    op.create_index("ix_document_templates_organization_id", "document_templates", ["organization_id"])

    # NOTE: ingredient_nutrition_defaults moved to recipes module migration (001_initial).

    # NOTE: inventory_periods, tax_rates, document_profiles, document_type_configs,
    #       documents, document_lines, document_relations, wms_pick_sessions,
    #       wms_pick_lines moved to documents module migration (001_initial).

    op.create_table(
        "item_type_definitions",
        sa.Column("code", sa.String(50), primary_key=True, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("organization_id", postgresql.UUID()),
        sa.Column("module_name", sa.String(50)),
        sa.Column("is_system", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("allowed_system_fields", postgresql.JSON(), nullable=False, server_default=sa.text("'[\"brand\", \"barcode\", \"quantity\", \"unit\"]'")),
        sa.Column("field_definitions", postgresql.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_index("ix_item_type_definitions_organization_id", "item_type_definitions", ["organization_id"])
    op.create_index("ix_item_type_definitions_is_active", "item_type_definitions", ["is_active"])
    op.create_index("ix_item_type_definitions_module_name", "item_type_definitions", ["module_name"])

    op.create_table(
        "notifications",
        sa.Column("id", postgresql.UUID(), primary_key=True, nullable=False),
        sa.Column("user_id", postgresql.UUID(), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("content", sa.String(1000), nullable=False),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("is_read", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("link", sa.String(255)),
        sa.Column("meta_data", postgresql.JSONB()),
    )

    op.create_index("ix_notifications_user_id", "notifications", ["user_id"])

    op.create_table(
        "organization_invitations",
        sa.Column("id", postgresql.UUID(), primary_key=True, nullable=False),
        sa.Column("organization_id", postgresql.UUID(), nullable=False),
        sa.Column("code", sa.String(10), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", postgresql.UUID(), nullable=False),
        sa.Column("is_used", sa.Boolean(), nullable=False),
    )

    op.create_index("ix_organization_invitations_code", "organization_invitations", ["code"], unique=True)

    op.create_table(
        "partners",
        sa.Column("id", postgresql.UUID(), primary_key=True, nullable=False),
        sa.Column("organization_id", postgresql.UUID(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("code", sa.String(50)),
        sa.Column("type", sa.String(30), nullable=False),
        sa.Column("tax_id", sa.String(50)),
        sa.Column("email", sa.String(255)),
        sa.Column("phone", sa.String(50)),
        sa.Column("website", sa.String(500)),
        sa.Column("contact_person", sa.String(255)),
        sa.Column("address", postgresql.JSONB()),
        sa.Column("notes", sa.Text()),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_by", postgresql.UUID()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_index("ix_partners_code", "partners", ["code"])
    op.create_index("uq_partner_org_code", "partners", ["organization_id", "code"], unique=True)
    op.create_index("ix_partners_is_active", "partners", ["is_active"])
    op.create_index("ix_partners_organization_id", "partners", ["organization_id"])

    # NOTE: recipe_tag_configs moved to recipes module migration (001_initial).

    # NOTE: recipes moved to recipes module migration (001_initial).

    op.create_table(
        "registration_requests",
        sa.Column("id", postgresql.UUID(), primary_key=True, nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(255)),
        sa.Column("token", sa.String(255)),
        sa.Column("preferred_language", sa.String(10), nullable=False, server_default=sa.text("'en'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("accepted_at", sa.DateTime(timezone=True)),
        sa.Column("rejected_at", sa.DateTime(timezone=True)),
        sa.Column("is_rejected", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("approved_by_id", postgresql.UUID()),
    )

    op.create_index("ix_registration_requests_email", "registration_requests", ["email"], unique=True)
    op.create_index("ix_registration_requests_token", "registration_requests", ["token"], unique=True)

    op.create_table(
        "roles",
        sa.Column("id", postgresql.UUID(), primary_key=True, nullable=False),
        sa.Column("organization_id", postgresql.UUID()),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("permissions", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_index("ix_roles_organization_id", "roles", ["organization_id"])

    # NOTE: shopping_lists is now created by the shopping_lists module migration (001_initial.py).

    op.create_table(
        "storage_types",
        sa.Column("id", postgresql.UUID(), primary_key=True, nullable=False),
        sa.Column("organization_id", postgresql.UUID()),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("type_code", sa.String(50), nullable=False),
        sa.Column("behavior_mode", sa.String(50), nullable=False),
        sa.Column("context_schema", postgresql.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("field_definitions", postgresql.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("icon", sa.String(100)),
        sa.Column("is_system", sa.Boolean(), nullable=False),
        sa.Column("created_by", postgresql.UUID()),
        sa.Column("default_settings", postgresql.JSON()),
    )

    op.create_table(
        "system_settings",
        sa.Column("key", sa.String(None), primary_key=True, nullable=False),
        sa.Column("value", postgresql.JSONB(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", postgresql.UUID()),
    )

    # NOTE: unit_conversions moved to recipes module migration (001_initial).

    op.create_table(
        "uom_categories",
        sa.Column("id", postgresql.UUID(), primary_key=True, nullable=False),
        sa.Column("organization_id", postgresql.UUID()),
        sa.Column("name", sa.String(50), nullable=False),
    )

    op.create_index("ix_uom_categories_organization_id", "uom_categories", ["organization_id"])

    # NOTE: webhook_endpoints and webhook_delivery_logs were extracted to the
    # webhooks module migration (app/modules/webhooks/migrations/versions/001_initial.py).
    # They are created on `module enable webhooks` via BaseModule.on_enable().

    # NOTE: approval_requests moved to approvals module migration (001_initial).

    # NOTE: meal_plans moved to recipes module migration (001_initial).

    # NOTE: picking_sessions moved to recipes module migration (001_initial).

    # NOTE: purchase_orders is now created by the purchase_orders module migration (001_initial.py).

    op.create_table(
        "storage_locations",
        sa.Column("id", postgresql.UUID(), primary_key=True, nullable=False),
        sa.Column("organization_id", postgresql.UUID(), nullable=False),
        sa.Column("parent_id", postgresql.UUID()),
        sa.Column("storage_type_id", postgresql.UUID()),
        sa.Column("context_schema", postgresql.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("behavior_mode", sa.String(50), nullable=False, server_default=sa.text("'STOCK'")),
        sa.Column("field_definitions", postgresql.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("location_details", sa.String(255)),
        sa.Column("short_code", sa.String(100)),
        sa.Column("usage", sa.String(50), nullable=False, server_default=sa.text("'internal'")),
        sa.Column("context_tag", sa.String(50)),
        sa.Column("settings", postgresql.JSON()),
        sa.Column("warehouse_config", postgresql.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", postgresql.UUID(), nullable=False),
    )

    op.create_index("ix_storage_locations_organization_id", "storage_locations", ["organization_id"])
    op.create_index("ix_storage_locations_context_tag", "storage_locations", ["context_tag"])
    op.create_index("ix_storage_locations_parent_id", "storage_locations", ["parent_id"])
    op.create_index("ix_storage_locations_short_code", "storage_locations", ["short_code"], unique=True)

    op.create_table(
        "uoms",
        sa.Column("id", postgresql.UUID(), primary_key=True, nullable=False),
        sa.Column("organization_id", postgresql.UUID()),
        sa.Column("category_id", postgresql.UUID(), nullable=False),
        sa.Column("name", sa.String(50), nullable=False),
        sa.Column("symbol", sa.String(10), nullable=False),
        sa.Column("factor", sa.Float(), nullable=False),
        sa.Column("is_reference", sa.Boolean(), nullable=False),
        sa.Column("is_system", sa.Boolean(), nullable=False),
        sa.Column("rounding", sa.Float(), nullable=False),
    )

    op.create_index("ix_uoms_organization_id", "uoms", ["organization_id"])

    op.create_table(
        "user_roles",
        sa.Column("user_id", postgresql.UUID(), primary_key=True, nullable=False),
        sa.Column("role_id", postgresql.UUID(), primary_key=True, nullable=False),
    )

    # NOTE: webhook_delivery_logs was extracted to the webhooks module migration.

    # NOTE: approval_decisions moved to approvals module migration (001_initial).

    op.create_table(
        "label_pool",
        sa.Column("id", postgresql.UUID(), primary_key=True, nullable=False),
        sa.Column("short_code", sa.String(20), nullable=False),
        sa.Column("is_assigned", sa.Boolean(), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True)),
        sa.Column("item_id", postgresql.UUID()),
        sa.Column("organization_id", postgresql.UUID(), nullable=False),
        sa.Column("created_by", postgresql.UUID(), nullable=False),
        sa.Column("label_type", sa.String(50), nullable=False),
        sa.Column("description", sa.String(255)),
        sa.Column("target_storage_location_id", postgresql.UUID()),
        sa.Column("context_tag", sa.String(50)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("printed_at", sa.DateTime(timezone=True)),
        sa.Column("scan_count", sa.Integer(), nullable=False),
        sa.Column("last_scanned_at", sa.DateTime(timezone=True)),
    )

    op.create_index("ix_label_pool_context_tag", "label_pool", ["context_tag"])
    op.create_index("ix_label_pool_short_code", "label_pool", ["short_code"], unique=True)
    op.create_index("ix_label_pool_is_assigned", "label_pool", ["is_assigned"])

    # NOTE: mealslot enum + meal_plan_entries moved to recipes module migration (001_initial).

    op.create_table(
        "product_templates",
        sa.Column("id", postgresql.UUID(), primary_key=True, nullable=False),
        sa.Column("organization_id", postgresql.UUID()),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("brand", sa.String(255)),
        sa.Column("barcode", sa.String(50)),
        sa.Column("sku", sa.String(50)),
        sa.Column("uom_id", postgresql.UUID()),
        sa.Column("weight_value", postgresql.DOUBLE_PRECISION()),
        sa.Column("weight_uom_id", postgresql.UUID()),
        sa.Column("volume_value", postgresql.DOUBLE_PRECISION()),
        sa.Column("volume_uom_id", postgresql.UUID()),
        sa.Column("image_url", sa.String(500)),
        sa.Column("description", sa.String(500)),
        sa.Column("min_quantity", postgresql.DOUBLE_PRECISION()),
        sa.Column("current_valuation_rate", sa.Numeric()),
        sa.Column("default_price", sa.Numeric()),
        sa.Column("default_price_uom_id", postgresql.UUID()),
        sa.Column("meta_data", postgresql.JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_index("ix_product_templates_barcode", "product_templates", ["barcode"])
    op.create_index("ix_product_templates_sku", "product_templates", ["sku"])
    op.create_index("ix_product_templates_organization_id", "product_templates", ["organization_id"])

    op.create_table(
        "stock_packages",
        sa.Column("id", postgresql.UUID(), primary_key=True, nullable=False),
        sa.Column("organization_id", postgresql.UUID(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("parent_id", postgresql.UUID()),
        sa.Column("storage_location_id", postgresql.UUID()),
        sa.Column("meta_data", postgresql.JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_index("ix_stock_packages_organization_id", "stock_packages", ["organization_id"])
    op.create_index("ix_stock_packages_parent_id", "stock_packages", ["parent_id"])

    # NOTE: stocktakestatus enum + stock_takes table are now created by the
    # stock_takes module migration (001_initial.py).

    op.create_table(
        "items",
        sa.Column("id", postgresql.UUID(), primary_key=True, nullable=False),
        sa.Column("organization_id", postgresql.UUID(), nullable=False),
        sa.Column("storage_location_id", postgresql.UUID(), nullable=False),
        sa.Column("category_id", postgresql.UUID()),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("brand", sa.String(255)),
        sa.Column("description", sa.String(500)),
        sa.Column("weight", sa.Numeric()),
        sa.Column("uom_id", postgresql.UUID()),
        sa.Column("template_id", postgresql.UUID()),
        sa.Column("quantity", sa.Numeric(), nullable=False),
        sa.Column("barcode", sa.String(50)),
        sa.Column("serial_number", sa.String(100)),
        sa.Column("lot_number", sa.String(100)),
        sa.Column("added_date", sa.Date(), nullable=False),
        sa.Column("expiry_date", sa.Date()),
        sa.Column("freeze_date", sa.Date()),
        sa.Column("production_date", sa.Date()),
        sa.Column("shelf_location", sa.String(255)),
        sa.Column("item_type", sa.String(100)),
        sa.Column("image_url", sa.String(500)),
        sa.Column("meta_data", postgresql.JSONB()),
        sa.Column("purchase_price", sa.Numeric()),
        sa.Column("currency", sa.String(3)),
        sa.Column("price_per_unit", sa.Numeric()),
        sa.Column("is_deleted", sa.Boolean(), nullable=False),
        sa.Column("is_catalog_entry", sa.Boolean(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("deleted_by", postgresql.UUID()),
        sa.Column("deletion_reason", sa.String(100)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("label_code", sa.String(20)),
        sa.Column("partner_id", postgresql.UUID()),
        sa.Column("source_document_id", postgresql.UUID()),
    )

    op.create_index("ix_items_created_at", "items", ["created_at"])
    op.create_index("ix_items_is_deleted", "items", ["is_deleted"])
    op.create_index("ix_items_storage_location_id", "items", ["storage_location_id"])
    op.create_index("ix_items_org_barcode_active", "items", ["organization_id", "barcode", "is_deleted"])
    op.create_index("ix_items_source_document_id", "items", ["source_document_id"])
    op.create_index("ix_items_organization_id", "items", ["organization_id"])
    op.create_index("ix_items_partner_id", "items", ["partner_id"])
    op.create_index("ix_items_serial_number", "items", ["serial_number"])
    op.create_index("ix_items_item_type", "items", ["item_type"])
    op.create_index("ix_items_lot_number", "items", ["lot_number"])
    op.create_index("ix_items_org_category_active", "items", ["organization_id", "category_id", "is_deleted"])
    op.create_index("ix_items_org_not_deleted", "items", ["organization_id", "is_deleted"])
    op.create_index("uq_items_org_serial", "items", ["organization_id", "serial_number"], unique=True, postgresql_where=sa.text("serial_number IS NOT NULL AND is_deleted = false"))
    op.create_index("ix_items_org_created", "items", ["organization_id", "is_deleted", sa.text("created_at DESC")])
    op.create_index("ix_items_meta_data_gin", "items", ["meta_data"], postgresql_using="gin")
    op.create_index("ix_items_barcode", "items", ["barcode"])
    op.create_index("ix_items_org_template_active", "items", ["organization_id", "template_id", "is_deleted"])
    op.create_index("ix_items_is_catalog_entry", "items", ["is_catalog_entry"])
    op.create_index("ix_items_expiry_date", "items", ["expiry_date"])

    # NOTE: purchase_order_lines is now created by the purchase_orders module migration.

    # NOTE: recipe_ingredients moved to recipes module migration (001_initial).

    # NOTE: shopping_exclusions moved to recipes module migration (001_initial).

    op.create_table(
        "stock_lots",
        sa.Column("id", postgresql.UUID(), primary_key=True, nullable=False),
        sa.Column("organization_id", postgresql.UUID(), nullable=False),
        sa.Column("product_template_id", postgresql.UUID(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("is_serial", sa.Boolean(), nullable=False),
        sa.Column("expiry_date", sa.Date()),
        sa.Column("production_date", sa.Date()),
        sa.Column("use_by_date", sa.Date()),
        sa.Column("removal_strategy", sa.String(10), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("meta_data", postgresql.JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_index("ix_stock_lots_product_template_id", "stock_lots", ["product_template_id"])
    op.create_index("ix_lot_org_expiry", "stock_lots", ["organization_id", "expiry_date"])
    op.create_index("ix_stock_lots_expiry_date", "stock_lots", ["expiry_date"])
    op.create_index("ix_stock_lots_organization_id", "stock_lots", ["organization_id"])

    # NOTE: wms_pick_sessions, document_lines, wms_pick_lines moved to documents
    #       module migration (001_initial).

    # NOTE: equipment_assignments, equipment_attachments, equipment_maintenance_logs
    #       moved to equipment module migration (001_initial).

    op.create_table(
        "item_attachments",
        sa.Column("id", postgresql.UUID(), primary_key=True, nullable=False),
        sa.Column("item_id", postgresql.UUID(), nullable=False),
        sa.Column("file_path", sa.String(500), nullable=False),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("file_type", sa.String(100), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_index("ix_item_attachments_item_id", "item_attachments", ["item_id"])

    op.create_table(
        "item_history",
        sa.Column("id", postgresql.UUID(), primary_key=True, nullable=False),
        sa.Column("organization_id", postgresql.UUID()),
        sa.Column("item_id", postgresql.UUID(), nullable=False),
        sa.Column("user_id", postgresql.UUID()),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("changes", postgresql.JSON()),
        sa.Column("source_document_id", postgresql.UUID()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_index("ix_item_history_user_id", "item_history", ["user_id"])
    op.create_index("ix_item_history_item_created", "item_history", ["item_id", "created_at"])
    op.create_index("ix_item_history_source_document_id", "item_history", ["source_document_id"])
    op.create_index("ix_item_history_organization_id", "item_history", ["organization_id"])

    # NOTE: picking_session_items moved to recipes module migration (001_initial).

    # NOTE: shopping_list_items is now created by the shopping_lists module migration.

    op.create_table(
        "stock_quants",
        sa.Column("id", postgresql.UUID(), primary_key=True, nullable=False),
        sa.Column("organization_id", postgresql.UUID(), nullable=False),
        sa.Column("product_template_id", postgresql.UUID(), nullable=False),
        sa.Column("storage_location_id", postgresql.UUID(), nullable=False),
        sa.Column("lot_id", postgresql.UUID()),
        sa.Column("package_id", postgresql.UUID()),
        sa.Column("owner_id", postgresql.UUID()),
        sa.Column("quantity", sa.Numeric(), nullable=False),
        sa.Column("reserved_quantity", sa.Numeric(), nullable=False),
        sa.Column("removal_strategy", sa.String(10), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_index("ix_quant_org_template_loc", "stock_quants", ["organization_id", "product_template_id", "storage_location_id"])
    op.create_index("ix_stock_quants_storage_location_id", "stock_quants", ["storage_location_id"])
    op.create_index("ix_stock_quants_organization_id", "stock_quants", ["organization_id"])
    op.create_index("ix_stock_quants_lot_id", "stock_quants", ["lot_id"])
    op.create_index("ix_stock_quants_product_template_id", "stock_quants", ["product_template_id"])

    # NOTE: stock_take_items is now created by the stock_takes module migration.

    op.create_table(
        "stock_valuation_layers",
        sa.Column("id", postgresql.UUID(), primary_key=True, nullable=False),
        sa.Column("organization_id", postgresql.UUID(), nullable=False),
        sa.Column("product_template_id", postgresql.UUID(), nullable=False),
        sa.Column("document_line_id", postgresql.UUID()),
        sa.Column("quantity", sa.Numeric(), nullable=False),
        sa.Column("remaining_qty", sa.Numeric(), nullable=False),
        sa.Column("unit_cost", sa.Numeric(), nullable=False),
        sa.Column("total_value", sa.Numeric(), nullable=False),
        sa.Column("direction", sa.String(10), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_index("ix_stock_valuation_layers_organization_id", "stock_valuation_layers", ["organization_id"])
    op.create_index("ix_svl_template_remaining", "stock_valuation_layers", ["product_template_id", "remaining_qty"])
    op.create_index("ix_stock_valuation_layers_product_template_id", "stock_valuation_layers", ["product_template_id"])
    op.create_index("ix_svl_org_template", "stock_valuation_layers", ["organization_id", "product_template_id"])


def downgrade() -> None:
    # NOTE: wms_pick_lines dropped by documents module migration.
    op.drop_table("wms_pick_lines")
    op.drop_index("ix_stock_valuation_layers_organization_id", table_name="stock_valuation_layers")
    op.drop_index("ix_svl_template_remaining", table_name="stock_valuation_layers")
    op.drop_index("ix_stock_valuation_layers_product_template_id", table_name="stock_valuation_layers")
    op.drop_index("ix_svl_org_template", table_name="stock_valuation_layers")
    op.drop_table("stock_valuation_layers")
    # NOTE: audit_responses dropped by equipment module migration.
    # NOTE: stock_take_items dropped by stock_takes module migration.
    op.drop_index("ix_quant_org_template_loc", table_name="stock_quants")
    op.drop_index("ix_stock_quants_storage_location_id", table_name="stock_quants")
    op.drop_index("ix_stock_quants_organization_id", table_name="stock_quants")
    op.drop_index("ix_stock_quants_lot_id", table_name="stock_quants")
    op.drop_index("ix_stock_quants_product_template_id", table_name="stock_quants")
    op.drop_table("stock_quants")
    # NOTE: shopping_list_items dropped by shopping_lists module migration.
    # NOTE: picking_session_items dropped by recipes module migration.
    op.drop_index("ix_item_history_user_id", table_name="item_history")
    op.drop_index("ix_item_history_item_created", table_name="item_history")
    op.drop_index("ix_item_history_source_document_id", table_name="item_history")
    op.drop_index("ix_item_history_organization_id", table_name="item_history")
    op.drop_table("item_history")
    op.drop_index("ix_item_attachments_item_id", table_name="item_attachments")
    op.drop_table("item_attachments")
    # NOTE: equipment_* + audit_* tables dropped by equipment module migration.
    # NOTE: document_lines, wms_pick_sessions dropped by documents module migration.
    op.drop_index("ix_stock_lots_product_template_id", table_name="stock_lots")
    op.drop_index("ix_lot_org_expiry", table_name="stock_lots")
    op.drop_index("ix_stock_lots_expiry_date", table_name="stock_lots")
    op.drop_index("ix_stock_lots_organization_id", table_name="stock_lots")
    op.drop_table("stock_lots")
    # NOTE: shopping_exclusions dropped by recipes module migration.
    # NOTE: recipe_ingredients dropped by recipes module migration.
    # NOTE: purchase_order_lines dropped by purchase_orders module migration.
    op.drop_index("ix_items_created_at", table_name="items")
    op.drop_index("ix_items_is_deleted", table_name="items")
    op.drop_index("ix_items_storage_location_id", table_name="items")
    op.drop_index("ix_items_org_barcode_active", table_name="items")
    op.drop_index("ix_items_source_document_id", table_name="items")
    op.drop_index("ix_items_organization_id", table_name="items")
    op.drop_index("ix_items_partner_id", table_name="items")
    op.drop_index("ix_items_serial_number", table_name="items")
    op.drop_index("ix_items_item_type", table_name="items")
    op.drop_index("ix_items_lot_number", table_name="items")
    op.drop_index("ix_items_org_category_active", table_name="items")
    op.drop_index("ix_items_org_not_deleted", table_name="items")
    op.drop_index("uq_items_org_serial", table_name="items")
    op.drop_index("ix_items_org_created", table_name="items")
    op.drop_index("ix_items_meta_data_gin", table_name="items")
    op.drop_index("ix_items_barcode", table_name="items")
    op.drop_index("ix_items_org_template_active", table_name="items")
    op.drop_index("ix_items_is_catalog_entry", table_name="items")
    op.drop_index("ix_items_expiry_date", table_name="items")
    op.drop_table("items")
    # NOTE: document_relations dropped by documents module migration.
    # NOTE: stock_takes + stocktakestatus enum dropped by stock_takes module migration.
    op.drop_index("ix_stock_packages_organization_id", table_name="stock_packages")
    op.drop_index("ix_stock_packages_parent_id", table_name="stock_packages")
    op.drop_table("stock_packages")
    op.drop_index("ix_product_templates_barcode", table_name="product_templates")
    op.drop_index("ix_product_templates_sku", table_name="product_templates")
    op.drop_index("ix_product_templates_organization_id", table_name="product_templates")
    op.drop_table("product_templates")
    # NOTE: meal_plan_entries + mealslot enum dropped by recipes module migration.
    op.drop_index("ix_label_pool_context_tag", table_name="label_pool")
    op.drop_index("ix_label_pool_short_code", table_name="label_pool")
    op.drop_index("ix_label_pool_is_assigned", table_name="label_pool")
    op.drop_table("label_pool")
    # NOTE: documents, document_type_configs dropped by documents module migration.
    op.drop_table("user_roles")
    op.drop_index("ix_uoms_organization_id", table_name="uoms")
    op.drop_table("uoms")
    op.drop_index("ix_storage_locations_organization_id", table_name="storage_locations")
    op.drop_index("ix_storage_locations_context_tag", table_name="storage_locations")
    op.drop_index("ix_storage_locations_parent_id", table_name="storage_locations")
    op.drop_index("ix_storage_locations_short_code", table_name="storage_locations")
    op.drop_table("storage_locations")
    # NOTE: purchase_orders dropped by purchase_orders module migration.
    # NOTE: picking_sessions dropped by recipes module migration.
    # NOTE: meal_plans dropped by recipes module migration.
    # NOTE: document_profiles dropped by documents module migration.
    op.drop_index("ix_uom_categories_organization_id", table_name="uom_categories")
    op.drop_table("uom_categories")
    # NOTE: unit_conversions dropped by recipes module migration.
    # NOTE: tax_rates dropped by documents module migration.
    op.drop_table("system_settings")
    op.drop_table("storage_types")
    # NOTE: shopping_lists dropped by shopping_lists module migration.
    op.drop_index("ix_roles_organization_id", table_name="roles")
    op.drop_table("roles")
    op.drop_index("ix_registration_requests_email", table_name="registration_requests")
    op.drop_index("ix_registration_requests_token", table_name="registration_requests")
    op.drop_table("registration_requests")
    # NOTE: recipes dropped by recipes module migration.
    # NOTE: recipe_tag_configs dropped by recipes module migration.
    op.drop_index("ix_partners_code", table_name="partners")
    op.drop_index("uq_partner_org_code", table_name="partners")
    op.drop_index("ix_partners_is_active", table_name="partners")
    op.drop_index("ix_partners_organization_id", table_name="partners")
    op.drop_table("partners")
    op.drop_index("ix_organization_invitations_code", table_name="organization_invitations")
    op.drop_table("organization_invitations")
    op.drop_index("ix_notifications_user_id", table_name="notifications")
    op.drop_table("notifications")
    op.drop_index("ix_item_type_definitions_organization_id", table_name="item_type_definitions")
    op.drop_index("ix_item_type_definitions_is_active", table_name="item_type_definitions")
    op.drop_index("ix_item_type_definitions_module_name", table_name="item_type_definitions")
    op.drop_table("item_type_definitions")
    # NOTE: inventory_periods dropped by documents module migration.
    # NOTE: ingredient_nutrition_defaults dropped by recipes module migration.
    # NOTE: equipment_document_templates dropped by equipment module migration.
    op.drop_index("ix_doc_templates_org_module", table_name="document_templates")
    op.drop_index("ix_document_templates_module", table_name="document_templates")
    op.drop_index("ix_document_templates_organization_id", table_name="document_templates")
    op.drop_table("document_templates")
    # NOTE: cycle_count_schedules dropped by stock_takes module migration.
    op.drop_index("ix_categories_context_tag", table_name="categories")
    op.drop_index("ix_categories_code", table_name="categories")
    op.drop_index("ix_categories_module_name", table_name="categories")
    op.drop_index("ix_categories_is_active", table_name="categories")
    op.drop_index("ix_categories_organization_id", table_name="categories")
    op.drop_table("categories")
    op.drop_index("ix_audit_log_user_id", table_name="audit_log")
    op.drop_index("ix_audit_log_organization_id", table_name="audit_log")
    op.drop_index("ix_audit_log_target", table_name="audit_log")
    op.drop_index("ix_audit_log_created_at", table_name="audit_log")
    op.drop_table("audit_log")
    # NOTE: audit_campaigns dropped by equipment module migration.
    # NOTE: api_keys dropped by api_keys module migration.
    op.drop_index("ix_ai_usage_logs_user_id", table_name="ai_usage_logs")
    op.drop_index("ix_ai_usage_logs_organization_id", table_name="ai_usage_logs")
    op.drop_index("ix_ai_usage_logs_created_at", table_name="ai_usage_logs")
    op.drop_table("ai_usage_logs")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_index("ix_users_is_superuser", table_name="users")
    op.drop_index("ix_users_organization_id", table_name="users")
    op.drop_table("users")
    op.drop_index("ix_organizations_short_id", table_name="organizations")
    op.drop_table("organizations")
    op.drop_index("ix_module_installations_module_name", table_name="module_installations")
    op.drop_table("module_installations")
    op.drop_table("announcements")
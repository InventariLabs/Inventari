"""baseline - the whole core schema as v0.11.0 starts.

The chain before this file grew two roots, four merge revisions and a set of
revisions that only repaired databases created before the previous squash.
Every one of those revision ids would have become permanent with the first
release, so the chain is flattened once more: this file creates the schema
that the previous head (``docvis01``) built, and a database at that head
is stamped onto it instead of replayed (``manage.py db stamp-baseline``).

Three things the last squash lost, and that this one spells out by hand
because a model cannot express them:

- the ``audit_log_immutable`` trigger, which makes audit entries append-only;
- the ``stock_holds_within_stock`` constraint trigger, the database's own
  guard that a reservation never outgrows its grain;
- the seven trigram indexes (and the ``pg_trgm`` extension) that keep the
  ILIKE searches off a sequential scan.

They are built here non-concurrently: a baseline only ever runs against an
empty database, where a plain CREATE INDEX is the whole build, and
CONCURRENTLY inside the entrypoint's advisory lock can wait for a snapshot
that never comes.

Revision ID: baseline_002
Revises:
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'baseline_002'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The audit log is append-only, enforced by the database rather than a story
#: in three docstrings. ``test_audit_log_is_immutable`` runs this same SQL.
TRIGGER_SQL = r"""


CREATE OR REPLACE FUNCTION audit_log_immutable()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'audit_log rows are immutable: % operation not allowed', TG_OP;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS audit_log_immutable ON audit_log;
CREATE TRIGGER audit_log_immutable
    BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION audit_log_immutable();


"""

#: The quants as the records tell them. A view, so a model cannot declare
#: it and a squash that rebuilds from ``Base.metadata`` would lose it; the
#: test databases create it from here (``conftest.py``).
VIEW_SQL = r"""
CREATE VIEW stock_quants_from_records AS
SELECT md5(
           sides.organization_id::text
           || '/' || sides.product_template_id::text
           || '/' || coalesce(sides.storage_location_id::text, '-')
           || '/' || coalesce(sides.lot_id::text, '-')
           || '/' || coalesce(sides.owner_id::text, '-')
       )::uuid AS id,
       sides.organization_id,
       sides.product_template_id,
       sides.storage_location_id,
       sides.lot_id,
       sides.owner_id,
       coalesce(sum(sides.quantity), 0)::numeric(12, 3) AS quantity,
       coalesce(sum(sides.reserved_quantity), 0)::numeric(12, 3) AS reserved_quantity,
       'FIFO'::varchar(10) AS removal_strategy,
       min(sides.created_at) AS created_at,
       max(sides.updated_at) AS updated_at
FROM (
    SELECT i.organization_id,
           i.template_id AS product_template_id,
           i.storage_location_id,
           i.lot_id,
           i.owner_id,
           nullif(i.quantity, 'NaN'::numeric) AS quantity,
           NULL::numeric AS reserved_quantity,
           i.created_at,
           i.updated_at
    FROM items i
    WHERE i.is_deleted IS FALSE AND i.template_id IS NOT NULL
    UNION ALL
    SELECT a.organization_id,
           a.product_template_id,
           a.storage_location_id,
           r.lot_id,
           r.owner_id,
           NULL::numeric,
           r.quantity,
           r.created_at,
           r.created_at
    FROM stock_reservations r
    JOIN stock_anchors a ON a.id = r.anchor_id
) AS sides
GROUP BY sides.organization_id,
         sides.product_template_id,
         sides.storage_location_id,
         sides.lot_id,
         sides.owner_id
"""

#: Tables a reservation must never outgrow, checked at commit. Kept verbatim:
#: the test databases run these same statements (``conftest.py``), so the suite
#: is guarded by what ships.
GUARD_SQL = (

    r"""
    CREATE FUNCTION stock_holds_within_stock() RETURNS trigger
    LANGUAGE plpgsql SET search_path = public AS $$
    DECLARE
        g_anchor uuid;
        g_lot uuid;
        g_owner uuid;
        anchor stock_anchors%ROWTYPE;
        held numeric;
        on_hand numeric;
    BEGIN
        IF TG_TABLE_NAME = 'stock_reservations' THEN
            g_anchor := NEW.anchor_id;
            g_lot := NEW.lot_id;
            g_owner := NEW.owner_id;
        ELSE
            SELECT id INTO g_anchor FROM stock_anchors
             WHERE organization_id = OLD.organization_id
               AND product_template_id = OLD.template_id
               AND storage_location_id = OLD.storage_location_id;
            g_lot := OLD.lot_id;
            g_owner := OLD.owner_id;
        END IF;
        -- A group with no anchor has no reservation rows to hold it.
        IF g_anchor IS NULL THEN
            RETURN NULL;
        END IF;
    
        SELECT coalesce(sum(quantity), 0) INTO held
          FROM stock_reservations
         WHERE anchor_id = g_anchor
           AND lot_id IS NOT DISTINCT FROM g_lot
           AND owner_id IS NOT DISTINCT FROM g_owner;
        IF held = 0 THEN
            RETURN NULL;
        END IF;
    
        SELECT * INTO anchor FROM stock_anchors WHERE id = g_anchor;
        SELECT coalesce(sum(nullif(quantity, 'NaN'::numeric)), 0) INTO on_hand
          FROM items
         WHERE organization_id = anchor.organization_id
           AND template_id = anchor.product_template_id
           AND storage_location_id = anchor.storage_location_id
           AND lot_id IS NOT DISTINCT FROM g_lot
           AND owner_id IS NOT DISTINCT FROM g_owner
           AND is_deleted IS FALSE;
    
        IF held > on_hand THEN
            RAISE EXCEPTION
                'ck_stock_holds_within_stock: % reserved of a grain holding %',
                held, on_hand
            USING ERRCODE = 'check_violation',
                  CONSTRAINT = 'ck_stock_holds_within_stock',
                  DETAIL = format(
                      'product %s, shelf %s, batch %s, owner %s',
                      anchor.product_template_id,
                      anchor.storage_location_id,
                      coalesce(g_lot::text, '-'),
                      coalesce(g_owner::text, '-')
                  );
        END IF;
        RETURN NULL;
    END $$
    """,
    r"""
    CREATE CONSTRAINT TRIGGER ck_stock_holds_within_stock
        AFTER INSERT OR UPDATE OF quantity, anchor_id, lot_id, owner_id
        ON stock_reservations
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW
        EXECUTE FUNCTION stock_holds_within_stock()
    """,
    r"""
    CREATE CONSTRAINT TRIGGER ck_stock_holds_within_stock
        AFTER UPDATE OF quantity, lot_id, owner_id, storage_location_id,
            template_id, is_deleted
        ON items
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW
        WHEN (
            OLD.is_deleted IS FALSE
            AND OLD.template_id IS NOT NULL
            AND OLD.storage_location_id IS NOT NULL
            AND (
                NEW.is_deleted IS NOT FALSE
                OR NEW.template_id IS DISTINCT FROM OLD.template_id
                OR NEW.storage_location_id IS DISTINCT FROM OLD.storage_location_id
                OR NEW.lot_id IS DISTINCT FROM OLD.lot_id
                OR NEW.owner_id IS DISTINCT FROM OLD.owner_id
                OR NEW.quantity IS NULL
                OR NEW.quantity = 'NaN'::numeric
                OR NEW.quantity < OLD.quantity
            )
        )
        EXECUTE FUNCTION stock_holds_within_stock()
    """,
    r"""
    CREATE CONSTRAINT TRIGGER ck_stock_holds_within_stock_on_delete
        AFTER DELETE
        ON items
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW
        WHEN (
            OLD.is_deleted IS FALSE
            AND OLD.template_id IS NOT NULL
            AND OLD.storage_location_id IS NOT NULL
        )
        EXECUTE FUNCTION stock_holds_within_stock()
    """
,
)

#: Indexes the models deliberately do not declare: a partial index for the
#: outbox's unpublished rows and two lookups the inventory queries make that
#: are not part of a model's own access path.
EXTRA_INDEXES = (
    (
        'ix_event_outbox_unpublished',
        'event_outbox',
        ['created_at'],
        {'postgresql_where': sa.text('published_at IS NULL')},
    ),
    ('ix_stock_moves_created_by', 'stock_moves', ['created_by'], {}),
    (
        'ix_stock_reservations_document_id',
        'stock_reservations',
        ['document_id'],
        {},
    ),
)

#: The seven trigram indexes the ILIKE searches ride. ``ix_*_trgm`` is read by
#: ``autogenerate_scope.MIGRATION_OWNED_INDEXES``, which keeps ``db migrate``
#: from proposing to drop them.
TRIGRAM_INDEXES = (
    ('ix_items_name_trgm', 'items', 'name'),
    ('ix_items_barcode_trgm', 'items', 'barcode'),
    ('ix_items_brand_trgm', 'items', 'brand'),
    ('ix_items_label_code_trgm', 'items', 'label_code'),
    ('ix_product_templates_name_trgm', 'product_templates', 'name'),
    ('ix_product_templates_sku_trgm', 'product_templates', 'sku'),
    ('ix_partners_name_trgm', 'partners', 'name'),
)


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS pg_trgm')

    op.create_table('users',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('hashed_password', sa.String(length=255), nullable=False),
    sa.Column('full_name', sa.String(length=255), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('preferred_language', sa.String(length=10), server_default='en', nullable=False),
    sa.Column('role', sa.String(length=50), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('is_superuser', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('is_blocked', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('blocked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('blocking_reason', sa.String(length=500), nullable=True),
    sa.Column('failed_login_count', sa.BigInteger(), server_default=sa.text('0'), nullable=True),
    sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('organization_id', sa.Uuid(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('organizations',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('enabled_modules', sa.JSON(), nullable=False),
    sa.Column('allowed_modules', sa.JSON(), nullable=True),
    sa.Column('settings', sa.JSON(), nullable=False),
    sa.Column('short_id', sa.String(length=20), nullable=True),
    sa.Column('active_profile_id', sa.String(length=50), nullable=True),
    sa.Column('onboarding_completed', sa.Boolean(), server_default='false', nullable=True),
    sa.Column('focus_module', sa.String(length=50), nullable=True),
    sa.Column('pre_focus_enabled_modules', sa.JSON(), nullable=True),
    sa.Column('pre_onboarding_manual_modules', sa.JSON(), nullable=True),
    sa.Column('currency', sa.String(length=3), server_default='USD', nullable=False),
    sa.Column('timezone', sa.String(length=50), server_default='UTC', nullable=False),
    sa.Column('tax_id', sa.String(length=50), nullable=True),
    sa.Column('country', sa.String(length=2), nullable=True),
    sa.Column('print_page_size', sa.String(length=10), nullable=True),
    sa.Column('address', sa.JSON(), nullable=True),
    sa.Column('logo_url', sa.String(length=500), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('ai_connections',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('organization_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('provider', sa.String(length=50), nullable=False),
    sa.Column('api_key_enc', sa.String(), server_default='', nullable=False),
    sa.Column('api_base_url', sa.String(length=512), server_default='', nullable=False),
    sa.Column('model_name', sa.String(length=255), server_default='', nullable=False),
    sa.Column('temperature', sa.Float(), nullable=True),
    sa.Column('max_tokens', sa.Integer(), nullable=True),
    sa.Column('top_p', sa.Float(), nullable=True),
    sa.Column('capabilities', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
    sa.Column('capability_checks', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('organization_id', 'name', name='uq_ai_connections_org_name')
    )
    op.create_table('ai_usage_logs',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=True),
    sa.Column('organization_id', sa.UUID(), nullable=False),
    sa.Column('model_name', sa.String(length=255), nullable=False),
    sa.Column('provider', sa.String(length=100), nullable=True),
    sa.Column('prompt_tokens', sa.Integer(), nullable=False),
    sa.Column('completion_tokens', sa.Integer(), nullable=False),
    sa.Column('total_tokens', sa.Integer(), nullable=False),
    sa.Column('estimated_cost_usd', sa.Float(), nullable=True),
    sa.Column('cost_is_estimated', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('action_type', sa.String(length=100), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('announcements',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('type', sa.String(length=50), nullable=False),
    sa.Column('active_from', sa.DateTime(timezone=True), nullable=False),
    sa.Column('active_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('audit_log',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=True),
    sa.Column('action', sa.String(length=50), nullable=False),
    sa.Column('target_type', sa.String(length=50), nullable=False),
    sa.Column('target_id', sa.Uuid(), nullable=False),
    sa.Column('snapshot', sa.JSON(), nullable=True),
    sa.Column('reason', sa.String(length=500), nullable=True),
    sa.Column('meta_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('categories',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=True),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('code', sa.String(length=100), nullable=True),
    sa.Column('context_tag', sa.String(length=100), nullable=True),
    sa.Column('group_label', sa.String(length=50), nullable=True),
    sa.Column('icon', sa.String(length=100), nullable=True),
    sa.Column('emoji', sa.String(length=32), nullable=True),
    sa.Column('color', sa.String(length=16), nullable=True),
    sa.Column('sort_order', sa.Integer(), nullable=False),
    sa.Column('meta_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('default_removal_strategy', sa.String(length=10), nullable=True),
    sa.Column('module_name', sa.String(length=50), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('field_definitions', sa.JSON(), server_default='[]', nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('document_templates',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('module', sa.String(length=50), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('document_type', sa.String(length=50), nullable=False),
    sa.Column('body_html', sa.Text(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('source_builtin', sa.String(length=255), nullable=True),
    sa.Column('source_checksum', sa.String(length=64), nullable=True),
    sa.Column('is_default', sa.Boolean(), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('email_jobs',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=True),
    sa.Column('to_email', sa.String(length=320), nullable=False),
    sa.Column('subject', sa.String(length=500), nullable=False),
    sa.Column('html_content', sa.Text(), nullable=False),
    sa.Column('attachment_bytes', sa.LargeBinary(), nullable=True),
    sa.Column('attachment_filename', sa.String(length=255), nullable=True),
    sa.Column('smtp_config_enc', sa.Text(), nullable=True),
    sa.Column('failure_notice_enc', sa.Text(), nullable=True),
    sa.Column('status', sa.String(length=20), server_default='pending', nullable=False),
    sa.Column('attempts', sa.Integer(), server_default='0', nullable=False),
    sa.Column('max_attempts', sa.Integer(), server_default='5', nullable=False),
    sa.Column('next_attempt_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('claimed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('event_deliveries',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('event_id', sa.String(length=64), nullable=False),
    sa.Column('event', sa.String(length=100), nullable=False),
    sa.Column('handler', sa.String(length=255), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=True),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('next_attempt_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('event_id', 'handler', name='uq_event_deliveries_event_handler')
    )
    op.create_table('event_outbox',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=True),
    sa.Column('event', sa.String(length=100), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('emitter_module', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('clock_timestamp()'), nullable=False),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('attempts', sa.Integer(), server_default='0', nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('partners',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('code', sa.String(length=50), nullable=True),
    sa.Column('type', sa.String(length=30), nullable=False),
    sa.Column('tax_id', sa.String(length=50), nullable=True),
    sa.Column('is_consumer', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=True),
    sa.Column('phone', sa.String(length=50), nullable=True),
    sa.Column('website', sa.String(length=500), nullable=True),
    sa.Column('contact_person', sa.String(length=255), nullable=True),
    sa.Column('address', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('organization_id', 'name', 'type', name='uq_partner_org_name_type')
    )
    op.create_table('uom_categories',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=True),
    sa.Column('name', sa.String(length=50), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('organization_id', 'name', name='uq_uom_category_org_name')
    )
    op.create_table('uoms',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=True),
    sa.Column('category_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=50), nullable=False),
    sa.Column('symbol', sa.String(length=10), nullable=False),
    sa.Column('factor', sa.Numeric(precision=18, scale=9), nullable=False),
    sa.Column('is_reference', sa.Boolean(), nullable=False),
    sa.Column('is_system', sa.Boolean(), nullable=False),
    sa.Column('rounding', sa.Numeric(precision=12, scale=6), nullable=False),
    sa.ForeignKeyConstraint(['category_id'], ['uom_categories.id'], ),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('organization_id', 'name', name='uq_uom_org_name')
    )
    op.create_table('product_templates',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=True),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('brand', sa.String(length=255), nullable=True),
    sa.Column('barcode', sa.String(length=50), nullable=True),
    sa.Column('sku', sa.String(length=50), nullable=True),
    sa.Column('uom_id', sa.Uuid(), nullable=True),
    sa.Column('weight_value', sa.Numeric(precision=14, scale=6), nullable=True),
    sa.Column('weight_uom_id', sa.Uuid(), nullable=True),
    sa.Column('volume_value', sa.Numeric(precision=14, scale=6), nullable=True),
    sa.Column('volume_uom_id', sa.Uuid(), nullable=True),
    sa.Column('image_url', sa.String(length=500), nullable=True),
    sa.Column('description', sa.String(length=500), nullable=True),
    sa.Column('min_quantity', sa.DOUBLE_PRECISION(), nullable=True),
    sa.Column('removal_strategy', sa.String(length=10), nullable=True),
    sa.Column('meta_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['uom_id'], ['uoms.id'], ),
    sa.ForeignKeyConstraint(['volume_uom_id'], ['uoms.id'], ),
    sa.ForeignKeyConstraint(['weight_uom_id'], ['uoms.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('storage_types',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=True),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('type_code', sa.String(length=50), nullable=False),
    sa.Column('behavior_mode', sa.String(length=50), nullable=False),
    sa.Column('context_schema', sa.JSON(), server_default='[]', nullable=False),
    sa.Column('field_definitions', sa.JSON(), server_default='[]', nullable=False),
    sa.Column('icon', sa.String(length=100), nullable=True),
    sa.Column('is_system', sa.Boolean(), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('default_settings', sa.JSON(), nullable=True),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('storage_locations',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('parent_id', sa.Uuid(), nullable=True),
    sa.Column('storage_type_id', sa.Uuid(), nullable=True),
    sa.Column('context_schema', sa.JSON(), server_default='[]', nullable=False),
    sa.Column('behavior_mode', sa.String(length=50), server_default='STOCK', nullable=False),
    sa.Column('field_definitions', sa.JSON(), server_default='[]', nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('location_details', sa.String(length=255), nullable=True),
    sa.Column('short_code', sa.String(length=100), nullable=True),
    sa.Column('sequence', sa.Integer(), nullable=True),
    sa.Column('usage', sa.String(length=50), server_default='internal', nullable=False),
    sa.Column('context_tag', sa.String(length=50), nullable=True),
    sa.Column('settings', sa.JSON(), nullable=True),
    sa.Column('warehouse_config', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['parent_id'], ['storage_locations.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['storage_type_id'], ['storage_types.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('organization_id', 'short_code', name='uq_storage_locations_org_short_code')
    )
    op.create_table('stock_anchors',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('product_template_id', sa.Uuid(), nullable=False),
    sa.Column('storage_location_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['product_template_id'], ['product_templates.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['storage_location_id'], ['storage_locations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('organization_id', 'product_template_id', 'storage_location_id', name='uq_stock_anchor_group')
    )
    op.create_table('stock_lots',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('product_template_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('is_serial', sa.Boolean(), nullable=False),
    sa.Column('expiry_date', sa.Date(), nullable=True),
    sa.Column('production_date', sa.Date(), nullable=True),
    sa.Column('use_by_date', sa.Date(), nullable=True),
    sa.Column('removal_strategy', sa.String(length=10), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('meta_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['product_template_id'], ['product_templates.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('organization_id', 'product_template_id', 'name', name='uq_lot_org_product_name')
    )
    op.create_table('items',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('storage_location_id', sa.Uuid(), nullable=False),
    sa.Column('category_id', sa.Uuid(), nullable=True),
    sa.Column('module_name', sa.String(length=50), nullable=True),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('brand', sa.String(length=255), nullable=True),
    sa.Column('description', sa.String(length=500), nullable=True),
    sa.Column('uom_id', sa.Uuid(), nullable=True),
    sa.Column('template_id', sa.Uuid(), nullable=True),
    sa.Column('quantity', sa.Numeric(precision=12, scale=3), nullable=False),
    sa.Column('barcode', sa.String(length=50), nullable=True),
    sa.Column('serial_number', sa.String(length=100), nullable=True),
    sa.Column('added_date', sa.Date(), nullable=False),
    sa.Column('expiry_date', sa.Date(), nullable=True),
    sa.Column('shelf_location', sa.String(length=255), nullable=True),
    sa.Column('item_type', sa.String(length=100), nullable=True),
    sa.Column('image_url', sa.String(length=500), nullable=True),
    sa.Column('meta_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('purchase_price', sa.Numeric(precision=10, scale=2), nullable=True),
    sa.Column('currency', sa.String(length=3), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), nullable=False),
    sa.Column('is_catalog_entry', sa.Boolean(), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_by', sa.Uuid(), nullable=True),
    sa.Column('deletion_reason', sa.String(length=100), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('label_code', sa.String(length=20), nullable=True),
    sa.Column('partner_id', sa.Uuid(), nullable=True),
    sa.Column('lot_id', sa.Uuid(), nullable=True),
    sa.Column('owner_id', sa.Uuid(), nullable=True),
    sa.Column('source_document_id', sa.Uuid(), nullable=True),
    sa.CheckConstraint('quantity >= 0', name='ck_items_quantity_nonneg'),
    sa.ForeignKeyConstraint(['category_id'], ['categories.id'], ),
    sa.ForeignKeyConstraint(['deleted_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['lot_id'], ['stock_lots.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['organization_id', 'template_id', 'storage_location_id'], ['stock_anchors.organization_id', 'stock_anchors.product_template_id', 'stock_anchors.storage_location_id'], name='fk_items_stock_anchor'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['owner_id'], ['partners.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['partner_id'], ['partners.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['storage_location_id'], ['storage_locations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['template_id'], ['product_templates.id'], ),
    sa.ForeignKeyConstraint(['uom_id'], ['uoms.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('item_attachments',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('item_id', sa.Uuid(), nullable=False),
    sa.Column('file_path', sa.String(length=500), nullable=False),
    sa.Column('file_name', sa.String(length=255), nullable=False),
    sa.Column('file_type', sa.String(length=100), nullable=False),
    sa.Column('file_size', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['item_id'], ['items.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('item_history',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=True),
    sa.Column('item_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=True),
    sa.Column('action', sa.String(length=50), nullable=False),
    sa.Column('changes', sa.JSON(), nullable=True),
    sa.Column('source_document_id', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['item_id'], ['items.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('item_type_definitions',
    sa.Column('code', sa.String(length=50), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=True),
    sa.Column('module_name', sa.String(length=50), nullable=True),
    sa.Column('is_system', sa.Boolean(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('allowed_system_fields', sa.JSON(), server_default='["brand", "barcode", "quantity", "unit"]', nullable=False),
    sa.Column('field_definitions', sa.JSON(), server_default='[]', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('code')
    )
    op.create_table('label_pool',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('short_code', sa.String(length=100), nullable=False),
    sa.Column('is_assigned', sa.Boolean(), nullable=False),
    sa.Column('assigned_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('item_id', sa.Uuid(), nullable=True),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=False),
    sa.Column('label_type', sa.String(length=50), nullable=False),
    sa.Column('description', sa.String(length=255), nullable=True),
    sa.Column('target_storage_location_id', sa.Uuid(), nullable=True),
    sa.Column('context_tag', sa.String(length=50), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('printed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('scan_count', sa.Integer(), nullable=False),
    sa.Column('last_scanned_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['item_id'], ['items.id'], name='fk_label_pool_item_id', ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['target_storage_location_id'], ['storage_locations.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('organization_id', 'short_code', name='uq_label_pool_org_short_code')
    )
    op.create_table('location_relocations',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('location_id', sa.Uuid(), nullable=True),
    sa.Column('location_name', sa.String(length=255), nullable=False),
    sa.Column('from_parent_id', sa.Uuid(), nullable=True),
    sa.Column('to_parent_id', sa.Uuid(), nullable=True),
    sa.Column('from_path', sa.Text(), nullable=True),
    sa.Column('to_path', sa.Text(), nullable=True),
    sa.Column('moved_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['from_parent_id'], ['storage_locations.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['location_id'], ['storage_locations.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['to_parent_id'], ['storage_locations.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('module_installations',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('module_name', sa.String(length=100), nullable=False),
    sa.Column('installed_version', sa.String(length=50), nullable=False),
    sa.Column('installed_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('notifications',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('content', sa.String(length=1000), nullable=False),
    sa.Column('type', sa.String(length=50), nullable=False),
    sa.Column('is_read', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('link', sa.String(length=255), nullable=True),
    sa.Column('meta_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('roles',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('permissions', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
    sa.Column('is_system', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('organization_invitations',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('code', sa.String(length=10), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=False),
    sa.Column('is_used', sa.Boolean(), nullable=False),
    sa.Column('role', sa.String(length=50), server_default='user', nullable=False),
    sa.Column('role_id', sa.Uuid(), nullable=True),
    sa.Column('invited_email', sa.String(length=255), nullable=True),
    sa.Column('used_by_user_id', sa.Uuid(), nullable=True),
    sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['role_id'], ['roles.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['used_by_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('registration_requests',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('full_name', sa.String(length=255), nullable=True),
    sa.Column('token', sa.String(length=255), nullable=True),
    sa.Column('preferred_language', sa.String(length=10), server_default='en', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('accepted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('rejected_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('is_rejected', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('approved_by_id', sa.Uuid(), nullable=True),
    sa.ForeignKeyConstraint(['approved_by_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('stock_moves',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('product_template_id', sa.Uuid(), nullable=False),
    sa.Column('from_location_id', sa.Uuid(), nullable=True),
    sa.Column('to_location_id', sa.Uuid(), nullable=True),
    sa.Column('quantity', sa.Numeric(precision=12, scale=3), nullable=False),
    sa.Column('lot_id', sa.Uuid(), nullable=True),
    sa.Column('owner_id', sa.Uuid(), nullable=True),
    sa.Column('expiry_date', sa.Date(), nullable=True),
    sa.Column('state', sa.String(length=20), server_default='done', nullable=False),
    sa.Column('reference_type', sa.String(length=20), nullable=True),
    sa.Column('reference_id', sa.UUID(), nullable=True),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint('from_location_id IS NOT NULL OR to_location_id IS NOT NULL', name='ck_stock_moves_at_least_one_location'),
    sa.CheckConstraint('quantity > 0', name='ck_stock_moves_qty_positive'),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['from_location_id'], ['storage_locations.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['lot_id'], ['stock_lots.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['owner_id'], ['partners.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['product_template_id'], ['product_templates.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['to_location_id'], ['storage_locations.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('stock_reservations',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('document_id', sa.UUID(), nullable=False),
    sa.Column('document_line_id', sa.Uuid(), nullable=True),
    sa.Column('anchor_id', sa.Uuid(), nullable=False),
    sa.Column('lot_id', sa.Uuid(), nullable=True),
    sa.Column('owner_id', sa.Uuid(), nullable=True),
    sa.Column('quantity', sa.Numeric(precision=12, scale=3), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['anchor_id'], ['stock_anchors.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['lot_id'], ['stock_lots.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['owner_id'], ['partners.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('stock_valuation_layers',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('product_template_id', sa.Uuid(), nullable=False),
    sa.Column('document_line_id', sa.Uuid(), nullable=True),
    sa.Column('quantity', sa.Numeric(precision=12, scale=3), nullable=False),
    sa.Column('remaining_qty', sa.Numeric(precision=12, scale=3), nullable=False),
    sa.Column('unit_cost', sa.Numeric(precision=12, scale=4), nullable=False),
    sa.Column('total_value', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('document_date', sa.Date(), nullable=True),
    sa.Column('currency', sa.String(length=3), nullable=True),
    sa.Column('direction', sa.String(length=10), nullable=False),
    sa.Column('cost_basis', sa.String(length=10), nullable=False),
    sa.Column('reason', sa.String(length=30), nullable=True),
    sa.Column('item_id', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('remaining_qty >= 0', name='ck_svl_remaining_not_negative'),
    sa.ForeignKeyConstraint(['item_id'], ['items.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['product_template_id'], ['product_templates.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('system_settings',
    sa.Column('key', sa.String(), nullable=False),
    sa.Column('value', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.ForeignKeyConstraint(['updated_by'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('key')
    )
    op.create_table('user_roles',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('role_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['role_id'], ['roles.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('user_id', 'role_id')
    )
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)
    op.create_index(op.f('ix_users_is_superuser'), 'users', ['is_superuser'], unique=False)
    op.create_index(op.f('ix_users_organization_id'), 'users', ['organization_id'], unique=False)
    op.create_index(op.f('ix_organizations_short_id'), 'organizations', ['short_id'], unique=True)
    op.create_index(op.f('ix_ai_connections_organization_id'), 'ai_connections', ['organization_id'], unique=False)
    op.create_index(op.f('ix_ai_usage_logs_created_at'), 'ai_usage_logs', ['created_at'], unique=False)
    op.create_index(op.f('ix_ai_usage_logs_organization_id'), 'ai_usage_logs', ['organization_id'], unique=False)
    op.create_index(op.f('ix_ai_usage_logs_user_id'), 'ai_usage_logs', ['user_id'], unique=False)
    op.create_index('ix_audit_log_org_created_at_id', 'audit_log', ['organization_id', sa.literal_column('created_at DESC'), 'id'], unique=False)
    op.create_index('ix_audit_log_org_type_created_at', 'audit_log', ['organization_id', 'target_type', sa.literal_column('created_at DESC'), 'id'], unique=False)
    op.create_index(op.f('ix_audit_log_organization_id'), 'audit_log', ['organization_id'], unique=False)
    op.create_index('ix_audit_log_target', 'audit_log', ['target_type', 'target_id'], unique=False)
    op.create_index(op.f('ix_audit_log_user_id'), 'audit_log', ['user_id'], unique=False)
    op.create_index(op.f('ix_categories_code'), 'categories', ['code'], unique=False)
    op.create_index(op.f('ix_categories_context_tag'), 'categories', ['context_tag'], unique=False)
    op.create_index(op.f('ix_categories_is_active'), 'categories', ['is_active'], unique=False)
    op.create_index(op.f('ix_categories_module_name'), 'categories', ['module_name'], unique=False)
    op.create_index(op.f('ix_categories_organization_id'), 'categories', ['organization_id'], unique=False)
    op.create_index('ix_doc_templates_org_module', 'document_templates', ['organization_id', 'module'], unique=False)
    op.create_index(op.f('ix_document_templates_module'), 'document_templates', ['module'], unique=False)
    op.create_index(op.f('ix_document_templates_organization_id'), 'document_templates', ['organization_id'], unique=False)
    op.create_index(op.f('ix_email_jobs_next_attempt_at'), 'email_jobs', ['next_attempt_at'], unique=False)
    op.create_index(op.f('ix_email_jobs_organization_id'), 'email_jobs', ['organization_id'], unique=False)
    op.create_index(op.f('ix_email_jobs_status'), 'email_jobs', ['status'], unique=False)
    op.create_index(op.f('ix_event_deliveries_organization_id'), 'event_deliveries', ['organization_id'], unique=False)
    op.create_index('ix_event_deliveries_status_next_attempt', 'event_deliveries', ['status', 'next_attempt_at'], unique=False)
    op.create_index(op.f('ix_event_outbox_organization_id'), 'event_outbox', ['organization_id'], unique=False)
    op.create_index(op.f('ix_partners_code'), 'partners', ['code'], unique=False)
    op.create_index(op.f('ix_partners_is_active'), 'partners', ['is_active'], unique=False)
    op.create_index(op.f('ix_partners_organization_id'), 'partners', ['organization_id'], unique=False)
    op.create_index('uq_partner_org_code', 'partners', ['organization_id', 'code'], unique=True, postgresql_where=sa.text('code IS NOT NULL'))
    op.create_index(op.f('ix_uom_categories_organization_id'), 'uom_categories', ['organization_id'], unique=False)
    op.create_index(op.f('ix_uoms_organization_id'), 'uoms', ['organization_id'], unique=False)
    op.create_index('uq_uom_category_reference', 'uoms', ['category_id'], unique=True, postgresql_where=sa.text('is_reference = true'))
    op.create_index(op.f('ix_product_templates_barcode'), 'product_templates', ['barcode'], unique=False)
    op.create_index(op.f('ix_product_templates_organization_id'), 'product_templates', ['organization_id'], unique=False)
    op.create_index(op.f('ix_product_templates_sku'), 'product_templates', ['sku'], unique=False)
    op.create_index('uq_templates_org_barcode', 'product_templates', ['organization_id', 'barcode'], unique=True, postgresql_where=sa.text('barcode IS NOT NULL'))
    op.create_index('uq_templates_org_sku', 'product_templates', ['organization_id', 'sku'], unique=True, postgresql_where=sa.text('sku IS NOT NULL'))
    op.create_index(op.f('ix_storage_locations_context_tag'), 'storage_locations', ['context_tag'], unique=False)
    op.create_index('ix_storage_locations_org_name', 'storage_locations', ['organization_id', 'name'], unique=False)
    op.create_index(op.f('ix_storage_locations_organization_id'), 'storage_locations', ['organization_id'], unique=False)
    op.create_index(op.f('ix_storage_locations_parent_id'), 'storage_locations', ['parent_id'], unique=False)
    op.create_index(op.f('ix_stock_anchors_product_template_id'), 'stock_anchors', ['product_template_id'], unique=False)
    op.create_index(op.f('ix_stock_anchors_storage_location_id'), 'stock_anchors', ['storage_location_id'], unique=False)
    op.create_index('ix_lot_org_expiry', 'stock_lots', ['organization_id', 'expiry_date'], unique=False)
    op.create_index(op.f('ix_stock_lots_expiry_date'), 'stock_lots', ['expiry_date'], unique=False)
    op.create_index(op.f('ix_stock_lots_organization_id'), 'stock_lots', ['organization_id'], unique=False)
    op.create_index(op.f('ix_stock_lots_product_template_id'), 'stock_lots', ['product_template_id'], unique=False)
    op.create_index(op.f('ix_items_barcode'), 'items', ['barcode'], unique=False)
    op.create_index(op.f('ix_items_created_at'), 'items', ['created_at'], unique=False)
    op.create_index(op.f('ix_items_expiry_date'), 'items', ['expiry_date'], unique=False)
    op.create_index(op.f('ix_items_is_catalog_entry'), 'items', ['is_catalog_entry'], unique=False)
    op.create_index(op.f('ix_items_is_deleted'), 'items', ['is_deleted'], unique=False)
    op.create_index(op.f('ix_items_item_type'), 'items', ['item_type'], unique=False)
    op.create_index('ix_items_meta_data_gin', 'items', ['meta_data'], unique=False, postgresql_using='gin')
    op.create_index(op.f('ix_items_module_name'), 'items', ['module_name'], unique=False)
    op.create_index('ix_items_org_barcode_active', 'items', ['organization_id', 'barcode', 'is_deleted'], unique=False)
    op.create_index('ix_items_org_category_active', 'items', ['organization_id', 'category_id', 'is_deleted'], unique=False)
    op.create_index('ix_items_org_created', 'items', ['organization_id', 'is_deleted', sa.literal_column('created_at DESC')], unique=False)
    op.create_index('ix_items_org_not_deleted', 'items', ['organization_id', 'is_deleted'], unique=False)
    op.create_index('ix_items_org_template_active', 'items', ['organization_id', 'template_id', 'is_deleted'], unique=False)
    op.create_index(op.f('ix_items_organization_id'), 'items', ['organization_id'], unique=False)
    op.create_index(op.f('ix_items_partner_id'), 'items', ['partner_id'], unique=False)
    op.create_index(op.f('ix_items_quantity'), 'items', ['quantity'], unique=False)
    op.create_index(op.f('ix_items_serial_number'), 'items', ['serial_number'], unique=False)
    op.create_index(op.f('ix_items_source_document_id'), 'items', ['source_document_id'], unique=False)
    op.create_index('ix_items_stock_group', 'items', ['organization_id', 'template_id', 'storage_location_id', 'lot_id', 'owner_id'], unique=False, postgresql_include=['quantity', 'is_deleted'])
    op.create_index(op.f('ix_items_storage_location_id'), 'items', ['storage_location_id'], unique=False)
    op.create_index('uq_items_org_barcode_active', 'items', ['organization_id', 'barcode'], unique=True, postgresql_where=sa.text('barcode IS NOT NULL AND is_deleted = false'))
    op.create_index('uq_items_org_serial', 'items', ['organization_id', 'serial_number'], unique=True, postgresql_where=sa.text('serial_number IS NOT NULL AND is_deleted = false'))
    op.create_index(op.f('ix_item_attachments_item_id'), 'item_attachments', ['item_id'], unique=False)
    op.create_index('ix_item_history_item_created', 'item_history', ['item_id', 'created_at'], unique=False)
    op.create_index('ix_item_history_org_action_created', 'item_history', ['organization_id', 'action', 'created_at'], unique=False)
    op.create_index(op.f('ix_item_history_organization_id'), 'item_history', ['organization_id'], unique=False)
    op.create_index(op.f('ix_item_history_source_document_id'), 'item_history', ['source_document_id'], unique=False)
    op.create_index(op.f('ix_item_history_user_id'), 'item_history', ['user_id'], unique=False)
    op.create_index(op.f('ix_item_type_definitions_is_active'), 'item_type_definitions', ['is_active'], unique=False)
    op.create_index(op.f('ix_item_type_definitions_module_name'), 'item_type_definitions', ['module_name'], unique=False)
    op.create_index(op.f('ix_item_type_definitions_organization_id'), 'item_type_definitions', ['organization_id'], unique=False)
    op.create_index(op.f('ix_label_pool_context_tag'), 'label_pool', ['context_tag'], unique=False)
    op.create_index(op.f('ix_label_pool_is_assigned'), 'label_pool', ['is_assigned'], unique=False)
    op.create_index('ix_location_relocations_org_moved_at', 'location_relocations', ['organization_id', 'moved_at'], unique=False)
    op.create_index(op.f('ix_module_installations_module_name'), 'module_installations', ['module_name'], unique=True)
    op.create_index(op.f('ix_notifications_user_id'), 'notifications', ['user_id'], unique=False)
    op.create_index(op.f('ix_roles_organization_id'), 'roles', ['organization_id'], unique=False)
    op.create_index(op.f('ix_organization_invitations_code'), 'organization_invitations', ['code'], unique=True)
    op.create_index(op.f('ix_registration_requests_email'), 'registration_requests', ['email'], unique=True)
    op.create_index(op.f('ix_registration_requests_token'), 'registration_requests', ['token'], unique=True)
    op.create_index('ix_stock_moves_completed_at', 'stock_moves', ['completed_at'], unique=False)
    op.create_index('ix_stock_moves_created_at', 'stock_moves', ['created_at'], unique=False)
    op.create_index('ix_stock_moves_from_loc', 'stock_moves', ['from_location_id'], unique=False)
    op.create_index(op.f('ix_stock_moves_lot_id'), 'stock_moves', ['lot_id'], unique=False)
    op.create_index('ix_stock_moves_org_moved_at', 'stock_moves', ['organization_id', sa.literal_column('coalesce(completed_at, created_at) DESC'), 'id'], unique=False)
    op.create_index('ix_stock_moves_org_template', 'stock_moves', ['organization_id', 'product_template_id'], unique=False)
    op.create_index(op.f('ix_stock_moves_organization_id'), 'stock_moves', ['organization_id'], unique=False)
    op.create_index(op.f('ix_stock_moves_owner_id'), 'stock_moves', ['owner_id'], unique=False)
    op.create_index(op.f('ix_stock_moves_product_template_id'), 'stock_moves', ['product_template_id'], unique=False)
    op.create_index('ix_stock_moves_reference', 'stock_moves', ['reference_type', 'reference_id'], unique=False)
    op.create_index('ix_stock_moves_to_loc', 'stock_moves', ['to_location_id'], unique=False)
    op.create_index('uq_stock_moves_backfill_ref', 'stock_moves', ['reference_type', 'reference_id'], unique=True, postgresql_where=sa.text("reference_type = 'item_history'"))
    op.create_index('ix_reservation_anchor', 'stock_reservations', ['anchor_id'], unique=False)
    op.create_index('ix_reservation_document', 'stock_reservations', ['document_id'], unique=False)
    op.create_index('ix_reservation_org_doc', 'stock_reservations', ['organization_id', 'document_id'], unique=False)
    op.create_index(op.f('ix_stock_reservations_organization_id'), 'stock_reservations', ['organization_id'], unique=False)
    op.create_index(op.f('ix_stock_valuation_layers_organization_id'), 'stock_valuation_layers', ['organization_id'], unique=False)
    op.create_index(op.f('ix_stock_valuation_layers_product_template_id'), 'stock_valuation_layers', ['product_template_id'], unique=False)
    op.create_index('ix_svl_org_direction_dated_at', 'stock_valuation_layers', ['organization_id', 'direction', sa.literal_column("coalesce(document_date, (created_at AT TIME ZONE 'UTC')::date)"), 'created_at', 'id'], unique=False)
    op.create_index('ix_svl_org_direction_reason', 'stock_valuation_layers', ['organization_id', 'direction', 'reason'], unique=False)
    op.create_index('ix_svl_org_template', 'stock_valuation_layers', ['organization_id', 'product_template_id'], unique=False)
    op.create_index('ix_svl_template_remaining', 'stock_valuation_layers', ['organization_id', 'product_template_id', 'remaining_qty'], unique=False)
    # ### end Alembic commands ###

    # The two tables reference each other; a foreign key that closes the cycle
    # is added once both exist. Their names are the ones the previous chain
    # gave them, so a stamped database and a fresh one read the same.
    op.create_foreign_key(
        'fk_users_organization_id_organizations',
        'users',
        'organizations',
        ['organization_id'],
        ['id'],
    )
    op.create_foreign_key(
        'fk_organizations_created_by_users',
        'organizations',
        'users',
        ['created_by'],
        ['id'],
    )

    for name, table, column in TRIGRAM_INDEXES:
        op.create_index(
            name,
            table,
            [column],
            unique=False,
            postgresql_using='gin',
            postgresql_ops={column: 'gin_trgm_ops'},
        )

    for name, table, columns, options in EXTRA_INDEXES:
        op.create_index(name, table, columns, unique=False, **options)

    for statement in GUARD_SQL:
        op.execute(statement)

    op.execute(TRIGGER_SQL)
    op.execute(VIEW_SQL)


def downgrade() -> None:

    op.execute('DROP VIEW IF EXISTS stock_quants_from_records')

    # The two tables reference each other; the constraint that closes the
    # cycle has to go before either table can.
    op.drop_constraint(
        'fk_users_organization_id_organizations', 'users', type_='foreignkey'
    )
    op.drop_constraint(
        'fk_organizations_created_by_users', 'organizations', type_='foreignkey'
    )

    op.drop_table('user_roles')
    op.drop_table('system_settings')
    op.drop_table('stock_valuation_layers')
    op.drop_table('stock_reservations')
    op.drop_table('stock_moves')
    op.drop_table('registration_requests')
    op.drop_table('organization_invitations')
    op.drop_table('roles')
    op.drop_table('notifications')
    op.drop_table('module_installations')
    op.drop_table('location_relocations')
    op.drop_table('label_pool')
    op.drop_table('item_type_definitions')
    op.drop_table('item_history')
    op.drop_table('item_attachments')
    op.drop_table('items')
    op.drop_table('stock_lots')
    op.drop_table('stock_anchors')
    op.drop_table('storage_locations')
    op.drop_table('storage_types')
    op.drop_table('product_templates')
    op.drop_table('uoms')
    op.drop_table('uom_categories')
    op.drop_table('partners')
    op.drop_table('event_outbox')
    op.drop_table('event_deliveries')
    op.drop_table('email_jobs')
    op.drop_table('document_templates')
    op.drop_table('categories')
    op.drop_table('audit_log')
    op.drop_table('announcements')
    op.drop_table('ai_usage_logs')
    op.drop_table('ai_connections')
    op.drop_table('organizations')
    op.drop_table('users')
    # ### end Alembic commands ###

    op.execute('DROP FUNCTION IF EXISTS stock_holds_within_stock()')
    op.execute('DROP FUNCTION IF EXISTS audit_log_immutable()')

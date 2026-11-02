"""apply organization schema rename fix

Revision ID: c4fb9b760dbe
Revises: 70cc64de9ba4
Create Date: 2026-02-19 22:48:07.918491

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'c4fb9b760dbe'
down_revision: Union[str, None] = '70cc64de9ba4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Rename core tables first.
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.organizations') IS NULL
               AND to_regclass('public.households') IS NOT NULL THEN
                ALTER TABLE public.households RENAME TO organizations;
            END IF;
        END
        $$;
        """
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.organization_invitations') IS NULL
               AND to_regclass('public.household_invitations') IS NOT NULL THEN
                ALTER TABLE public.household_invitations RENAME TO organization_invitations;
            END IF;
        END
        $$;
        """
    )

    # Rename tenant FK columns across all known tenant-scoped tables.
    for table in [
        'users',
        'storage_locations',
        'storage_types',
        'categories',
        'items',
        'item_history',
        'label_pool',
        'item_type_definitions',
        'ai_usage_logs',
        'product_templates',
        'shopping_lists',
        'stock_takes',
        'organization_invitations',
    ]:
        op.execute(
            f"""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = '{table}'
                      AND column_name = 'household_id'
                ) AND NOT EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = '{table}'
                      AND column_name = 'organization_id'
                ) THEN
                    ALTER TABLE public.{table} RENAME COLUMN household_id TO organization_id;
                END IF;
            END
            $$;
            """
        )

    # Rename commonly used indexes when they still use legacy names.
    op.execute(
        "ALTER INDEX IF EXISTS ix_households_short_id RENAME TO ix_organizations_short_id"
    )
    op.execute(
        "ALTER INDEX IF EXISTS ix_household_invitations_code RENAME TO ix_organization_invitations_code"
    )
    op.execute(
        "ALTER INDEX IF EXISTS ix_ai_usage_logs_household_id RENAME TO ix_ai_usage_logs_organization_id"
    )
    op.execute(
        "ALTER INDEX IF EXISTS ix_categories_household_id RENAME TO ix_categories_organization_id"
    )
    op.execute(
        "ALTER INDEX IF EXISTS ix_item_history_household_id RENAME TO ix_item_history_organization_id"
    )
    op.execute(
        "ALTER INDEX IF EXISTS ix_item_type_definitions_household_id RENAME TO ix_item_type_definitions_organization_id"
    )
    op.execute(
        "ALTER INDEX IF EXISTS ix_label_pool_household_id RENAME TO ix_label_pool_organization_id"
    )
    op.execute(
        "ALTER INDEX IF EXISTS ix_product_templates_household_id RENAME TO ix_product_templates_organization_id"
    )
    op.execute(
        "ALTER INDEX IF EXISTS ix_storage_locations_household_id RENAME TO ix_storage_locations_organization_id"
    )


def downgrade() -> None:
    for table in [
        'users',
        'storage_locations',
        'storage_types',
        'categories',
        'items',
        'item_history',
        'label_pool',
        'item_type_definitions',
        'ai_usage_logs',
        'product_templates',
        'shopping_lists',
        'stock_takes',
        'organization_invitations',
    ]:
        op.execute(
            f"""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = '{table}'
                      AND column_name = 'organization_id'
                ) AND NOT EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = '{table}'
                      AND column_name = 'household_id'
                ) THEN
                    ALTER TABLE public.{table} RENAME COLUMN organization_id TO household_id;
                END IF;
            END
            $$;
            """
        )

    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.household_invitations') IS NULL
               AND to_regclass('public.organization_invitations') IS NOT NULL THEN
                ALTER TABLE public.organization_invitations RENAME TO household_invitations;
            END IF;
        END
        $$;
        """
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.households') IS NULL
               AND to_regclass('public.organizations') IS NOT NULL THEN
                ALTER TABLE public.organizations RENAME TO households;
            END IF;
        END
        $$;
        """
    )

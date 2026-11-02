"""the documents module is called warehouse: carry its stored key across

Revision ID: modkey01
Revises: locreloc01
Create Date: 2026-10-22

The module that keeps the numbered documents was relabelled Warehouse, and its
key followed before the first release. An installation that ran the old key
stored it by name, and every such place is rewritten here:

* ``roles.permissions`` — ``documents:read`` and the other keys of the module
  become ``warehouse:…``;
* ``organizations`` — ``enabled_modules``, ``allowed_modules``,
  ``pre_focus_enabled_modules``, ``pre_onboarding_manual_modules``,
  ``focus_module`` and the ``module:documents`` namespace in ``settings``;
* ``module_installations.module_name``, ``document_templates.module``,
  ``event_outbox.emitter_module`` and the ``module_name`` of items,
  categories and item types (the module declares none today; a stale row
  would otherwise point at a module that no longer exists);
* the module's own version table, ``alembic_version_documents``, which its
  migrations now look for as ``alembic_version_warehouse``. The pre-flight
  check runs before this revision and reads the old table until then.

Where both spellings are present, the old one is the record and the new one
is dropped: a development server that reloaded the renamed code before this
revision ran saw a module it had never installed, installed it, and stamped a
fresh ``alembic_version_warehouse`` and ``module_installations`` row over the
existing tables. Nothing under the new key can predate this revision.

Left as they are, on purpose: ``audit_log`` is append-only in the database
(a trigger refuses an UPDATE) and records what happened under the name it had;
webhook delivery logs and event deliveries are what was sent to a receiver,
and rewriting them would make the log say something else was sent.

A data migration of its own, with no schema change, written as plain SQL so
that it also renders offline (``alembic upgrade --sql``); the module key is
frozen here as text and the module's code is not imported.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'modkey01'
down_revision: str | None = 'lockey01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = 'documents'
NEW = 'warehouse'

_MODULE_LISTS = (
    'enabled_modules',
    'allowed_modules',
    'pre_focus_enabled_modules',
    'pre_onboarding_manual_modules',
)

_NAME_COLUMNS = (
    ('module_installations', 'module_name'),
    ('document_templates', 'module'),
    ('event_outbox', 'emitter_module'),
    ('items', 'module_name'),
    ('categories', 'module_name'),
    ('item_type_definitions', 'module_name'),
)


def _execute(sql: str) -> None:
    # A colon inside a literal ('module:documents') would read as a bind.
    op.execute(sa.text(sql.replace(':', r'\:')))


def _rename_module_lists(old: str, new: str) -> None:
    """Swap the name in each JSON list, keeping its order and no duplicate."""
    for column in _MODULE_LISTS:
        _execute(
            f"""
            UPDATE organizations SET {column} = (
                SELECT json_agg(name ORDER BY first_seen) FROM (
                    SELECT CASE WHEN e.value = '{old}' THEN '{new}' ELSE e.value END
                           AS name, MIN(e.ord) AS first_seen
                    FROM json_array_elements_text(organizations.{column})
                         WITH ORDINALITY AS e(value, ord)
                    GROUP BY 1
                ) AS renamed
            )
            WHERE {column}::jsonb @> '["{old}"]'::jsonb
            """
        )
    _execute(f"UPDATE organizations SET focus_module = '{new}' WHERE focus_module = '{old}'")
    # A settings namespace already under the new name stays as it is.
    _execute(
        f"""
        UPDATE organizations SET settings = (
            jsonb_build_object('module:{new}', settings::jsonb -> 'module:{old}')
            || (settings::jsonb - 'module:{old}')
        )::json
        WHERE settings::jsonb ? 'module:{old}'
        """
    )


def _rename_permissions(old: str, new: str) -> None:
    prefix = f'{old}:'
    _execute(
        f"""
        UPDATE roles SET permissions = (
            SELECT jsonb_agg(name ORDER BY first_seen) FROM (
                SELECT CASE WHEN left(p.value, {len(prefix)}) = '{prefix}'
                            THEN '{new}:' || substr(p.value, {len(prefix) + 1})
                            ELSE p.value END AS name,
                       MIN(p.ord) AS first_seen
                FROM jsonb_array_elements_text(roles.permissions)
                     WITH ORDINALITY AS p(value, ord)
                GROUP BY 1
            ) AS renamed
        )
        WHERE EXISTS (
            SELECT 1 FROM jsonb_array_elements_text(roles.permissions) AS p(value)
            WHERE left(p.value, {len(prefix)}) = '{prefix}'
        )
        """
    )


def _rename_name_columns(old: str, new: str) -> None:
    # One row per module, and the old one is the record.
    _execute(
        f"""
        DELETE FROM module_installations WHERE module_name = '{new}'
        AND EXISTS (SELECT 1 FROM module_installations WHERE module_name = '{old}')
        """
    )
    for table, column in _NAME_COLUMNS:
        _execute(f"UPDATE {table} SET {column} = '{new}' WHERE {column} = '{old}'")


def _rename_version_table(old: str, new: str) -> None:
    old_table, new_table = f'alembic_version_{old}', f'alembic_version_{new}'
    _execute(
        f"""
        DO $$
        BEGIN
            IF to_regclass('{old_table}') IS NOT NULL THEN
                DROP TABLE IF EXISTS {new_table};
                ALTER TABLE {old_table} RENAME TO {new_table};
                IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = '{old_table}_pkc')
                THEN
                    ALTER TABLE {new_table}
                        RENAME CONSTRAINT {old_table}_pkc TO {new_table}_pkc;
                END IF;
            END IF;
        END
        $$
        """
    )


def _rename(old: str, new: str) -> None:
    _rename_module_lists(old, new)
    _rename_permissions(old, new)
    _rename_name_columns(old, new)
    _rename_version_table(old, new)


def upgrade() -> None:
    _rename(OLD, NEW)


def downgrade() -> None:
    _rename(NEW, OLD)

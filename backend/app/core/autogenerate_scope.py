"""What ``alembic revision --autogenerate`` compares the database against.

``migrations/env.py`` and the schema gates read it from here, so the
revision ``make db-migrate`` writes and the test that checks it ask the same
question. Without it, autogenerate on a freshly migrated database proposed
dropping every module's version table and every index a migration builds by
hand, and the contributor guide said to apply what it wrote.
"""

from __future__ import annotations

import importlib
from typing import Any

from sqlalchemy import MetaData
from sqlalchemy.engine import Connection
from sqlalchemy.schema import SchemaItem

#: Indexes a named migration builds by hand - trigram searches and partial
#: lookups - as expression or partial constructs the models deliberately do
#: not carry. Autogenerate reads each as an index to drop; each name is owned
#: by the migration that builds it, and a new hand-built index is added here.
#: A unique index is never one of them: it is a rule the data obeys, so the
#: models declare it and the test databases, built from the models, enforce
#: it too.
MIGRATION_OWNED_INDEXES = frozenset(
    {
        'ix_document_lines_brand_trgm',
        'ix_document_lines_held',
        'ix_document_lines_name_trgm',
        'ix_documents_external_reference_trgm',
        'ix_documents_notes_trgm',
        'ix_documents_number_trgm',
        'ix_documents_partner_name_trgm',
        'ix_event_outbox_unpublished',
        'ix_items_barcode_trgm',
        'ix_items_brand_trgm',
        'ix_items_label_code_trgm',
        'ix_items_name_trgm',
        'ix_items_org_name',
        'ix_items_serial_number_trgm',
        'ix_partners_name_trgm',
        'ix_product_templates_barcode_trgm',
        'ix_product_templates_name_trgm',
        'ix_product_templates_org_name',
        'ix_product_templates_sku_trgm',
        'ix_stock_moves_created_by',
        'ix_stock_moves_lot_id',
        'ix_stock_reservations_document_id',
    }
)

#: Each module records its own chain in ``alembic_version_<module>``; the
#: models never declare those tables.
_MODULE_VERSION_TABLE_PREFIX = 'alembic_version_'


def load_model_metadata() -> MetaData:
    """``Base.metadata`` with every core and module model imported."""
    from app.core.module_registry import module_registry
    from app.database import Base

    importlib.import_module('app.core.template_models')
    importlib.import_module('app.models')
    module_registry.discover_modules()
    for module in module_registry.get_all():
        try:
            importlib.import_module(f'app.modules.{module.metadata.name}.models')
        except ImportError:
            pass  # a module without models.py
    return Base.metadata


def include_object(
    obj: SchemaItem,
    name: str | None,
    type_: str,
    reflected: bool,
    compare_to: SchemaItem | None,
) -> bool:
    """Alembic's ``include_object`` hook: leave out what migrations own."""
    if name is None:
        return True
    if type_ == 'table' and name.startswith(_MODULE_VERSION_TABLE_PREFIX):
        return False
    if (
        type_ == 'index'
        and reflected
        and compare_to is None
        and name in MIGRATION_OWNED_INDEXES
    ):
        return False
    return True


def schema_gaps(connection: Connection, metadata: MetaData) -> list[Any]:
    """How the live schema differs from the models, ignoring what migrations own.

    The one comparison both the schema gate and ``db stamp-baseline`` ask:
    ``compare_metadata`` with the type comparison on, then the noise removed —
    the module tables this database does not have (a module not installed is
    not a gap), the foreign keys anchored on them, and the indexes migrations
    build by hand. Anything left is a table, column, index or rule the database
    has and the models do not, or the other way round.
    """
    from alembic.autogenerate import compare_metadata
    from alembic.runtime.migration import MigrationContext
    from sqlalchemy import inspect

    diff = compare_metadata(
        MigrationContext.configure(
            connection, opts={'include_object': include_object, 'compare_type': True}
        ),
        metadata,
    )
    migrated_tables = set(inspect(connection).get_table_names())
    out_of_scope = {name for name in metadata.tables if name not in migrated_tables}

    def is_noise(operation: Any) -> bool:
        if any(name in str(operation) for name in out_of_scope):
            return True
        return (
            isinstance(operation, tuple)
            and operation[0] == 'remove_index'
            and operation[1].name in MIGRATION_OWNED_INDEXES
        )

    return [operation for operation in diff if not is_noise(operation)]

"""rewrite the two Polish document-type codes as neutral ones.

Revision ID: doc_neutral_type_codes01
Revises: doc_opening_stock01
Create Date: 2026-09-05

``DocumentType`` is meant to be country-neutral — IN, OUT, INT, CORRECTION,
ADJUSTMENT, SCRAP — and two Polish abbreviations sat among them: ``PW``
(przyjęcie wewnętrzne) and ``RW`` (rozchód wewnętrzny). They are now
``INTERNAL_IN`` and ``INTERNAL_OUT``.

The value is stored as text in four places, and all four move together:

* ``documents.type`` — the register itself
* ``document_type_configs.document_type`` — per-type defaults
* ``document_templates.document_type`` — user print templates of this module
* ``document_profiles`` — ``type_labels`` (JSON keys) and
  ``approval_required_for_types`` (JSON list values)

What deliberately does **not** move is ``document_number_sequences``. Its
prefix is the literal text a number starts with, so a row keyed ``PW/2026/``
belongs to numbers already printed and handed out. Renaming it would either
re-issue numbers already in use or, for an organization whose ``PL Magazyn``
type label is itself the string ``PW``, rewrite a prefix that is still
correct. Documents created after this migration start a fresh counter under
the new prefix; the old numbers stay valid and unique, because the prefix
differs.

``rewrite`` takes its connection as an argument rather than reaching for
``op.get_bind()``, so the round trip can be tested on a real database
instead of being asserted about in prose.
"""

import json
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = 'doc_neutral_type_codes01'
down_revision: str | None = 'doc_opening_stock01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: old code -> new code
FORWARD = {'PW': 'INTERNAL_IN', 'RW': 'INTERNAL_OUT'}
BACKWARD = {new: old for old, new in FORWARD.items()}

#: table -> column holding a document type, with an optional extra predicate.
_COLUMNS: list[tuple[str, str, str]] = [
    ('documents', 'type', ''),
    ('document_type_configs', 'document_type', ''),
    ('document_templates', 'document_type', " AND module = 'documents'"),
]


def rewrite(bind: Any, mapping: dict[str, str]) -> None:
    """Apply *mapping* to every stored document type, in either direction."""
    inspector = sa.inspect(bind)

    for old, new in mapping.items():
        for table, column, extra in _COLUMNS:
            if not inspector.has_table(table):
                continue
            bind.execute(
                sa.text(
                    f'UPDATE {table} SET {column} = :new '  # noqa: S608 - names are literals above
                    f'WHERE {column} = :old{extra}'
                ),
                {'new': new, 'old': old},
            )

    if not inspector.has_table('document_profiles'):
        return

    rows = bind.execute(
        sa.text(
            'SELECT id, type_labels, approval_required_for_types '
            'FROM document_profiles'
        )
    ).fetchall()

    for profile_id, type_labels, approval_types in rows:
        new_labels = type_labels
        if isinstance(type_labels, dict):
            new_labels = {mapping.get(k, k): v for k, v in type_labels.items()}
        new_types = approval_types
        if isinstance(approval_types, list):
            new_types = [mapping.get(t, t) for t in approval_types]
        if new_labels == type_labels and new_types == approval_types:
            continue
        bind.execute(
            sa.text(
                'UPDATE document_profiles '
                'SET type_labels = CAST(:labels AS JSON), '
                'approval_required_for_types = CAST(:types AS JSON) '
                'WHERE id = :id'
            ),
            {
                'labels': None if new_labels is None else json.dumps(new_labels),
                'types': None if new_types is None else json.dumps(new_types),
                'id': profile_id,
            },
        )


def upgrade() -> None:
    rewrite(op.get_bind(), FORWARD)


def downgrade() -> None:
    rewrite(op.get_bind(), BACKWARD)

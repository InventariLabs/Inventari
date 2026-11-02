"""migrate legacy settings.llm -> ai_connections rows + bindings

Revision ID: aiconn02
Revises: aiconn01
Create Date: 2026-07-05

Data step of the AI Connections Registry.

Background
----------
Before the registry, every LLM consumer (vision, recipes) read its
config from ``organization.settings.llm`` (org-global) and
``organization.settings.modules.<module>.llm`` (module override). The
shape::

    settings.llm = {
        "provider": "openrouter" | "google_direct" | "custom"
                    | "lm_studio" | "ollama",
        "api_key": "<plain or enc:...>",
        "api_base_url": "https://...",
        "model_name": "...",
        "temperature": float,    # optional
        "max_tokens": int,       # optional
        "top_p": float,          # optional
    }

The registry replaces that with two pieces:

  1. ``ai_connections`` rows — one per provider/api_key combo
  2. ``settings.ai.defaults[<purpose_key>]`` (Core-owned purposes)
     or ``settings.modules.<module>.ai_default_connection_id``
     (module-owned purposes) — binding the org's chosen connection
     to the purpose

This migration does BOTH halves and is IDEMPOTENT — re-running it on
an already-migrated org is a no-op (guarded by the presence of any
``AiConnection`` row with a ``Migrated (...)`` name).

Per AGENTS.md §Backend.5, this is a *data* migration that lives in
its own Alembic file. Schema work is in ``aiconn01``.

Provider mapping
-----------------
``google_direct`` -> ``google`` (the registry enum has ``google``;
the SDK path handles native Gemini).

``lm_studio`` / ``ollama`` -> ``custom`` (both are OpenAI-compatible
endpoints at a custom ``api_base_url``).

``openrouter`` and ``custom`` pass through unchanged.

Capabilities
------------
Legacy entries default to ``["text", "vision"]`` (the legacy
OpenRouter recipes/vision models were multimodal). Tightening
capabilities to ``["text"]`` for orgs that only used it for
recipes would be safer, but a downgrade path that loses vision
would be a behaviour regression. We prefer the conservative set.

Encryption
----------
``migration_helpers.encrypt_secret`` is idempotent on already-encrypted
values, so rows already encrypted at rest (``enc:`` prefix) round-trip
unchanged.

Frozen schema
-------------
The tables are declared below as they stood when this revision was cut, not
imported from the ORM: a fresh install replays the chain against a schema
older than the live models, and a column a later revision adds (and the
model then requires) would make an ORM insert fail here.

Downgrade
---------
``downgrade()`` removes ONLY the rows this migration created (named
``Migrated (...)``) AND the binding entries it wrote under
``settings.ai.defaults`` / ``settings.modules.<module>.ai_default_connection_id``.
Legacy ``settings.llm`` and ``settings.modules.<module>.llm`` are
intentionally preserved — a future ``alembic upgrade head`` must be
able to replay this migration without data loss.
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, TypeGuard

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from app.core.migration_helpers import encrypt_secret

revision: str = 'aiconn02'
down_revision: str | None = 'aiconn01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MIGRATED_GLOBAL_NAME = 'Migrated (Global)'
_MIGRATED_RECIPES_NAME = 'Migrated (Recipes)'

_PROVIDER_MAP: dict[str, str] = {
    'openrouter': 'openrouter',
    'google_direct': 'google',
    'custom': 'custom',
    'lm_studio': 'custom',
    'ollama': 'custom',
}

_DEFAULT_CAPABILITIES = ['text', 'vision']

_VISION_PURPOSE = 'vision.extract'
_RECIPES_PURPOSE = 'recipes.text_parse'

# The two tables as they stood at this revision, and only the columns it
# touches. ``ai_connections`` is listed without the columns later revisions
# add, which carry a server default or are nullable. The timestamps are written
# explicitly: the column default exists only on a database built by the chain.
_metadata = sa.MetaData()

_organizations = sa.Table(
    'organizations',
    _metadata,
    sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
    sa.Column('settings', sa.JSON),
)

_ai_connections = sa.Table(
    'ai_connections',
    _metadata,
    sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
    sa.Column('organization_id', postgresql.UUID(as_uuid=True)),
    sa.Column('name', sa.String(255)),
    sa.Column('provider', sa.String(50)),
    sa.Column('api_key_enc', sa.String),
    sa.Column('api_base_url', sa.String(512)),
    sa.Column('model_name', sa.String(255)),
    sa.Column('temperature', sa.Float),
    sa.Column('max_tokens', sa.Integer),
    sa.Column('top_p', sa.Float),
    sa.Column('capabilities', postgresql.JSONB),
    sa.Column('created_at', sa.DateTime(timezone=True)),
    sa.Column('updated_at', sa.DateTime(timezone=True)),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_provider(raw: str | None) -> str | None:
    if not raw:
        return 'openrouter'
    return _PROVIDER_MAP.get(raw, 'custom')


def _llm_has_key(llm: dict[str, Any] | None) -> TypeGuard[dict[str, Any]]:
    if not llm:
        return False
    api_key = llm.get('api_key')
    return bool(api_key and isinstance(api_key, str))


def _existing_migrated_names(db: Session, organization_id) -> set[str]:
    """Names of migrated rows already present for the org — guard
    against re-running the migration on a partially-migrated DB."""
    rows = db.execute(
        sa.select(_ai_connections.c.name).where(
            _ai_connections.c.organization_id == organization_id,
            _ai_connections.c.name.in_([_MIGRATED_GLOBAL_NAME, _MIGRATED_RECIPES_NAME]),
        )
    ).all()
    return {row[0] for row in rows}


def _insert_connection(
    db: Session,
    *,
    organization_id,
    name: str,
    llm: dict[str, Any],
) -> uuid.UUID:
    connection_id = uuid.uuid4()
    now = datetime.now(UTC)
    db.execute(
        sa.insert(_ai_connections).values(
            id=connection_id,
            organization_id=organization_id,
            name=name,
            provider=_resolve_provider(llm.get('provider')),
            api_key_enc=encrypt_secret(str(llm.get('api_key') or '')),
            api_base_url=str(llm.get('api_base_url') or ''),
            model_name=str(llm.get('model_name') or ''),
            temperature=llm.get('temperature'),
            max_tokens=llm.get('max_tokens'),
            top_p=llm.get('top_p'),
            capabilities=list(_DEFAULT_CAPABILITIES),
            created_at=now,
            updated_at=now,
        )
    )
    return connection_id


def _set_binding_path(settings: dict, path: tuple[str, ...], uuid_value) -> None:
    """Nest ``str(uuid_value)`` at ``settings[<path>]`` (mutates in place)."""
    cursor = settings
    for key in path[:-1]:
        existing = cursor.get(key)
        if not isinstance(existing, dict):
            existing = {}
            cursor[key] = existing
        cursor = existing
    cursor[path[-1]] = str(uuid_value)


def _drop_binding_path(settings: dict, path: tuple[str, ...]) -> bool:
    """Remove ``settings[<path>]``; returns whether anything was removed."""
    cursor = settings
    for key in path[:-1]:
        cursor = cursor.get(key)
        if not isinstance(cursor, dict):
            return False
    return cursor.pop(path[-1], None) is not None


# ---------------------------------------------------------------------------
# upgrade
# ---------------------------------------------------------------------------


def upgrade() -> None:
    """Alembic entrypoint — resolves the active bind and delegates."""
    upgrade_with_bind(op.get_bind())


def upgrade_with_bind(bind) -> None:
    """Reusable upgrade body — also called directly by tests with a
    hand-rolled ``db_session.get_bind()`` (the conftest seeds the DB at
    head, so alembic's own revision tracking would skip this migration
    in tests)."""
    db = Session(bind=bind)

    # Only the columns this revision touches are read, through the frozen table
    # above, and settings are written back with plain UPDATEs: on a
    # fresh-install chain the table is older than the current model.
    org_table = _organizations

    try:
        # Org-global LLM -> Migrated (Global) + bind vision.extract
        for org_id, org_settings in db.execute(
            sa.select(org_table.c.id, org_table.c.settings)
        ).all():
            org_settings = dict(org_settings or {})
            changed = False
            llm = org_settings.get('llm')
            existing_names = _existing_migrated_names(db, org_id)

            if _llm_has_key(llm) and _MIGRATED_GLOBAL_NAME not in existing_names:
                connection_id = _insert_connection(
                    db,
                    organization_id=org_id,
                    name=_MIGRATED_GLOBAL_NAME,
                    llm=llm,
                )
                _set_binding_path(
                    org_settings, ('ai', 'defaults', _VISION_PURPOSE), connection_id
                )
                changed = True

            # Module override: recipes -> Migrated (Recipes) + bind recipes.text_parse
            recipes_llm = (
                org_settings.get('modules', {}).get('recipes', {}).get('llm')
            )
            if (
                _llm_has_key(recipes_llm)
                and _MIGRATED_RECIPES_NAME not in existing_names
            ):
                connection_id = _insert_connection(
                    db,
                    organization_id=org_id,
                    name=_MIGRATED_RECIPES_NAME,
                    llm=recipes_llm,
                )
                _set_binding_path(
                    org_settings,
                    ('modules', 'recipes', 'ai_default_connection_id'),
                    connection_id,
                )
                changed = True

            if changed:
                db.execute(
                    sa.update(org_table)
                    .where(org_table.c.id == org_id)
                    .values(settings=org_settings)
                )

        db.commit()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# downgrade
# ---------------------------------------------------------------------------


def downgrade() -> None:
    """Alembic entrypoint — resolves the active bind and delegates."""
    downgrade_with_bind(op.get_bind())


def downgrade_with_bind(bind) -> None:
    """Remove ONLY the migrated rows and the bindings they wrote.

    Legacy ``settings.llm`` / ``settings.modules.<module>.llm`` are
    intentionally preserved so the migration can be replayed safely.
    """
    db = Session(bind=bind)

    # Same frozen, column-scoped tables as upgrade.
    org_table = _organizations

    try:
        db.execute(
            sa.delete(_ai_connections).where(
                _ai_connections.c.name.in_(
                    [_MIGRATED_GLOBAL_NAME, _MIGRATED_RECIPES_NAME]
                )
            )
        )
        db.flush()

        for org_id, org_settings in db.execute(
            sa.select(org_table.c.id, org_table.c.settings)
        ).all():
            org_settings = dict(org_settings or {})
            dropped = _drop_binding_path(
                org_settings, ('ai', 'defaults', _VISION_PURPOSE)
            )
            dropped = (
                _drop_binding_path(
                    org_settings, ('modules', 'recipes', 'ai_default_connection_id')
                )
                or dropped
            )
            if dropped:
                db.execute(
                    sa.update(org_table)
                    .where(org_table.c.id == org_id)
                    .values(settings=org_settings)
                )

        db.commit()
    finally:
        db.close()

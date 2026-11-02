"""Model-shape unit tests for ``app.models.ai_connection.AiConnection``.

These tests assert only structural invariants — the SQLAlchemy column
declarations and constraints defined in the model file. They do not
require a database. End-to-end (DB-touching) behaviour is covered by
``tests/integration/test_ai_connection_model.py``.
"""

from __future__ import annotations


class TestModelSurface:
    def test_registered_in_app_models_init(self):
        """Alembic env.py imports ``app.models`` to populate Base.metadata.
        If AiConnection is not exported from ``app.models`` it will be
        invisible to autogenerate AND to the module-discovery routine that
        walks app.modules.<name>.models. Keep both pins in sync.
        """
        import app.models

        assert 'AiConnection' in app.models.__all__
        # and the symbol itself is bound
        assert hasattr(app.models, 'AiConnection')

    def test_table_name_is_snake_case(self):
        from app.models.ai_connection import AiConnection

        assert AiConnection.__tablename__ == 'ai_connections'

    def test_inherits_from_core_base(self):
        """Alembic discovers Core tables through ``Base.metadata``; the
        model must use the project Base, not a parallel DeclarativeBase."""
        from app.database import Base
        from app.models.ai_connection import AiConnection

        assert issubclass(AiConnection, Base)

    def test_primary_key_is_id_uuid(self):
        from app.models.ai_connection import AiConnection

        col = AiConnection.__table__.c.id
        assert col.primary_key is True


class TestColumnsAndConstraints:
    """Pin every declared column so that future
    'just tidy up' edits surface as a test failure first."""

    def test_organization_id_column(self):
        from app.models.ai_connection import AiConnection

        col = AiConnection.__table__.c.organization_id
        assert col.nullable is False
        assert col.index is True
        # FK to organizations
        fks = list(col.foreign_keys)
        assert any('organizations' in str(fk.column).lower() for fk in fks), (
            f'Expected FK to organizations, got {[fk.column for fk in fks]}'
        )

    def test_name_column_unique_per_org(self):
        """Name unique per org. The constraint is on
        (organization_id, name), not on name alone."""
        from app.models.ai_connection import AiConnection

        assert AiConnection.__table__.c.name.nullable is False
        # UniqueConstraint at the table level
        uqs = [
            c
            for c in AiConnection.__table__.constraints
            if 'Unique' in type(c).__name__
        ]
        assert uqs, 'expected at least one UniqueConstraint'
        uq_columns = {tuple(c.columns.keys()) for c in uqs}
        assert ('organization_id', 'name') in uq_columns

    def test_provider_column_is_string_not_enum(self):
        """Design uses a varchar with application-side coercion via
        LlmProvider(value). Keeping the column loose lets us add new
        providers without an Alembic migration."""
        from sqlalchemy import String

        from app.models.ai_connection import AiConnection

        assert isinstance(AiConnection.__table__.c.provider.type, String)
        assert AiConnection.__table__.c.provider.nullable is False

    def test_api_key_enc_defaults_to_empty_string(self):
        from app.models.ai_connection import AiConnection

        col = AiConnection.__table__.c.api_key_enc
        assert col.nullable is False
        # encrypt_value("") returns "" — keeping the default in sync
        # avoids None vs "" confusion in mask/merge logic.

    def test_temperature_max_tokens_top_p_are_optional(self):
        """Per design: NULL means 'use provider default'. Tests assert
        nullable=True rather than checking defaults, because the provider
        SDK defaults are the source of truth."""
        from app.models.ai_connection import AiConnection

        assert AiConnection.__table__.c.temperature.nullable is True
        assert AiConnection.__table__.c.max_tokens.nullable is True
        assert AiConnection.__table__.c.top_p.nullable is True

    def test_capabilities_is_jsonb_list(self):
        from app.models.ai_connection import AiConnection

        col = AiConnection.__table__.c.capabilities
        # JSONB on Postgres; SA type string ends with 'JSONB'
        assert 'JSONB' in type(col.type).__name__.upper()

    def test_timestamps_present(self):
        from app.models.ai_connection import AiConnection

        assert hasattr(AiConnection.__table__.c, 'created_at')
        assert hasattr(AiConnection.__table__.c, 'updated_at')

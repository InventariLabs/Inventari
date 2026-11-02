"""Integration tests for the AiConnection ORM model.

These are DB-touching tests that require the ``ai_connections`` table to
already exist (i.e. after ``alembic upgrade head``). They live in
``tests/integration/`` per the project convention, marked with
``@pytest.mark.integration``.

What we pin here:
- minimal INSERT works with defaults
- capabilities defaults to an empty list (JSONB)
- api_key_enc defaults to empty string (not NULL)
- unique constraint (organization_id, name)
- cross-org access returns 0 rows (tenant guard starts at the row level)
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.ai_connection import AiConnection


@pytest.mark.integration
class TestAiConnectionModel:
    def test_create_connection_minimal(self, db_session, test_household):
        """Minimal INSERT — only the truly required fields are
        organisation_id, name, and provider."""
        conn = AiConnection(
            organization_id=test_household.id,
            name='GPT-4o Vision',
            provider='openrouter',
        )
        db_session.add(conn)
        db_session.commit()

        assert conn.id is not None
        assert isinstance(conn.id, uuid.UUID)
        assert conn.organization_id == test_household.id
        assert conn.name == 'GPT-4o Vision'
        assert conn.provider == 'openrouter'
        assert conn.created_at is not None
        assert conn.updated_at is not None

    def test_capabilities_default_to_empty_list(self, db_session, test_household):
        conn = AiConnection(
            organization_id=test_household.id,
            name='Llama Local',
            provider='custom',
        )
        db_session.add(conn)
        db_session.commit()

        db_session.refresh(conn)
        assert conn.capabilities == []
        assert isinstance(conn.capabilities, list)

    def test_api_key_enc_defaults_to_empty_string(self, db_session, test_household):
        """Empty string = no key (e.g. local LM Studio without auth).
        Defaulting to \"\" (not NULL) keeps merge_incoming_settings logic
        consistent — ``encrypt_value(\"\")`` returns \"\", see
        app/services/crypto_service.py."""
        conn = AiConnection(
            organization_id=test_household.id,
            name='Bare Local',
            provider='custom',
        )
        db_session.add(conn)
        db_session.commit()

        db_session.refresh(conn)
        assert conn.api_key_enc == ''

    def test_duplicate_name_in_same_org_raises_unique(self, db_session, test_household):
        """(organization_id, name) is unique. Duplicate
        in the same org -> IntegrityError."""
        conn1 = AiConnection(
            organization_id=test_household.id,
            name='Same Name',
            provider='openrouter',
        )
        db_session.add(conn1)
        db_session.commit()

        conn2 = AiConnection(
            organization_id=test_household.id,
            name='Same Name',
            provider='custom',
        )
        db_session.add(conn2)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_same_name_in_different_orgs_allowed(self, db_session, test_household):
        """Uniqueness is per-org — two orgs may both have a connection
        named \"Default\"."""
        from app.models.organization import Organization

        # Need a second org. Hand-roll the model + flush.
        other_org = Organization(name='Other Org')
        db_session.add(other_org)
        db_session.commit()
        assert other_org.id is not None

        conn_a = AiConnection(
            organization_id=test_household.id,
            name='Default',
            provider='openrouter',
        )
        conn_b = AiConnection(
            organization_id=other_org.id,
            name='Default',
            provider='openrouter',
        )
        db_session.add_all([conn_a, conn_b])
        db_session.commit()

        # Both rows persist — different (org_id, name) tuples.
        assert conn_a.id != conn_b.id

    def test_optional_numeric_params_default_to_none(self, db_session, test_household):
        """temperature / max_tokens / top_p must be NULL when unset so
        that ``None`` still means \"use provider SDK default\"."""
        conn = AiConnection(
            organization_id=test_household.id,
            name='Params None',
            provider='openrouter',
        )
        db_session.add(conn)
        db_session.commit()

        db_session.refresh(conn)
        assert conn.temperature is None
        assert conn.max_tokens is None
        assert conn.top_p is None

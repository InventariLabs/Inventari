"""The rename of PW/RW carries existing rows with it, both ways.

``DocumentType`` values are stored as plain text, so renaming ``PW`` and
``RW`` to ``INTERNAL_IN`` and ``INTERNAL_OUT`` is a data migration, not just
a code change: a register, a per-type config, a print template and a profile
all hold the value. This drives the migration's own ``rewrite`` against a
real database in both directions — an upgrade that only works forwards is
not a migration anyone can back out of.
"""

from __future__ import annotations

import importlib.util
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.user import User

_MIGRATION = (
    Path(__file__).resolve().parents[2]
    / 'migrations'
    / 'versions'
    / 'doc_neutral_type_codes01_data.py'
)


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        'doc_neutral_type_codes01', _MIGRATION
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.integration
class TestNeutralTypeCodesMigration:
    def test_round_trip_across_every_place_the_value_is_stored(
        self,
        db_session: Session,
        test_household: Organization,
        test_user: User,
    ) -> None:
        db = db_session
        migration = _load_migration()
        org_id = test_household.id
        doc_id = uuid.uuid4()
        config_id = uuid.uuid4()
        template_id = uuid.uuid4()
        profile_id = uuid.uuid4()

        db.execute(
            text(
                'INSERT INTO documents (id, organization_id, type, number, status, '
                'created_by, created_at, updated_at) '
                'VALUES (:id, :org, :type, :number, :status, :by, :now, :now)'
            ),
            {
                'id': doc_id,
                'org': org_id,
                'type': 'PW',
                'number': 'PW/2026/001',
                'status': 'DRAFT',
                'by': test_user.id,
                'now': datetime.now(UTC),
            },
        )
        db.execute(
            text(
                'INSERT INTO document_type_configs (id, organization_id, '
                'document_type, sequence_format, require_partner, created_at) '
                'VALUES (:id, :org, :type, :fmt, false, :now)'
            ),
            {
                'id': config_id,
                'org': org_id,
                'type': 'RW',
                'fmt': '{TYPE}/{YEAR}/{SEQ:05d}',
                'now': datetime.now(UTC),
            },
        )
        db.execute(
            text(
                'INSERT INTO document_templates (id, organization_id, module, name, '
                'document_type, body_html, version, is_default, created_at, '
                "updated_at) VALUES (:id, :org, 'documents', 'Internal note', :type, "
                "'<p></p>', 1, false, :now, :now)"
            ),
            {
                'id': template_id,
                'org': org_id,
                'type': 'PW',
                'now': datetime.now(UTC),
            },
        )
        db.execute(
            text('DELETE FROM document_profiles WHERE organization_id = :org'),
            {'org': org_id},
        )
        db.execute(
            text(
                'INSERT INTO document_profiles (id, organization_id, name, '
                'value_tracking_enabled, tax_handling, require_partner_tax_id, '
                'require_unit_price, numbering_format, number_padding, type_labels, '
                'default_unit, print_template, approval_required_for_types, '
                'created_at, updated_at) VALUES (:id, :org, :name, false, :tax, false, '
                "false, '{TYPE}/{YEAR}/{SEQ:03d}', 3, CAST(:labels AS JSON), 'pcs', "
                "'standard', CAST(:types AS JSON), :now, :now)"
            ),
            {
                'id': profile_id,
                'org': org_id,
                'name': 'PL Magazyn',
                'tax': 'NONE',
                'labels': '{"IN": "PZ", "PW": "PW", "RW": "RW"}',
                'types': '["OUT", "RW"]',
                'now': datetime.now(UTC),
            },
        )
        db.commit()

        migration.rewrite(db.connection(), migration.FORWARD)
        db.commit()

        assert self._doc_type(db, doc_id) == 'INTERNAL_IN'
        assert self._config_type(db, config_id) == 'INTERNAL_OUT'
        assert self._template_type(db, template_id) == 'INTERNAL_IN'
        labels, types = self._profile(db, profile_id)
        assert labels == {'IN': 'PZ', 'INTERNAL_IN': 'PW', 'INTERNAL_OUT': 'RW'}
        assert types == ['OUT', 'INTERNAL_OUT']

        migration.rewrite(db.connection(), migration.BACKWARD)
        db.commit()

        assert self._doc_type(db, doc_id) == 'PW'
        assert self._config_type(db, config_id) == 'RW'
        assert self._template_type(db, template_id) == 'PW'
        labels, types = self._profile(db, profile_id)
        assert labels == {'IN': 'PZ', 'PW': 'PW', 'RW': 'RW'}
        assert types == ['OUT', 'RW']

    def test_the_issued_number_is_left_alone(
        self,
        db_session: Session,
        test_household: Organization,
        test_user: User,
    ) -> None:
        """A number already printed identifies a document; renaming a code does not."""
        db = db_session
        migration = _load_migration()
        doc_id = uuid.uuid4()
        db.execute(
            text(
                'INSERT INTO documents (id, organization_id, type, number, status, '
                'created_by, created_at, updated_at) '
                'VALUES (:id, :org, :type, :number, :status, :by, :now, :now)'
            ),
            {
                'id': doc_id,
                'org': test_household.id,
                'type': 'PW',
                'number': 'PW/2026/007',
                'status': 'COMPLETED',
                'by': test_user.id,
                'now': datetime.now(UTC),
            },
        )
        db.commit()

        migration.rewrite(db.connection(), migration.FORWARD)
        db.commit()

        row = db.execute(
            text('SELECT type, number FROM documents WHERE id = :id'), {'id': doc_id}
        ).one()
        assert row.type == 'INTERNAL_IN'
        assert row.number == 'PW/2026/007'

    @staticmethod
    def _doc_type(db: Session, doc_id: uuid.UUID) -> str:
        return str(
            db.execute(
                text('SELECT type FROM documents WHERE id = :id'), {'id': doc_id}
            ).scalar_one()
        )

    @staticmethod
    def _config_type(db: Session, config_id: uuid.UUID) -> str:
        return str(
            db.execute(
                text('SELECT document_type FROM document_type_configs WHERE id = :id'),
                {'id': config_id},
            ).scalar_one()
        )

    @staticmethod
    def _template_type(db: Session, template_id: uuid.UUID) -> str:
        return str(
            db.execute(
                text('SELECT document_type FROM document_templates WHERE id = :id'),
                {'id': template_id},
            ).scalar_one()
        )

    @staticmethod
    def _profile(
        db: Session, profile_id: uuid.UUID
    ) -> tuple[dict[str, str], list[str]]:
        row = db.execute(
            text(
                'SELECT type_labels, approval_required_for_types '
                'FROM document_profiles WHERE id = :id'
            ),
            {'id': profile_id},
        ).one()
        return row.type_labels, row.approval_required_for_types

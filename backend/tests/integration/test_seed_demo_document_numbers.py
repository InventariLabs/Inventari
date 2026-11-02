"""The demo seeder must not insist on document numbers the organization holds.

It writes its own numbers rather than asking ``document_numbering_service``:
that service is async and takes an advisory lock to promise numbering without
gaps, which demo data does not need. What it does need is to look first — an
organization already carrying ``IN/<year>/001``, from ordinary use or from a
seed run whose documents ``clean_seed_data`` does not own, turned
``make db-seed-demo`` into a UniqueViolation on ``uq_document_org_number``.
"""

from __future__ import annotations

import uuid
from collections.abc import Generator
from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.user import User
from app.modules.warehouse.models import Document
from app.services.token_service import get_password_hash
from seed_demo_data import highest_document_seq

pytestmark = pytest.mark.integration

YEAR = datetime.now(UTC).year


@pytest.fixture
def seed_org(db_session: Session) -> Generator[uuid.UUID]:
    org = Organization(id=uuid.uuid4(), name='Smoke Test Seed Numbers')
    db_session.add(org)
    db_session.commit()
    author = User(
        id=uuid.uuid4(),
        organization_id=org.id,
        email=f'seednum+{uuid.uuid4().hex[:8]}@example.com',
        full_name='Seed Numbers',
        hashed_password=get_password_hash('smoke-test-password'),
    )
    db_session.add(author)
    db_session.commit()
    _AUTHOR[org.id] = author.id
    yield org.id
    db_session.query(Document).filter(Document.organization_id == org.id).delete(
        synchronize_session=False
    )
    db_session.query(User).filter(User.organization_id == org.id).delete(
        synchronize_session=False
    )
    db_session.query(Organization).filter(Organization.id == org.id).delete(
        synchronize_session=False
    )
    db_session.commit()


#: Documents need an author; the fixture makes one per organization.
_AUTHOR: dict[uuid.UUID, uuid.UUID] = {}


def _document(org_id: uuid.UUID, number: str, ref: str | None = None) -> Document:
    return Document(
        id=uuid.uuid4(),
        organization_id=org_id,
        type=number.split('/')[0].split('-')[0],
        number=number,
        status='DRAFT',
        external_reference=ref,
        created_by=_AUTHOR[org_id],
    )


class TestHighestDocumentSeq:
    def test_an_untouched_pattern_starts_the_caller_at_one(
        self, db_session: Session, seed_org: uuid.UUID
    ) -> None:
        assert highest_document_seq(db_session, seed_org, 'IN', YEAR) == 0

    def test_it_clears_the_highest_number_already_taken(
        self, db_session: Session, seed_org: uuid.UUID
    ) -> None:
        db_session.add(_document(seed_org, f'IN/{YEAR}/001'))
        db_session.add(_document(seed_org, f'IN/{YEAR}/007'))
        db_session.add(_document(seed_org, f'IN/{YEAR}/003'))
        db_session.commit()

        assert highest_document_seq(db_session, seed_org, 'IN', YEAR) == 7

    def test_each_type_and_year_counts_on_its_own(
        self, db_session: Session, seed_org: uuid.UUID
    ) -> None:
        db_session.add(_document(seed_org, f'IN/{YEAR}/009'))
        db_session.add(_document(seed_org, f'OUT/{YEAR}/002'))
        db_session.add(_document(seed_org, f'IN/{YEAR - 1}/044'))
        db_session.commit()

        assert highest_document_seq(db_session, seed_org, 'IN', YEAR) == 9
        assert highest_document_seq(db_session, seed_org, 'OUT', YEAR) == 2
        assert highest_document_seq(db_session, seed_org, 'INT', YEAR) == 0

    def test_a_number_the_seeder_does_not_own_still_counts(
        self, db_session: Session, seed_org: uuid.UUID
    ) -> None:
        """The collision that started this: no marker, and still in the way."""
        db_session.add(_document(seed_org, f'IN/{YEAR}/012', ref=None))
        db_session.commit()

        assert highest_document_seq(db_session, seed_org, 'IN', YEAR) == 12

    def test_a_custom_format_is_left_alone(
        self, db_session: Session, seed_org: uuid.UUID
    ) -> None:
        """An organization numbering its own way does not shift the seeder.

        Only the pattern the seeder writes can collide with the seeder.
        """
        db_session.add(_document(seed_org, f'IN-{YEAR}-0099'))
        db_session.add(_document(seed_org, f'IN/{YEAR}/FV-1'))
        db_session.commit()

        assert highest_document_seq(db_session, seed_org, 'IN', YEAR) == 0

    def test_another_organization_does_not_shift_this_one(
        self, db_session: Session, seed_org: uuid.UUID
    ) -> None:
        other = Organization(id=uuid.uuid4(), name='Neighbour')
        db_session.add(other)
        db_session.commit()
        neighbour = User(
            id=uuid.uuid4(),
            organization_id=other.id,
            email=f'neighbour+{uuid.uuid4().hex[:8]}@example.com',
            full_name='Neighbour',
            hashed_password=get_password_hash('smoke-test-password'),
        )
        db_session.add(neighbour)
        db_session.commit()
        _AUTHOR[other.id] = neighbour.id
        db_session.add(_document(other.id, f'IN/{YEAR}/050'))
        db_session.commit()

        assert highest_document_seq(db_session, seed_org, 'IN', YEAR) == 0

        db_session.query(Document).filter(Document.organization_id == other.id).delete(
            synchronize_session=False
        )
        db_session.query(User).filter(User.organization_id == other.id).delete(
            synchronize_session=False
        )
        db_session.query(Organization).filter(Organization.id == other.id).delete(
            synchronize_session=False
        )
        db_session.commit()

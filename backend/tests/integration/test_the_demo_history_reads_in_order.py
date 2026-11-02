"""A fresh demo's History has to read like a warehouse that has been working.

Four things read wrong on the Warehouse → History screen of a new sandbox:

* every seeded entry carried the clock time of the seeding hour;
* the receipt behind the half-delivered purchase order was numbered after the
  delivery notes although it was dated weeks before them, so ``IN/…/004``
  dated the 10th sat under ``IN/…/001`` dated the 18th;
* the two dispatches the seed walks were completed at the moment of seeding;
* every entry was signed by the visitor's own account, a fortnight before the
  visitor arrived.

Each test reads a freshly seeded and dressed organization.
"""

from __future__ import annotations

import uuid
from collections.abc import Generator

import pytest
from sqlalchemy.orm import Session

from app.database import Base
from app.models.organization import Organization
from app.models.user import User
from app.modules.warehouse.models import Document
from app.services.token_service import get_password_hash
from seed_demo_data import SEEDED_MODULES, seed_organization
from seed_demo_showcase import dress_for_visitors

pytestmark = pytest.mark.integration


@pytest.fixture
def sandbox(db_session: Session) -> Generator[tuple[uuid.UUID, uuid.UUID]]:
    """An organization seeded and dressed the way a visitor's sandbox is."""
    org = Organization(
        id=uuid.uuid4(),
        name='My Organization',
        enabled_modules=sorted(
            {
                'core',
                'items',
                'locations',
                'categories',
                'stats',
                'approvals',
                *SEEDED_MODULES,
            }
        ),
    )
    visitor = User(
        id=uuid.uuid4(),
        organization_id=org.id,
        email=f'visitor+{uuid.uuid4().hex[:8]}@example.com',
        full_name='Demo Visitor',
        hashed_password=get_password_hash('demo-test-password'),
        role='admin',
        is_active=True,
    )
    db_session.add(org)
    db_session.commit()
    db_session.add(visitor)
    db_session.commit()

    seed_organization(db_session, org.id, visitor.id, items=60)
    dress_for_visitors(db_session, org.id, visitor.id)

    yield org.id, visitor.id

    for table in reversed(Base.metadata.sorted_tables):
        column = table.c.get('organization_id')
        if column is None or table.name in ('organizations', 'audit_log'):
            continue
        db_session.execute(table.delete().where(column == org.id))
    db_session.query(Organization).filter(Organization.id == org.id).delete(
        synchronize_session=False
    )
    db_session.commit()


def _documents(db: Session, org_id: uuid.UUID) -> list[Document]:
    db.expire_all()
    return db.query(Document).filter(Document.organization_id == org_id).all()


class TestDocumentNumbersFollowTheirDates:
    def test_each_type_is_numbered_in_the_order_its_documents_were_written(
        self, db_session: Session, sandbox
    ) -> None:
        org_id, _visitor_id = sandbox
        documents = _documents(db_session, org_id)
        assert {doc.type for doc in documents} >= {'IN', 'OUT'}

        for doc_type in {doc.type for doc in documents}:
            of_type = [doc for doc in documents if doc.type == doc_type]
            by_number = sorted(of_type, key=lambda doc: doc.number)
            written = [doc.created_at for doc in by_number]
            assert written == sorted(written), f'{doc_type}: ' + ', '.join(
                f'{d.number} {d.created_at:%m-%d %H:%M}' for d in by_number
            )

    def test_the_numbers_of_a_type_are_consecutive(
        self, db_session: Session, sandbox
    ) -> None:
        org_id, _visitor_id = sandbox
        receipts = sorted(
            doc.number for doc in _documents(db_session, org_id) if doc.type == 'IN'
        )
        sequence = [int(number.rsplit('/', 1)[1]) for number in receipts]
        assert sequence == list(range(1, len(sequence) + 1))


class TestEntriesAreNotAllStampedAtTheSameMinute:
    def test_completed_documents_carry_varied_times_within_a_working_day(
        self, db_session: Session, sandbox
    ) -> None:
        org_id, _visitor_id = sandbox
        finished = [
            doc
            for doc in _documents(db_session, org_id)
            if doc.completed_at is not None
        ]
        assert len(finished) >= 5, 'too few finished documents to compare'

        clock_times = {doc.completed_at.strftime('%H:%M') for doc in finished}
        assert len(clock_times) >= 4, clock_times
        for doc in finished:
            assert 8 <= doc.completed_at.hour < 18, (doc.number, doc.completed_at)
            assert doc.created_at < doc.confirmed_at < doc.completed_at, doc.number


class TestTheHistoryIsNotTheVisitorsOwn:
    def test_no_seeded_document_is_signed_by_the_visitor(
        self, db_session: Session, sandbox
    ) -> None:
        org_id, visitor_id = sandbox
        for doc in _documents(db_session, org_id):
            assert visitor_id not in (
                doc.created_by,
                doc.confirmed_by,
                doc.completed_by,
            ), doc.number

"""The demo seeder never gives two locations of one organization the same code.

Codes are drawn at random; a draw that lands on a code the organization
already holds used to end the whole seed in a unique violation.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import Session

import seed_demo_data
from app.models.organization import Organization
from app.models.storage_location import LocationUsage, StorageLocation
from app.models.user import User
from app.services.token_service import get_password_hash

pytestmark = pytest.mark.integration


def test_a_repeated_draw_is_drawn_again(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    org = Organization(id=uuid.uuid4(), name='Shelf Code Org')
    db_session.add(org)
    db_session.flush()
    user = User(
        id=uuid.uuid4(),
        organization_id=org.id,
        email=f'shelf-code+{uuid.uuid4().hex[:8]}@example.com',
        full_name='Seed',
        hashed_password=get_password_hash('seed-test-password'),
    )
    db_session.add(user)
    db_session.commit()
    draws = iter([list('AAAA'), list('AAAA'), list('BBBB')])
    monkeypatch.setattr(seed_demo_data.random, 'choices', lambda *_a, **_k: next(draws))

    first = seed_demo_data._short_code(db_session, org.id)
    db_session.add(
        StorageLocation(
            id=uuid.uuid4(),
            organization_id=org.id,
            name='First',
            usage=LocationUsage.INTERNAL,
            short_code=first,
            created_by=user.id,
        )
    )
    db_session.flush()
    second = seed_demo_data._short_code(db_session, org.id)

    assert first == seed_demo_data.SEED_PREFIX + 'AAAA'
    assert second == seed_demo_data.SEED_PREFIX + 'BBBB'

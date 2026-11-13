"""The k6 user seed's --clean can delete the users it created.

A k6 user and its organization reference each other: ``users.organization_id``
points at the organization, and ``organizations.created_by`` points back at the
user. Deleting both through the ORM in one flush made SQLAlchemy report a
circular dependency and abort, so --clean deleted nothing. The clean breaks the
cycle first, then deletes.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

import seed_load_test_users as seed
from app.models.organization import Organization
from app.models.user import User

PREFIX = 'k6cycle'


def _a_seeded_user(db_session: Session, number: int = 1) -> tuple[User, Organization]:
    user = User(
        email=f'{PREFIX}{number:04d}@loadtest.inventari.app',
        hashed_password='not-a-real-hash',
        full_name=f'Load Test User {number:04d}',
        role='user',
        is_active=True,
    )
    db_session.add(user)
    db_session.flush()

    org = Organization(name=f'LoadTest Org {number:04d}', created_by=user.id)
    db_session.add(org)
    db_session.flush()

    user.organization_id = org.id
    db_session.commit()
    return user, org


@pytest.mark.parametrize('user_count', [2, 20])
def test_clean_removes_the_users_and_the_orgs_they_created(
    db_session: Session, user_count: int
) -> None:
    created = [_a_seeded_user(db_session, i) for i in range(1, user_count + 1)]
    emails = [user.email for user, _ in created]
    org_ids = [org.id for _, org in created]

    deleted = seed.clean_k6_users(db_session, PREFIX, info=lambda *a, **kw: None)

    assert deleted == user_count
    assert db_session.query(User).filter(User.email.in_(emails)).count() == 0
    assert (
        db_session.query(Organization).filter(Organization.id.in_(org_ids)).count() == 0
    )

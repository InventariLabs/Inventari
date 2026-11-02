"""Fixtures for the reference module's tests.

Two things live here. The model import registers this module in
``Base.metadata``: the root conftest derives the import path from
``_DeclarativeModule.__class__.__module__``, which resolves to ``app.core``
for modules built with ``define_module()``, so it has to be explicit.

And the organisations, accounts and headers every test in this module needs.
They belong in a conftest rather than in one test file, because this module
is what ``cli/module_generator.py`` copies: a second test file in a generated
module should find them, not import them from a sibling.
"""

import pytest
from sqlalchemy.orm import Session

import app.modules.example_widgets.models  # noqa: F401
from app.models.organization import Organization
from app.models.user import User


@pytest.fixture
def widget_org(db_session: Session) -> Organization:
    from app.models.organization import Organization

    org = Organization(
        name='Widget Test Org',
        enabled_modules=[
            'core',
            'items',
            'locations',
            'categories',
            'example_widgets',
        ],
    )
    db_session.add(org)
    db_session.commit()
    db_session.refresh(org)
    return org


@pytest.fixture
def widget_user(db_session: Session, widget_org: Organization) -> User:
    from app.models.user import User
    from app.services.auth_service import get_password_hash

    user = User(
        email='widget-test@example.com',
        hashed_password=get_password_hash('testpassword123'),
        full_name='Widget Tester',
        organization_id=widget_org.id,
        role='admin',
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def widget_auth(widget_user: User) -> dict[str, str]:
    from app.services.token_service import create_access_token

    token = create_access_token(data={'sub': str(widget_user.id)})
    return {'Authorization': f'Bearer {token}'}


@pytest.fixture
def widget_org_b(db_session: Session) -> Organization:
    from app.models.organization import Organization

    org = Organization(
        name='Widget Test Org B',
        enabled_modules=[
            'core',
            'items',
            'locations',
            'categories',
            'example_widgets',
        ],
    )
    db_session.add(org)
    db_session.commit()
    db_session.refresh(org)
    return org


@pytest.fixture
def widget_user_b(db_session: Session, widget_org_b: Organization) -> User:
    from app.models.user import User
    from app.services.auth_service import get_password_hash

    user = User(
        email='widget-test-b@example.com',
        hashed_password=get_password_hash('testpassword123'),
        full_name='Widget Tester B',
        organization_id=widget_org_b.id,
        role='admin',
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def widget_auth_b(widget_user_b: User) -> dict[str, str]:
    from app.services.token_service import create_access_token

    token = create_access_token(data={'sub': str(widget_user_b.id)})
    return {'Authorization': f'Bearer {token}'}

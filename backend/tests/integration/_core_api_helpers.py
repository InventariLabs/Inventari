"""
Shared test helpers for CoreAPI contract tests.

Avoids duplication of `_make_other_org`, `_make_template`, `_run` across
5 contract test files.  These helpers are NOT pytest fixtures because
they take parameters (e.g. db_session) that vary per call — fixtures
can't model that cleanly.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.core.contracts import UserContextDTO
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.user import User
from app.services.token_service import get_password_hash

if TYPE_CHECKING:
    pass


def run_async(coro):
    """Run an async coroutine from a sync test function.

    Note: each call creates a fresh event loop, which is fine for
    single-call async CoreAPI methods. For tests that need many async
    calls in sequence, prefer pytest-asyncio with @pytest.mark.asyncio.
    """
    return asyncio.run(coro)


def make_other_org(db_session: Session) -> Organization:
    """Create a second organization for org-scoping tests."""
    other = Organization(name='Other Org', enabled_modules=['core'])
    db_session.add(other)
    db_session.commit()
    db_session.refresh(other)
    return other


def make_user(
    db_session: Session,
    email: str,
    organization_id: UUID,
    *,
    role: str = 'user',
    is_active: bool = True,
) -> User:
    user = User(
        email=email,
        hashed_password=get_password_hash('testpassword123'),
        full_name=f'User {email}',
        organization_id=organization_id,
        role=role,
        is_active=is_active,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def make_user_context(org_id: UUID, user_id: UUID) -> UserContextDTO:
    return UserContextDTO(id=user_id, organization_id=org_id)


def make_template(
    db_session: Session,
    organization_id: UUID,
    *,
    name: str = 'Test Template',
    sku_prefix: str = 'SKU',
) -> ProductTemplate:
    template = ProductTemplate(
        organization_id=organization_id,
        name=name,
        sku=f'{sku_prefix}-{uuid4().hex[:8]}',
    )
    db_session.add(template)
    db_session.commit()
    db_session.refresh(template)
    return template


def make_valuation_template(
    db_session: Session,
    organization_id: UUID,
    *,
    name: str = 'Valuation Test',
) -> ProductTemplate:
    return make_template(
        db_session,
        organization_id,
        name=name,
        sku_prefix='SKU-VAL',
    )


def decimal(value: str | int | float) -> Decimal:
    """Convenience for Decimal(...) without explicit type."""
    return Decimal(str(value))

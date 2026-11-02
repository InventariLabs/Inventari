"""A read asks for the permission that names its data.

The roles editor and the API key dialog both offer "Read products and stock
levels", "Read locations", "Read the category list" and "Read the
organization's details" as things one can withhold, and the key screen says
the list a key was issued with is the whole of what it may do. The server
enforced none of the four on the reads themselves: the product, location and
member lists depended on organization membership alone. Measured before the
fix with a key issued holding only ``categories:read``: 200 on the products
(with their quantities), 200 on every location, 200 on every member's e-mail
and role — while the stock ledger, guarded with ``items:read``, refused the
same key with 403. A custom role without ``items:read`` read the products the
same way.

The guard is ``UserContextDTO.has_permission``, which keys and roles share,
so enforcing a permission for one enforces it for the other: a role that
withholds a read now loses that read, which is what the editor promised.

The class — every route of the application, read off the live route table —
is held in test_every_route_asks_for_a_permission.py. Here: the report's walk
with a real key, and the same walk with a custom role.
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.contracts import API_KEY_HEADER, SystemPermission
from app.models.organization import Organization
from app.models.role import Role, UserRole
from app.models.user import User
from app.services.auth_service import get_password_hash
from app.services.token_service import create_access_token

pytestmark = pytest.mark.integration

ITEMS = SystemPermission.ITEMS_READ.value
LOCATIONS = SystemPermission.STORAGES_READ.value
CATEGORIES = SystemPermission.CATEGORIES_READ.value
ORG = SystemPermission.ORG_READ.value


def _auth(user: User) -> dict:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


def _member(db: Session, org: Organization, role: str) -> User:
    user = User(
        email=f'reader_{uuid.uuid4().hex[:8]}@test.com',
        hashed_password=get_password_hash('pass'),
        organization_id=org.id,
        role=role,
        is_active=True,
    )
    db.add(user)
    db.commit()
    return user


@pytest.fixture
def admin(db_session: Session, test_household: Organization) -> User:
    test_household.enabled_modules = ['api_keys']
    db_session.commit()
    return _member(db_session, test_household, 'admin')


def _key(client: TestClient, admin: User, permissions: list[str]) -> dict:
    response = client.post(
        '/api/v1/api-keys',
        json={'name': f'probe-{uuid.uuid4().hex[:6]}', 'permissions': permissions},
        headers=_auth(admin),
    )
    assert response.status_code == 201, response.text
    return {API_KEY_HEADER: response.json()['raw_key']}


_LISTS = {
    ITEMS: '/api/v1/items',
    LOCATIONS: '/api/v1/locations',
    CATEGORIES: '/api/v1/categories',
    ORG: '/api/v1/organizations/my/members',
}


def _answers(client: TestClient, headers: dict) -> dict[str, int]:
    return {
        permission: client.get(url, headers=headers).status_code
        for permission, url in _LISTS.items()
    }


class TestAKeyReadsWhatItWasIssuedFor:
    def test_a_category_key_reads_the_categories_and_nothing_else(
        self, client: TestClient, admin: User
    ) -> None:
        answers = _answers(client, _key(client, admin, [CATEGORIES]))

        assert answers == {ITEMS: 403, LOCATIONS: 403, CATEGORIES: 200, ORG: 403}

    def test_a_key_holding_the_reads_reads_them(
        self, client: TestClient, admin: User
    ) -> None:
        answers = _answers(client, _key(client, admin, list(_LISTS)))

        assert set(answers.values()) == {200}, answers


class TestACustomRoleReadsWhatItGrants:
    def _with_role(
        self, db: Session, org: Organization, permissions: list[str]
    ) -> User:
        user = _member(db, org, 'user')
        role = Role(
            name=f'role_{uuid.uuid4().hex[:6]}',
            permissions=permissions,
            is_system=False,
            organization_id=org.id,
        )
        db.add(role)
        db.flush()
        db.add(UserRole(user_id=user.id, role_id=role.id))
        db.commit()
        return user

    def test_a_role_without_the_reads_is_refused_them(
        self, client: TestClient, db_session: Session, test_household: Organization
    ) -> None:
        operator = self._with_role(
            db_session, test_household, ['stock_takes:read', 'stock_takes:write']
        )

        answers = _answers(client, _auth(operator))

        assert set(answers.values()) == {403}, answers

    def test_a_role_holding_the_reads_reads_them(
        self, client: TestClient, db_session: Session, test_household: Organization
    ) -> None:
        reader = self._with_role(db_session, test_household, list(_LISTS))

        answers = _answers(client, _auth(reader))

        assert set(answers.values()) == {200}, answers

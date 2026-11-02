"""An API key is a machine's hands, not an administrator's.

The five AI-connection writes carry ``org:settings:write`` and, for a
person, refuse anyone without it. For a machine identity the gate was
transparent: the fixed permission set every key carries included that
permission, so a key described as "items, categories and storages, plus
reading the organization" could swap the organization's AI provider,
enter its own billing key, spend it on a real outbound request and
delete somebody else's connection. Measured before the fix, on all five
routes: 200 / 400 (behind the gate) / 400 (from the provider) / 200 /
200 — not one refusal.

Two tests, and they answer different questions. The first is the class:
every route in the application that asks for ``org:settings:write`` is
closed to a key, enumerated from the live route table so a route added
tomorrow is covered without anyone remembering this file. The second is
the report's own walk, end to end through HTTP with a real key.
"""

import uuid

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.contracts import API_KEY_PERMISSIONS, SystemPermission, UserContextDTO
from app.models.organization import Organization
from app.models.user import User
from app.services.auth_service import get_password_hash
from app.services.token_service import create_access_token

pytestmark = pytest.mark.integration

ADMIN_PERMISSION = SystemPermission.ORG_SETTINGS_WRITE
_GUARD_NAME = f'require_{ADMIN_PERMISSION.value.replace(":", "_")}'


def _auth(user: User) -> dict:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


@pytest.fixture
def admin(db_session: Session, test_household: Organization) -> User:
    user = User(
        email=f'key_admin_{uuid.uuid4().hex[:8]}@test.com',
        hashed_password=get_password_hash('pass'),
        organization_id=test_household.id,
        role='admin',
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def modules_on(db_session: Session, test_household: Organization) -> None:
    test_household.enabled_modules = ['api_keys']
    db_session.commit()


@pytest.fixture
def key(client: TestClient, admin: User, modules_on) -> str:
    response = client.post(
        '/api/v1/api-keys', json={'name': 'probe'}, headers=_auth(admin)
    )
    assert response.status_code == 201, response.text
    return response.json()['raw_key']


def _guarded_endpoints() -> list[str]:
    """Every endpoint the application closes with the administrative permission.

    Read off the live route table rather than listed by hand: the point of
    the rule is that a route added later inherits it, and a hand-written
    list is exactly what stops inheriting. Routers hang under FastAPI's
    lazy ``_IncludedRouter`` nodes, whose ``original_router`` carries the
    endpoints without their mount prefix — so an endpoint is named by the
    module and function that answer it, which is what a reader needs
    anyway.
    """
    from app.main import app

    def routes(nodes) -> list[APIRoute]:
        found: list[APIRoute] = []
        for node in nodes:
            if isinstance(node, APIRoute):
                found.append(node)
                continue
            nested = (
                getattr(getattr(node, 'original_router', None), 'routes', None)
                or getattr(node, 'routes', None)
                or getattr(getattr(node, 'app', None), 'routes', None)
            )
            if nested:
                found.extend(routes(nested))
        return found

    guarded = []
    for route in routes(app.routes):
        pending = list(route.dependant.dependencies)
        while pending:
            dependency = pending.pop()
            call = getattr(dependency, 'call', None)
            if getattr(call, '__name__', '') == _GUARD_NAME:
                guarded.append(f'{route.endpoint.__module__}.{route.endpoint.__name__}')
                break
            pending.extend(dependency.dependencies)
    return sorted(guarded)


class TestTheAdministrativePermissionIsNotAKeys:
    def test_the_permission_guards_real_routes(self, client: TestClient) -> None:
        # A guard nobody uses would make the rule below vacuously true.
        guarded = _guarded_endpoints()
        assert guarded, 'no endpoint asks for the administrative permission'
        ai = [name for name in guarded if name.startswith('app.api.ai_connections.')]
        assert len(ai) == 5, ai

    def test_a_key_satisfies_none_of_them(self, client: TestClient) -> None:
        context = UserContextDTO(
            id=uuid.uuid4(),
            organization_id=uuid.uuid4(),
            organization=None,
            role='api_key',
            email='machine@example.com',
            permissions=set(API_KEY_PERMISSIONS),
            extra_permissions=set(),
        )

        assert not context.has_permission(ADMIN_PERMISSION), (
            f'a key still opens every administrative door: {_guarded_endpoints()}'
        )


class TestTheFiveAiConnectionWrites:
    """The report's own walk, with a real key over HTTP."""

    def _connection_id(self, client: TestClient, admin: User) -> str:
        response = client.post(
            '/api/v1/ai-connections',
            json={
                'name': f'conn-{uuid.uuid4().hex[:6]}',
                'provider': 'openai',
                'model': 'gpt-4o-mini',
                'api_key': 'sk-probe',
                'api_base_url': 'https://api.openai.com/v1',
            },
            headers=_auth(admin),
        )
        assert response.status_code == 200, response.text
        return response.json()['id']

    def test_every_write_refuses_the_key(
        self, client: TestClient, admin: User, key: str, modules_on
    ) -> None:
        conn_id = self._connection_id(client, admin)
        machine = {'Authorization': f'Bearer {key}'}
        base = '/api/v1/ai-connections'

        answers = {
            'POST /': client.post(
                base,
                json={
                    'name': 'from-a-machine',
                    'provider': 'openai',
                    'model': 'gpt-4o-mini',
                    'api_key': 'sk-machine',
                    'api_base_url': 'https://api.openai.com/v1',
                },
                headers=machine,
            ).status_code,
            'PUT /bindings': client.put(
                f'{base}/bindings',
                json={'purpose_key': 'vision', 'connection_id': conn_id},
                headers=machine,
            ).status_code,
            'POST /test': client.post(
                f'{base}/test', json={'connection_id': conn_id}, headers=machine
            ).status_code,
            'PUT /{id}': client.put(
                f'{base}/{conn_id}', json={'name': 'renamed'}, headers=machine
            ).status_code,
            'DELETE /{id}': client.delete(
                f'{base}/{conn_id}', headers=machine
            ).status_code,
        }

        assert set(answers.values()) == {403}, answers

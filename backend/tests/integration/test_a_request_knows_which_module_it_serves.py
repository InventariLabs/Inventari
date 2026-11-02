"""A request is served under the identity of the module whose router it hits.

``ModuleIdentityMiddleware`` reads the ``/api/v1/<segment>`` the path
mounts and asks the registry whether a module answers to that name — a
core route looks the same to a string split, but no module own it, and
the core speaks for everyone. This is the boundary that makes
``require_permission`` and the settings/secrets/scheduler refusals see a
module's identity on a real HTTP request, so it is pinned against the
real app rather than a stub.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


def _probe_route(prefix: str):
    from fastapi import APIRouter

    from app.core.module_identity import current_module

    probe = APIRouter()

    @probe.get('/_module_identity_probe')
    async def probe_identity():
        return {'module': current_module()}

    from app.main import app

    app.include_router(probe, prefix='/api/v1' + prefix)
    # First in line: a module's own `/{id}` route would otherwise answer it.
    app.router.routes.insert(0, app.router.routes.pop())
    return app, '/api/v1' + prefix + '/_module_identity_probe'


def _remove_probe(app, path: str) -> None:
    app.router.routes[:] = [
        route for route in app.router.routes if getattr(route, 'path', '') != path
    ]


def test_a_modules_route_runs_under_the_modules_identity(client):
    app, path = _probe_route('/webhooks')
    try:
        response = client.get(path)
    finally:
        _remove_probe(app, path)

    assert response.status_code == 200, response.text
    assert response.json() == {'module': 'webhooks'}


def test_a_core_route_runs_without_an_identity(client):
    app, path = _probe_route('/labels')
    try:
        response = client.get(path)
    finally:
        _remove_probe(app, path)

    assert response.status_code == 200
    assert response.json() == {'module': None}


def test_the_warehouse_route_runs_under_the_warehouses_identity(client):
    """The module answers under its own name and keeps its identity there.

    Its key and its REST prefix changed before the first release, and this
    is the boundary that makes the settings, secret and scheduler refusals
    see ``warehouse`` on a real request instead of core's empty identity.
    """
    app, path = _probe_route('/warehouse')
    try:
        response = client.get(path)
    finally:
        _remove_probe(app, path)

    assert response.status_code == 200, response.text
    assert response.json() == {'module': 'warehouse'}


def test_the_warehouse_routes_answer_only_at_their_own_address(client):
    # Unauthenticated on purpose: a route that exists asks who is calling,
    # one that does not is simply not found.
    assert client.get('/api/v1/warehouse/profile').status_code == 401
    assert client.get('/api/v1/documents/profile').status_code == 404

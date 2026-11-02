"""A key scope admits the endpoints that guard its permissions, by no path.

A scope used to be a list of URL prefixes, so renaming a route silently
changed what a scoped key could reach. It is a list of permissions now: the
route is read for what it guards, wherever it lives.
"""

from collections.abc import Iterator

import pytest
from fastapi import APIRouter

from app.core import api_key_auth
from app.core.api_key_auth import api_key_scopes_admit, register_api_key_scope
from app.core.deps import require_permission, require_read_write


@pytest.fixture(autouse=True)
def _scope() -> Iterator[None]:
    saved = dict(api_key_auth._scopes)
    register_api_key_scope('lamp', ('lamp:switch',))
    yield
    api_key_auth._scopes.clear()
    api_key_auth._scopes.update(saved)


def _route(path: str, *dependencies: object) -> object:
    router = APIRouter(dependencies=list(dependencies))

    @router.post(path)
    async def endpoint() -> None:
        return None

    return router.routes[0]


class TestAScopeBoundToPermissions:
    def test_a_route_guarding_the_permission_admits_wherever_it_lives(self) -> None:
        route = _route('/renamed/anywhere', require_permission('lamp:switch'))

        assert api_key_scopes_admit(['lamp'], route)

    def test_a_route_guarding_nothing_refuses_whatever_its_path(self) -> None:
        assert not api_key_scopes_admit(['lamp'], _route('/lamp/switch'))

    def test_a_route_guarding_another_permission_refuses(self) -> None:
        route = _route('/lamp/switch', require_permission('items:read'))

        assert not api_key_scopes_admit(['lamp'], route)

    def test_a_read_write_guard_counts_both_of_its_permissions(self) -> None:
        route = _route('/lamps', require_read_write('lamp:read', 'lamp:switch'))

        assert api_key_scopes_admit(['lamp'], route)

    def test_a_scope_nobody_registered_admits_nothing(self) -> None:
        route = _route('/lamp/switch', require_permission('lamp:switch'))

        assert not api_key_scopes_admit(['garden'], route)

    def test_no_route_resolved_admits_nothing(self) -> None:
        assert not api_key_scopes_admit(['lamp'], None)

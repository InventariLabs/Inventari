"""A module's own request handler is refused when it names another module.

The refusals are proven where they live — against the real registry in
``test_one_module_cannot_call_another`` and ``test_module_identity`` — and
the HTTP identity binding in ``test_a_request_knows_which_module_it_serves``.
This one composes the two on a fixture of two modules: a loaded module the
repository does not ship (``shelf_notes``) whose handler runs inside a live
request, and a loaded module it names (``warehouse``). The identity the
middleware bound is the one ``core_api.settings`` and ``core_api.scheduler``
see, so the foreign name is refused there. The same handler naming its own
module, and one under a core prefix that runs without any identity, reach
the APIs.
"""

from __future__ import annotations

import pytest
from fastapi import APIRouter

from app.core.module_identity import current_module
from app.core.modules import BaseModule, ModuleMetadata
from app.core.public_api import core_api

pytestmark = pytest.mark.integration

PATH = '/_module_naming_probe'
REACHED = 'reached the API'


class _ShelfNotes(BaseModule):
    @property
    def metadata(self) -> ModuleMetadata:
        return ModuleMetadata(
            name='shelf_notes',
            version='1.0.0',
            display_name='Shelf notes',
            description='',
            icon='box',
        )

    def register_routes(self) -> APIRouter:
        return APIRouter()


@pytest.fixture
def probe_mounted():
    """Mount a handler under a prefix; it calls the core APIs naming ``?module=``."""
    from app.core.module_registry import module_registry
    from app.main import app

    probe = APIRouter()

    @probe.get(PATH)
    async def name_a_module(module: str):
        outcome: dict[str, object] = {'identity': current_module()}
        calls = {
            'settings': lambda: core_api.settings.encrypt_secret(module, 'value'),
            'scheduler': lambda: core_api.scheduler.unregister_task(
                'no_such_job', module_name=module
            ),
        }
        for api, call in calls.items():
            try:
                call()
                outcome[api] = REACHED
            except PermissionError as refusal:
                outcome[api] = str(refusal)
        return outcome

    mounted: list[str] = []

    def mount(prefix: str) -> str:
        app.include_router(probe, prefix='/api/v1' + prefix)
        # First in line: a module's own `/{id}` route would answer it.
        app.router.routes.insert(0, app.router.routes.pop())
        mounted.append('/api/v1' + prefix + PATH)
        return mounted[-1]

    module_registry.register(_ShelfNotes())
    yield mount
    module_registry._modules.pop('shelf_notes', None)
    app.router.routes[:] = [
        route
        for route in app.router.routes
        if getattr(route, 'path', '') not in mounted
    ]


def _call(client, mount, prefix: str, module: str) -> dict:
    response = client.get(mount(prefix), params={'module': module})
    assert response.status_code == 200, response.text
    return response.json()


def test_a_module_route_naming_another_module_is_refused_by_both_apis(
    client, probe_mounted
):
    outcome = _call(client, probe_mounted, '/shelf-notes', 'warehouse')

    assert outcome['identity'] == 'shelf_notes'
    for api in ('settings', 'scheduler'):
        refusal = outcome[api]
        assert refusal != REACHED, f'core_api.{api} let a foreign name through'
        assert 'shelf_notes' in refusal
        assert 'warehouse' in refusal


def test_a_module_route_naming_itself_reaches_the_apis(client, probe_mounted):
    outcome = _call(client, probe_mounted, '/shelf-notes', 'shelf_notes')

    assert outcome['identity'] == 'shelf_notes'
    assert outcome['settings'] == REACHED
    assert outcome['scheduler'] == REACHED


def test_a_core_route_naming_a_module_reaches_the_apis(client, probe_mounted):
    outcome = _call(client, probe_mounted, '/labels', 'warehouse')

    assert outcome['identity'] is None
    assert outcome['settings'] == REACHED
    assert outcome['scheduler'] == REACHED

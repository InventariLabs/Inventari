"""Every route of the assembled application asks for a permission.

Each permission hole found so far was one route that forgot its guard, and
each was closed one route at a time: the product, location and member lists
answered a key holding only "Read the category list"; three webhook and API
key reads answered any member; the purchase-order approval threshold took a
member's write. A walk through the screens finds the routes it happens to
step on. This file reads the route table instead — core and every module, as
the application mounts them — so a route added tomorrow without a guard fails
here, whichever module adds it.

The rule. A route guards a permission (``require_permission``,
``require_any_permission`` or ``require_read_write``, which mark themselves
for this walk), or is closed to everyone but administrators, or is named in
``_OPEN`` with the reason it has none. A read asks for a read: a route that
serves data — a ``GET``, a WebSocket — has a guard that only a ``:read``
permission passes, because the grant to change something is not the grant to
see it; the few that answer to another grant (an administrator's screen, the
print agent, a workflow's editor) are named in ``_READ_BEHIND_ANOTHER_GRANT``
with why. Both lists name a method and a path, not the function behind them:
the same handler mounted at a second path is a second route and needs its
own reason. A write to a ``settings`` resource asks for more than the
module's plain write, because a setting decides for everyone in the
organization.

A guard is read for every way through it. ``require_any_permission`` admits
the holder of any one of its permissions, so a read guarded by "read or
write" opens to the write alone, and a setting guarded by "configure or
write" to the plain write: the rule holds when one guard of the route admits
nobody but the permission it asks for.
"""

from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from operator import attrgetter

import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.routing import APIRoute, APIWebSocketRoute

from app.core.api_key_auth import GUARDED_PERMISSIONS_ATTR
from app.core.contracts import SystemPermission
from app.core.deps import (
    get_current_user_context,
    require_any_permission,
    require_permission,
    require_read_write,
)
from app.main import app, health_check

pytestmark = pytest.mark.integration

ITEMS = SystemPermission.ITEMS_READ.value
LOCATIONS = SystemPermission.STORAGES_READ.value
CATEGORIES = SystemPermission.CATEGORIES_READ.value
ORG = SystemPermission.ORG_READ.value

#: Dependencies that let only an administrator or a superuser through: a
#: route behind one of them is closed to a key and to an ordinary member.
_ROLE_GATES = frozenset({'get_current_admin_user', 'get_superuser'})

#: Routes that ask for no permission on purpose, each with the reason. Keyed
#: by methods and path as the application serves them and a failure prints
#: them.
_OPEN = {
    # Before sign-in: the probes, the root, the API documentation (absent in
    # production), and what a visitor needs to get an account or back in.
    'GET /api/': 'unauthenticated index',
    'GET /health': 'liveness probe',
    'GET /': 'liveness probe',
    'GET /health/ready': 'readiness probe',
    'GET,HEAD /openapi.json': 'API documentation, not served in production',
    'GET,HEAD /docs': 'API documentation',
    'GET,HEAD /docs/oauth2-redirect': 'API documentation',
    'GET,HEAD /redoc': 'API documentation',
    'GET /api/v1/auth/init-status': 'asked before any account exists',
    'POST /api/v1/auth/register': 'creates the first account',
    'POST /api/v1/auth/registration-request': 'before sign-in',
    'GET /api/v1/auth/registration-link/{token}': 'before sign-in',
    'POST /api/v1/auth/register-complete': 'before sign-in',
    'POST /api/v1/auth/login': 'signing in',
    'POST /api/v1/auth/refresh': 'the session renewing itself',
    'POST /api/v1/auth/logout': "ending the caller's own session",
    'POST /api/v1/auth/password-reset/request': 'before sign-in',
    'POST /api/v1/auth/password-reset/check': 'before sign-in',
    'POST /api/v1/auth/password-reset/confirm': 'before sign-in',
    'GET /public/invitation/{code}': 'asked before sign-in',
    'POST /api/v1/auth/password-reset/_dev_token': 'only under TESTING, for E2E',
    'POST /api/v1/demo/sandbox': 'a demo visitor opening their own sandbox',
    # The equipment attestation page: the holder confirms from an e-mailed
    # link; the token in the path is the authority.
    'GET /public/attestation/{token}': 'the token is the authority',
    'POST /public/attestation/{token}/confirm': 'the token is the authority',
    'POST /public/attestation/{token}/dispute': 'the token is the authority',
    # About the caller alone: their account, notifications and membership.
    'GET /api/v1/auth/me': "the caller's own account",
    'PATCH /api/v1/auth/me': "the caller's own account",
    'POST /api/v1/auth/me/language': "the caller's own account",
    'GET /api/v1/notifications': "the caller's own notifications",
    'PATCH /api/v1/notifications/{notification_id}': "the caller's own notifications",
    'POST /api/v1/notifications/read-all': "the caller's own notifications",
    'DELETE /api/v1/notifications/{notification_id}': "the caller's own notifications",
    'WEBSOCKET /api/v1/ws/notifications': "the caller's own notifications",
    'POST /api/v1/organizations': 'a user without one founds it',
    'POST /api/v1/organizations/join': 'a user without one joins by code',
    'POST /api/v1/organizations/my/leave': "the caller's own membership",
    # Owed to every user.
    'GET /api/v1/about': 'the licence and source link (AGPL-3.0 §13)',
    'GET /api/v1/announcements/active': 'notices addressed to everyone',
    # The shell every screen stands on: which modules are on, the focus mode,
    # the organization's name and profile. A role without "Read the
    # organization's details" still has to load the app; that permission is
    # the team list.
    'GET /api/v1/organizations/my': 'the shell reads it on every screen',
    'GET /api/v1/modules/available': 'the shell reads it on every screen',
    'GET /api/v1/modules/my': 'the shell reads it on every screen',
    'GET /api/v1/modules/focus': 'the shell reads it on every screen',
    # Reference catalogues no permission names.
    'GET /api/v1/profiles': 'installation-wide catalogue of profiles',
    'GET /api/v1/profiles/{profile_id}': 'installation-wide catalogue of profiles',
    'GET /api/v1/uoms': 'units of measure, reference data',
    'GET /api/v1/uoms/categories': 'units of measure, reference data',
    # Only the writes are administration: every AI feature reads the
    # connection it runs on (frontend/src/components/settingsAccess.ts).
    'GET /api/v1/ai-connections': 'every AI feature reads it',
    'GET /api/v1/ai-connections/{conn_id}': 'every AI feature reads it',
    'GET /api/v1/ai-connections/purposes': 'every AI feature reads it',
    # A file is reached by the path an answer handed out; the read that
    # handed it out is the one that asks.
    'GET /uploads/{filepath:path}': 'reached by a path a guarded read gave',
    # Approvals decides per request, not per route: a member sees the
    # requests they raised and the ones waiting on their decision, the
    # organization's whole traffic is ``approvals:read``. The order and
    # document screens read these for every role that sees an order, so a
    # role without an approvals grant gets the empty answer, not a refusal.
    'GET /api/v1/approvals/workflows': 'empty without approvals:read or :configure',
    'GET /api/v1/approvals/workflows/configured': 'one bit, read before a request',
    'GET /api/v1/approvals/requests': 'own requests and those awaiting the caller',
    'GET /api/v1/approvals/requests/{request_id}': 'own or awaiting the caller',
    'POST /api/v1/approvals/requests/{request_id}/approve': 'approve grant or named',
    'POST /api/v1/approvals/requests/{request_id}/reject': 'approve grant or named',
    'POST /api/v1/approvals/requests/{request_id}/cancel': 'the requester withdraws it',
}

#: Reads that answer to a grant other than a read, each with why that grant
#: is the one the screen asking for it implies. Keyed like ``_OPEN``.
_READ_BEHIND_ANOTHER_GRANT = {
    # An administrator's screen: its reads ask for the grant the screen
    # itself is behind (frontend/src/components/settingsAccess.ts and the
    # API keys module's own screen entry).
    'GET /api/v1/api-keys': 'the API keys screen is org:settings:write',
    'GET /api/v1/api-keys/capabilities': 'the API keys screen is org:settings:write',
    'GET /api/v1/roles': 'the roles editor is system:config:write',
    'GET /api/v1/roles/permission-catalog': (
        'the roles editor is system:config:write; the audit log, admin:access'
    ),
    'GET /api/v1/roles/{role_id}/members': 'the roles editor is system:config:write',
    # The answer to a change the caller made or is about to make.
    'GET /api/v1/items/import/jobs/{job_id}': 'how far an items:write import got',
    'GET /api/v1/approvals/workflows/{workflow_id}/waiting': (
        'what switching a workflow off would release, asked by its editor'
    ),
    'GET /api/v1/approvals/workflows/{workflow_id}': (
        'approvals:read or the editor configuring it, as the workflow list'
    ),
    # A machine's credential, not a person's.
    'GET /api/v1/printing/agent/jobs/{job_id}/image': 'the agent fetching its label',
}

_EXEMPT = {**_OPEN, **_READ_BEHIND_ANOTHER_GRANT}

#: The data the key dialog and the roles editor name, and the reads that
#: serve it. Each must ask for exactly that permission.
_NAMED = {
    'app.api.items.get_items': ITEMS,
    'app.api._items_queries.get_items_aggregates_endpoint': ITEMS,
    'app.api._items_queries.get_attention_counts_endpoint': ITEMS,
    'app.api._items_queries.get_expiring_items': ITEMS,
    'app.api._items_import_export.export_items_xlsx': ITEMS,
    'app.api.item_pagination.get_items_history': ITEMS,
    'app.api.item_pagination.get_item_history': ITEMS,
    'app.api.item_pagination.get_items_cursor_page': ITEMS,
    'app.api._items_product_templates.search_product_templates': ITEMS,
    'app.api._items_product_templates.count_product_templates': ITEMS,
    'app.api._items_product_templates.lookup_product_template': ITEMS,
    'app.api._items_product_templates.get_sku_schema': ITEMS,
    'app.api._items_product_templates.get_product_template': ITEMS,
    'app.api._items_product_templates.get_product_template_stock': ITEMS,
    'app.api.attachments.list_item_attachments': ITEMS,
    'app.api.labels.get_label_pool': ITEMS,
    'app.api.labels.get_label_stats': ITEMS,
    'app.api.labels.scan_label': ITEMS,
    'app.api.storages._reads.list_archived_storages': LOCATIONS,
    'app.api.storages._reads.print_storage_label': LOCATIONS,
    'app.api.storages._reads.get_storage_summary': LOCATIONS,
    'app.api.storages._reads.get_storage_tree': LOCATIONS,
    'app.api.storage_types.get_storage_types': LOCATIONS,
    'app.api.storage_types.get_storage_type': LOCATIONS,
    'app.api.categories.get_category': CATEGORIES,
    'app.api.organizations.get_organization_members': ORG,
    'app.api.users.list_org_members': ORG,
}

#: Named Core reads a module's own screens also make, and the module read that
#: opens the screen. The Core key still guards the data — a caller holding
#: neither gets 403 — and the module read joins it on that one route, because
#: the screen that shows the data is the only way its holder reaches it. The
#: value names every read the guard admits, so a new alternative is a change
#: reviewed here and not a quiet widening.
_NAMED_ALSO_READ_BY_A_MODULE_READ: dict[str, tuple[str, frozenset[str]]] = {
    # The equipment register's Archive tab.
    'app.api._items_queries.get_archived_items': (ITEMS, frozenset({'equipment:read'})),
    # The equipment register's asset card, linked from the list and from
    # assignment history.
    'app.api._items_crud.get_item': (ITEMS, frozenset({'equipment:read'})),
    # The equipment register's Print labels download.
    'app.api.labels.export_labels_png': (ITEMS, frozenset({'equipment:read'})),
    # The warehouse's codes page finds and lists its shelves; the equipment
    # register names the place every asset stands in and opens one to edit.
    'app.api.storages._reads.get_storages': (
        LOCATIONS,
        frozenset({'equipment:read', 'warehouse:read'}),
    ),
    'app.api.storages._reads.get_storage_detail': (
        LOCATIONS,
        frozenset({'equipment:read', 'warehouse:read'}),
    ),
    # The warehouse's path through a branch, its codes card and a shelf's
    # contents.
    'app.api.storages._reads.get_storage_breadcrumb': (
        LOCATIONS,
        frozenset({'warehouse:read'}),
    ),
    'app.api.storages._reads.get_storage_codes': (
        LOCATIONS,
        frozenset({'warehouse:read'}),
    ),
    'app.api.storages._reads.get_storage_items': (
        LOCATIONS,
        frozenset({'warehouse:read'}),
    ),
    # The equipment register's category names and filters; the warehouse's
    # putaway rules and product pickers.
    'app.api.categories.get_categories': (
        CATEGORIES,
        frozenset({'equipment:read', 'warehouse:read'}),
    ),
}

_SAFE = frozenset({'GET', 'HEAD', 'OPTIONS'})

#: What serves data back: a page, a list, a stream.
_READS = frozenset({'GET', 'HEAD', 'WEBSOCKET'})


def _is_read(permission: str) -> bool:
    return permission.rpartition(':')[2] == 'read'


def _above_plain_write(permission: str) -> bool:
    return (
        permission == SystemPermission.ORG_SETTINGS_WRITE.value
        or permission.rpartition(':')[2] not in {'read', 'write'}
    )


@dataclass(frozen=True)
class Route:
    methods: frozenset[str]
    path: str
    name: str
    #: The route's guards, each as the permissions it accepts: a caller
    #: passes every guard by holding one permission of each.
    guards: frozenset[frozenset[str]]
    dependencies: frozenset[str]

    @property
    def key(self) -> str:
        return f'{",".join(sorted(self.methods))} {self.path}'

    @property
    def guarded(self) -> list[str]:
        """The guards as a failure prints them: alternatives joined by ``|``."""
        return sorted('|'.join(sorted(guard)) for guard in self.guards)

    def requires(self, admits: Callable[[str], bool]) -> bool:
        """Whether one guard lets through only permissions ``admits`` accepts."""
        return any(all(map(admits, guard)) for guard in self.guards)

    @property
    def writes(self) -> bool:
        return bool(self.methods - _SAFE)

    @property
    def admin_only(self) -> bool:
        return bool(self.dependencies & _ROLE_GATES)

    @property
    def open(self) -> bool:
        return not self.guards and not self.admin_only

    @property
    def read_behind_another_grant(self) -> bool:
        """A read that a grant other than a read opens: a write's, a configure's."""
        return (
            bool(self.methods & _READS)
            and bool(self.guards)
            and not self.admin_only
            and not self.requires(_is_read)
        )


def _dependency_names(dependant) -> set[str]:
    names = set()
    for dependency in dependant.dependencies:
        names.add(getattr(dependency.call, '__name__', ''))
        names |= _dependency_names(dependency)
    return names


def _guards(dependant, reads: bool) -> set[frozenset[str]]:
    """The permission guards of a route, each as the permissions it accepts.

    A guard marks the permissions it checks. ``require_read_write`` marks its
    read and its write, but admits neither as an alternative: the request's
    method picks one.
    """
    found = set()
    for dependency in dependant.dependencies:
        marked = tuple(getattr(dependency.call, GUARDED_PERMISSIONS_ATTR, ()))
        factory = getattr(dependency.call, '__qualname__', '').partition('.')[0]
        if factory == require_read_write.__name__:
            marked = marked[:1] if reads else marked[1:]
        if marked:
            found.add(frozenset(marked))
        found |= _guards(dependency, reads)
    return found


def _route(methods, path, endpoint, dependant) -> Route:
    methods = frozenset(methods or {'WEBSOCKET'})
    reads = not (methods - _SAFE - {'WEBSOCKET'}) or getattr(
        endpoint, '__read_only_post__', False
    )
    return Route(
        methods=methods,
        path=path,
        name=f'{endpoint.__module__}.{endpoint.__name__}',
        guards=frozenset(_guards(dependant, reads) if dependant else ()),
        dependencies=frozenset(_dependency_names(dependant) if dependant else ()),
    )


def route_table(nodes: Iterable) -> Iterator[Route]:
    """Every route of an application, mounted or nested, as it is served.

    FastAPI keeps an included router — core's and every module's — behind a
    lazy node whose ``effective_route_contexts`` yields its routes with the
    mount applied. A WebSocket route comes out of it built whole as the
    context's ``starlette_route``: its path and its dependencies are there,
    not on the context.
    """
    for node in nodes:
        if isinstance(node, APIRoute):
            yield _route(node.methods, node.path, node.endpoint, node.dependant)
        elif hasattr(node, 'effective_route_contexts'):
            for c in node.effective_route_contexts():
                if c.starlette_route is not None:
                    yield from route_table([c.starlette_route])
                else:
                    endpoint = c.endpoint or c.original_route.endpoint
                    yield _route(c.methods, c.path, endpoint, c.dependant)
        elif isinstance(node, APIWebSocketRoute):
            yield _route(None, node.path, node.endpoint, node.dependant)
        else:
            yield _route(node.methods, node.path, node.endpoint, None)


def _app_routes() -> list[Route]:
    # A test may mount a probe on the live application for its own run;
    # that route is the test's, not the application's.
    return [r for r in route_table(app.routes) if not r.name.startswith('tests.')]


def unguarded(routes: Iterable[Route], exempt: Iterable[str]) -> list[str]:
    """Routes that ask for no permission, and reads that ask for no read."""
    exempt = set(exempt)
    return sorted(
        f'{r.key} {r.guarded} ({r.name})'
        for r in routes
        if (r.open or r.read_behind_another_grant) and r.key not in exempt
    )


def _above_write(route: Route) -> bool:
    """Whether the route asks for more than a module's plain read or write."""
    return route.admin_only or route.requires(_above_plain_write)


def loose_settings(routes: Iterable[Route]) -> list[str]:
    """Writes to a ``settings`` resource that ask for no more than plain write."""
    return sorted(
        f'{r.key} {r.guarded}'
        for r in routes
        if r.writes and 'settings' in r.path.split('/') and not _above_write(r)
    )


def misnamed(routes: Iterable[Route], named: dict[str, str]) -> dict[str, object]:
    """Named reads that do not ask for the permission they are named with."""
    served: dict[str, Route] = {}
    for route in routes:
        served.setdefault(route.name, route)
    return {
        name: served[name].guarded if name in served else 'route gone'
        for name, permission in named.items()
        if name not in served or not served[name].requires(permission.__eq__)
    }


def misnamed_beside_a_module_read(
    routes: Iterable[Route], named: dict[str, tuple[str, frozenset[str]]]
) -> dict[str, object]:
    """Named reads whose guard does not admit exactly the reads it names.

    The Core key has to be on the guard — a route left to a module read alone
    would answer a role the key catalogue never promised the data to — and
    every other permission on that guard has to be one the entry names.
    """
    served: dict[str, Route] = {}
    for route in routes:
        served.setdefault(route.name, route)
    wrong: dict[str, object] = {}
    for name, (core, module_reads) in named.items():
        route = served.get(name)
        allowed = {core} | module_reads
        if route is None:
            wrong[name] = 'route gone'
        elif not any(core in guard and guard <= allowed for guard in route.guards):
            wrong[name] = route.guarded
    return wrong


class TestEveryRouteAsksForAPermission:
    def test_no_route_goes_without_its_guard_unless_named(self) -> None:
        assert not unguarded(_app_routes(), _EXEMPT), (
            'routes that ask for no permission, or reads that ask for no read: '
            'guard each with the one its screen implies, or say in _OPEN or '
            '_READ_BEHIND_ANOTHER_GRANT why it has none'
        )

    def test_every_exemption_still_exists_and_still_needs_one(self) -> None:
        served: dict[str, list[Route]] = {}
        for route in _app_routes():
            served.setdefault(route.key, []).append(route)

        stale = sorted(
            key
            for exempt, still_needs_it in (
                (_OPEN, attrgetter('open')),
                (_READ_BEHIND_ANOTHER_GRANT, attrgetter('read_behind_another_grant')),
            )
            for key in exempt
            if key not in served or not all(map(still_needs_it, served[key]))
        )

        assert not stale, stale

    def test_the_named_data_asks_for_its_own_permission(self) -> None:
        wrong = misnamed(_app_routes(), _NAMED)

        assert not wrong, wrong

    def test_a_named_read_admits_the_module_read_of_the_screen_that_shows_it(
        self,
    ) -> None:
        wrong = misnamed_beside_a_module_read(
            _app_routes(), _NAMED_ALSO_READ_BY_A_MODULE_READ
        )

        assert not wrong, wrong

    def test_a_settings_write_asks_for_more_than_write(self) -> None:
        """A setting decides for the whole organization, not for one record.

        The purchase-order approval threshold answered to the module's plain
        write, so a buyer could lift the control meant to stop their own
        orders.
        """
        loose = loose_settings(_app_routes())

        assert not loose, loose


class TestTheGateWalksAMountedModule:
    """A community module is mounted by the same ``include_router`` as a shipped
    one, so its routes are in the table this file reads; shown on a router of
    its own, mounted the way the module registry mounts one."""

    def _mounted(self) -> list[Route]:
        module = APIRouter()

        @module.get('/open')
        async def forgot_its_guard(_=Depends(get_current_user_context)) -> None:
            return None

        @module.get('/guarded', dependencies=[require_permission('noticeboard:read')])
        async def guarded() -> None:
            return None

        @module.get('/posts', dependencies=[require_permission('noticeboard:write')])
        async def read_behind_a_write() -> None:
            return None

        @module.post('/posts', dependencies=[require_permission('noticeboard:write')])
        async def write() -> None:
            return None

        # A guard of alternatives admits a caller holding any one of them.
        @module.get(
            '/either',
            dependencies=[
                require_any_permission('noticeboard:read', 'noticeboard:write')
            ],
        )
        async def read_or_write() -> None:
            return None

        @module.get(
            '/shared',
            dependencies=[require_any_permission('noticeboard:read', 'items:read')],
        )
        async def one_read_or_another() -> None:
            return None

        @module.put(
            '/settings',
            dependencies=[
                require_any_permission('noticeboard:configure', 'noticeboard:write')
            ],
        )
        async def settings_or_write() -> None:
            return None

        @module.patch(
            '/settings', dependencies=[require_permission('noticeboard:configure')]
        )
        async def settings_configured() -> None:
            return None

        # The router-wide pair is not a choice: the method picks one of them.
        board = APIRouter(
            dependencies=[require_read_write('noticeboard:read', 'noticeboard:write')]
        )

        @board.get('')
        async def board_read() -> None:
            return None

        @board.put('/settings')
        async def board_settings() -> None:
            return None

        module.include_router(board, prefix='/board')

        # A handler the application exempts, mounted again under the module.
        module.add_api_route('/alias', health_check)

        @module.websocket('/live')
        async def stream(_=Depends(get_current_user_context)) -> None:
            return None

        api = APIRouter()
        api.include_router(module, prefix='/noticeboard')
        mounted = FastAPI()
        mounted.include_router(api, prefix='/api/v1')
        return [
            r
            for r in route_table(mounted.routes)
            if r.path.startswith('/api/v1/noticeboard')
        ]

    def test_an_unguarded_module_route_fails_the_gate(self) -> None:
        failures = unguarded(self._mounted(), _EXEMPT)
        forgot = f'GET /api/v1/noticeboard/open [] ({__name__}.forgot_its_guard)'

        assert forgot in failures
        assert not [f for f in failures if '/noticeboard/guarded' in f]
        assert not [f for f in failures if 'POST /api/v1/noticeboard/posts' in f]

    def test_a_read_behind_a_write_alone_fails_the_gate(self) -> None:
        """A grant to change the data is not the grant to read it."""
        failures = unguarded(self._mounted(), _EXEMPT)

        assert (
            "GET /api/v1/noticeboard/posts ['noticeboard:write'] "
            f'({__name__}.read_behind_a_write)'
        ) in failures

    def test_an_exempt_handler_at_a_new_path_needs_its_own_reason(self) -> None:
        """An exemption names a method and a path, not the function behind them."""
        failures = unguarded(self._mounted(), _EXEMPT)

        assert 'GET /api/v1/noticeboard/alias [] (app.main.health_check)' in failures

    def test_a_websocket_is_walked_at_the_path_it_is_served_on(self) -> None:
        failures = unguarded(self._mounted(), _EXEMPT)

        assert f'WEBSOCKET /api/v1/noticeboard/live [] ({__name__}.stream)' in failures

    def test_a_read_that_a_write_alone_also_opens_fails_the_gate(self) -> None:
        """Every way through a guard counts: a write among a read's alternatives
        lets the holder of the write alone read."""
        failures = unguarded(self._mounted(), _EXEMPT)

        assert (
            "GET /api/v1/noticeboard/either ['noticeboard:read|noticeboard:write'] "
            f'({__name__}.read_or_write)'
        ) in failures
        assert not [f for f in failures if '/noticeboard/shared' in f]
        assert not [f for f in failures if 'GET /api/v1/noticeboard/board ' in f]

    def test_a_setting_that_a_plain_write_also_opens_fails_the_gate(self) -> None:
        loose = loose_settings(self._mounted())

        assert loose == [
            "PUT /api/v1/noticeboard/board/settings ['noticeboard:write']",
            'PUT /api/v1/noticeboard/settings '
            "['noticeboard:configure|noticeboard:write']",
        ]

    def test_named_data_behind_an_alternative_is_not_asked_for_its_own(self) -> None:
        name = f'{__name__}.read_or_write'

        assert misnamed(self._mounted(), {name: 'noticeboard:read'}) == {
            name: ['noticeboard:read|noticeboard:write']
        }

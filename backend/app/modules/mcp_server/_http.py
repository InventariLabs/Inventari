"""The MCP server, its HTTP transport, and the session manager it needs.

The SDK's mounted app does not receive an ASGI lifespan, and even stateless
Streamable HTTP requires ``StreamableHTTPSessionManager.run()`` before the
first request: the manager raises without its task group, and the 2026-07-28
single-exchange path still uses the lifespan state the manager holds. So the
module owns one manager per application lifespan. Production starts it in
``on_startup_async``; tests, which skip module startup hooks, start it on the
first request. ``on_shutdown_async`` closes it, and the next lifespan builds a
fresh server because the SDK forbids reusing a manager after ``run()`` exits.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from mcp.server.caching import CacheHint
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from .resources import register_resources
from .tools import register_tools

_MANIFEST = json.loads(Path(__file__).with_name('manifest.json').read_text('utf-8'))

_INSTRUCTIONS = """\
Read tools for an Inventari workspace. Search stock with search_items, then read
one record, the shelves it can stand on, its stock levels, its batches and what
expires soon. Every tool acts in the workspace the API key belongs to; a tool
may refuse when the key does not hold the read permission it needs.
"""


def build_server() -> MCPServer:
    """Build one MCP server with the module's tools, resources and cache hints."""
    server: MCPServer = MCPServer(
        name='inventari',
        title='Inventari',
        description=_MANIFEST['description'],
        instructions=_INSTRUCTIONS,
        version=str(_MANIFEST['version']),
        cache_hints={
            # The tool catalogue and the resource list change only when the
            # module's semver changes; a client may keep them for a minute.
            'tools/list': CacheHint(ttl_ms=60_000, scope='private'),
            'resources/list': CacheHint(ttl_ms=60_000, scope='private'),
            'resources/templates/list': CacheHint(ttl_ms=60_000, scope='private'),
            # A resource read answers from live stock; it is fresh for one call.
            'resources/read': CacheHint(ttl_ms=0, scope='private'),
        },
    )
    register_tools(server)
    register_resources(server)
    return server


class McpHttpApp:
    """One MCP transport per application lifespan, behind a stable ASGI app.

    The router serves this object once. The SDK server and its session manager
    are built on the first ``startup()`` and dropped by ``shutdown()``, so a
    test client that opens and closes the app twice gets two managers; a
    single manager cannot be run twice.

    The manager is entered by a task of its own and closes in that same task.
    An anyio cancel scope belongs to the task that entered it, and the manager
    is started in production from the lifespan while the requests that use it
    run in other tasks; entering it in the first request's task (what a test
    run without module startup hooks does) made the shutdown exit fail with
    "cancel scope in a different task". A dedicated owner task is the same
    task for both halves in either case.
    """

    def __init__(self, factory: Callable[[], MCPServer] = build_server) -> None:
        self._factory = factory
        self._lock: asyncio.Lock | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._app: Any = None
        self._task: asyncio.Task[None] | None = None
        self._stop: asyncio.Event | None = None

    def _get_lock(self) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        if self._lock is None or self._loop is not loop:
            # A lock and an event are bound to the loop that first waits on
            # them. A new lifespan (a new TestClient in the suite) is a new
            # loop.
            self._lock = asyncio.Lock()
            self._loop = loop
        return self._lock

    @staticmethod
    async def _serve(
        server: MCPServer, stop: asyncio.Event, ready: asyncio.Event
    ) -> None:
        """Own the manager's context in the one task that both enters and exits it."""
        try:
            async with AsyncExitStack() as stack:
                await stack.enter_async_context(server.session_manager.run())
                ready.set()
                await stop.wait()
        finally:
            ready.set()

    async def startup(self) -> Any:
        """Start the transport, or return the running one."""
        if self._app is not None:
            return self._app
        async with self._get_lock():
            if self._app is None:
                server = self._factory()
                app = server.streamable_http_app(
                    streamable_http_path='/',
                    stateless_http=True,
                    json_response=True,
                    # Host/Origin is checked per request in _auth, where the
                    # key's organization (and so its configured host list) is
                    # known; a static list here would refuse every deployment
                    # host before that point.
                    transport_security=TransportSecuritySettings(
                        enable_dns_rebinding_protection=False
                    ),
                )
                stop = asyncio.Event()
                ready = asyncio.Event()
                task = asyncio.create_task(self._serve(server, stop, ready))
                await ready.wait()
                failure = task.exception() if task.done() else None
                if failure is not None:
                    raise failure
                self._app, self._task, self._stop = app, task, stop
        return self._app

    async def shutdown(self) -> None:
        """Stop the transport and forget it; the next startup builds a new one."""
        async with self._get_lock():
            task, stop = self._task, self._stop
            self._app, self._task, self._stop = None, None, None
            self._lock, self._loop = None, None
            if stop is not None:
                stop.set()
            if task is not None:
                await task

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        app = await self.startup()
        await app(scope, receive, send)


mcp_http_app = McpHttpApp()


class AtRootPath:
    """Serve an app built for ``/`` under the deeper path a Route matched.

    ``streamable_http_app(streamable_http_path='/')`` registers its route at
    ``/``. A mount rewrites the child scope's path for us; the exact-path
    Starlette Route that keeps ``/mcp`` redirect-free does not, so this sets
    the path the SDK app expects before handing the request over.
    """

    def __init__(self, app: Any) -> None:
        self.app = app
        # The rate limiter names a handler by ``module.name``; this app is the
        # endpoint, and a class instance has no ``__name__`` of its own.
        self.__name__ = 'mcp_endpoint'

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope.get('type') in ('http', 'websocket'):
            scope = dict(scope)
            scope['path'] = '/'
            scope['raw_path'] = b'/'
        await self.app(scope, receive, send)

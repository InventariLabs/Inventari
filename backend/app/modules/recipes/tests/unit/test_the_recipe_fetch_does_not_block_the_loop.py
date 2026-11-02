"""The recipe reader fetch runs off the event loop.

``scrape_with_jina_llm_async`` used to call its synchronous ``httpx.get``
straight from the coroutine: one slow page froze the whole worker — every
request on it, health checks included — until the 30 s timeout allowed.
This pins the loop's liveness against a deliberately hanging reader.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import MagicMock
from uuid import uuid4

import httpx
import pytest

from app.modules.recipes.scrapers import jina_llm

_HANG_SECONDS = 1.5


class _ReaderAndProbeHandler(BaseHTTPRequestHandler):
    """``/reader`` hangs; ``/probe`` answers at once, on its own thread."""

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if self.path.startswith('/reader'):
            time.sleep(_HANG_SECONDS)
            self.send_response(500)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain')
        self.end_headers()
        self.wfile.write(b'ok')

    def log_message(self, *args: object) -> None:  # silence test server logging
        pass


@pytest.fixture
def local_reader(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    server = ThreadingHTTPServer(('127.0.0.1', 0), _ReaderAndProbeHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f'http://127.0.0.1:{server.server_address[1]}'
    monkeypatch.setattr(jina_llm, '_JINA_BASE_URL', f'{base_url}/')
    try:
        yield base_url
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.asyncio
async def test_a_request_finishes_while_the_reader_hangs(local_reader: str) -> None:
    import_in_flight = False

    async def _import() -> None:
        nonlocal import_in_flight
        import_in_flight = True
        try:
            with pytest.raises(ValueError):
                await jina_llm.scrape_with_jina_llm_async(
                    MagicMock(),
                    uuid4(),
                    'reader',
                    jina_api_key=None,
                    usage_ctx=None,
                )
        finally:
            import_in_flight = False

    async def _probe() -> bool:
        async with httpx.AsyncClient() as client:
            response = await client.get(f'{local_reader}/probe')
        assert response.status_code == 200
        return import_in_flight

    _, probe_answered_mid_import = await asyncio.gather(_import(), _probe())

    assert probe_answered_mid_import is True

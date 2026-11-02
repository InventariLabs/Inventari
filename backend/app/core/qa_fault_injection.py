"""Makes the error state of a screen reachable on purpose.

Every list, form and detail screen has a state where the request behind it
failed, and it is the state nobody checks: reaching it means waiting for a real
outage, or editing code. So it is the state where a screen most often has
nothing to say — a spinner that never stops, or a blank panel.

This turns it into a cookie. A browser sets ``qa_fail`` to a status code and
every API call under it comes back with that status until the cookie is
cleared; ``qa_fail_path`` narrows it to one endpoint, which is what makes the
difference between "this screen handles failure" and "the whole app is down"
visible.

    document.cookie = "qa_fail=500; path=/";
    document.cookie = "qa_fail_path=/api/v1/items; path=/";
    document.cookie = "qa_fail=; path=/; max-age=0";   // back to normal

Both cookies, not one. ``qa_fail_path`` is a filter and on its own it fails
nothing, and the filter is not really optional either: an unnarrowed cookie
also fails the call the shell makes to learn who is signed in, which the
frontend reads as "nobody" — so the screen under test is replaced by the login
form before anyone can look at it.

It is registered only when ``QA_FAULT_INJECTION`` is set **and** ``DEBUG`` is
on, so an installation that is neither cannot be switched into it by a cookie —
see ``app/main.py``. Pure ASGI, like the rest of the middleware here: it must
be able to answer before any handler starts reading the body.
"""

from __future__ import annotations

import json
from http.cookies import SimpleCookie

from starlette.types import ASGIApp, Receive, Scope, Send

STATUS_COOKIE = 'qa_fail'
PATH_COOKIE = 'qa_fail_path'

#: Only API traffic. Failing the document request would replace the screen
#: under test with the browser's own error page.
GUARDED_PREFIX = '/api/'

_MIN_STATUS = 400
_MAX_STATUS = 599


def _cookies(scope: Scope) -> dict[str, str]:
    for name, value in scope.get('headers') or []:
        if name.lower() != b'cookie':
            continue
        jar = SimpleCookie()
        jar.load(value.decode('latin-1'))
        return {key: morsel.value for key, morsel in jar.items()}
    return {}


def _requested_status(cookies: dict[str, str]) -> int | None:
    raw = cookies.get(STATUS_COOKIE, '').strip()
    if not raw.isdigit():
        return None
    status = int(raw)
    return status if _MIN_STATUS <= status <= _MAX_STATUS else None


class FaultInjectionMiddleware:
    """Answers with the status a ``qa_fail`` cookie asks for."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return

        path = scope.get('path', '')
        if not path.startswith(GUARDED_PREFIX):
            await self.app(scope, receive, send)
            return

        cookies = _cookies(scope)
        status = _requested_status(cookies)
        if status is None:
            await self.app(scope, receive, send)
            return

        only = cookies.get(PATH_COOKIE, '').strip()
        if only and only not in path:
            await self.app(scope, receive, send)
            return

        body = json.dumps(
            {
                'detail': (
                    f'Injected failure ({status}) — the {STATUS_COOKIE} cookie is '
                    'set. Clear it to restore normal responses.'
                ),
                'error': 'qa_fault_injection',
            }
        ).encode()
        await send(
            {
                'type': 'http.response.start',
                'status': status,
                'headers': [
                    (b'content-type', b'application/json'),
                    (b'content-length', str(len(body)).encode()),
                    # Says which layer answered, so a confusing 500 in a
                    # screenshot can be told apart from a real one.
                    (b'x-qa-fault-injection', b'1'),
                ],
            }
        )
        await send({'type': 'http.response.body', 'body': body})

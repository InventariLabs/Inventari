"""Who the journal should say acted, when it was not a person.

An API key authenticates as its owner: the request carries that account's
identity and permissions, so an entry written by a key read exactly like one
written at the screen — same ``user_email``, no ``meta_data`` at all. That
matters most at the moment an administrator revokes a key on suspicion of a
leak: the key leaves the list of keys, and if the journal never named it,
there is nowhere left that says what it did.

The credential is known at exactly one point on the read path — where the
request is authenticated, in ``identity_service`` — and the write path
(``audit_service.log_action_async``) is reached from dozens of call sites,
none of which see it. So the actor travels *beside* the request rather than
through it: :func:`set_api_key_actor` is called where the key is resolved,
:func:`current_actor` is read where the entry is written, and
:func:`audit_actor_scope` — an app-level FastAPI dependency — surrounds every
request, so a name set in one can neither outlive it nor reach the next.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextvars import ContextVar

#: The key an entry's ``meta_data`` carries its actor under. Reserved: the
#: journal's own writer sets it, and everything a caller wrote itself is kept
#: beside it (see ``audit_service.log_action_async``).
ACTOR_KEY = 'actor'

#: ``actor.type`` for a request that carried an API key. A person's request
#: writes no actor at all — the absence is the answer — which is also why the
#: filter has two values and not three.
ACTOR_TYPE_API_KEY = 'api_key'

_actor: ContextVar[dict[str, str] | None] = ContextVar('audit_actor', default=None)


def set_api_key_actor(key_prefix: str) -> None:
    """Record that the request in flight authenticated with an API key.

    Called once, where the key is resolved and its prefix is in hand.
    """
    _actor.set({'type': ACTOR_TYPE_API_KEY, 'key_prefix': key_prefix})


def current_actor() -> dict[str, str] | None:
    """The credential behind the request in flight, or ``None`` for a person.

    ``None`` is also the answer outside a request — a scheduler, a CLI job —
    where the journal has no credential to name.
    """
    return _actor.get()


async def audit_actor_scope() -> AsyncIterator[None]:
    """One actor context per request: empty at the start, dropped at the end.

    Declared on the app (``app.main``) rather than on the endpoints that write
    to the journal: any of them may write, and a name that survived its own
    request would be attributed to whatever the next one did.
    """
    token = _actor.set(None)
    try:
        yield
    finally:
        _actor.reset(token)

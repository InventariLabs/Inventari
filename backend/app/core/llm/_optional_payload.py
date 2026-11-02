"""Body keys that are an optimisation, and what to do when one is refused.

Three of the keys the clients send are not the request, they are ways of
asking for the request to go better: ``response_format`` is OpenAI's
structured output, and ``reasoning`` / ``thinking`` are the two spellings of
"do not think out loud". Between them they go to sixteen products that agree
on the shape of a chat request and on very little else.

A provider that has never heard of one of these can ignore it — most do — or
answer 400. Where it answers 400 the whole call fails over a key that was
never the point, which is why the OpenAI-compatible client has always retried
without ``response_format``. The other two keys were added later and got no
such treatment: switching reasoning off on the image path would have
turned "this model thinks out loud" into "this model cannot read labels at
all" on any endpoint strict about unknown fields.

Dropping the key is strictly better than dropping the request. Without
``response_format`` the answer still goes through the parser and the retry;
without the reasoning switch the model thinks out loud and still answers,
inside the budget the caller now sizes for exactly that.

Shared rather than duplicated: the Anthropic adapter sends ``thinking`` too,
and a model with no extended thinking to switch off refuses it the same way.
"""

from __future__ import annotations

import time
from typing import Any, Protocol

from app.core.llm._outbound import route_base_url

__all__ = [
    'OPTIONAL_PAYLOAD_KEYS',
    'rejected_optional_key',
    'remember_rejected_key',
    'remembered_rejections',
]

OPTIONAL_PAYLOAD_KEYS = ('response_format', 'reasoning', 'thinking')

#: Words that mean "I do not know that key" without saying which one.
_REJECTION_WORDS = ('unknown', 'unsupported', 'unrecognized', 'not supported')

#: Which to give up first when the provider will not say which key it means.
#: The reasoning switch costs the least — the model thinks out loud and still
#: answers. Structured output goes last: without it the answer rides on the
#: parser and one retry.
_GIVE_UP_ORDER = ('thinking', 'reasoning', 'response_format')


class _HttpAnswer(Protocol):
    """As much of a response as this decision needs."""

    @property
    def status_code(self) -> int: ...

    @property
    def text(self) -> str: ...


def rejected_optional_key(response: _HttpAnswer, payload: dict[str, Any]) -> str | None:
    """The optional key this 400 is complaining about, if it is one of ours.

    Read off the provider's own words rather than assumed from the status:
    retrying on every 400 would mask a genuinely malformed request, and
    stripping a key the provider never named would turn one failure into two.
    """
    if response.status_code != 400:
        return None
    error_text = response.text.lower()

    named = [
        key for key in OPTIONAL_PAYLOAD_KEYS if key in payload and key in error_text
    ]
    if named:
        return named[0]
    # OpenAI's structured output gets refused under its inner name as often as
    # under its own.
    if 'json_schema' in error_text and 'response_format' in payload:
        return 'response_format'
    # "unknown parameter", nothing named. One guess, in the order above; a
    # second 400 surfaces to the caller.
    if any(word in error_text for word in _REJECTION_WORDS):
        return next((key for key in _GIVE_UP_ORDER if key in payload), None)
    return None


#: How long a refusal is trusted. OpenRouter's model id is a pool of hosts
#: that do not agree on unknown keys, so today's refusal can be tomorrow's
#: acceptance. The TTL bounds the damage in both directions: at worst one
#: wasted call per key per hour (in each worker, below) is paid again, and
#: a route that changed its mind is re-learned within the hour — a refusal
#: is remembered, never concluded.
_REJECTION_TTL_SECONDS = 3600.0

#: The memory lives in each worker process, and production runs several
#: (``WEB_CONCURRENCY``, 4 by default — ``backend/Dockerfile``). A refusal
#: learned in one worker is unknown to the others, so a route pays the
#: wasted call once per worker that serves it in the hour rather than once:
#: at most 4, not 1. Measured with the real client against a refusing
#: provider, 4 processes taking requests in turn (the most even spread, so
#: the worst case): 4 requests an hour save nothing, 8 save 4 of the 7 a
#: shared memory would, 20 save 16 of 19, 100 save 96 of 99. The calls a
#: shared store could still save are those first few per worker, and Redis
#: would put a network round trip, and a way to fail, in front of every
#: LLM call to save them — so the memory stays per process.
#:
#: Hard ceiling on remembered refusals. Entries are keyed by owner (a row,
#: or a draft's organization) × provider × address × model × key, and the
#: address and model are free text in both branches, so the keyspace is
#: not finite by construction. In practice it is small: an entry is
#: written only after a provider answered a billed call with 400, and a
#: draft probe takes the organization-settings permission and the
#: organization's AI budget. An instance with a few connections and a few
#: models each stays in the tens; 256 is reached only by refusals from
#: that many distinct routes inside one hour in one worker. Past it the
#: oldest entry goes first, whatever organization it belongs to — losing
#: it costs exactly what its expiry would, one question asked again.
_MAX_MEMORY_ENTRIES = 256

#: (connection identity, payload key) → monotonic time of the last refusal.
_refused_since: dict[tuple[tuple[Any, ...], str], float] = {}


def _connection_key(connection: Any) -> tuple[Any, ...]:
    """One memory per route: the row's id, address and model when there is a
    row, otherwise the draft's own address — organization, provider, base
    URL and model.

    The model is part of both branches because the refusal is the model's,
    not the connection's: a row switched to a model that does support the
    key was inheriting the previous model's refusal for its whole hour, and
    a row is exactly where a model gets changed. It is read defensively,
    like the draft's own fields, so a connection naming no model still
    buckets as one route.

    The address is part of the row's key for the same reason, and it is
    editable too — ``AiConnectionUpdate`` can point a saved row at another
    host — so a row moved to a host that accepts the key must not keep
    serving the old host's hour. It is the address the client actually
    sends to (:func:`route_base_url`): a trailing slash, or an Anthropic
    row leaving the default unwritten, is the same route and one memory.
    The provider rides along in both branches; a row cannot change it
    today, and if it ever can, the route it names changes with it.

    A draft (the pre-save "test connection" probe) has no row id yet, and
    keying it by bare provider merged every organization's probe into one
    bucket: one org's draft pointing at a strict host silenced another
    org's key for an hour, though the two share nothing but the provider
    name. The address is what the refusal is about — the same provider at
    a different base URL is a different route, asked on its own merits.

    A tuple, not a joined string: the address and the model are free text,
    and ``'a|b' + '|' + 'c'`` is ``'a' + '|' + 'b|c'`` — two routes, one key.
    """
    row_id = getattr(connection, 'id', None)
    owner = (
        ('row', row_id)
        if row_id
        else ('draft', getattr(connection, 'organization_id', None))
    )
    return (
        *owner,
        getattr(connection, 'provider', '') or '',
        route_base_url(connection),
        getattr(connection, 'model_name', '') or '',
    )


def remember_rejected_key(connection: Any, key: str) -> None:
    """This connection's route refused *key* — stop paying to relearn it.

    Writing prunes: expired entries are dropped first and the oldest
    survivors go overboard past the ceiling, so the memory cannot grow
    without bound no matter how many drafts name their own hosts.
    """
    now = time.monotonic()
    for entry, since in list(_refused_since.items()):
        if now - since >= _REJECTION_TTL_SECONDS:
            del _refused_since[entry]
    while len(_refused_since) >= _MAX_MEMORY_ENTRIES:
        _refused_since.pop(next(iter(_refused_since)))
    _refused_since[(_connection_key(connection), key)] = now


def remembered_rejections(connection: Any) -> frozenset[str]:
    """Keys this connection's route refused recently enough to trust."""
    now = time.monotonic()
    owner = _connection_key(connection)
    return frozenset(
        key
        for (conn, key), since in list(_refused_since.items())
        if conn == owner and now - since < _REJECTION_TTL_SECONDS
    )

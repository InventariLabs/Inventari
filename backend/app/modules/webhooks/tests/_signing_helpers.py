"""Helpers for the signing tests: an unreadable secret and a silent transport.

The unit file and the integration file both need the same two things — a
stored value in one of the shapes whose key is gone, and a way to see what a
delivery would put on the wire (or that nothing was put there). Shared so the
two read the same measurements.
"""

from collections.abc import Callable
from typing import Any


def unreadable(value: str) -> str:
    """*value* with a character deep in its ciphertext edited: a rotation, in
    effect.

    The edit stays away from the token's version byte, so the value still has
    the shape of the format it was written in — only the key that would open
    it is gone. That is the measured shape: ``decrypt_value`` cannot tell it
    apart from the empty string a caller never configured.
    """
    position = len(value) - 8
    replacement = 'A' if value[position] != 'A' else 'B'
    return f'{value[:position]}{replacement}{value[position + 1 :]}'


def recording_transport(calls: list[dict[str, Any]]) -> Callable[..., Any]:
    """An ``httpx.AsyncClient`` stand-in that records every request.

    Returns the factory the delivery path calls with client kwargs; whatever
    a delivery would send lands in *calls*, and a refusal leaves it empty.
    """

    class _FakeResponse:
        status_code = 200
        text = 'OK'

    class _FakeClient:
        async def __aenter__(self) -> Any:
            return self

        async def __aexit__(self, *exc: Any) -> bool:
            return False

        async def request(self, method: str, url: str, **kwargs: Any) -> Any:
            calls.append(
                {'method': method, 'url': url, 'headers': kwargs.get('headers')}
            )
            return _FakeResponse()

    return lambda **kwargs: _FakeClient()

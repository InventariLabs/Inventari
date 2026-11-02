"""The address a printed code points at.

A QR now carries ``{base}/s/{code}``. Labels carried
``{base}/scan?code={code}`` until a deployment's address got long: every
byte of the payload is paid for in modules, and a 58-character base URL
pushed the matrix to 37 modules — 18.8 mm at the half-millimetre module a
phone needs, past the 18 mm a label has for the square. Eight bytes of
``scan?code=`` are the part of the address the installation does not
choose, so they are the part that went. With the renderer dropping to a
lighter error correction when the matrix would outgrow its share, an
eight-character label code stays at 33 modules up to a 67-character base
URL; ``scan?code=`` alone would have run out at 59.

The old shapes still resolve, in the app and in :func:`scan_code_in` —
``?code=`` and the app's own ``/labels/scan/{code}`` page, which the first
stickers opened: labels already stuck on shelves carry them and nobody is
going to reprint them. Documents print the same shape as labels — one scanning path, not
two — so both formats live here instead of being spelled out again at
every printout and every parser.
"""

from __future__ import annotations

from urllib.parse import parse_qs, quote, unquote, urlsplit

#: The path a printed QR opens. One letter on purpose: see the module
#: docstring for what each byte of it costs on a label.
SHORT_SCAN_PATH = '/s/'

#: The app's own scan page, which QR stickers printed before the short path
#: opened directly. A 2D hardware scanner types the whole address into
#: whatever field has the focus, so it is read back to the code like the
#: other two shapes.
APP_SCAN_PATH = '/labels/scan/'

# Hosts that only resolve on the machine that rendered the PDF. A printout is
# handed to somebody else; a link to one of these opens their own device.
_UNROUTABLE_HOSTS = frozenset(
    {'localhost', '127.0.0.1', '::1', '0.0.0.0', ''}  # noqa: S104 — matched, not bound
)


def scan_url(code: str, base_url: str) -> str:
    """The scan address for *code* under *base_url*.

    The code is quoted as a path, keeping its slashes — a document number
    such as ``IN/2026/0001`` reads back whole through the app's catch-all
    route — so a character that means something in a URL (``?``, ``#``,
    a space) cannot cut the code short.
    """
    return f'{base_url.rstrip("/")}{SHORT_SCAN_PATH}{quote(code, safe="/")}'


def scan_code_in(raw: str) -> str | None:
    """The code a scan address carries, or ``None`` when *raw* is not one.

    Reads both shapes a QR has printed: ``{base}/s/{code}`` and the
    ``?code=`` query labels carried before it. Only the path at the root of
    the address counts as the short shape — the app is served there, so a
    ``/s/`` deeper in somebody else's URL is not a code of ours.
    """
    if 'code=' in raw:
        params = parse_qs(urlsplit(raw).query)
        if 'code' in params:
            return params['code'][0]
    parts = urlsplit(raw)
    if parts.scheme not in ('http', 'https'):
        return None
    for path in (SHORT_SCAN_PATH, APP_SCAN_PATH):
        if parts.path.startswith(path):
            return unquote(parts.path[len(path) :]) or None
    return None


def scanned_code(raw: str) -> str:
    """What a scan field matches: the code inside a scan address, else *raw*.

    A sticker's QR carries an address; the warehouse's scan fields match
    codes. A malformed address (an unclosed IPv6 bracket, say) is still a
    string somebody scanned, and is matched as typed.
    """
    try:
        return scan_code_in(raw) or raw
    except ValueError:
        return raw


def printable_scan_url(code: str) -> str | None:
    """The scan address worth printing, or ``None`` when there is none.

    Returns ``None`` when the installation's ``FRONTEND_URL`` names a host
    that only resolves on this machine: the printed QR would carry a link
    that opens the reader's own device. Callers fall back to encoding the
    bare code, which at least tells a human what they are holding.
    """
    from app.config import settings

    base = str(getattr(settings, 'FRONTEND_URL', '') or '')
    host = urlsplit(base).hostname if '//' in base else None
    if not base or host is None or host.strip('[]') in _UNROUTABLE_HOSTS:
        return None
    return scan_url(code, base)

"""A proxy ceiling under the application's own refuses an upload twice approved.

Three gates see the same upload. The browser's is at the file's limit
(``IMAGE_UPLOAD_MAX_BYTES``, 10 MiB of a photograph), the application's own
per-file limits run at the route, and the request ceiling in front of those
is ``MAX_REQUEST_BODY_SIZE`` — the largest file the product takes, the
50 MiB import (``MAX_IMPORT_SIZE``), plus a megabyte of multipart framing:
51 MiB, 53,477,376 B. The proxies stand in front of all of it: Caddy's
``request_body max_size`` on the deployment (``Caddyfile.demo`` imports that
file, so the demo edge is the same number) and nginx's ``client_max_body_size``
in the frontend image.

A ceiling below the request ceiling is a refusal both of the others pass: it
answers a generic 413 that names neither the file nor the endpoint, while the
application would have answered with the limit in the caller's language. The
unit is where the old ceilings fell — Caddy parses ``max_size`` through
go-humanize, in which ``MB`` is 10^6 (so ``10MB`` refused a ten-megabyte
photograph at 10,000,000 B, under its 10,485,760 B) and only ``MiB`` is
1024², while nginx's ``m`` is always 1024² — so each file is parsed here
the way its own proxy parses it, and every ceiling found has to sit above
the request ceiling. Then the application's refusal stays the one a reader
sees, and the proxy answers only what the application would refuse anyway.

Nothing here starts Docker; both configs are read as text.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from app.config import settings
from app.core.upload_validation import MAX_IMPORT_SIZE

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(
    os.environ.get('INVENTARI_REPO_ROOT') or Path(__file__).resolve().parents[3]
)

_MIB = 1024 * 1024

#: What go-humanize's ``ParseBytes`` — Caddy's ``max_size`` parser — multiplies
#: a size by. Note ``mb``/``m``: decimal, not the binary megabyte.
_CADDY_UNITS = {
    '': 1,
    'b': 1,
    'k': 1_000,
    'kb': 1_000,
    'm': 1_000_000,
    'mb': 1_000_000,
    'g': 1_000_000_000,
    'gb': 1_000_000_000,
    'ki': 1024,
    'kib': 1024,
    'mi': _MIB,
    'mib': _MIB,
    'gi': 1024**3,
    'gib': 1024**3,
}

#: nginx sizes: bare bytes, or ``k``/``m``/``g`` of 1024 each.
_NGINX_UNITS = {'': 1, 'k': 1024, 'm': _MIB, 'g': 1024**3}

_CADDY_SIZE = re.compile(r'max_size\s+(\S+)')
_NGINX_SIZE = re.compile(r'client_max_body_size\s+([^;]+);')


def _bytes(value: str, units: dict[str, int], where: str) -> int:
    """The size *value* names, in bytes, under *units*' own reading of it."""
    match = re.fullmatch(r'(\d+)\s*([A-Za-z]*)', value.strip())
    assert match is not None, (
        f'{where}: size {value!r} is not a number with an optional unit — '
        'teach this test to read the form before the config uses it'
    )
    suffix = match.group(2).lower()
    assert suffix in units, (
        f'{where}: size unit {match.group(2)!r} is unknown to this test — '
        'it would otherwise be read as bytes and pass or fail by luck'
    )
    return int(match.group(1)) * units[suffix]


def _ceilings(
    relative: str, regex: re.Pattern[str], units: dict[str, int]
) -> list[tuple[str, int]]:
    """``(where, bytes)`` for every body ceiling declared in one config file.

    Comments are dropped first: a commented-out ceiling enforces nothing,
    and a comment that merely names the directive must not be read as one.
    """
    path = _REPO_ROOT / relative
    ceilings: list[tuple[str, int]] = []
    for line_no, raw in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
        line = raw.split('#', 1)[0]
        for match in regex.finditer(line):
            where = f'{relative}:{line_no}'
            ceilings.append((where, _bytes(match.group(1), units, where)))
    return ceilings


def _all_ceilings() -> list[tuple[str, int]]:
    return [
        *_ceilings('Caddyfile', _CADDY_SIZE, _CADDY_UNITS),
        *_ceilings('frontend/nginx.conf', _NGINX_SIZE, _NGINX_UNITS),
    ]


def test_both_proxies_declare_a_body_ceiling() -> None:
    """The scan has to find one in each file, or nothing below proves anything."""
    found = {where.split(':', 1)[0] for where, _ in _all_ceilings()}
    assert found == {'Caddyfile', 'frontend/nginx.conf'}, (
        f'body ceilings found only in {sorted(found)} — a config that stops '
        'declaring one would otherwise pass the check by having none'
    )


def test_no_proxy_ceiling_refuses_a_body_the_application_accepts() -> None:
    """Every ceiling sits above the request ceiling, not merely near it.

    Above and not at it: a ceiling equal to ``MAX_REQUEST_BODY_SIZE`` would
    answer first with its own bare 413, and the application's refusal — the
    one that carries the limit and the language — would never be reached by
    a reader in production.
    """
    ceiling = settings.MAX_REQUEST_BODY_SIZE
    assert MAX_IMPORT_SIZE < ceiling, (
        'the ceiling must already cover the largest file plus multipart framing'
    )
    problems = [
        f'{where}: {size} B is not above the request ceiling {ceiling} B'
        for where, size in _all_ceilings()
        if size <= ceiling
    ]
    assert not problems, '\n  '.join(
        [
            'a proxy would refuse an upload the browser and the API both accept:',
            *problems,
        ]
    )


def test_the_demo_edge_holds_the_production_ceiling() -> None:
    """The demo's Caddy is the production one plus the inbox, never a copy.

    A ceiling written only in the production file would leave the demo on
    whatever it had, so the import is what makes the check above cover both.
    """
    demo = (_REPO_ROOT / 'Caddyfile.demo').read_text(encoding='utf-8')
    assert re.search(r'^\s*import\s+/etc/caddy/Caddyfile\s*$', demo, re.MULTILINE), (
        'Caddyfile.demo no longer imports the production Caddyfile, so the '
        'production ceiling no longer reaches the demo edge'
    )

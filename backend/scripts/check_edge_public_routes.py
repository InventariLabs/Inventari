"""Fail when the production edge stops forwarding ``/public/*`` API calls.

Caddy and the SPA's nginx once forwarded only ``/api`` and ``/uploads``. A
same-origin ``fetch('/public/invitation/<code>')`` then fell through to the SPA
fallback and came back as ``200 text/html``, which axios reads as success: the
invitation check and the attestation page worked on the dev server, whose proxy
has a ``/public`` entry, and nowhere behind a configured edge.

It also refuses the quieter edge mistake: nginx drops *all* inherited
``add_header`` directives the moment a location declares one of its own, so a
location that adds only ``Cache-Control`` answers without CSP or
X-Frame-Options. Every block that sets a header must repeat the whole security
set; two locations used to answer that way.

The address is shared. ``/public/attestation/<token>`` is also a page of the
SPA, so a browser navigation (``Accept: text/html``) must stay with the SPA —
the split ``vite.config.ts`` makes for the dev server. This pins both halves in
both files, because a config file has no type checker and neither test
container mounts the repository root.

Runs on the host with the standard library only, for the same reason as the
other checks that read files above the backend directory.

    python3 backend/scripts/check_edge_public_routes.py [--caddyfile PATH] [--nginx PATH]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

CADDY_MATCHER = re.compile(
    r'@publicApi \{\s*path /public/\*\s*not header Accept \*text/html\*\s*\}'
)
CADDY_PROXY = 'reverse_proxy @publicApi backend:8000'
CADDY_CATCH_ALL = 'reverse_proxy * frontend:8080'

NGINX_NAVIGATION = re.compile(
    r'if \(\$http_accept ~\* "text/html"\) \{\s*rewrite \^ /index\.html last;\s*\}'
)
NGINX_PROXY = 'proxy_pass http://backend:8000;'

SECURITY_HEADERS = (
    'Content-Security-Policy',
    'X-Frame-Options',
    'X-Content-Type-Options',
    'Referrer-Policy',
    'Permissions-Policy',
)

# One whole directive, alone on its line. A line that opens add_header and
# fails this is refused rather than skipped: skipping it would hide the block.
NGINX_ADD_HEADER = re.compile(
    r'^\s*add_header\s+(\S+)\s*(?:"([^"]*)")?[^;"]*?(\balways\s*)?;\s*$'
)
NGINX_ADD_HEADER_LINE = re.compile(r'^\s*add_header\b')

NGINX_SERVER_TOKENS = re.compile(r'^\s*server_tokens off;', re.MULTILINE)
NGINX_DOTFILES = re.compile(
    r'^ *location ~ ' + re.escape(r'/\.(?!well-known/)') + r' \{\s*return 404;\s*\}\n',
    re.MULTILINE,
)
NGINX_REGEX_LOCATION = re.compile(r'^[ \t]*location ~\*? ', re.MULTILINE)
# A prefix location, plain or `^~`; `=` and the regex forms start with no `/`.
NGINX_PREFIX_LOCATION = re.compile(r'^[ \t]*location (\^~ )?(/\S*) \{', re.MULTILINE)


def check_caddyfile(text: str) -> list[str]:
    problems: list[str] = []
    if not CADDY_MATCHER.search(text):
        problems.append(
            'Caddyfile: no `@publicApi` matcher for `path /public/*` that excludes '
            'requests asking for text/html'
        )
    proxy = text.find(CADDY_PROXY)
    if proxy == -1:
        problems.append(f'Caddyfile: missing `{CADDY_PROXY}`')
    elif proxy > text.find(CADDY_CATCH_ALL):
        problems.append(
            f'Caddyfile: `{CADDY_PROXY}` comes after the catch-all and never runs'
        )
    return problems


def check_nginx(text: str) -> list[str]:
    start = text.find('location /public/ {')
    if start == -1:
        return ['nginx.conf: no `location /public/` block']
    block = text[start : text.find('\n    }', start)]
    problems: list[str] = []
    if NGINX_PROXY not in block:
        problems.append(f'nginx.conf: `location /public/` lacks `{NGINX_PROXY}`')
    if not NGINX_NAVIGATION.search(block):
        problems.append(
            'nginx.conf: `location /public/` does not hand text/html navigations back to the SPA'
        )
    return problems


def check_nginx_document_cache(text: str) -> list[str]:
    start = text.find('location = /index.html {')
    if start == -1:
        return ['nginx.conf: no `location = /index.html` block']
    block = text[start : text.find('\n    }', start)]
    problems: list[str] = []
    if 'expires -1;' not in block:
        problems.append(
            'nginx.conf: `location = /index.html` lacks `expires -1;`, so the browser may '
            "answer the attestation page's own JSON GET with the cached HTML"
        )
    if 'add_header' in block:
        problems.append(
            'nginx.conf: `location = /index.html` uses add_header, which drops the '
            'server-level CSP and X-Frame-Options from the document'
        )
    return problems


_HeaderBlock = tuple[str, int, dict[str, tuple[str | None, bool]]]


def _header_blocks(text: str) -> list[_HeaderBlock]:
    """Every nginx block that declares ``add_header``, with its header values.

    Returns ``(label, line number, {name: (quoted value or None, has always)})`` — outer
    ``server`` first, locations as encountered. The file is hand-formatted one
    directive per line — ``check_nginx_security_headers`` refuses an
    ``add_header`` that is not — so a brace-counting scan is enough: comments are
    dropped, ``{`` pushes the line's block and ``}`` pops it. Labels are the
    block's first line (``server``, ``location = /sw.js``), which is what a
    failure message should name.
    """
    stack: list[_HeaderBlock] = []
    blocks: list[_HeaderBlock] = []
    for line_no, raw in enumerate(text.splitlines(), 1):
        line = raw.split('#', 1)[0]
        header = NGINX_ADD_HEADER.match(line)
        if header and stack:
            stack[-1][2][header.group(1)] = (header.group(2), bool(header.group(3)))
        for _ in range(line.count('{')):
            stack.append((line.split('{', 1)[0].strip(), line_no, {}))
        for _ in range(line.count('}')):
            if stack:
                blocks.append(stack.pop())
    blocks.extend(reversed(stack))
    return blocks


def _without_always(headers: dict[str, tuple[str | None, bool]]) -> list[str]:
    return [h for h in SECURITY_HEADERS if h in headers and not headers[h][1]]


def check_nginx_security_headers(text: str) -> list[str]:
    """Refuse an nginx block whose own headers displace the security set.

    An ``add_header`` at server level is inherited only while every location
    below it declares none; the first location-level ``add_header`` discards
    the inherited set wholesale. The rule: a block may add Cache-Control, but
    then it carries CSP, X-Frame-Options, X-Content-Type-Options,
    Referrer-Policy and Permissions-Policy itself — with the same values, so a
    copied policy cannot go stale in one place. Every one of them also ends in
    ``always``: without it nginx adds the header to 2xx and 3xx responses only,
    so a 404 or a 502 would leave without the policy.
    """
    problems = [
        f'nginx.conf:{line_no}: an add_header that is not one whole directive on '
        'one line; this check reads the file line by line and would not see the '
        'header it sets'
        for line_no, raw in enumerate(text.splitlines(), 1)
        if NGINX_ADD_HEADER_LINE.match(code := raw.split('#', 1)[0])
        and not NGINX_ADD_HEADER.match(code)
    ]
    blocks = _header_blocks(text)
    server = next(
        (block for block in blocks if block[0] == 'server' and block[2]), None
    )
    if server is None:
        return problems + [
            'nginx.conf: no `server` block declares the security headers'
        ]
    expected = server[2]
    absent = [header for header in SECURITY_HEADERS if header not in expected]
    if absent:
        problems.append(
            'nginx.conf: the `server` block does not declare ' + ', '.join(absent)
        )
    unsealed = _without_always(server[2])
    if unsealed:
        problems.append(
            'nginx.conf: the `server` block declares '
            + ', '.join(unsealed)
            + ' without `always`, so error responses leave without them'
        )
    for label, line, headers in blocks:
        if not headers or label == 'server':
            continue
        missing = [header for header in SECURITY_HEADERS if header not in headers]
        if missing:
            problems.append(
                f'nginx.conf:{line}: `{label}` sets add_header of its own, so it '
                'inherits none from the server block; its responses leave without '
                + ', '.join(missing)
            )
            continue
        unsealed = _without_always(headers)
        if unsealed:
            problems.append(
                f'nginx.conf:{line}: `{label}` declares '
                + ', '.join(unsealed)
                + ' without `always`, so its 4xx and 5xx responses leave without them'
            )
        stale = [
            header
            for header in SECURITY_HEADERS
            if header in expected and headers[header][0] != expected[header][0]
        ]
        if stale:
            problems.append(
                f'nginx.conf:{line}: `{label}` carries a different value for '
                + ', '.join(stale)
                + ' than the server block; the edge would answer two policies'
            )
    return problems


def check_nginx_probe_surface(text: str) -> list[str]:
    """Refuse an nginx that names its version or answers dotfile probes with 200.

    Without a rule of its own, ``/.env`` reaches the SPA fallback and comes back
    as ``200 index.html``: nothing leaks, but a scanner counts it as a hit. The
    404 rule must be the first regex location — nginx answers with the first
    regex that matches, and the static-asset one matches ``/.env.js`` as well.
    """
    code = '\n'.join(line.split('#', 1)[0] for line in text.splitlines()) + '\n'
    problems: list[str] = []
    if not NGINX_SERVER_TOKENS.search(code):
        problems.append(
            'nginx.conf: no `server_tokens off;`, so every response names the nginx version'
        )
    rule = NGINX_DOTFILES.search(code)
    if rule is None:
        problems.append(
            'nginx.conf: no `location ~ /\\.(?!well-known/)` returning 404, so a path '
            'with a dot-segment (/.env, /.git/config) is answered by the SPA fallback'
        )
    else:
        first = NGINX_REGEX_LOCATION.search(code)
        if first and first.start() < rule.start():
            problems.append(
                'nginx.conf: the dot-segment 404 rule is not the first regex location, '
                'so an earlier regex answers the probes it was meant to refuse'
            )
    return problems


def check_nginx_proxy_precedence(text: str) -> list[str]:
    """Refuse a proxying prefix location that a regex location can take over.

    nginx settles on the longest matching prefix and then, unless that prefix
    carries ``^~``, asks the regex locations and answers with the first that
    matches. The static-asset regex matches any path ending in ``.jpg``,
    ``.png`` or ``.svg``, so a plain ``location /uploads`` sent every stored
    photo to that block, which looked for it on disk and answered 404 — out
    of sight behind Caddy, which routes ``/uploads/*`` itself, and every photo
    lost on a deployment that reaches the frontend container directly. A
    block that hands paths to another server must therefore be ``^~``.

    ``location /public/`` is the one exception, and it is one by design: it
    also serves the SPA document to a navigation, so it stays under the
    regexes the way the SPA fallback does — ``^~`` would let ``/public/.env``
    asked as text/html bypass the dot-segment 404 and come back ``200
    index.html``. Its paths are a code or a URL-safe token, never a file name.
    """
    code = '\n'.join(line.split('#', 1)[0] for line in text.splitlines()) + '\n'
    problems: list[str] = []
    for match in NGINX_PREFIX_LOCATION.finditer(code):
        if match.group(1):
            continue
        block = code[match.end() : code.find('\n    }', match.end())]
        if 'proxy_pass' in block and not NGINX_NAVIGATION.search(block):
            path = match.group(2)
            problems.append(
                f'nginx.conf: `location {path}` proxies without `^~`, so a regex '
                f'location answers any {path} path it matches: one ending in '
                '.jpg or .svg reaches the static-asset block and 404s'
            )
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--caddyfile', type=Path, default=REPO_ROOT / 'Caddyfile')
    parser.add_argument(
        '--nginx', type=Path, default=REPO_ROOT / 'frontend' / 'nginx.conf'
    )
    args = parser.parse_args(argv)

    nginx = args.nginx.read_text()
    problems = (
        check_caddyfile(args.caddyfile.read_text())
        + check_nginx(nginx)
        + check_nginx_document_cache(nginx)
        + check_nginx_security_headers(nginx)
        + check_nginx_probe_surface(nginx)
        + check_nginx_proxy_precedence(nginx)
    )
    for problem in problems:
        print(problem, file=sys.stderr)
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())

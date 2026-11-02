"""The published demo inbox answers reads and refuses everything else.

``Caddyfile.demo`` publishes Mailpit at ``/mailpit`` so a visitor can read the
purchase order or invitation that would have gone out — that is what
``docs/DEMO.md`` points at. Mailpit's API writes as well as reads, though, and
the route published the writes too: ``POST /api/v1/send`` let anyone on the
internet drop a message into the inbox and hand out a link to it (a page served
from our own domain), ``DELETE`` wiped it for every other visitor, ``PUT``
marked and tagged. The three fetching endpoints were the same door the other
way round: ``/proxy``, the link checker and the HTML checker make Mailpit
fetch addresses taken from a message, and with the send API open the message
was a stranger's.

So the edge answers GET and HEAD on that route and refuses the rest. Mail still
arrives — the application speaks SMTP to Mailpit on the app network
(``docker-compose.demo.yml``) and never through this route — and a visitor
reading the inbox cannot tell the difference.

Nothing here starts Docker; ``Caddyfile.demo`` is parsed as text, because the
failure worth catching is a later edit quietly loosening one of these matchers.
The matcher expressions are evaluated rather than matched as substrings: a
403 that became a 200, or a ``not method`` that forgot HEAD, reads no
differently on screen until somebody else reads it for you.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(
    os.environ.get('INVENTARI_REPO_ROOT') or Path(__file__).resolve().parents[3]
)

#: The route the docs hand to visitors; everything published under it is this
#: block's to answer.
_SITE_BLOCK = '{$DOMAIN}/mailpit*'


def _mailpit_block() -> str:
    """The body of the demo's ``/mailpit`` site block, comments stripped."""
    text = (_REPO_ROOT / 'Caddyfile.demo').read_text(encoding='utf-8')
    assert _SITE_BLOCK in text, 'Caddyfile.demo no longer publishes the inbox'
    body: list[str] = []
    for line in text[text.index(_SITE_BLOCK) :].splitlines()[1:]:
        if line.startswith('}'):  # the site block closes at column 0
            break
        body.append(line.split('#', 1)[0])
    return '\n'.join(body)


def _refusals(body: str) -> dict[str, str]:
    """The matcher expression behind every ``respond … 403`` in the block.

    A ``respond`` whose matcher is gone or renamed would answer nothing, so a
    refusal naming an unknown matcher is an error rather than a pass.
    """
    matchers = dict(re.findall(r'^ *@(\S+) +(.+)$', body, re.MULTILINE))
    answered = re.findall(r'^ *respond *@(\S+) +"[^"]*" +(\d+) *$', body, re.MULTILINE)
    assert answered, (
        'the /mailpit block refuses nothing: writes and server-side fetches '
        'would reach Mailpit again'
    )
    refusals: dict[str, str] = {}
    for name, status in answered:
        assert int(status) == 403, (
            f'respond @{name} answers {status}; the refusal this demo makes is a 403'
        )
        assert name in matchers, f'respond @{name} names no matcher in the block'
        refusals[name] = matchers[name]
    return refusals


def _refused(body: str, method: str, path: str) -> bool:
    """Whether the block's own 403 directives answer this request.

    Caddy evaluates each named matcher on its own; a matcher this cannot read
    fails the test instead of silently counting as "not refused", so teaching
    the test a new shape is the author's to do when they change it.
    """
    for name, expression in _refusals(body).items():
        tokens = expression.split()
        if tokens[:2] == ['not', 'method']:
            if method not in tokens[2:]:
                return True
        elif tokens[:1] == ['path_regexp']:
            if re.search(tokens[1], path):
                return True
        else:
            pytest.fail(
                f'Caddyfile.demo: @{name} is `{expression}`, which this test '
                'cannot evaluate; teach it the shape or narrow the matcher'
            )
    return False


class TestWritesAreRefused:
    """Mailpit's API writes as well as reads; the published route may read."""

    @pytest.mark.parametrize(
        ('method', 'path'),
        [
            ('POST', '/mailpit/api/v1/send'),
            ('DELETE', '/mailpit/api/v1/messages'),
            ('PUT', '/mailpit/api/v1/messages/read'),
            ('DELETE', '/mailpit/api/v1/message/0abc123'),
        ],
    )
    def test_the_inbox_route_refuses_a_write(self, method: str, path: str) -> None:
        assert _refused(_mailpit_block(), method, path), (
            f'{method} {path} would reach Mailpit: anyone on the internet could '
            'put a message in the inbox, hand out a link to it, or wipe what '
            'every visitor came to read'
        )


class TestReadsStillPass:
    """The inbox the docs point at keeps loading — UI, list and one message."""

    @pytest.mark.parametrize(
        ('method', 'path'),
        [
            ('GET', '/mailpit/'),
            ('GET', '/mailpit'),
            ('GET', '/mailpit/api/v1/messages'),
            ('GET', '/mailpit/api/v1/message/0abc123'),
            ('HEAD', '/mailpit/api/v1/messages'),
        ],
    )
    def test_the_inbox_route_answers_a_read(self, method: str, path: str) -> None:
        assert not _refused(_mailpit_block(), method, path), (
            f'{method} {path} would be refused: a visitor could no longer read '
            'the inbox the sign-in screen links to'
        )


class TestTheServerFetchesNothingForAVisitor:
    """These three make Mailpit fetch an address taken from a message."""

    @pytest.mark.parametrize(
        'path',
        [
            '/mailpit/proxy?image=http://tracker.invalid/pixel',
            '/mailpit/api/v1/message/0abc123/link-check',
            '/mailpit/api/v1/message/0abc123/html-check',
        ],
    )
    def test_the_fetching_endpoint_is_refused(self, path: str) -> None:
        assert _refused(_mailpit_block(), 'GET', path), (
            f'GET {path} would have the demo server fetch an address of the '
            "caller's choosing"
        )


class TestTheDocsSaySo:
    def test_demo_md_calls_the_inbox_read_only_from_outside(self) -> None:
        """A reader of the docs must know the inbox cannot be written to.

        The sign-in screen links here, so "read-only" belongs where the inbox
        is described — not only in the configuration that enforces it.
        """
        demo = (_REPO_ROOT / 'docs' / 'DEMO.md').read_text(encoding='utf-8')
        section = demo.split('## No email leaves the demo', 1)[1].split('\n## ', 1)[0]

        assert 'read-only' in section.lower(), (
            'docs/DEMO.md no longer tells the reader the inbox is read-only '
            'from outside'
        )

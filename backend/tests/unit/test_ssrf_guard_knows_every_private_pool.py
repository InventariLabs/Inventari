"""Which addresses count as "inside", by pool rather than by luck.

The guard held a hand-written list of ranges. It covered RFC 1918, loopback,
link-local and ULA, and nothing else — so a Home Assistant reached over
Tailscale (100.64.0.0/10) was accepted without any switch while the same box on
the LAN was refused, and no message could explain the difference because there
was no reason behind it.

Each row here is a pool the list missed or a pool it caught. They are one test
so the rule is read as a rule: refused when not globally routable, allowed when
it is, and the operator's switch turns the whole thing off at once.
"""

import ipaddress

import pytest

from app.core.ssrf_guard import validate_webhook_url
from app.i18n.service import get_error_message


@pytest.mark.parametrize(
    ('lang', 'wording'),
    [
        ('en', 'not publicly routable'),
        ('pl', 'publicznie routowalny'),
        ('de', 'öffentlich routbar'),
        ('fr', 'routable publiquement'),
        ('es', 'enrutamiento público'),
        ('pt', 'roteável publicamente'),
    ],
)
def test_documentation_address_refusal_names_the_rule(lang: str, wording: str) -> None:
    with pytest.raises(ValueError):
        validate_webhook_url('https://203.0.113.10/hook', allow_private=False)
    message = get_error_message('webhook_url_private', lang, host='203.0.113.10')
    assert wording in message
    assert '203.0.113.10' in message
    resolved = get_error_message(
        'webhook_url_rebinding', lang, host='example.test', resolved='203.0.113.10'
    )
    assert wording in resolved
    assert '203.0.113.10' in resolved


#: Pools the server must not be aimed at. The first four were already refused;
#: the last three were the hole, and the last one is refused on top of
#: `is_global` rather than by it.
REFUSED = [
    ('192.168.1.50', 'rfc-1918'),
    ('10.1.2.3', 'rfc-1918-ten'),
    ('172.17.0.1', 'docker-bridge'),
    ('127.0.0.1', 'loopback'),
    ('169.254.169.254', 'link-local-metadata'),
    ('100.64.1.5', 'carrier-nat-tailscale'),
    ('198.18.0.7', 'benchmarking'),
    ('192.0.0.9', 'ietf-protocol-assignments'),
    ('203.0.113.5', 'documentation'),
    ('240.0.0.1', 'reserved'),
    ('[::1]', 'loopback-v6'),
    ('[fd00::1]', 'ula-v6'),
    ('[fe80::1]', 'link-local-v6'),
    ('[2001:db8::1]', 'documentation-v6'),
    ('[::ffff:192.168.1.28]', 'v4-mapped-into-v6'),
]

#: Addresses a real receiver sits on. The middle two guard against the fix
#: swallowing more than it should: 100.0.0.0/8 outside 100.64/10 is ordinary
#: public space, and so is the rest of 192.0.0.0/8 outside the /24.
ALLOWED = [
    ('8.8.8.8', 'public-resolver'),
    ('1.1.1.1', 'public-resolver-2'),
    ('100.1.2.3', 'public-inside-100-slash-8'),
    ('192.1.0.9', 'public-inside-192-slash-8'),
    ('[2606:4700::1111]', 'public-v6'),
]


@pytest.mark.parametrize(
    'address', [a for a, _ in REFUSED], ids=[i for _, i in REFUSED]
)
def test_refused_when_private_networks_are_off(address: str) -> None:
    with pytest.raises(ValueError):
        validate_webhook_url(f'https://{address}/hook', allow_private=False)


@pytest.mark.parametrize(
    'address', [a for a, _ in REFUSED], ids=[i for _, i in REFUSED]
)
def test_the_operator_switch_covers_every_pool(address: str) -> None:
    """One switch, not one per pool — otherwise the list is back."""
    assert validate_webhook_url(f'https://{address}/hook', allow_private=True)


@pytest.mark.parametrize(
    'address', [a for a, _ in ALLOWED], ids=[i for _, i in ALLOWED]
)
def test_a_real_receiver_still_passes(address: str) -> None:
    assert validate_webhook_url(f'https://{address}/hook', allow_private=False)


def test_the_extra_refusal_is_narrow() -> None:
    """192.0.0.9 and .10 are globally reachable by RFC; we refuse them anyway.

    Worth stating in a test, because the rule elsewhere is exactly
    ``is_global`` and this is the one place it is not. They are PCP anycast and
    NAT64 prefix discovery — protocol infrastructure, never a webhook target.
    """
    assert ipaddress.ip_address('192.0.0.9').is_global
    with pytest.raises(ValueError):
        validate_webhook_url('https://192.0.0.9/hook', allow_private=False)

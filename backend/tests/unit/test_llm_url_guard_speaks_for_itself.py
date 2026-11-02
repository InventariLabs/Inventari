"""The LLM URL guard refuses in its own voice, through the catalogue.

`guard_llm_url` delegates the check to the shared webhook validator, and
used to delegate the sentence too: an installer saving an AI connection
was told about "Webhook URL"s and pointed at WEBHOOKS_ALLOW_PRIVATE_
NETWORKS — a switch that has nothing to do with what they were
configuring, and one the two flags' documentation says is deliberately
separate. Every refusal now carries its own key, so an unresolvable name
(a typo) and a private address (a policy) stay different causes with
different sentences, the catalogue says them in the reader's language,
and the word "webhook" leaves this path never.
"""

from __future__ import annotations

import socket
from unittest.mock import patch

import pytest

from app.core.exceptions import ServiceRejectionError
from app.core.llm._outbound import guard_llm_url
from app.i18n.service import get_current_lang, set_current_lang

pytestmark = pytest.mark.unit


@pytest.fixture
def _no_dns(monkeypatch):
    """The resolver is stubbed: the guard's sentences are under test, not
    the network."""

    def refuse(name, port, *args, **kwargs):
        raise socket.gaierror(f'name or service not known: {name}')

    monkeypatch.setattr(socket, 'getaddrinfo', refuse)


@pytest.mark.parametrize(
    'url',
    [
        'http://10.0.0.5:11434/v1',
        'http://localhost:8000/v1',
        'http://no-such-host.invalid/v1',
        'ftp://provider.example.com/v1',
    ],
)
def test_no_refusal_speaks_of_webhooks(url: str, _no_dns):
    with pytest.raises(ServiceRejectionError) as caught:
        guard_llm_url(url)

    assert 'webhook' not in str(caught.value).lower()


def test_an_unresolvable_name_and_a_private_address_read_differently(_no_dns):
    """A typo and a policy are different causes; one sentence for both
    sends someone with a typo flipping a policy flag."""

    def resolve(name, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, '', ('10.0.0.5', 0))]

    with patch('socket.getaddrinfo', resolve):
        with pytest.raises(ServiceRejectionError) as private:
            guard_llm_url('http://10.0.0.5:11434/v1')
    with pytest.raises(ServiceRejectionError) as unresolved:
        guard_llm_url('http://no-such-host.invalid/v1')

    assert private.value.key == 'llm_base_url_private'
    assert unresolved.value.key == 'llm_base_url_unresolved'
    assert str(private.value) != str(unresolved.value)
    assert 'could not be resolved' in str(unresolved.value)
    assert 'private or internal' in str(private.value)


def test_a_loopback_name_has_its_own_key(_no_dns):
    """A loopback hostname is neither a private range nor an unresolved
    name; its own key lets the sentence name which one it was."""

    with pytest.raises(ServiceRejectionError) as caught:
        guard_llm_url('http://localhost:8000/v1')

    assert caught.value.key == 'llm_base_url_loopback'
    assert 'loopback' in str(caught.value)


@pytest.mark.parametrize(
    'url',
    [
        'http://10.0.0.5:11434/v1',
        'http://localhost:8000/v1',
    ],
)
def test_the_self_host_hint_names_the_llm_flag(url: str, _no_dns):
    with pytest.raises(ServiceRejectionError) as caught:
        guard_llm_url(url)

    assert 'LLM_ALLOW_PRIVATE_NETWORKS' in str(caught.value)
    assert 'WEBHOOKS_ALLOW_PRIVATE_NETWORKS' not in str(caught.value)


def test_a_disallowed_scheme_is_reworded_for_this_path(_no_dns):
    with pytest.raises(ServiceRejectionError) as caught:
        guard_llm_url('ftp://provider.example.com/v1')

    assert caught.value.key == 'llm_base_url_scheme'
    assert 'http or https' in str(caught.value)


@pytest.mark.parametrize(
    'url',
    [
        'http://10.0.0.5:11434/v1',
        'http://localhost:8000/v1',
    ],
)
def test_a_sentence_never_resumes_lowercase_after_the_hint(url: str, _no_dns):
    """The hint sometimes begins a sentence of its own; a refusal that
    reads "…provider. ask whoever…" is a splinter on the screen it lands on.
    It sends the reader to whoever runs the installation, not to the server's
    environment file."""

    with pytest.raises(ServiceRejectionError) as caught:
        guard_llm_url(url)

    message = str(caught.value)
    assert '. ask ' not in message
    assert 'ask whoever runs this installation' in message
    assert message.count('LLM_ALLOW_PRIVATE_NETWORKS') == 1
    assert '.env' not in message


@pytest.mark.parametrize('lang', ['en', 'pl', 'de', 'fr', 'es', 'pt'])
def test_an_unresolvable_public_name_says_nothing_of_the_private_network_flag(
    lang: str, _no_dns
):
    """A name that does not resolve is a typo or a missing DNS record, not
    a private address the policy refused. Naming the flag there sends an
    administrator with a mistyped host to loosen a security switch; the
    sentence says what to check instead."""

    previous = get_current_lang()
    set_current_lang(lang)
    try:
        with pytest.raises(ServiceRejectionError) as caught:
            guard_llm_url('https://nonexistent.invalid/v1')
    finally:
        set_current_lang(previous)

    text = str(caught.value)
    assert caught.value.key == 'llm_base_url_unresolved'
    assert 'nonexistent.invalid' in text
    assert 'LLM_ALLOW_PRIVATE_NETWORKS' not in text


def test_the_refusal_is_a_key_the_catalogue_speaks_in_the_request_language(_no_dns):
    """The raise site carries the key and its arguments; the sentence is
    the catalogue's, in the language the request asked for."""

    previous = get_current_lang()
    set_current_lang('pl')
    try:
        with pytest.raises(ServiceRejectionError) as caught:
            guard_llm_url('http://no-such-host.invalid/v1')
    finally:
        set_current_lang(previous)

    assert caught.value.key == 'llm_base_url_unresolved'
    assert caught.value.kwargs == {'host': 'no-such-host.invalid'}
    assert 'Nie udało się rozwiązać' in str(caught.value)
    assert 'could not be resolved' not in str(caught.value)


def test_allow_private_returns_the_hostname_for_a_local_name(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, 'LLM_ALLOW_PRIVATE_NETWORKS', True)

    def refuse(name, port, *args, **kwargs):
        raise socket.gaierror(f'name or service not known: {name}')

    monkeypatch.setattr(socket, 'getaddrinfo', refuse)

    assert guard_llm_url('http://ollama.lan:11434/v1') == 'ollama.lan'

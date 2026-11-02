"""A refused private address sends an organization administrator to the operator.

The refusal for a webhook (and for an AI connection) used to tell the reader
to set a variable in ``.env`` and restart the server. On an instance with
several organizations the reader is an administrator of one of them, not the
person who runs the installation, and has no ``.env`` to edit. The sentence now
says to ask whoever runs the installation, in every language; the name of the
setting stays so the operator knows what to look for.
"""

from __future__ import annotations

import pytest

from app.i18n.service import get_error_message

pytestmark = pytest.mark.unit

LANGUAGES = ['en', 'pl', 'de', 'fr', 'es', 'pt']
KEYS = [
    ('webhook_url_loopback', 'WEBHOOKS_ALLOW_PRIVATE_NETWORKS'),
    ('webhook_url_private', 'WEBHOOKS_ALLOW_PRIVATE_NETWORKS'),
    ('webhook_url_unresolved', 'WEBHOOKS_ALLOW_PRIVATE_NETWORKS'),
    ('webhook_url_rebinding', 'WEBHOOKS_ALLOW_PRIVATE_NETWORKS'),
    ('llm_base_url_loopback', 'LLM_ALLOW_PRIVATE_NETWORKS'),
    ('llm_base_url_private', 'LLM_ALLOW_PRIVATE_NETWORKS'),
]


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize(('key', 'setting'), KEYS)
def test_the_refusal_does_not_ask_the_reader_to_edit_the_server(
    language: str, key: str, setting: str
) -> None:
    message = get_error_message(key, language, host='nas.local', resolved='10.0.0.5')

    assert setting in message
    assert '.env' not in message
    assert '=true' not in message

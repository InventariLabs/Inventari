"""A demo visitor cannot be told where the inbox is unless the API says so.

The demo sends no real mail — Mailpit beside the stack catches everything, in
a public inbox — so the sign-in screen tells visitors where to look. The screen
is part of the frontend, but the URL is deployment configuration and travels
over ``GET /auth/init-status``, the unauthenticated call the SPA already makes
on every boot. These tests pin that contract from the API side: a demo answers
with the URL, an ordinary install answers with nothing and renders no notice.
"""

from __future__ import annotations

import pytest

from app.config import settings

pytestmark = pytest.mark.integration


class TestTheInitStatusNamesTheDemoInbox:
    def test_a_demo_serves_the_public_inbox_url(self, client, monkeypatch):
        monkeypatch.setattr(
            settings, 'DEMO_INBOX_URL', 'https://demo.example.com/mailpit/'
        )

        response = client.get('/api/v1/auth/init-status')

        assert response.status_code == 200
        assert response.json()['demo_inbox_url'] == 'https://demo.example.com/mailpit/'

    def test_an_ordinary_install_has_no_inbox_to_name(self, client, monkeypatch):
        """Empty means unset, and the screen must not render a bare link."""
        monkeypatch.setattr(settings, 'DEMO_INBOX_URL', '')

        response = client.get('/api/v1/auth/init-status')

        assert response.status_code == 200
        assert response.json()['demo_inbox_url'] is None
        # Existing callers keep what they had: the initialization answer is
        # still there and still authoritative.
        assert 'is_initialized' in response.json()

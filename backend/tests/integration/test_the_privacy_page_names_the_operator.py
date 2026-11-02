"""The privacy page names whoever runs this installation — from configuration.

The page is public and the text is the same for every install, so the one
thing that differs — who runs it and how to reach them — has to come from the
deployment, never from the code: a hard-coded name would make every
self-hosted copy claim to be somebody else's. It travels over
``GET /auth/init-status``, the unauthenticated call the SPA already makes on
every boot. Unset means ``None``, and the page says the operator has not
published a contact instead of rendering an empty one.
"""

from __future__ import annotations

import pytest

from app.config import settings

pytestmark = pytest.mark.integration


class TestTheInitStatusNamesTheOperator:
    def test_a_configured_install_serves_its_operator(self, client, monkeypatch):
        monkeypatch.setattr(settings, 'OPERATOR_NAME', 'Example Foods Ltd')
        monkeypatch.setattr(settings, 'OPERATOR_CONTACT', 'privacy@example.com')

        response = client.get('/api/v1/auth/init-status')

        assert response.status_code == 200
        assert response.json()['operator_name'] == 'Example Foods Ltd'
        assert response.json()['operator_contact'] == 'privacy@example.com'

    def test_an_unconfigured_install_names_nobody(self, client, monkeypatch):
        """Blank counts as unset: a line of spaces in .env is not a name."""
        monkeypatch.setattr(settings, 'OPERATOR_NAME', '')
        monkeypatch.setattr(settings, 'OPERATOR_CONTACT', '   ')

        response = client.get('/api/v1/auth/init-status')

        assert response.status_code == 200
        assert response.json()['operator_name'] is None
        assert response.json()['operator_contact'] is None

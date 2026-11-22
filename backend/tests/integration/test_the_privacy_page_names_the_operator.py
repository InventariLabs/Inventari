"""The privacy page names whoever runs this installation — from configuration.

The page is public and the text is the same for every install, so the one
thing that differs — who runs it and how to reach them — has to come from the
deployment, never from the code: a hard-coded name would make every
self-hosted copy claim to be somebody else's. It travels over
``GET /auth/init-status``, the unauthenticated call the SPA already makes on
every boot. Unset means ``None``, and the page says the operator has not
published a contact instead of rendering an empty one.

The same call carries how long the installation keeps its server logs: the
period is the operator's journald retention, so the page states what is
configured rather than a number of its own.
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


class TestTheInitStatusStatesTheLogRetention:
    """GDPR art. 13 asks for the storage period; the page cannot know it alone.

    The number is the operator's journald retention, configured on the host
    (DEPLOYMENT.md, "Keeping the server's logs"), so it comes from the server
    with the rest of the privacy page's configuration.
    """

    def test_a_configured_install_serves_its_retention(self, client, monkeypatch):
        monkeypatch.setattr(settings, 'LOG_RETENTION_DAYS', 30)

        response = client.get('/api/v1/auth/init-status')

        assert response.status_code == 200
        assert response.json()['log_retention_days'] == 30

    def test_the_documented_default_is_thirty_days(self, client):
        """The default matches DEPLOYMENT.md and the privacy page's wording."""
        assert settings.LOG_RETENTION_DAYS == 30

        response = client.get('/api/v1/auth/init-status')

        assert response.json()['log_retention_days'] == 30


class TestTheInitStatusServesTheConfiguredLogRetention:
    def test_the_configured_period_is_served_not_the_default(self, client, monkeypatch):
        """The privacy page states the period the installation sets.

        7 is not the schema default (30), so a response that stops reading
        the setting cannot pass by coincidence.
        """
        monkeypatch.setattr(settings, 'LOG_RETENTION_DAYS', 7)

        response = client.get('/api/v1/auth/init-status')

        assert response.status_code == 200
        assert response.json()['log_retention_days'] == 7

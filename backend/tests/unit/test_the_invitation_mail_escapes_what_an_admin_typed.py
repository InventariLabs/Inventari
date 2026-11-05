"""An invitation carries two values an admin typed into someone else's inbox.

The organization's name and, for a custom role, the role's name — used as it
was typed, because a name the organization chose has no translation to look
up. Both were interpolated straight into the HTML body. The attestation mail
next door has escaped its values since it was written; this one had not.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services.email_service import EmailService

pytestmark = pytest.mark.unit

MARKUP = '<img src=x onerror="alert(1)">'


def _rendered(organization_name: str, role: str) -> str:
    import asyncio

    captured: dict[str, str] = {}

    def _capture(to_email, subject, html, smtp_config=None):
        captured['html'] = html
        return True

    with patch.object(EmailService, 'send_email', side_effect=_capture):
        asyncio.run(
            EmailService.send_invitation_async(
                'invitee@example.com',
                '/join/abc',
                organization_name,
                role,
            )
        )
    return captured['html']


class TestTheValuesAnAdminControls:
    def test_the_organization_name_is_escaped(self) -> None:
        html = _rendered(MARKUP, 'admin')

        assert MARKUP not in html
        assert '&lt;img' in html

    def test_a_custom_role_name_is_escaped(self) -> None:
        html = _rendered('Acme', MARKUP)

        assert MARKUP not in html
        assert '&lt;img' in html

    def test_an_ordinary_name_still_reads_as_itself(self) -> None:
        html = _rendered('Acme Ltd', 'admin')

        assert 'Acme Ltd' in html

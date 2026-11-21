"""The invitation mail names the person who invited and the role as the app does.

The screen that issues an invitation, the join page and the members list call
the built-in level ``user`` "Member" and name the inviter; the mail has to say
the same, in the reader's language.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from app.services.email_service import EmailService

pytestmark = pytest.mark.unit


def _rendered(role: str, lang: str, inviter_name: str | None) -> str:
    captured: dict[str, str] = {}

    def _capture(to_email, subject, html, smtp_config=None):
        captured['html'] = html
        return True

    with patch.object(EmailService, 'send_email', side_effect=_capture):
        asyncio.run(
            EmailService.send_invitation_async(
                'invitee@example.com',
                '/join/abc',
                'Acme',
                role,
                lang=lang,
                inviter_name=inviter_name,
            )
        )
    return captured['html']


@pytest.mark.parametrize(
    ('lang', 'role', 'label'),
    [
        ('en', 'user', 'Member'),
        ('en', 'viewer', 'Viewer'),
        ('pl', 'manager', 'Menedżer'),
        ('de', 'user', 'Mitglied'),
        ('fr', 'user', 'Membre'),
        ('es', 'user', 'Miembro'),
        ('pt', 'user', 'Membro'),
    ],
)
def test_the_role_reads_as_it_does_in_the_app(lang: str, role: str, label: str) -> None:
    assert f'<b>{label}</b>' in _rendered(role, lang, None)


def test_the_inviter_is_named() -> None:
    html = _rendered('user', 'en', 'Ola Nowak')
    assert 'Ola Nowak has invited you' in html
    assert 'An administrator' not in html


def test_an_unnamed_inviter_falls_back_to_an_administrator() -> None:
    assert 'An administrator has invited you' in _rendered('user', 'en', None)


def test_the_inviters_name_is_escaped() -> None:
    html = _rendered('user', 'en', '<script>alert(1)</script>')
    assert '<script>' not in html

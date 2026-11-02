"""Every transactional email arrives in the same card.

The 20-line shell — max-width 600, the grey border, the rule above the
footer — was written out four times: registration, invitation, password
reset, and the equipment attestation in a module of its own. Restyling it
would have reached three of the four.
"""

from __future__ import annotations

import re

import pytest

from app.core.public_api import core_api
from app.services.email_service import (
    email_button,
    email_fallback_link,
    email_shell,
)

#: The marks that make the card what it is, in the order they appear.
CARD_MARKS = (
    '<html>',
    'max-width: 600px',
    'border: 1px solid #eee',
    '<h2 style="color: #2563eb;">',
    '<hr style="border: 0; border-top: 1px solid #eee; margin: 20px 0;">',
    '</html>',
)


def _rendered_emails() -> dict[str, str]:
    """One of each, built the way its own caller builds it."""
    from app.modules.equipment._attestation_email import _build_email_html

    return {
        'attestation': _build_email_html(
            assignee_name='Anna Kowalska',
            item_name='Laptop',
            attestation_url='https://example.test/attest/1',
            deadline='2026-10-01',
            custom_body=None,
        ),
        'shell': email_shell(
            'Heading',
            '            <p>body</p>\n'
            + email_button('https://example.test/go', 'Open')
            + '\n'
            + email_fallback_link('Or paste:', 'https://example.test/go'),
            'Sent automatically',
        ),
    }


@pytest.mark.unit
class TestEveryEmailArrivesInTheSameCard:
    @pytest.mark.parametrize('name', ['attestation', 'shell'])
    def test_it_is_the_same_card(self, name: str) -> None:
        html = _rendered_emails()[name]
        position = 0
        for mark in CARD_MARKS:
            found = html.find(mark, position)
            assert found >= 0, f'{name}: card is missing {mark!r}'
            position = found

    def test_the_module_goes_through_the_facade(self) -> None:
        """Not by importing `email_service`, which module code may not."""
        assert core_api.email.render_shell('H', '<p>b</p>', 'f') == email_shell(
            'H', '<p>b</p>', 'f'
        )

    def test_an_administrators_own_words_stay_inert(self) -> None:
        """The one part of the body a person types is escaped before it
        reaches the shell, which inserts markup as it is."""
        from app.modules.equipment._attestation_email import _build_email_html

        html = _build_email_html(
            assignee_name='Anna',
            item_name='Laptop',
            attestation_url='https://example.test/attest/1',
            deadline='2026-10-01',
            custom_body='<script>alert(1)</script>',
        )
        assert '<script>' not in html
        assert '&lt;script&gt;' in html

    def test_the_button_carries_the_link_once(self) -> None:
        button = email_button('https://example.test/go', 'Open')
        assert len(re.findall(r'https://example\.test/go', button)) == 1
        assert 'text-align: center' in button

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.modules.approvals import _services_notify


@pytest.fixture
def captured_email(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, str]]:
    """Run notify_rejection_async against stubbed CoreAPI, keeping the email."""
    sent: list[tuple[str, str, str]] = []

    async def _send(
        to: str,
        subject: str,
        html: str,
        smtp_config: dict[str, object] | None = None,
        *,
        organization_id: object = None,
    ) -> None:
        sent.append((to, subject, html))

    requester = SimpleNamespace(
        id=uuid4(), email='requester@example.com', preferred_language='en'
    )
    core_api = _services_notify.core_api
    monkeypatch.setattr(
        core_api.users, 'get_full_async', AsyncMock(return_value=requester)
    )
    monkeypatch.setattr(
        core_api.notifications, 'create_async', AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        core_api.notifications, 'publish_async', AsyncMock(return_value=None)
    )
    monkeypatch.setattr(core_api.email, 'send_async', _send)
    return sent


async def _notify(reason: str) -> None:
    await _services_notify.notify_rejection_async(
        MagicMock(),
        org_id=uuid4(),
        doc_id=uuid4(),
        request_id=uuid4(),
        requester_id=uuid4(),
        reason=reason,
    )


@pytest.mark.unit
class TestRejectionEmailEscaping:
    """the approver's free-text reason is pasted into an HTML mail.

    The approver is a trusted-ish colleague, but nothing stops them typing
    markup, and the requester's mail client would render it — a script tag or
    a spoofed "click here" link arriving from the deployment's own address.
    """

    async def test_markup_in_the_reason_is_escaped(
        self, captured_email: list[tuple[str, str, str]]
    ) -> None:
        await _notify('<script>alert(1)</script>')

        assert captured_email, 'no email was sent'
        html = captured_email[0][2]
        assert '<script>' not in html
        assert '&lt;script&gt;alert(1)&lt;/script&gt;' in html

    async def test_an_anchor_cannot_be_smuggled_in(
        self, captured_email: list[tuple[str, str, str]]
    ) -> None:
        """The mail already carries one legitimate link; the reason must not
        be able to add a second one pointing somewhere else."""
        await _notify('<a href="https://evil.example/pay">Pay now</a>')

        html = captured_email[0][2]
        assert html.count('<a href=') == 1
        assert '&lt;a href=&quot;https://evil.example/pay&quot;&gt;' in html

    async def test_plain_reason_survives_readable(
        self, captured_email: list[tuple[str, str, str]]
    ) -> None:
        await _notify('Budget exceeded for Q3')

        assert 'Budget exceeded for Q3' in captured_email[0][2]

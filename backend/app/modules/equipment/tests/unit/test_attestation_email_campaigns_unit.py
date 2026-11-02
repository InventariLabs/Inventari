"""Localized + escaped attestation emails.

Coverage:
1. ``launch_campaign`` and ``send_reminders`` produce HTML that uses
   ``markupsafe.escape`` on attacker-controlled strings (``assignee_name``,
   ``item_name``, custom bodies) so a malicious assignee name cannot
   inject scripts.
2. Default ``lang='en'`` is honoured, every supported language
   (``pl``, ``de``, ``fr``, ``es``) renders its own heading/greeting/
   button/subject/reminder prefix, and an unknown language falls back
   to English rather than raising.
3. A custom ``email_subject`` and ``email_body`` provided by the admin
   passes through verbatim (no re-translation).
4. The launch path uses the localized subject fallback when
   ``email_subject`` is ``None``.

Mirrors the email-assertion style of
``purchase_orders/tests/unit/test_purchase_orders_email_unit.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


def _make_campaign(
    *,
    email_subject: str | None = None,
    email_body: str | None = None,
    status: str = 'DRAFT',
    deadline: datetime | None = None,
) -> MagicMock:
    campaign = MagicMock()
    campaign.id = uuid4()
    campaign.organization_id = uuid4()
    campaign.email_subject = email_subject
    campaign.email_body = email_body
    campaign.status = status
    campaign.deadline = deadline or datetime.now(UTC) + timedelta(days=7)
    campaign.responses = []
    return campaign


def _make_assignment(
    *,
    email: str = 'alice@example.com',
    name: str = 'Alice',
    item_name: str = 'Laptop',
) -> MagicMock:
    assignment = MagicMock()
    assignment.id = uuid4()
    assignment.organization_id = uuid4()
    assignment.assigned_to_email = email
    assignment.assigned_to_name = name
    item = MagicMock()
    item.id = uuid4()
    item.name = item_name
    assignment.item = item
    return assignment


def _stub_db(
    campaign: MagicMock, assignments: list[MagicMock] | None = None
) -> MagicMock:
    """Build a DB mock that returns ``campaign`` and the given assignments."""
    db = MagicMock()

    campaign_result = MagicMock()
    campaign_result.scalars.return_value.first.return_value = campaign

    assign_result = MagicMock()
    assign_result.scalars.return_value.all.return_value = assignments or []

    db.execute = AsyncMock(side_effect=[campaign_result, assign_result])
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    return db


async def _call_launch(
    db: MagicMock,
    campaign_id: Any,
    org_id: Any,
    frontend_url: str = 'http://localhost:5173',
    lang: str | None = None,
) -> tuple[Any, str]:
    """Invoke ``launch_campaign`` and return ``(mock_core, html_body)``."""
    from app.modules.equipment import _attestation_campaigns as ac

    mock_core = MagicMock()
    send_mock = AsyncMock(return_value=True)
    mock_core.email.send_async = send_mock
    mock_core.audit_log.log_action_async = AsyncMock()
    # launch/reminders read the organization's clock for the printed
    # deadline day; UTC keeps those assertions reading as they always did.
    mock_core.organizations.timezone_async = AsyncMock(return_value=UTC)

    # Patch the ``core_api`` reference INSIDE the consumer module so we
    # override the import-time binding captured by
    # ``from app.core.public_api import core_api`` at line 17.
    with patch.object(ac, 'core_api', mock_core):
        if lang is None:
            await ac.launch_campaign(
                db, campaign_id, org_id, frontend_url, user_id=uuid4()
            )
        else:
            await ac.launch_campaign(
                db, campaign_id, org_id, frontend_url, lang=lang, user_id=uuid4()
            )

    if not send_mock.call_args_list:
        return mock_core, ''
    html_body = send_mock.call_args.kwargs['html_content']
    return mock_core, html_body


async def _call_send_reminders(
    db: MagicMock,
    campaign_id: Any,
    org_id: Any,
    frontend_url: str = 'http://localhost:5173',
    lang: str | None = None,
    tz: Any = UTC,
) -> tuple[Any, str, str]:
    """Invoke ``send_reminders`` and return ``(mock_core, subject, html_body)``."""
    from app.modules.equipment import _attestation_campaigns as ac

    mock_core = MagicMock()
    send_mock = AsyncMock(return_value=True)
    mock_core.email.send_async = send_mock
    mock_core.audit_log.log_action_async = AsyncMock()
    # launch/reminders read the organization's clock for the printed
    # deadline day; UTC keeps those assertions reading as they always did.
    mock_core.organizations.timezone_async = AsyncMock(return_value=tz)

    with patch.object(ac, 'core_api', mock_core):
        if lang is None:
            await ac.send_reminders(db, campaign_id, org_id, frontend_url)
        else:
            await ac.send_reminders(db, campaign_id, org_id, frontend_url, lang=lang)

    if not send_mock.call_args_list:
        return mock_core, '', ''
    call = send_mock.call_args.kwargs
    return mock_core, call.get('subject', ''), call.get('html_content', '')


# ---------------------------------------------------------------------------
# (1) HTML-escape contract — XSS prevention
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestReminderEmailPrintsTheOrgDay:
    async def test_reminder_prints_the_deadline_day_in_the_org_zone(self) -> None:
        """The reminder names the organization's deadline day, not UTC's.

        The stored deadline is a UTC instant whose UTC date is the next day
        for an org west of Greenwich: end of September 30 in Los Angeles is
        06:59 UTC on October 1st. Rendering the instant without the org's
        zone is how a reminder would have said "October 1st" to an org whose
        every screen says "September 30" — and this path had no test, so
        cutting ``deadline_tz`` from the reminder call went unnoticed.
        """
        from zoneinfo import ZoneInfo

        # End of September 30 in Los Angeles: 06:59 UTC on October 1st —
        # UTC's date is the next day, which is exactly the trap.
        deadline = datetime(2026, 10, 1, 6, 59, 59, 999999, tzinfo=UTC)
        campaign = _make_campaign(status='ACTIVE', deadline=deadline)
        response = MagicMock()
        response.status = 'PENDING'
        response.token_expires_at = datetime.now(UTC) + timedelta(days=7)
        response.reminder_sent_at = None
        # Its asset is still out: a returned one is no longer chased.
        response.assets_returned = False
        response.assignee_name = 'Alice'
        response.assignee_email = 'alice@example.com'
        response.token = 'tok'
        response.items = [MagicMock(item_name='Laptop')]
        campaign.responses = [response]
        db = _stub_db(campaign, [MagicMock()])

        _, _, html = await _call_send_reminders(
            db,
            campaign.id,
            campaign.organization_id,
            tz=ZoneInfo('America/Los_Angeles'),
        )

        assert '2026-09-30' in html
        assert '2026-10-01' not in html


@pytest.mark.unit
class TestLaunchCampaignEmailEscaping:
    async def test_assignee_name_with_html_is_escaped(self) -> None:
        """Attacker-controlled assignee_name must be HTML-escaped, not raw."""
        campaign = _make_campaign()
        assignment = _make_assignment(name='<script>alert("xss")</script>')
        db = _stub_db(campaign, [assignment])

        _, html = await _call_launch(db, campaign.id, campaign.organization_id)

        assert '<script>' not in html
        assert '&lt;script&gt;' in html

    async def test_item_name_with_html_is_escaped(self) -> None:
        """Attacker-controlled item_name must be HTML-escaped, not raw."""
        campaign = _make_campaign()
        assignment = _make_assignment(item_name='<img src=x onerror=alert(1)>')
        db = _stub_db(campaign, [assignment])

        _, html = await _call_launch(db, campaign.id, campaign.organization_id)

        assert '<img' not in html
        assert '&lt;img' in html

    async def test_custom_email_body_with_html_is_escaped(self) -> None:
        """Custom admin body containing raw HTML must still be escaped."""
        campaign = _make_campaign(email_body='<script>alert("body-xss")</script>')
        assignment = _make_assignment()
        db = _stub_db(campaign, [assignment])

        _, html = await _call_launch(db, campaign.id, campaign.organization_id)

        assert '<script>' not in html
        assert '&lt;script&gt;' in html


# ---------------------------------------------------------------------------
# (2) Localization contract — body, subject, greeting
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    'lang,expected_substrings',
    [
        ('en', ('Asset Attestation', 'Hello', 'Confirm / Report Issue')),
        ('pl', ('Atestacja', 'Witaj', 'Potwierdź / Zgłoś problem')),
        ('de', ('Attestierung', 'Hallo', 'Bestätigen / Problem melden')),
        ('fr', ('Attestation d', 'Bonjour', 'Confirmer / Signaler un problème')),
        ('es', ('Atestación', 'Hola', 'Confirmar / Reportar problema')),
    ],
)
class TestLaunchCampaignEmailLocalization:
    async def test_all_five_languages_render_localized_body(
        self, lang: str, expected_substrings: tuple[str, str, str]
    ) -> None:
        campaign = _make_campaign()  # no custom subject/body
        assignment = _make_assignment(name='<b>Alice</b>', item_name='Laptop')
        db = _stub_db(campaign, [assignment])

        _, html = await _call_launch(
            db, campaign.id, campaign.organization_id, lang=lang
        )

        for needle in expected_substrings:
            assert needle in html, f'lang={lang}: expected {needle!r} in HTML body'
        # And HTML-escape still in effect.
        assert '<b>Alice</b>' not in html
        assert '&lt;b&gt;Alice&lt;/b&gt;' in html


@pytest.mark.unit
@pytest.mark.parametrize(
    'lang,expected_subject',
    [
        ('en', 'Asset attestation required'),
        ('pl', 'Atestacja sprzętu — wymagane działanie'),
        ('de', 'Attestierung erforderlich'),
        ('fr', "Attestation d'équipement requise"),
        ('es', 'Atestación de equipo requerida'),
    ],
)
class TestLaunchCampaignSubjectLocalization:
    async def test_default_subject_is_localized_per_lang(
        self, lang: str, expected_subject: str
    ) -> None:
        campaign = _make_campaign(email_subject=None)
        assignment = _make_assignment()
        db = _stub_db(campaign, [assignment])

        mock_core, _ = await _call_launch(
            db, campaign.id, campaign.organization_id, lang=lang
        )

        send_mock = mock_core.email.send_async
        subject = send_mock.call_args.kwargs['subject']
        assert subject == expected_subject


@pytest.mark.unit
class TestLaunchCampaignCustomSubjectPreserved:
    async def test_custom_subject_overrides_localized_default(self) -> None:
        """Admin-provided email_subject passes through verbatim."""
        campaign = _make_campaign(email_subject='<Custom> Subject XYZ')
        assignment = _make_assignment()
        db = _stub_db(campaign, [assignment])

        mock_core, _ = await _call_launch(
            db, campaign.id, campaign.organization_id, lang='pl'
        )

        send_mock = mock_core.email.send_async
        assert send_mock.call_args.kwargs['subject'] == '<Custom> Subject XYZ'


# ---------------------------------------------------------------------------
# (3) Reminder localization contract
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    'lang,expected_prefix',
    [
        ('en', '[Reminder] '),
        ('pl', '[Przypomnienie] '),
        ('de', '[Erinnerung] '),
        ('fr', '[Rappel] '),
        ('es', '[Recordatorio] '),
    ],
)
class TestSendRemindersEmailLocalization:
    async def test_reminder_subject_prefix_is_localized(
        self, lang: str, expected_prefix: str
    ) -> None:
        campaign = _make_campaign(email_subject=None, status='ACTIVE')
        response = MagicMock()
        response.id = uuid4()
        response.assignee_email = 'bob@example.com'
        response.assignee_name = 'Bob'
        response.status = 'PENDING'
        response.token = 'tok-xyz'
        response.token_expires_at = datetime.now(UTC) + timedelta(days=3)
        response.reminder_sent_at = None
        # Its asset is still out: a returned one is no longer chased.
        response.assets_returned = False
        campaign.responses = [response]

        # _get_campaign → returns campaign. send_reminders iterates campaign.responses
        # so we don't need a second db.execute.
        db = MagicMock()
        campaign_result = MagicMock()
        campaign_result.scalars.return_value.first.return_value = campaign
        db.execute = AsyncMock(return_value=campaign_result)
        db.commit = AsyncMock()

        _, subject, _ = await _call_send_reminders(
            db, campaign.id, campaign.organization_id, lang=lang
        )

        assert subject.startswith(expected_prefix), (
            f'lang={lang}: expected subject to start with {expected_prefix!r}, got {subject!r}'
        )


# ---------------------------------------------------------------------------
# (4) Fallback & edge-case contract
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEmailLanguageFallback:
    async def test_unknown_lang_falls_back_to_english(self) -> None:
        """Unknown 'lang' values must not raise; English is the safe default."""
        campaign = _make_campaign()
        assignment = _make_assignment(name='Alice', item_name='Laptop')
        db = _stub_db(campaign, [assignment])

        _, html = await _call_launch(
            db, campaign.id, campaign.organization_id, lang='xx'
        )

        assert 'Asset Attestation' in html
        assert 'Hello' in html

    async def test_default_lang_is_english_when_unspecified(self) -> None:
        """``launch_campaign`` with no ``lang`` arg defaults to English."""
        campaign = _make_campaign()
        assignment = _make_assignment()
        db = _stub_db(campaign, [assignment])

        # No lang passed (covers the localized path and the legacy default).
        _, html = await _call_launch(db, campaign.id, campaign.organization_id)
        assert 'Asset Attestation' in html


# ---------------------------------------------------------------------------
# (5) The printed deadline day is the organization's day, not UTC's
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDeadlinePrintedInOrganizationDay:
    """``_build_email_html`` prints a *day*, and a stored deadline is a UTC
    instant. The two disagree for any organization west of Greenwich: the end
    of its 25th is stored as 04:59:59 UTC on the 26th, and a bare strftime
    printed the 26th in the invitation while the screen named the 25th."""

    def test_west_of_utc_prints_the_org_day_not_the_next_one(self) -> None:
        from zoneinfo import ZoneInfo

        from app.modules.equipment._attestation_email import _build_email_html

        # End of the 25th in New York (UTC-4 in September), as stored.
        deadline = datetime(2026, 9, 26, 3, 59, 59, 999999, tzinfo=UTC)
        html = _build_email_html(
            assignee_name='Alice',
            item_name='Laptop',
            attestation_url='https://example.com/attest',
            deadline=deadline,
            custom_body=None,
            deadline_tz=ZoneInfo('America/New_York'),
        )

        assert '2026-09-25' in html
        assert '2026-09-26' not in html

    def test_bare_utc_instant_prints_its_own_date(self) -> None:
        """Without a zone the builder prints the instant's own date — the
        historical behaviour, kept for callers that pass a zone-free day."""
        from app.modules.equipment._attestation_email import _build_email_html

        deadline = datetime(2026, 9, 26, 3, 59, 59, 999999, tzinfo=UTC)
        html = _build_email_html(
            assignee_name='Alice',
            item_name='Laptop',
            attestation_url='https://example.com/attest',
            deadline=deadline,
            custom_body=None,
        )

        assert '2026-09-26' in html

    async def test_launch_passes_the_organization_clock(self) -> None:
        """``launch_campaign`` reads the organization's timezone and hands it
        to the builder, so the mail names the day the admin picked."""
        from zoneinfo import ZoneInfo

        from app.modules.equipment import _attestation_campaigns as ac

        campaign = _make_campaign(
            deadline=datetime(2026, 9, 26, 3, 59, 59, 999999, tzinfo=UTC)
        )
        assignment = _make_assignment()
        db = _stub_db(campaign, [assignment])

        mock_core = MagicMock()
        send_mock = AsyncMock(return_value=True)
        mock_core.email.send_async = send_mock
        mock_core.audit_log.log_action_async = AsyncMock()
        mock_core.organizations.timezone_async = AsyncMock(
            return_value=ZoneInfo('America/New_York')
        )

        with patch.object(ac, 'core_api', mock_core):
            await ac.launch_campaign(
                db, campaign.id, campaign.organization_id, user_id=uuid4()
            )

        html = send_mock.call_args.kwargs['html_content']
        assert '2026-09-25' in html
        assert '2026-09-26' not in html

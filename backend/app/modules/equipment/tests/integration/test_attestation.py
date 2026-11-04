"""Integration tests for Asset Attestation (Audit Campaigns)."""

import uuid
from typing import Any

import pytest
from fastapi import status
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models.item import Item
from app.models.storage_location import StorageLocation
from app.modules.equipment.models import (
    AuditCampaign,
    AuditResponse,
)


def _make_deadline(days: int = 30) -> str:
    """Return ISO datetime string N days from now (UTC)."""
    from datetime import UTC, datetime, timedelta

    return (datetime.now(UTC) + timedelta(days=days)).isoformat()


def _checkout(
    client: TestClient,
    headers: dict[str, str],
    item_id: Any,
    name: str = 'Alice',
    email: str = 'alice@example.com',
) -> None:
    r = client.post(
        '/api/v1/equipment/assignments',
        headers=headers,
        json={
            'item_id': str(item_id),
            'assigned_to_name': name,
            'assigned_to_email': email,
        },
    )
    r.raise_for_status()


# ---------------------------------------------------------------------------
# Campaign CRUD + Launch
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestAuditCampaign:
    """Tests for campaign creation, listing, and launch."""

    def test_create_campaign_success(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        """POST /equipment/campaigns creates a DRAFT campaign."""
        payload = {
            'name': 'Q1 Asset Audit',
            'deadline': _make_deadline(30),
            'scope_type': 'ALL',
            'reminder_days_before': 3,
        }
        r = client.post(
            '/api/v1/equipment/campaigns', headers=eq_auth_headers, json=payload
        )

        assert r.status_code == status.HTTP_201_CREATED
        data = r.json()
        assert data['name'] == 'Q1 Asset Audit'
        assert data['status'] == 'DRAFT'
        assert data['launched_at'] is None

    def test_deadline_stays_on_the_day_the_form_chose(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_org: Any,
        db_session: Any,
    ) -> None:
        """The chosen day survives the round trip through the org's clock.

        The form sent the end of 30 September in Warsaw
        (2026-09-30T21:59:59Z in the review's example). Pinning 23:59:59 onto
        that instant in UTC pushed the deadline into 1 October for everyone
        east of Greenwich, and the register then advertised a day nobody
        picked. The day is taken from the org's clock and the test picks
        tomorrow, so it holds at any hour the suite runs.
        """
        from datetime import UTC, datetime, timedelta
        from zoneinfo import ZoneInfo

        tz = ZoneInfo('Europe/Warsaw')
        eq_org.timezone = 'Europe/Warsaw'
        db_session.commit()

        day = (datetime.now(tz) + timedelta(days=1)).date()
        arrival = datetime(
            day.year, day.month, day.day, 23, 59, 59, tzinfo=tz
        ).astimezone(UTC)

        r = client.post(
            '/api/v1/equipment/campaigns',
            headers=eq_auth_headers,
            json={
                'name': 'Warsaw Deadline',
                'deadline': arrival.isoformat(),
                'scope_type': 'ALL',
            },
        )
        assert r.status_code == status.HTTP_201_CREATED
        stored = datetime.fromisoformat(r.json()['deadline'].replace('Z', '+00:00'))
        # Still the chosen day in Warsaw: end of that day, not the UTC day's
        # end rendered as the next morning.
        assert stored == arrival.replace(microsecond=999999)
        assert stored.astimezone(tz).date() == day

    def test_an_arrival_inside_the_org_day_pins_that_day_east_of_utc(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_org: Any,
        db_session: Any,
    ) -> None:
        """The write half of the form fix (review 2026-09-22, criterion 1b).

        The form now sends noon of the picked day in the *organization's*
        zone, so the day it reads off the arrival is the day the admin
        picked. The old shape — an instant in the *browser's* zone — moved
        the stored day one forward for every organization east of the
        reader: a Warsaw admin picking "Sep 30" for this Tokyo organization
        stored October 1st, and every screen but the form said so.
        """
        from datetime import UTC, datetime, timedelta
        from zoneinfo import ZoneInfo

        tz = ZoneInfo('Asia/Tokyo')
        eq_org.timezone = 'Asia/Tokyo'
        db_session.commit()

        # Noon of tomorrow on the org's clock — what instantInsideDay now
        # sends. Tomorrow keeps the test true at any hour it runs.
        day = (datetime.now(tz) + timedelta(days=1)).date()
        arrival = datetime(day.year, day.month, day.day, 12, 0, 0, tzinfo=tz)
        r = client.post(
            '/api/v1/equipment/campaigns',
            headers=eq_auth_headers,
            json={
                'name': 'Tokyo Deadline',
                'deadline': arrival.astimezone(UTC).isoformat(),
                'scope_type': 'ALL',
            },
        )
        assert r.status_code == status.HTTP_201_CREATED
        stored = datetime.fromisoformat(r.json()['deadline'].replace('Z', '+00:00'))
        # End of the picked day in the org's zone — not the next day.
        assert stored.astimezone(tz).date() == day

    def test_deadline_utc_organization_keeps_its_own_day_end(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        """For an org on UTC the old behavior was already right: the end of
        the UTC day. The timezone-aware path must not change that."""
        from datetime import UTC, datetime, timedelta

        day = (datetime.now(UTC) + timedelta(days=1)).date()
        r = client.post(
            '/api/v1/equipment/campaigns',
            headers=eq_auth_headers,
            json={
                'name': 'UTC Deadline',
                'deadline': datetime(
                    day.year, day.month, day.day, 12, 0, 0, tzinfo=UTC
                ).isoformat(),
                'scope_type': 'ALL',
            },
        )
        assert r.status_code == status.HTTP_201_CREATED
        stored = datetime.fromisoformat(r.json()['deadline'].replace('Z', '+00:00'))
        assert stored == datetime(
            day.year, day.month, day.day, 23, 59, 59, 999999, tzinfo=UTC
        )

    def test_today_stays_creatable_after_the_org_afternoon(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_org: Any,
        db_session: Any,
    ) -> None:
        """ "Today" is a legal pick for the whole of the organization's day.

        The form sends noon of the picked day on the org's clock, and the
        schema validator used to compare that instant with "now": from the
        org's noon onward the arrival was already past, so picking today was
        refused for half of the org's day — while dev accepted it. The check
        now lives where the org's clock is known and tests the stored value
        (the day's end): the picked day is over for the org exactly when
        creation must refuse.

        The zone is picked from a spread covering every hour, so the "org is
        in its afternoon" premise holds at whatever moment the suite runs.
        """
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo

        # UTC-11 … UTC+14, six steps: at any UTC moment at least one of
        # these zones reads an hour between 13 and 22 local.
        candidates = [
            'Etc/GMT+11',
            'Etc/GMT+5',
            'Etc/GMT',
            'Etc/GMT-5',
            'Etc/GMT-9',
            'Etc/GMT-14',
        ]
        zone_name = next(
            name for name in candidates if 13 <= datetime.now(ZoneInfo(name)).hour <= 22
        )
        eq_org.timezone = zone_name
        db_session.commit()

        tz = ZoneInfo(zone_name)
        org_today = datetime.now(tz).date()
        # Noon of the org's today — the instant instantInsideDay sends.
        noon = datetime(
            org_today.year, org_today.month, org_today.day, 12, 0, 0, tzinfo=tz
        )

        r = client.post(
            '/api/v1/equipment/campaigns',
            headers=eq_auth_headers,
            json={
                'name': 'Today, Org Afternoon',
                'deadline': noon.astimezone(ZoneInfo('UTC')).isoformat(),
                'scope_type': 'ALL',
            },
        )
        assert r.status_code == status.HTTP_201_CREATED
        stored = datetime.fromisoformat(r.json()['deadline'].replace('Z', '+00:00'))
        assert stored.astimezone(tz).date().isoformat() == org_today.isoformat()

        # And the org's yesterday is refused: its end is already gone.
        yesterday = org_today - timedelta(days=1)
        noon_yesterday = datetime(
            yesterday.year, yesterday.month, yesterday.day, 12, 0, 0, tzinfo=tz
        )
        r = client.post(
            '/api/v1/equipment/campaigns',
            headers=eq_auth_headers,
            json={
                'name': 'Yesterday, Refused',
                'deadline': noon_yesterday.astimezone(ZoneInfo('UTC')).isoformat(),
                'scope_type': 'ALL',
            },
        )
        assert r.status_code == 400
        assert 'today or later' in r.json()['detail']['message']

    def test_list_campaigns_org_scoped(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        """GET /equipment/campaigns returns only campaigns for the user's org."""
        for name in ('Audit A', 'Audit B'):
            client.post(
                '/api/v1/equipment/campaigns',
                headers=eq_auth_headers,
                json={'name': name, 'deadline': _make_deadline(30)},
            )

        r = client.get('/api/v1/equipment/campaigns', headers=eq_auth_headers)
        assert r.status_code == status.HTTP_200_OK
        names = [c['name'] for c in r.json()['items']]
        assert 'Audit A' in names
        assert 'Audit B' in names

    def test_launch_campaign_creates_responses(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        """Launching a campaign creates AuditResponse records for active assignments."""
        _checkout(client, eq_auth_headers, eq_item.id)

        # Create campaign
        payload = {'name': 'Full Launch Test', 'deadline': _make_deadline(14)}
        create_r = client.post(
            '/api/v1/equipment/campaigns', headers=eq_auth_headers, json=payload
        )
        campaign_id = create_r.json()['id']

        # Launch
        launch_r = client.post(
            f'/api/v1/equipment/campaigns/{campaign_id}/launch', headers=eq_auth_headers
        )
        assert launch_r.status_code == status.HTTP_200_OK
        data = launch_r.json()
        assert data['responses_created'] == 1

        # Campaign should be ACTIVE now
        detail_r = client.get(
            f'/api/v1/equipment/campaigns/{campaign_id}', headers=eq_auth_headers
        )
        assert detail_r.status_code == status.HTTP_200_OK
        detail = detail_r.json()
        assert detail['status'] == 'ACTIVE'
        assert detail['stats']['total'] == 1
        assert detail['stats']['pending'] == 1

    def test_launch_campaign_skips_no_email_assignments(
        self, client: TestClient, eq_auth_headers: dict[str, str], eq_item: Item
    ) -> None:
        """Assignment without email is skipped but doesn't fail the launch."""
        # Checkout without email
        client.post(
            '/api/v1/equipment/assignments',
            headers=eq_auth_headers,
            json={'item_id': str(eq_item.id), 'assigned_to_name': 'Bob (no email)'},
        )

        payload = {'name': 'Partial Email Test', 'deadline': _make_deadline(14)}
        create_r = client.post(
            '/api/v1/equipment/campaigns', headers=eq_auth_headers, json=payload
        )
        campaign_id = create_r.json()['id']

        launch_r = client.post(
            f'/api/v1/equipment/campaigns/{campaign_id}/launch', headers=eq_auth_headers
        )
        assert launch_r.status_code == status.HTTP_200_OK
        data = launch_r.json()
        assert data['responses_created'] == 0
        assert data['skipped_no_email'] == 1

    def test_launch_already_active_returns_400(
        self, client: TestClient, eq_auth_headers: dict[str, str], eq_item: Item
    ) -> None:
        """Attempting to re-launch an ACTIVE campaign returns 400."""
        _checkout(client, eq_auth_headers, eq_item.id)
        payload = {'name': 'Duplicate Launch', 'deadline': _make_deadline(14)}
        campaign_id = client.post(
            '/api/v1/equipment/campaigns', headers=eq_auth_headers, json=payload
        ).json()['id']

        client.post(
            f'/api/v1/equipment/campaigns/{campaign_id}/launch', headers=eq_auth_headers
        )

        # Second launch should fail
        r = client.post(
            f'/api/v1/equipment/campaigns/{campaign_id}/launch', headers=eq_auth_headers
        )
        assert r.status_code == status.HTTP_400_BAD_REQUEST

    def test_complete_campaign(
        self, client: TestClient, eq_auth_headers: dict[str, str], eq_item: Item
    ) -> None:
        """POST /campaigns/{id}/complete moves ACTIVE → COMPLETED."""
        _checkout(client, eq_auth_headers, eq_item.id)
        payload = {'name': 'Complete Me', 'deadline': _make_deadline(14)}
        campaign_id = client.post(
            '/api/v1/equipment/campaigns', headers=eq_auth_headers, json=payload
        ).json()['id']
        client.post(
            f'/api/v1/equipment/campaigns/{campaign_id}/launch', headers=eq_auth_headers
        )

        r = client.post(
            f'/api/v1/equipment/campaigns/{campaign_id}/complete',
            headers=eq_auth_headers,
        )
        assert r.status_code == status.HTTP_200_OK
        assert r.json()['status'] == 'COMPLETED'

    def test_launch_skips_assignment_to_soft_deleted_item(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        eq_storage_location: StorageLocation,
        db_session: Session,
    ) -> None:
        """Active assignment whose Item is soft-deleted must NOT be attested.

        Documents the deliberate semantics introduced when switching from
        ``JOIN Item`` (no soft-delete filter) to ``core_api.items.list_async``
        (which filters out ``is_deleted=True`` items). CoreAPI exclusion is
        the safer default — attesters must not receive requests about
        retired assets.
        """
        from datetime import UTC, datetime

        from app.models.item import Item

        _checkout(client, eq_auth_headers, eq_item.id)

        # Soft-delete the item AFTER the assignment was created
        item = db_session.get(Item, eq_item.id)
        assert item is not None
        item.is_deleted = True
        item.deleted_at = datetime.now(UTC)
        db_session.commit()

        payload = {
            'name': 'Soft Delete Skip Test',
            'deadline': _make_deadline(14),
            'scope_type': 'STORAGE',
            'scope_filter_id': str(eq_storage_location.id),
        }
        campaign_id = client.post(
            '/api/v1/equipment/campaigns', headers=eq_auth_headers, json=payload
        ).json()['id']

        launch_r = client.post(
            f'/api/v1/equipment/campaigns/{campaign_id}/launch', headers=eq_auth_headers
        )
        # No assignable items remain in storage scope -> the refusal that names
        # that scope. It is a catalogue key, so the message is in the reader's
        # language; the English here is the test client's default.
        assert launch_r.status_code == status.HTTP_400_BAD_REQUEST
        assert (
            launch_r.json()['detail']['message']
            == 'No active assignments found for the configured scope'
        )

    def test_the_refusal_answers_in_the_language_the_request_asks_in(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_storage_location: StorageLocation,
    ) -> None:
        """A Polish reader gets the Polish sentence, from the same key."""
        campaign_id = client.post(
            '/api/v1/equipment/campaigns',
            headers=eq_auth_headers,
            json={
                'name': 'Polish Refusal',
                'deadline': _make_deadline(14),
                'scope_type': 'STORAGE',
                'scope_filter_id': str(eq_storage_location.id),
            },
        ).json()['id']

        launch_r = client.post(
            f'/api/v1/equipment/campaigns/{campaign_id}/launch',
            headers={**eq_auth_headers, 'Accept-Language': 'pl'},
        )
        assert launch_r.status_code == status.HTTP_400_BAD_REQUEST
        body = launch_r.json()['detail']
        assert body['message'] == ('W wybranym zakresie nie ma aktywnych wydań sprzętu')
        # The language this response claims is the language it speaks.
        assert body.get('lang') == 'pl'


# ---------------------------------------------------------------------------
# Public token flow
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestAttestationPublic:
    """Tests for zero-login public confirm/dispute endpoints."""

    def _setup_active_response(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> str:
        """Helper: checkout item, create + launch campaign, return token."""
        _checkout(client, eq_auth_headers, eq_item.id)
        campaign_id = client.post(
            '/api/v1/equipment/campaigns',
            headers=eq_auth_headers,
            json={'name': 'Token Test Campaign', 'deadline': _make_deadline(14)},
        ).json()['id']
        client.post(
            f'/api/v1/equipment/campaigns/{campaign_id}/launch', headers=eq_auth_headers
        )
        response = db_session.scalars(
            select(AuditResponse).where(AuditResponse.campaign_id == campaign_id)
        ).first()
        assert response is not None
        return response.token

    def test_get_attestation_valid_token(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        """GET /public/attestation/{token} returns response details."""
        token = self._setup_active_response(
            client, eq_auth_headers, eq_item, db_session
        )
        r = client.get(f'/public/attestation/{token}')
        assert r.status_code == status.HTTP_200_OK
        data = r.json()
        assert data['status'] == 'PENDING'
        assert data['assignee_email'] == 'alice@example.com'
        # Response must surface the asset so the public page can show
        # the attester *what* they are confirming.
        assert data['item_name'] == eq_item.name
        assert data['serial_number'] == 'SN-001'

    def test_confirm_valid_token(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        """POST /public/attestation/{token}/confirm sets status to CONFIRMED."""
        token = self._setup_active_response(
            client, eq_auth_headers, eq_item, db_session
        )
        r = client.post(f'/public/attestation/{token}/confirm')
        assert r.status_code == status.HTTP_200_OK
        assert r.json()['status'] == 'CONFIRMED'

    def test_confirm_idempotent(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        """Confirming twice returns CONFIRMED without error."""
        token = self._setup_active_response(
            client, eq_auth_headers, eq_item, db_session
        )
        client.post(f'/public/attestation/{token}/confirm')
        r = client.post(f'/public/attestation/{token}/confirm')
        assert r.status_code == status.HTTP_200_OK
        assert r.json()['status'] == 'CONFIRMED'

    def test_dispute_valid_token(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        """POST /public/attestation/{token}/dispute sets DISPUTED with reason."""
        token = self._setup_active_response(
            client, eq_auth_headers, eq_item, db_session
        )
        r = client.post(
            f'/public/attestation/{token}/dispute',
            json={'dispute_type': 'MISSING', 'reason': 'I no longer have this item'},
        )
        assert r.status_code == status.HTTP_200_OK
        data = r.json()
        assert data['status'] == 'DISPUTED'
        assert data['dispute_type'] == 'MISSING'
        assert 'no longer' in data['dispute_reason']

    def test_invalid_token_returns_404(self, client: TestClient) -> None:
        r = client.get('/public/attestation/totally-invalid-token-xyz')
        assert r.status_code == status.HTTP_404_NOT_FOUND

    def test_confirm_invalid_token_returns_404(self, client: TestClient) -> None:
        r = client.post('/public/attestation/totally-invalid-token-xyz/confirm')
        assert r.status_code == status.HTTP_404_NOT_FOUND

    def test_dispute_invalid_token_returns_404(self, client: TestClient) -> None:
        r = client.post(
            '/public/attestation/totally-invalid-token-xyz/dispute',
            json={'dispute_type': 'MISSING', 'reason': 'gone'},
        )
        assert r.status_code == status.HTTP_404_NOT_FOUND

    def test_dispute_expired_token_returns_410(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        from datetime import UTC, datetime, timedelta

        token = self._setup_active_response(
            client, eq_auth_headers, eq_item, db_session
        )
        response = db_session.scalars(
            select(AuditResponse).where(AuditResponse.token == token)
        ).first()
        assert response is not None
        response.token_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db_session.commit()
        r = client.post(
            f'/public/attestation/{token}/dispute',
            json={'dispute_type': 'MISSING', 'reason': 'gone'},
        )
        assert r.status_code == status.HTTP_410_GONE

    def test_expired_token_returns_410(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        """Expired token confirms as 410 Gone."""
        from datetime import UTC, datetime, timedelta

        token = self._setup_active_response(
            client, eq_auth_headers, eq_item, db_session
        )

        # Manually expire the token
        response = db_session.scalars(
            select(AuditResponse).where(AuditResponse.token == token)
        ).first()
        assert response is not None
        response.token_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db_session.commit()

        r = client.post(f'/public/attestation/{token}/confirm')
        assert r.status_code == status.HTTP_410_GONE

    def test_deadline_at_midnight_means_end_of_day(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        """a deadline is a day, not a moment.

        A client that sends midnight of day D ("last day to answer" read as
        "start of day D") used to expire every token the moment day D began.
        The service pins the contract on write: the stored deadline is the end
        of the deadline's own day, and the launch token is valid until then.
        """
        from datetime import UTC, datetime, timedelta

        _checkout(client, eq_auth_headers, eq_item.id)

        day_d = (datetime.now(UTC) + timedelta(days=14)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        payload = {
            'name': 'Midnight Deadline',
            'deadline': day_d.isoformat(),
        }
        create_r = client.post(
            '/api/v1/equipment/campaigns', headers=eq_auth_headers, json=payload
        )
        assert create_r.status_code == status.HTTP_201_CREATED
        campaign_id = create_r.json()['id']

        launch_r = client.post(
            f'/api/v1/equipment/campaigns/{campaign_id}/launch',
            headers=eq_auth_headers,
        )
        assert launch_r.status_code == status.HTTP_200_OK

        campaign = db_session.scalars(
            select(AuditCampaign).where(AuditCampaign.id == campaign_id)
        ).first()
        assert campaign is not None
        # The contract: stored as the end of day D, in the deadline's own zone.
        assert campaign.deadline == day_d.replace(
            hour=23, minute=59, second=59, microsecond=999999
        )

        response = db_session.scalars(
            select(AuditResponse).where(AuditResponse.campaign_id == campaign_id)
        ).first()
        assert response is not None
        assert response.token_expires_at == campaign.deadline
        # The email still prints the day, not the time of day.
        from app.modules.equipment._attestation_email import _build_email_html

        html = _build_email_html(
            assignee_name='Alice',
            item_name='ThinkPad X1 Carbon',
            attestation_url='http://test',
            deadline=campaign.deadline,
            custom_body=None,
            lang='en',
        )
        assert day_d.strftime('%Y-%m-%d') in html


# ---------------------------------------------------------------------------
# Reminders
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestAttestationReminders:
    """Tests for reminder dispatch logic."""

    def test_manual_remind_sends_to_pending(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        """POST /campaigns/{id}/remind reports reminders_sent count."""
        _checkout(client, eq_auth_headers, eq_item.id)
        campaign_id = client.post(
            '/api/v1/equipment/campaigns',
            headers=eq_auth_headers,
            json={'name': 'Reminder Test', 'deadline': _make_deadline(14)},
        ).json()['id']
        client.post(
            f'/api/v1/equipment/campaigns/{campaign_id}/launch', headers=eq_auth_headers
        )

        r = client.post(
            f'/api/v1/equipment/campaigns/{campaign_id}/remind', headers=eq_auth_headers
        )
        assert r.status_code == status.HTTP_200_OK
        # email_sent may be 0 if SMTP not configured — just verify the key exists
        assert 'reminders_sent' in r.json()

    def test_remind_does_not_send_to_confirmed(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        """CONFIRMED responses are not re-sent reminders."""
        _checkout(client, eq_auth_headers, eq_item.id)
        campaign_id = client.post(
            '/api/v1/equipment/campaigns',
            headers=eq_auth_headers,
            json={'name': 'Confirmed Reminder', 'deadline': _make_deadline(14)},
        ).json()['id']
        client.post(
            f'/api/v1/equipment/campaigns/{campaign_id}/launch', headers=eq_auth_headers
        )

        # Confirm via public endpoint
        audit_response = db_session.scalars(
            select(AuditResponse).where(AuditResponse.campaign_id == campaign_id)
        ).first()
        assert audit_response is not None
        token = audit_response.token
        client.post(f'/public/attestation/{token}/confirm')

        r = client.post(
            f'/api/v1/equipment/campaigns/{campaign_id}/remind', headers=eq_auth_headers
        )
        assert r.status_code == status.HTTP_200_OK
        assert r.json()['reminders_sent'] == 0


# ---------------------------------------------------------------------------
# What a reminder run reports, and what a return does to a campaign
# ---------------------------------------------------------------------------


def _smtp(monkeypatch: pytest.MonkeyPatch, *, configured: bool) -> None:
    """The production queue path, with or without a mail server behind it."""
    monkeypatch.setattr('app.services.email_service.settings.TESTING', False)
    for name, value in (
        ('SMTP_HOST', 'smtp.test.invalid' if configured else ''),
        ('SMTP_PORT', 587),
        ('SMTP_USER', 'queue@test.invalid' if configured else ''),
        ('SMTP_PASSWORD', 'secret' if configured else ''),
    ):
        monkeypatch.setattr(f'app.services.email_service.settings.{name}', value)


def _launched_campaign(
    client: TestClient, headers: dict[str, str], item_id: Any
) -> tuple[str, str]:
    """Hand the item to Alice and launch a campaign over it.

    Returns the campaign id and the assignment id.
    """
    assignment = client.post(
        '/api/v1/equipment/assignments',
        headers=headers,
        json={
            'item_id': str(item_id),
            'assigned_to_name': 'Alice',
            'assigned_to_email': 'alice@example.com',
        },
    )
    assignment.raise_for_status()
    campaign_id = client.post(
        '/api/v1/equipment/campaigns',
        headers=headers,
        json={'name': 'Autumn check', 'deadline': _make_deadline(14)},
    ).json()['id']
    client.post(
        f'/api/v1/equipment/campaigns/{campaign_id}/launch', headers=headers
    ).raise_for_status()
    return campaign_id, assignment.json()['id']


@pytest.mark.integration
def test_launched_campaign_refusals_speak_polish(
    client: TestClient, eq_auth_headers: dict[str, str], eq_item: Item
) -> None:
    campaign_id, _ = _launched_campaign(client, eq_auth_headers, eq_item.id)
    headers = {**eq_auth_headers, 'Accept-Language': 'pl'}
    response = client.delete(
        f'/api/v1/equipment/campaigns/{campaign_id}', headers=headers
    )
    assert response.status_code == 409
    assert response.json()['detail']['message'] == (
        'Nie można usunąć rozpoczętej kampanii — zamiast tego ją anuluj.'
    )
    assert response.json()['detail']['lang'] == 'pl'
    assert (
        client.post(
            f'/api/v1/equipment/campaigns/{campaign_id}/cancel', headers=headers
        ).status_code
        == 200
    )
    response = client.post(
        f'/api/v1/equipment/campaigns/{campaign_id}/cancel', headers=headers
    )
    assert response.status_code == 409
    assert response.json()['detail']['message'] == 'Kampania jest już anulowana.'


@pytest.mark.integration
class TestWhatTheReminderRunReports:
    """A run that sent nothing says why, so the button never answers in silence."""

    def test_without_a_mail_server_it_says_so_and_queues_nothing(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from unittest.mock import AsyncMock, patch

        _smtp(monkeypatch, configured=False)
        enqueue = AsyncMock(return_value=uuid.uuid4())
        with patch('app.services.email_jobs.enqueue_email_job', enqueue):
            campaign_id, _ = _launched_campaign(client, eq_auth_headers, eq_item.id)
            enqueue.reset_mock()
            r = client.post(
                f'/api/v1/equipment/campaigns/{campaign_id}/remind',
                headers=eq_auth_headers,
            )

        assert r.status_code == status.HTTP_200_OK, r.text
        assert r.json() == {
            'reminders_sent': 0,
            'awaiting_reply': 1,
            'reminded_recently': 0,
            'not_delivered': 0,
            'email_unavailable': True,
        }
        enqueue.assert_not_called()

    def test_a_second_run_the_same_day_names_the_24_hour_rule(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from unittest.mock import AsyncMock, patch

        _smtp(monkeypatch, configured=True)
        enqueue = AsyncMock(return_value=uuid.uuid4())
        with patch('app.services.email_jobs.enqueue_email_job', enqueue):
            campaign_id, _ = _launched_campaign(client, eq_auth_headers, eq_item.id)
            url = f'/api/v1/equipment/campaigns/{campaign_id}/remind'
            first = client.post(url, headers=eq_auth_headers).json()
            second = client.post(url, headers=eq_auth_headers).json()

        assert first['reminders_sent'] == 1
        assert second == {
            'reminders_sent': 0,
            'awaiting_reply': 1,
            'reminded_recently': 1,
            'not_delivered': 0,
            'email_unavailable': False,
        }


@pytest.mark.integration
class TestAReturnClosesTheQuestion:
    """An asset that came back is not a person who has not answered."""

    def test_a_returned_asset_leaves_the_pending_count_and_the_reminders(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from unittest.mock import AsyncMock, patch

        _smtp(monkeypatch, configured=True)
        enqueue = AsyncMock(return_value=uuid.uuid4())
        with patch('app.services.email_jobs.enqueue_email_job', enqueue):
            campaign_id, assignment_id = _launched_campaign(
                client, eq_auth_headers, eq_item.id
            )
            client.post(
                f'/api/v1/equipment/assignments/{assignment_id}/checkin',
                headers=eq_auth_headers,
                json={},
            ).raise_for_status()

            detail = client.get(
                f'/api/v1/equipment/campaigns/{campaign_id}', headers=eq_auth_headers
            ).json()
            enqueue.reset_mock()
            reminded = client.post(
                f'/api/v1/equipment/campaigns/{campaign_id}/remind',
                headers=eq_auth_headers,
            ).json()

        assert detail['stats']['total'] == 1
        assert detail['stats']['pending'] == 0
        assert detail['stats']['returned'] == 1
        assert detail['responses'][0]['assets_returned'] is True
        assert reminded['reminders_sent'] == 0
        assert reminded['awaiting_reply'] == 0
        enqueue.assert_not_called()

    def test_bulk_return_closes_it_too(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from unittest.mock import AsyncMock, patch

        _smtp(monkeypatch, configured=True)
        with patch(
            'app.services.email_jobs.enqueue_email_job',
            AsyncMock(return_value=uuid.uuid4()),
        ):
            campaign_id, _ = _launched_campaign(client, eq_auth_headers, eq_item.id)
            client.post(
                '/api/v1/equipment/items/bulk-return',
                headers=eq_auth_headers,
                json={'item_ids': [str(eq_item.id)]},
            ).raise_for_status()
            detail = client.get(
                f'/api/v1/equipment/campaigns/{campaign_id}', headers=eq_auth_headers
            ).json()

        assert detail['stats']['pending'] == 0
        assert detail['stats']['returned'] == 1


@pytest.mark.integration
class TestAPartlyReturnedEnvelope:
    """Alice holds a laptop and a phone and returns the phone after the
    request went out. One returned asset used to close her whole envelope:
    the link said "already returned" and the laptop she still had could not
    be confirmed, so her answer stayed missing for good."""

    def _launch_for_two(
        self,
        client: TestClient,
        headers: dict[str, str],
        laptop: Item,
        phone: Item,
        monkeypatch: pytest.MonkeyPatch,
    ) -> tuple[str, str, str]:
        from unittest.mock import AsyncMock, patch

        _smtp(monkeypatch, configured=True)
        ids = []
        for item in (laptop, phone):
            r = client.post(
                '/api/v1/equipment/assignments',
                headers=headers,
                json={
                    'item_id': str(item.id),
                    'assigned_to_name': 'Alice',
                    'assigned_to_email': 'alice@example.com',
                },
            )
            r.raise_for_status()
            ids.append(r.json()['id'])
        campaign_id = client.post(
            '/api/v1/equipment/campaigns',
            headers=headers,
            json={'name': 'Two assets', 'deadline': _make_deadline(14)},
        ).json()['id']
        with patch(
            'app.services.email_jobs.enqueue_email_job',
            AsyncMock(return_value=uuid.uuid4()),
        ):
            client.post(
                f'/api/v1/equipment/campaigns/{campaign_id}/launch', headers=headers
            ).raise_for_status()
        client.post(
            f'/api/v1/equipment/assignments/{ids[1]}/checkin',
            headers=headers,
            json={},
        ).raise_for_status()
        return campaign_id, ids[0], ids[1]

    @pytest.fixture
    def phone(self, db_session: Session, eq_item: Item) -> Item:
        item = Item(
            name='Pixel 8',
            organization_id=eq_item.organization_id,
            storage_location_id=eq_item.storage_location_id,
            category_id=eq_item.category_id,
            quantity=1,
            meta_data={'equipment': {'equipment_status': 'AVAILABLE'}},
        )
        db_session.add(item)
        db_session.commit()
        db_session.refresh(item)
        return item

    def _token(self, db_session: Session, campaign_id: str) -> str:
        db_session.expire_all()
        response = db_session.scalars(
            select(AuditResponse).where(AuditResponse.campaign_id == campaign_id)
        ).one()
        return response.token

    def test_the_link_stays_open_and_confirms_what_is_still_out(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        phone: Item,
        db_session: Session,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        campaign_id, laptop_assignment, phone_assignment = self._launch_for_two(
            client, eq_auth_headers, eq_item, phone, monkeypatch
        )
        token = self._token(db_session, campaign_id)

        view = client.get(f'/public/attestation/{token}').json()
        assert view['closed_reason'] is None
        returned = {i['assignment_id']: i['returned'] for i in view['items']}
        assert returned == {laptop_assignment: False, phone_assignment: True}

        confirmed = client.post(f'/public/attestation/{token}/confirm')
        assert confirmed.status_code == status.HTTP_200_OK, confirmed.text
        statuses = {i['assignment_id']: i['status'] for i in confirmed.json()['items']}
        # The phone is back; confirming does not say she still has it.
        assert statuses == {laptop_assignment: 'CONFIRMED', phone_assignment: 'PENDING'}

        detail = client.get(
            f'/api/v1/equipment/campaigns/{campaign_id}', headers=eq_auth_headers
        ).json()
        assert detail['stats']['confirmed'] == 1
        assert detail['stats']['pending'] == 0

    def test_a_report_about_the_returned_asset_is_refused(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        phone: Item,
        db_session: Session,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        campaign_id, laptop_assignment, phone_assignment = self._launch_for_two(
            client, eq_auth_headers, eq_item, phone, monkeypatch
        )
        token = self._token(db_session, campaign_id)

        refused = client.post(
            f'/public/attestation/{token}/dispute',
            json={
                'dispute_type': 'MISSING',
                'reason': 'gone',
                'assignment_id': phone_assignment,
            },
        )
        assert refused.status_code == status.HTTP_409_CONFLICT

        reported = client.post(
            f'/public/attestation/{token}/dispute',
            json={
                'dispute_type': 'DAMAGED',
                'reason': 'cracked screen',
                'assignment_id': laptop_assignment,
            },
        )
        assert reported.status_code == status.HTTP_200_OK, reported.text
        assert reported.json()['status'] == 'DISPUTED'


@pytest.mark.integration
class TestTheLocationScopeMeansTheAssetsOwnLocation:
    """The hint said "assets checked out to this location"; the scope counts
    the assets whose own location it is — the asset in Server Room A that
    Alice holds. The hint now says that, and this pins what it says."""

    def test_an_asset_kept_here_and_held_by_a_person_is_in_scope(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        eq_storage_location: StorageLocation,
    ) -> None:
        _checkout(client, eq_auth_headers, eq_item.id)

        preview = client.get(
            '/api/v1/equipment/campaigns/scope-preview',
            headers=eq_auth_headers,
            params={
                'scope_type': 'STORAGE',
                'scope_filter_id': str(eq_storage_location.id),
            },
        ).json()

        assert preview == {
            'assets': 1,
            'people': 1,
            'without_email': 0,
            'holders': ['Alice'],
        }


@pytest.mark.integration
class TestThePreviewNamesWhoWillBeAsked:
    """A draft showed "people: 2" and nobody to go with it; the preview now
    carries the holders' names — once each, sorted, the person without an
    address included because the launch will name them as not asked."""

    def test_each_holder_appears_once_by_name(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        laptop = Item(
            name='Dell XPS',
            organization_id=eq_item.organization_id,
            storage_location_id=eq_item.storage_location_id,
            quantity=1,
            meta_data={'equipment': {'equipment_status': 'AVAILABLE'}},
        )
        db_session.add(laptop)
        db_session.commit()
        _checkout(client, eq_auth_headers, eq_item.id, 'Zofia', 'zofia@example.com')
        _checkout(client, eq_auth_headers, laptop.id, 'Zofia', 'zofia@example.com')

        preview = client.get(
            '/api/v1/equipment/campaigns/scope-preview',
            headers=eq_auth_headers,
            params={'scope_type': 'ALL'},
        ).json()

        assert preview['assets'] == 2
        assert preview['holders'] == ['Zofia']


@pytest.mark.integration
class TestALaunchWithoutMail:
    """The New attestation dialog warned that requests "will have to be
    delivered by hand", the launch confirmation promised an e-mail to
    everyone, and no screen gave out a link to deliver. The launch now says
    who was not asked and why, queues nothing that cannot leave, and each
    person's link can be taken from the campaign page."""

    def test_it_names_who_was_skipped_and_hands_out_the_link(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from unittest.mock import AsyncMock, patch

        _smtp(monkeypatch, configured=False)
        phone = Item(
            name='Pixel 8',
            organization_id=eq_item.organization_id,
            storage_location_id=eq_item.storage_location_id,
            quantity=1,
            meta_data={'equipment': {'equipment_status': 'AVAILABLE'}},
        )
        db_session.add(phone)
        db_session.commit()
        _checkout(client, eq_auth_headers, eq_item.id)
        client.post(
            '/api/v1/equipment/assignments',
            headers=eq_auth_headers,
            json={'item_id': str(phone.id), 'assigned_to_name': 'Bob Without Mail'},
        ).raise_for_status()
        campaign_id = client.post(
            '/api/v1/equipment/campaigns',
            headers=eq_auth_headers,
            json={'name': 'No mail', 'deadline': _make_deadline(14)},
        ).json()['id']

        enqueue = AsyncMock(return_value=uuid.uuid4())
        with patch('app.services.email_jobs.enqueue_email_job', enqueue):
            launched = client.post(
                f'/api/v1/equipment/campaigns/{campaign_id}/launch',
                headers=eq_auth_headers,
            ).json()

        assert launched['email_unavailable'] is True
        assert launched['emails_sent'] == 0
        assert launched['skipped_people'] == ['Bob Without Mail']
        enqueue.assert_not_called()

        detail = client.get(
            f'/api/v1/equipment/campaigns/{campaign_id}', headers=eq_auth_headers
        ).json()
        alice = detail['responses'][0]
        link = client.get(
            f'/api/v1/equipment/campaigns/{campaign_id}/responses/{alice["id"]}/link',
            headers=eq_auth_headers,
        )
        assert link.status_code == status.HTTP_200_OK, link.text
        token = link.json()['url'].rsplit('/', 1)[1]
        assert client.get(f'/public/attestation/{token}').json()['id'] == alice['id']

"""Integration tests for inventory period closure (month-end lock)."""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError as SyncIntegrityError
from sqlalchemy.orm import Session

from app.models.item import Item
from app.models.partner import Partner
from app.models.storage_location import StorageLocation


@pytest.mark.integration
class TestInventoryPeriodClosure:
    """Tests for period closure and document workflow guards."""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _create_doc(
        client: TestClient,
        auth_headers: dict[str, str],
        doc_type: str,
        partner_id: uuid.UUID,
        location_id: uuid.UUID,
        lines: list[dict[str, Any]],
        scheduled_date: str | None = None,
    ) -> str:
        payload = {
            'type': doc_type,
            'partner_id': str(partner_id),
            'lines': lines,
            'target_location_id': str(location_id),
        }
        if scheduled_date:
            payload['scheduled_date'] = scheduled_date
        resp = client.post(
            '/api/v1/warehouse/documents', headers=auth_headers, json=payload
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        data = resp.json()
        assert isinstance(data, dict)
        doc_id = data['id']
        assert isinstance(doc_id, str)
        return doc_id

    @staticmethod
    def _confirm_and_complete(
        client: TestClient,
        auth_headers: dict[str, str],
        doc_id: str,
    ) -> None:
        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=auth_headers
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=auth_headers,
            json={'complete_as_planned': True},
        )

    # ------------------------------------------------------------------
    # Period CRUD
    # ------------------------------------------------------------------

    def test_close_period_success(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        """Admin can close a period."""
        resp = client.post(
            '/api/v1/warehouse/periods/2026/5/close',
            headers=doc_auth_headers,
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        data = resp.json()
        assert data['year'] == 2026
        assert data['month'] == 5
        assert data['closed_at'] is not None
        assert data['closed_by'] is not None

    def test_close_period_user_role_forbidden(
        self,
        client: TestClient,
        h: Any,
        doc_org: Any,
    ) -> None:
        """Only admin/manager can close inventory periods."""
        user = h.create_user(doc_org, email='period-user@example.com', role='user')
        headers = h.get_auth_headers(user)
        resp = client.post(
            '/api/v1/warehouse/periods/2026/11/close',
            headers=headers,
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_reopen_period_user_role_forbidden(
        self,
        client: TestClient,
        h: Any,
        doc_org: Any,
    ) -> None:
        """Only admin/manager can reopen inventory periods."""
        user = h.create_user(doc_org, email='period-user2@example.com', role='user')
        headers = h.get_auth_headers(user)
        resp = client.post(
            '/api/v1/warehouse/periods/2026/11/reopen',
            headers=headers,
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_unique_constraint_org_year_month(
        self,
        db_session: Session,
        doc_org: Any,
    ) -> None:
        """DB enforces one inventory period per (org, year, month).

        Previously uniqueness relied only on an advisory lock; a hard UNIQUE
        constraint now backstops it.
        """
        from app.modules.warehouse.models import InventoryPeriod

        db_session.add(InventoryPeriod(organization_id=doc_org.id, year=2026, month=12))
        db_session.commit()

        db_session.add(InventoryPeriod(organization_id=doc_org.id, year=2026, month=12))
        with pytest.raises(SyncIntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_close_same_period_twice_returns_409(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        """Closing an already closed period returns 409."""
        client.post(
            '/api/v1/warehouse/periods/2026/6/close',
            headers=doc_auth_headers,
        )
        resp = client.post(
            '/api/v1/warehouse/periods/2026/6/close',
            headers=doc_auth_headers,
        )
        assert resp.status_code == status.HTTP_409_CONFLICT, resp.text
        assert resp.json()['detail']['code'] == 'PERIOD_ALREADY_CLOSED'

    def test_reopen_period_success(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        """Admin can reopen a closed period."""
        client.post(
            '/api/v1/warehouse/periods/2026/7/close',
            headers=doc_auth_headers,
        )
        resp = client.post(
            '/api/v1/warehouse/periods/2026/7/reopen',
            headers=doc_auth_headers,
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        data = resp.json()
        # `closed_at` used to be NULLed here, which erased the evidence that
        # the month had ever been closed. The state is its own field now.
        assert data['is_closed'] is False
        assert data['closed_at'] is not None
        assert data['reopened_at'] is not None

    def test_reopen_open_period_returns_409(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        """Reopening an open period returns 409."""
        resp = client.post(
            '/api/v1/warehouse/periods/2026/8/reopen',
            headers=doc_auth_headers,
        )
        assert resp.status_code == status.HTTP_409_CONFLICT, resp.text
        # Not PERIOD_CLOSED, which said the opposite of the sentence beside it.
        assert resp.json()['detail']['code'] == 'PERIOD_NOT_CLOSED'

    def test_the_refusals_reach_a_polish_reader_in_polish(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        """The reader's language, on both period refusals, measured on the
        envelope the screen's toast prints. The server sentences used to be
        bare ``ValueError`` prose — English no matter the interface."""
        pl = {'Accept-Language': 'pl', **doc_auth_headers}

        client.post('/api/v1/warehouse/periods/2026/9/close', headers=doc_auth_headers)
        resp = client.post('/api/v1/warehouse/periods/2026/9/close', headers=pl)
        assert resp.status_code == status.HTTP_409_CONFLICT, resp.text
        detail = resp.json()['detail']
        assert detail['message'] == 'Okres 2026-09 jest już zamknięty.'
        # The conflict envelope names the language it speaks, like the 400
        # path does — the stock-take refusal stamps `lang`, so the period
        # refusals do too.
        assert detail['lang'] == 'pl'

        resp = client.post('/api/v1/warehouse/periods/2026/9/reopen', headers=pl)
        assert resp.status_code == status.HTTP_200_OK, resp.text

        resp = client.post('/api/v1/warehouse/periods/2026/9/reopen', headers=pl)
        assert resp.status_code == status.HTTP_409_CONFLICT, resp.text
        assert resp.json()['detail']['message'] == 'Okres 2026-09 nie jest zamknięty.'
        assert resp.json()['detail']['lang'] == 'pl'

        # The English reader keeps the English sentence.
        client.post(
            '/api/v1/warehouse/periods/2026/10/close',
            headers={**doc_auth_headers, 'Accept-Language': 'en'},
        )
        resp = client.post(
            '/api/v1/warehouse/periods/2026/10/close',
            headers={**doc_auth_headers, 'Accept-Language': 'en'},
        )
        assert resp.status_code == status.HTTP_409_CONFLICT, resp.text
        assert resp.json()['detail']['message'] == 'Period 2026-10 is already closed.'
        assert resp.json()['detail']['lang'] == 'en'

    def test_list_periods_returns_closed_and_open(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        """List includes both closed and not-yet-closed periods."""
        client.post(
            '/api/v1/warehouse/periods/2026/9/close',
            headers=doc_auth_headers,
        )
        resp = client.get('/api/v1/warehouse/periods', headers=doc_auth_headers)
        assert resp.status_code == status.HTTP_200_OK, resp.text
        data = resp.json()['items']
        assert isinstance(data, list)
        closed = [p for p in data if p['year'] == 2026 and p['month'] == 9]
        assert len(closed) == 1
        assert closed[0]['closed_at'] is not None

    def test_list_periods_pages_past_twenty_four_months(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        db_session: Session,
        doc_org: Any,
    ) -> None:
        """The envelope counts and pages the whole collection, not a capped slice."""
        from app.modules.warehouse.models import InventoryPeriod

        for index in range(25):
            db_session.add(
                InventoryPeriod(
                    organization_id=doc_org.id,
                    year=2001 + index // 12,
                    month=index % 12 + 1,
                )
            )
        db_session.commit()

        resp = client.get(
            '/api/v1/warehouse/periods?limit=50', headers=doc_auth_headers
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        body = resp.json()
        assert body['total'] == 25
        assert len(body['items']) == 25
        assert body['has_more'] is False

        resp = client.get(
            '/api/v1/warehouse/periods?limit=1&offset=24', headers=doc_auth_headers
        )
        body = resp.json()
        assert body['total'] == 25
        assert [(p['year'], p['month']) for p in body['items']] == [(2001, 1)]

    # ------------------------------------------------------------------
    # Workflow guards
    # ------------------------------------------------------------------

    def test_confirm_document_in_closed_period_blocked(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
    ) -> None:
        """Confirming a document dated in a closed period is blocked."""
        # Dated March 2026, while March is still open — the month can no
        # longer be closed first, because creation is guarded too.
        doc_id = self._create_doc(
            client,
            doc_auth_headers,
            'IN',
            doc_partner.id,
            doc_target_location.id,
            [{'item_id': str(doc_item.id), 'expected_quantity': 5}],
            scheduled_date='2026-03-15',
        )
        # Close March 2026
        client.post(
            '/api/v1/warehouse/periods/2026/3/close',
            headers=doc_auth_headers,
        )
        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        assert resp.status_code == status.HTTP_409_CONFLICT, resp.text
        assert 'closed' in resp.json()['detail']['message'].lower()

    def test_complete_document_in_closed_period_blocked(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
    ) -> None:
        """Completing a document dated in a closed period is blocked."""
        # Create and confirm document first
        doc_id = self._create_doc(
            client,
            doc_auth_headers,
            'IN',
            doc_partner.id,
            doc_target_location.id,
            [{'item_id': str(doc_item.id), 'expected_quantity': 5}],
            scheduled_date='2026-04-10',
        )
        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        # Close April 2026
        client.post(
            '/api/v1/warehouse/periods/2026/4/close',
            headers=doc_auth_headers,
        )
        # Try complete
        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert resp.status_code == status.HTTP_409_CONFLICT, resp.text

    def test_cancel_document_in_closed_period_blocked(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
    ) -> None:
        """Cancelling a document dated in a closed period is blocked."""
        doc_id = self._create_doc(
            client,
            doc_auth_headers,
            'IN',
            doc_partner.id,
            doc_target_location.id,
            [{'item_id': str(doc_item.id), 'expected_quantity': 5}],
            scheduled_date='2026-05-15',
        )
        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        # Close May 2026
        client.post(
            '/api/v1/warehouse/periods/2026/5/close',
            headers=doc_auth_headers,
        )
        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/cancel', headers=doc_auth_headers
        )
        assert resp.status_code == status.HTTP_409_CONFLICT, resp.text

    def test_update_document_in_closed_period_blocked(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
    ) -> None:
        """Updating a document dated in a closed period is blocked."""
        doc_id = self._create_doc(
            client,
            doc_auth_headers,
            'IN',
            doc_partner.id,
            doc_target_location.id,
            [{'item_id': str(doc_item.id), 'expected_quantity': 5}],
            scheduled_date='2026-06-20',
        )
        # Close June 2026
        client.post(
            '/api/v1/warehouse/periods/2026/6/close',
            headers=doc_auth_headers,
        )
        resp = client.put(
            f'/api/v1/warehouse/documents/{doc_id}',
            headers=doc_auth_headers,
            json={'notes': 'changed'},
        )
        assert resp.status_code == status.HTTP_409_CONFLICT, resp.text

    # ------------------------------------------------------------------
    # Non-closed periods are fine
    # ------------------------------------------------------------------

    def test_confirm_document_in_open_period_allowed(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
    ) -> None:
        """Confirming a document in an open period works fine."""
        # Close only February 2026
        client.post(
            '/api/v1/warehouse/periods/2026/2/close',
            headers=doc_auth_headers,
        )
        # July is open
        doc_id = self._create_doc(
            client,
            doc_auth_headers,
            'IN',
            doc_partner.id,
            doc_target_location.id,
            [{'item_id': str(doc_item.id), 'expected_quantity': 5}],
            scheduled_date='2026-07-10',
        )
        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text

    def test_full_workflow_after_reopening_period(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
    ) -> None:
        """After reopening a period, documents can be processed again."""
        # Create document
        doc_id = self._create_doc(
            client,
            doc_auth_headers,
            'IN',
            doc_partner.id,
            doc_target_location.id,
            [{'item_id': str(doc_item.id), 'expected_quantity': 5}],
            scheduled_date='2026-08-15',
        )
        # Close August
        client.post(
            '/api/v1/warehouse/periods/2026/8/close',
            headers=doc_auth_headers,
        )
        # Blocked
        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        assert resp.status_code == status.HTTP_409_CONFLICT

        # Reopen August
        client.post(
            '/api/v1/warehouse/periods/2026/8/reopen',
            headers=doc_auth_headers,
        )
        # Now works
        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        assert resp.status_code == status.HTTP_200_OK

    # ------------------------------------------------------------------
    # A closed month refuses documents it does not yet have
    # ------------------------------------------------------------------

    def test_create_document_in_closed_period_blocked(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
    ) -> None:
        """The dialog promises documents can no longer be *created*.

        The guard read the date off an existing document, so by definition it
        could not run before one existed: POST answered 201 and every later
        act on that document answered 409. The user got a document that was
        born unusable and only found out on the first thing they tried.
        """
        client.post(
            '/api/v1/warehouse/periods/2026/5/close',
            headers=doc_auth_headers,
        )

        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [{'item_id': str(doc_item.id), 'expected_quantity': 5}],
                'scheduled_date': '2026-05-20',
            },
        )

        assert resp.status_code == status.HTTP_409_CONFLICT, resp.text
        # The refusal names the month, so "change the date" is actionable.
        assert '2026-05' in resp.text

    def test_create_undated_document_in_closed_current_period_blocked(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_item: Item,
    ) -> None:
        """A document with no date of its own is dated today, and today counts."""
        today = datetime.now(UTC).date()
        client.post(
            f'/api/v1/warehouse/periods/{today.year}/{today.month}/close',
            headers=doc_auth_headers,
        )

        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [{'item_id': str(doc_item.id), 'expected_quantity': 5}],
            },
        )

        assert resp.status_code == status.HTTP_409_CONFLICT, resp.text

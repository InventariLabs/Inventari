"""The public attestation page says who is asking and until which day.

The page names the organization that asks and the last day to answer, so a
person who follows a link from an email sees who wants the answer and how long
they have. The public GET carries the organization's name and that day, a
calendar day on the organization's own clock, so every reader sees the day the
organizer picked.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import status
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models.item import Item
from app.models.organization import Organization
from app.modules.equipment.models import AuditResponse


@pytest.mark.integration
class TestThePublicLinkNamesWhoAsksAndByWhen:
    def test_the_get_carries_the_organization_and_the_deadline_day(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        client.post(
            '/api/v1/equipment/assignments',
            headers=eq_auth_headers,
            json={
                'item_id': str(eq_item.id),
                'assigned_to_name': 'Alice',
                'assigned_to_email': 'alice@example.com',
            },
        ).raise_for_status()
        deadline = datetime.now(UTC) + timedelta(days=14)
        created = client.post(
            '/api/v1/equipment/campaigns',
            headers=eq_auth_headers,
            json={'name': 'Spring attestation', 'deadline': deadline.isoformat()},
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        client.post(
            f'/api/v1/equipment/campaigns/{created.json()["id"]}/launch',
            headers=eq_auth_headers,
        ).raise_for_status()
        token = db_session.scalars(select(AuditResponse.token)).first()
        org_name = db_session.scalars(select(Organization.name)).first()

        response = client.get(f'/public/attestation/{token}')

        assert response.status_code == status.HTTP_200_OK, response.text
        body: dict[str, Any] = response.json()
        assert body['organization_name'] == org_name
        assert body['deadline_day'] == deadline.date().isoformat()

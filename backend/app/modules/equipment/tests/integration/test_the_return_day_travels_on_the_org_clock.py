"""The return day the form picked, on the organization's clock (review
2026-09-23).

A checkout sent "2026-09-30", Pydantic parsed the date-only value to
midnight, and the column held ``2026-09-30T00:00:00Z``. A reader west of
UTC read the previous day off it, and the day itself was a UTC day for
every organization whose clock is not UTC. The form now sends noon of the
picked day inside the organization's day, and the service pins the end of
the day it reads there — the same contract the attestation deadline
follows (review 2026-09-22). The walk below posts exactly what the form
now sends for a Los Angeles organization and requires the stored pin to
read the picked day through the org clock, and to be the day's end rather
than a moment inside it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi import status
from starlette.testclient import TestClient

from app.models.item import Item


@pytest.mark.integration
class TestTheReturnDayOnTheOrgClock:
    def test_an_arrival_inside_the_org_day_pins_that_day_west_of_utc(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_org: Any,
        eq_item: Item,
        db_session: Any,
    ) -> None:
        eq_org.timezone = 'America/Los_Angeles'
        db_session.commit()

        # Noon of Sep 30 in Los Angeles — what instantInsideDay now sends.
        arrival = '2026-09-30T19:00:00.000Z'
        r = client.post(
            '/api/v1/equipment/assignments',
            headers=eq_auth_headers,
            json={
                'item_id': str(eq_item.id),
                'assigned_to_name': 'Alice',
                'expected_return_at': arrival,
            },
        )
        assert r.status_code == status.HTTP_201_CREATED, r.text
        stored = datetime.fromisoformat(
            r.json()['expected_return_at'].replace('Z', '+00:00')
        )
        la = stored.astimezone(ZoneInfo('America/Los_Angeles'))
        # The day the form said, read through the organization's clock.
        assert la.date().isoformat() == '2026-09-30'
        # The end of that day — "last day to return", never a moment inside it.
        assert (la.hour, la.minute, la.second) == (23, 59, 59)

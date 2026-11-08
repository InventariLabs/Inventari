"""A time zone whose today is not the server's, for tests of the organization's clock.

A test that pins "which day it is" to the organization (TECHNICAL_DECISIONS
§19) has to tell the organization's day from the server's at whatever hour
the suite runs, not only around midnight. +14 and −11: whatever the hour, one
of them is on a different date than a server running in UTC.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

_CANDIDATE_ZONES = ('Pacific/Kiritimati', 'Pacific/Midway')


def zone_where_today_differs() -> tuple[str, date]:
    """A zone whose today is not the server's, plus that zone's today."""
    now = datetime.now(UTC)
    for name in _CANDIDATE_ZONES:
        local_today = now.astimezone(ZoneInfo(name)).date()
        if local_today != date.today():
            return name, local_today
    raise AssertionError(
        'no candidate zone differs from the server day — the server is not '
        f'running in UTC (now={now.isoformat()}, today={date.today()})'
    )

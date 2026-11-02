"""The organization's day, pinned to the instant the column holds.

A day picked in a form is not a moment (reviews 2026-09-22 and 2026-09-23). The wire speaks
instants, so the day travels as an instant *inside* the organization's day —
noon of the picked day in the org's zone, built by ``instantInsideDay`` in
the frontend — and the service that owns the record pins the *end* of the
day it reads there. The stored value is then an instant whose day, read
through the org clock, is the day the form said; readers render it with
``formatDateInZone`` / ``useFormatOrgDay``, never with the browser's zone.

The end of the day, not the start: an attestation deadline and an expected
return are both "the last day to do it", so the record must not count as
past for the whole of the day it names.
"""

from __future__ import annotations

from datetime import UTC, datetime, tzinfo


def pin_org_day_end(value: datetime, tz: tzinfo) -> datetime:
    """The last microsecond of *value*'s day on *tz*, back in UTC.

    A naive arrival — a date-only wire value Pydantic parsed to midnight —
    is read as UTC first, the same normalization the attestation deadline
    has always used.
    """
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return (
        value.astimezone(tz)
        .replace(hour=23, minute=59, second=59, microsecond=999999)
        .astimezone(UTC)
    )

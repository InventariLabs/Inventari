"""Canonical date parsing and display formatting.

Two kinds of artifact read a date in this codebase, and they read it
differently on purpose:

* **The wire and the record.** An audit row, a label key, an export, an
  import, an API field, a reference number. Read by a machine, compared
  across rows, or quoted into another system — they keep the canonical
  ``2026-08-22 14:30`` whatever language the reader uses, because a date that
  changes spelling with the interface is a date two systems cannot compare.
* **The document a person reads and signs.** The equipment handover and
  return protocol is the most human artifact this application produces: the
  worker who signs it reads their own language, and the screen they opened it
  from shows them ``18.09.2026``. For those, :func:`format_date_for` and
  :func:`format_datetime_for` write the date the way their language writes
  it. A refusal the screen prints verbatim belongs to this family too: its
  day is read beside the screen's own dates, not compared across systems —
  an ISO day inside a translated sentence is how one screen came to show the
  same boundary as two different days.

The wire and the record keep the canonical spelling — ``DATE_FORMAT`` is its
single home, and the call sites that need it spell their dates through that
constant (the equipment importer's date column is one). The document a person
reads and signs goes through :func:`format_date_for` and
:func:`format_datetime_for`. The reference number *inside* such a document
(``EQ-20260918-A0A94455``) stays canonical as well — it is an identifier, not
a date to read.

What deliberately stays out:

* ISO-8601 *durations* (``PT1H30M``) — only the recipe scrapers speak that
  format, so it fails the three-vertical test in AGENTS.md §4.
* Spreadsheet cell parsing (``pandas.to_datetime`` over a mapped column) —
  its input is a dataframe cell, not a string, and item import is its only
  caller.
"""

from __future__ import annotations

from contextvars import ContextVar
from datetime import UTC, date, datetime

#: What an empty date looks like on a printed document.
MISSING = '—'

#: The canonical wire spelling of a date: what an export, an import column or
#: a reference number keeps whatever language the reader uses.
DATE_FORMAT = '%Y-%m-%d'

#: The date as each language writes it, for documents a person reads.
#: Numeric patterns on purpose: strftime's ``%b`` would give English month
#: names whatever the document's language is. English is the exception: it is
#: spelled out (``_english_date``), because 04/11/2026 is April 11 to a US
#: reader and 4 November to everyone else. Matches what the interface shows
#: for the same language (``Intl.DateTimeFormat`` in the frontend).
LANGUAGE_DATE_FORMATS: dict[str, str] = {
    'pl': '%d.%m.%Y',
    'de': '%d.%m.%Y',
    'fr': '%d/%m/%Y',
    'es': '%d/%m/%Y',
}

_ENGLISH_MONTHS = (
    'Jan',
    'Feb',
    'Mar',
    'Apr',
    'May',
    'Jun',
    'Jul',
    'Aug',
    'Sep',
    'Oct',
    'Nov',
    'Dec',
)


#: The country of the organization the request acts for, set once where the
#: request's user is resolved — next to the language it already travels with.
#: A printed date that is given no *country* of its own reads it from here, so
#: a caller that only knows ``lang`` still writes the order the screen shows.
_request_country: ContextVar[str | None] = ContextVar('request_country', default=None)


def utc_now() -> datetime:
    """The current moment, timezone-aware in UTC.

    The one spelling for a column default (``default=utc_now``) and for code
    that stamps a record. A model can take it instead of spelling its own
    ``lambda: datetime.now(UTC)``; the existing lambdas are left as they are.
    """
    return datetime.now(UTC)


def set_request_country(country: str | None) -> None:
    """Record the acting organization's ISO country for this request."""
    _request_country.set(country)


def _english_date(value: date, country: str | None) -> str:
    """``Nov 4, 2026`` for the US, ``4 Nov 2026`` anywhere else (or when unknown)."""
    month = _ENGLISH_MONTHS[value.month - 1]
    if country and country.strip().upper() != 'US':
        return f'{value.day} {month} {value.year}'
    return f'{month} {value.day}, {value.year}'


def _render(lang: str, value: date | datetime, country: str | None, time: str) -> str:
    code = lang[:2].lower()
    pattern = LANGUAGE_DATE_FORMATS.get(code)
    if pattern is None:
        return _english_date(value, country or _request_country.get()) + (
            value.strftime(f', {time}') if time else ''
        )
    return value.strftime(f'{pattern} {time}'.strip())


def format_date_for(
    lang: str,
    value: date | datetime | None,
    *,
    missing: str = MISSING,
    country: str | None = None,
) -> str:
    """Render a date the way *lang* writes it, for a document a person reads.

    ``format_date_for('pl', date(2026, 9, 18))`` is ``18.09.2026`` — the same
    date the interface shows the reader who opened the document. *country*
    is the organisation's ISO code, by default that of the organisation the
    request acts for: English spells the month and reads day-first unless it
    is the US (or not known), as the interface does.
    """
    if value is None:
        return missing
    return _render(lang, value, country, '')


def format_datetime_for(
    lang: str,
    value: datetime | None,
    *,
    missing: str = MISSING,
    country: str | None = None,
) -> str:
    """Render a timestamp the way *lang* writes it, for a document a person reads."""
    if value is None:
        return missing
    return _render(lang, value, country, '%H:%M')


def parse_iso_date(value: str | None) -> date | None:
    """Parse an ISO-8601 date, or return ``None`` when it is absent or malformed.

    Never raises: every caller so far treats an unparseable date as "not
    given" and carries on, so the refusal belongs here rather than in a
    try/except at each site.
    """
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None

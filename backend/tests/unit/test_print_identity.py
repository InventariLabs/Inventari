"""The header every printout shares."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from app.core.print_identity import IssuerContext, print_date_rows


@pytest.mark.unit
class TestPrintDateRows:
    def test_a_stamp_that_repeats_the_one_above_it_is_dropped(self) -> None:
        """A document confirmed and completed the day it was issued printed
        the same date three times, one under the other."""
        rows = print_date_rows(
            [
                ('Issued', datetime(2026, 8, 23, 9, 0)),
                ('Confirmed', datetime(2026, 8, 23, 10, 0)),
                ('Completed', datetime(2026, 8, 23, 17, 30)),
            ],
            lang='pl',
        )
        assert rows == [{'label': 'Issued', 'value': '23.08.2026'}]

    def test_a_stamp_that_says_something_new_survives(self) -> None:
        rows = print_date_rows(
            [
                ('Issued', datetime(2026, 8, 23)),
                ('Confirmed', datetime(2026, 8, 23)),
                ('Completed', datetime(2026, 8, 25)),
            ],
            lang='pl',
        )
        assert rows == [
            {'label': 'Issued', 'value': '23.08.2026'},
            {'label': 'Completed', 'value': '25.08.2026'},
        ]

    def test_a_repeat_is_measured_against_the_last_printed_row(self) -> None:
        """Not against the previous entry — otherwise a date that returns to
        an earlier value would print twice."""
        rows = print_date_rows(
            [
                ('Issued', datetime(2026, 8, 23)),
                ('Confirmed', None),
                ('Completed', datetime(2026, 8, 23)),
            ],
            lang='pl',
        )
        assert rows == [{'label': 'Issued', 'value': '23.08.2026'}]

    def test_a_stamp_that_never_happened_is_not_a_row(self) -> None:
        assert print_date_rows([('Confirmed', None), ('Completed', '')]) == []

    def test_a_date_is_written_the_way_its_language_writes_it(self) -> None:
        """The printout follows the interface language.

        The header printed ``26.09.2026`` on an English screen — a date the
        reader had to decode, beside dates the interface spelled Sep 26, 2026.
        """
        rows = print_date_rows([('Issued', datetime(2026, 9, 26))], lang='en')
        assert rows == [{'label': 'Issued', 'value': 'Sep 26, 2026'}]

    def test_english_follows_the_issuing_organisations_country(self) -> None:
        """A UK organisation's printout reads 26 Sep 2026, as its screen does."""
        entry = [('Issued', datetime(2026, 9, 26))]
        assert print_date_rows(entry, 'en', 'GB') == [
            {'label': 'Issued', 'value': '26 Sep 2026'}
        ]
        assert print_date_rows(entry, 'en', 'US') == [
            {'label': 'Issued', 'value': 'Sep 26, 2026'}
        ]


@pytest.mark.unit
class TestIssuerContext:
    def test_no_organization_prints_an_empty_letterhead(self) -> None:
        ctx = IssuerContext.from_organization(None)
        assert ctx.name is None
        assert ctx.address is None
        assert ctx.logo is None

    def test_the_country_column_joins_the_address_jsonb(self) -> None:
        org = SimpleNamespace(
            name='Acme',
            tax_id='PL1234567890',
            address={'street': 'Main 1', 'city': 'Warsaw', 'postal_code': '00-001'},
            country='PL',
        )
        ctx = IssuerContext.from_organization(org, lang='pl')
        assert ctx.address == 'Main 1, Warsaw, 00-001, Polska'

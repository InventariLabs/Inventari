"""Unit tests for the canonical date helpers (app.core.datetimes)."""

from datetime import date, datetime

import pytest

from app.core.datetimes import (
    DATE_FORMAT,
    format_date_for,
    format_datetime_for,
    parse_iso_date,
    set_request_country,
)


@pytest.mark.unit
class TestParseIsoDate:
    def test_parses_an_iso_date(self) -> None:
        assert parse_iso_date('2026-08-22') == date(2026, 8, 22)

    @pytest.mark.parametrize(
        'value', [None, '', 'yesterday', '22/08/2026', '2026-13-01']
    )
    def test_anything_unparseable_is_none(self, value: str | None) -> None:
        """Callers treat a bad date as "not given" — none of them want an exception."""
        assert parse_iso_date(value) is None


@pytest.mark.unit
class TestTheDateInTheReadersLanguage:
    """The other half of the decision in the module docstring.

    A document a person signs is written in that person's language; the wire
    keeps the canonical form.
    """

    def test_polish_writes_the_day_first(self) -> None:
        assert format_date_for('pl', date(2026, 9, 18)) == '18.09.2026'

    def test_english_keeps_its_own_order(self) -> None:
        assert format_date_for('en', date(2026, 9, 18)) == 'Sep 18, 2026'

    def test_english_outside_the_us_writes_the_day_first(self) -> None:
        """The screen does: an organisation outside the US reads 18/09/2026."""
        assert format_date_for('en', date(2026, 9, 18), country='GB') == '18 Sep 2026'
        assert format_date_for('en', date(2026, 9, 18), country='nl') == '18 Sep 2026'
        assert (
            format_datetime_for('en', datetime(2026, 9, 18, 14, 30), country='IE')
            == '18 Sep 2026, 14:30'
        )

    def test_a_us_organisation_or_none_keeps_english_as_it_was(self) -> None:
        assert format_date_for('en', date(2026, 9, 18), country='US') == 'Sep 18, 2026'
        assert format_date_for('en', date(2026, 9, 18), country=None) == 'Sep 18, 2026'

    def test_a_caller_given_only_the_language_gets_the_requests_country(self) -> None:
        """What the label and template filters rely on: lang alone is enough."""
        set_request_country('GB')
        try:
            assert format_date_for('en', date(2026, 4, 3)) == '3 Apr 2026'
            assert (
                format_date_for('en', date(2026, 4, 3), country='US') == 'Apr 3, 2026'
            )
        finally:
            set_request_country(None)
        assert format_date_for('en', date(2026, 4, 3)) == 'Apr 3, 2026'

    def test_the_country_does_not_touch_other_languages(self) -> None:
        assert format_date_for('pl', date(2026, 9, 18), country='US') == '18.09.2026'

    @pytest.mark.parametrize(
        ('lang', 'expected'),
        [
            ('de', '18.09.2026'),
            ('fr', '18/09/2026'),
            ('es', '18/09/2026'),
        ],
    )
    def test_the_other_languages(self, lang: str, expected: str) -> None:
        assert format_date_for(lang, date(2026, 9, 18)) == expected

    def test_a_language_nobody_taught_falls_back_to_english(self) -> None:
        assert format_date_for('xx', date(2026, 9, 18)) == 'Sep 18, 2026'

    def test_the_time_keeps_the_same_order(self) -> None:
        assert (
            format_datetime_for('pl', datetime(2026, 9, 18, 18, 10))
            == '18.09.2026 18:10'
        )

    def test_an_absent_date_is_the_marker_in_every_language(self) -> None:
        assert format_date_for('pl', None) == '—'
        assert format_datetime_for('de', None) == '—'

    def test_the_canonical_spelling_is_the_wires_own(self) -> None:
        """The two ways of writing a date live in one file; they are not one way."""
        assert date(2026, 9, 18).strftime(DATE_FORMAT) == '2026-09-18'
        assert format_date_for('pl', date(2026, 9, 18)) == '18.09.2026'


@pytest.mark.unit
class TestARegionalLanguageTag:
    def test_a_regional_tag_writes_the_date_of_its_base_language(self) -> None:
        """``pl-PL`` is what a browser reports; it printed the US spelling."""
        assert format_date_for('pl-PL', date(2026, 10, 25)) == '25.10.2026'
        assert format_datetime_for('de_DE', datetime(2026, 10, 25, 9, 5)) == (
            '25.10.2026 09:05'
        )


def test_utc_now_is_timezone_aware_utc():
    from datetime import UTC

    from app.core.datetimes import utc_now

    assert utc_now().utcoffset() == UTC.utcoffset(None)

"""The organization timezone field refuses what the org clock cannot read.

A zone the backend cannot resolve degrades every org-clock read to UTC with
a warning log — silently shifting expiry buckets and period guards. The
schema refuses such a string at the door instead (mirroring the country
code validator next to it).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.organization import OrganizationBase, OrganizationUpdate


class TestOrganizationTimezone:
    def test_accepts_iana_zone_name(self) -> None:
        updated = OrganizationUpdate(timezone='Pacific/Auckland')
        assert updated.timezone == 'Pacific/Auckland'

    def test_blank_falls_back_to_utc(self) -> None:
        updated = OrganizationUpdate(timezone='   ')
        assert updated.timezone == 'UTC'

    def test_none_means_not_provided(self) -> None:
        updated = OrganizationUpdate(timezone=None)
        assert updated.timezone is None

    def test_rejects_unreadable_zone(self) -> None:
        with pytest.raises(ValidationError) as exc:
            OrganizationUpdate(timezone='Not/AZone')
        # Every translation names the standard, so the assertion holds in
        # any request language.
        assert 'IANA' in str(exc.value)

    @pytest.mark.parametrize('name', ['Europe/', '../etc/passwd', 'America'])
    def test_rejects_a_name_that_is_not_a_zone_key(self, name: str) -> None:
        # A malformed key fails with ValueError and a directory of zones with
        # ZoneInfoNotFoundError; both are a refusal, never a server error.
        with pytest.raises(ValidationError):
            OrganizationUpdate(timezone=name)

    def test_base_schema_rejects_unreadable_zone_too(self) -> None:
        with pytest.raises(ValidationError):
            OrganizationBase(name='Cold Storage', timezone='Mars/Olympus')

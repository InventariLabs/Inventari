"""The organization lookup behind ``db seed`` reads what the database holds.

The command decides on this list — one organization is seeded, none is
reported, several are refused — so what the list contains is the difference
between seeding the right tenant and quietly doing nothing.
"""

from uuid import UUID

import pytest

from app.models.organization import Organization
from app.seed_data import list_seedable_organizations


@pytest.mark.integration
class TestSeedOrganizationLookup:
    def test_every_organization_that_exists_is_listed(self, db_session):
        db_session.add_all(
            [Organization(name='First Org'), Organization(name='Second Org')]
        )
        db_session.commit()

        names = [name for _, name in list_seedable_organizations(db_session)]

        assert 'First Org' in names
        assert 'Second Org' in names

    def test_a_listing_entry_carries_the_id_and_the_name(self, db_session):
        organization = Organization(name='Named Tenant')
        db_session.add(organization)
        db_session.commit()

        entries = list_seedable_organizations(db_session)

        match = [entry for entry in entries if entry[1] == 'Named Tenant']
        assert len(match) == 1
        assert isinstance(match[0][0], UUID)
        assert match[0][0] == organization.id

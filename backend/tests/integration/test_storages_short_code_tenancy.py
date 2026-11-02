"""Storage short codes belong to one organization, not to the whole table.

``storage_locations.short_code`` carried a global UNIQUE while the equivalent
column on ``label_pool`` had gone per-organization long before. Because short
codes are client-supplied on create and update, the asymmetry let one tenant
take a code — accidentally or on purpose — and every other tenant was then
refused it, with a message ("already in use by another location") that
confirmed a row existed in an organization the caller cannot see.

These tests pin the fixed contract:

- two organizations may hold the same short code
- a foreign organization's code does not block create or update
- a duplicate WITHIN the organization is still rejected, with a 4xx rather
  than the IntegrityError the bare constraint would raise
- the code generator searches only the tenant it generates for
"""

import pytest
from fastapi import status


def _make_org(db_session, name):
    from app.models.organization import Organization

    org = Organization(name=name, enabled_modules=[])
    db_session.add(org)
    db_session.commit()
    db_session.refresh(org)
    return org


def _make_storage(db_session, organization_id, created_by, name, short_code):
    from app.models.storage_location import StorageLocation

    storage = StorageLocation(
        organization_id=organization_id,
        created_by=created_by,
        name=name,
        short_code=short_code,
    )
    db_session.add(storage)
    db_session.commit()
    db_session.refresh(storage)
    return storage


@pytest.mark.integration
class TestShortCodeIsPerOrganization:
    def test_two_organizations_hold_the_same_code(self, db_session, test_user) -> None:
        """The global UNIQUE made this an IntegrityError."""
        other_org = _make_org(db_session, 'Other Organization')

        mine = _make_storage(
            db_session, test_user.organization_id, test_user.id, 'Mine', 'LOC-SAME'
        )
        theirs = _make_storage(
            db_session, other_org.id, test_user.id, 'Theirs', 'LOC-SAME'
        )

        assert mine.short_code == theirs.short_code
        assert mine.organization_id != theirs.organization_id

    def test_create_accepts_a_code_another_organization_uses(
        self, client, auth_headers, db_session, test_user
    ) -> None:
        other_org = _make_org(db_session, 'Squatter Organization')
        _make_storage(db_session, other_org.id, test_user.id, 'Foreign', 'LOC-TAKEN')

        response = client.post(
            '/api/v1/locations/',
            headers=auth_headers,
            json={'name': 'Mine', 'short_code': 'LOC-TAKEN'},
        )

        assert response.status_code == status.HTTP_201_CREATED, response.text
        assert response.json()['short_code'] == 'LOC-TAKEN'

    def test_update_accepts_a_code_another_organization_uses(
        self, client, auth_headers, db_session, test_user
    ) -> None:
        other_org = _make_org(db_session, 'Squatter Organization')
        _make_storage(db_session, other_org.id, test_user.id, 'Foreign', 'LOC-WANTED')
        mine = _make_storage(
            db_session, test_user.organization_id, test_user.id, 'Mine', 'LOC-OLD'
        )

        response = client.put(
            f'/api/v1/locations/{mine.id}',
            headers=auth_headers,
            json={'short_code': 'LOC-WANTED'},
        )

        assert response.status_code == status.HTTP_200_OK, response.text
        assert response.json()['short_code'] == 'LOC-WANTED'


@pytest.mark.integration
class TestShortCodeStillUniqueInsideTheOrganization:
    def test_create_rejects_a_code_the_organization_already_uses(
        self, client, auth_headers, db_session, test_user
    ) -> None:
        _make_storage(
            db_session, test_user.organization_id, test_user.id, 'First', 'LOC-DUP'
        )

        response = client.post(
            '/api/v1/locations/',
            headers=auth_headers,
            json={'name': 'Second', 'short_code': 'LOC-DUP'},
        )

        # A 500 from the raw IntegrityError would also "reject" it — the point
        # is that the caller is told what is wrong, and told it the same way
        # the update endpoint below does.
        assert response.status_code == status.HTTP_409_CONFLICT, response.text

    def test_update_rejects_a_code_the_organization_already_uses(
        self, client, auth_headers, db_session, test_user
    ) -> None:
        _make_storage(
            db_session, test_user.organization_id, test_user.id, 'First', 'LOC-DUP2'
        )
        second = _make_storage(
            db_session, test_user.organization_id, test_user.id, 'Second', 'LOC-OK'
        )

        response = client.put(
            f'/api/v1/locations/{second.id}',
            headers=auth_headers,
            json={'short_code': 'LOC-DUP2'},
        )

        assert response.status_code == status.HTTP_409_CONFLICT, response.text


@pytest.mark.integration
@pytest.mark.asyncio
class TestGeneratorSearchesOneTenant:
    async def test_generator_reuses_a_code_held_by_another_organization(
        self, real_async_db_session, async_test_user, monkeypatch
    ) -> None:
        """Otherwise one tenant's rows keep shrinking everyone else's space."""
        from app.models.organization import Organization
        from app.models.storage_location import StorageLocation
        from app.services import label_service

        theirs = Organization(name='Theirs', enabled_modules=[])
        real_async_db_session.add(theirs)
        await real_async_db_session.flush()

        # Pin the random part so the generator can only ever propose one code,
        # and hand that code to the other organization.
        monkeypatch.setattr(label_service.secrets, 'choice', lambda _alphabet: 'Z')
        real_async_db_session.add(
            StorageLocation(
                organization_id=theirs.id,
                created_by=async_test_user.id,
                name='Foreign',
                short_code='GEN-ZZZZ',
            )
        )
        await real_async_db_session.flush()

        code = await label_service.generate_short_code_async(
            real_async_db_session,
            prefix='GEN',
            max_attempts=3,
            organization_id=async_test_user.organization_id,
        )

        assert code == 'GEN-ZZZZ'

    async def test_generator_still_avoids_codes_in_its_own_organization(
        self, real_async_db_session, async_test_user, monkeypatch
    ) -> None:
        from app.models.storage_location import StorageLocation
        from app.services import label_service

        monkeypatch.setattr(label_service.secrets, 'choice', lambda _alphabet: 'Y')
        real_async_db_session.add(
            StorageLocation(
                organization_id=async_test_user.organization_id,
                created_by=async_test_user.id,
                name='Own',
                short_code='GEN-YYYY',
            )
        )
        await real_async_db_session.flush()

        with pytest.raises(Exception, match='Could not generate a unique code'):
            await label_service.generate_short_code_async(
                real_async_db_session,
                prefix='GEN',
                max_attempts=3,
                organization_id=async_test_user.organization_id,
            )

"""
Integration tests for organizations API endpoints.
"""

import pytest
from fastapi import status

from app.core.exceptions import ConflictException


@pytest.mark.integration
class TestHouseholdsCreate:
    """Tests for creating organizations."""

    def test_create_household_success(
        self, client, auth_headers, db_session, test_user
    ):
        """Test successful organization creation."""
        # Remove user from organization first
        test_user.organization_id = None
        db_session.commit()

        response = client.post(
            '/api/v1/organizations',
            headers=auth_headers,
            json={'name': 'New Organization'},
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data['name'] == 'New Organization'
        assert data['id'] is not None

    def test_create_household_already_in_household(
        self, client, auth_headers, test_user
    ):
        """Test that user cannot create organization if already in one."""
        response = client.post(
            '/api/v1/organizations',
            headers=auth_headers,
            json={'name': 'Another Organization'},
        )

        assert response.status_code == status.HTTP_409_CONFLICT
        detail = response.json().get('detail', {})
        assert 'already belongs' in detail.get('message', str(detail))

    def test_create_household_unauthorized(self, client):
        """Test that unauthenticated user cannot create organization."""
        response = client.post(
            '/api/v1/organizations', json={'name': 'Test Organization'}
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.integration
class TestHouseholdsGet:
    """Tests for getting organization information."""

    def test_get_my_household_success(self, client, auth_headers, test_household):
        """Test getting own organization."""
        response = client.get('/api/v1/organizations/my', headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['id'] == str(test_household.id)
        assert data['name'] == 'Test Organization'

    def test_get_my_household_returns_profile_fields(
        self, client, auth_headers, db_session, test_household
    ):
        test_household.active_profile_id = 'equipment_wms'
        test_household.onboarding_completed = True
        db_session.commit()

        response = client.get('/api/v1/organizations/my', headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['active_profile_id'] == 'equipment_wms'
        assert data['onboarding_completed'] is True

    def test_get_my_household_not_in_household(
        self, client, auth_headers, db_session, test_user
    ):
        """Test getting organization when user is not in any."""
        test_user.organization_id = None
        db_session.commit()

        response = client.get('/api/v1/organizations/my', headers=auth_headers)

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_get_household_members(self, client, auth_headers, test_user, test_user2):
        """Test getting organization members (paginated envelope)."""
        response = client.get('/api/v1/organizations/my/members', headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert 'items' in data and 'total' in data
        assert data['total'] >= 2  # At least test_user and test_user2
        emails = [m['email'] for m in data['items']]
        assert 'test@example.com' in emails
        assert 'test2@example.com' in emails

    def test_get_household_members_paginated(
        self, client, auth_headers, test_user, test_user2
    ):
        """Test that offset/limit query params control the page slice."""
        response = client.get(
            '/api/v1/organizations/my/members',
            params={'offset': 0, 'limit': 1},
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['limit'] == 1
        assert data['offset'] == 0
        assert len(data['items']) == 1
        assert data['has_more'] is True
        assert data['total'] >= 2

    def test_get_household_members_empty_org(
        self, client, auth_headers_user2, db_session, test_user2
    ):
        """Test members endpoint when current user has no organization."""
        test_user2.organization_id = None
        db_session.commit()

        response = client.get(
            '/api/v1/organizations/my/members',
            headers=auth_headers_user2,
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['items'] == []
        assert data['total'] == 0

    def test_get_household_members_search(
        self, client, auth_headers, test_user, test_user2
    ):
        """Test that ``search`` narrows results to email/full_name substring."""
        response = client.get(
            '/api/v1/organizations/my/members',
            params={'search': 'test2@example.com'},
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        emails = [m['email'] for m in data['items']]
        assert emails == ['test2@example.com']
        assert data['total'] >= 2  # total is org-wide, NOT filtered

    def test_get_household_members_search_full_name(
        self, client, auth_headers, test_user, test_user2
    ):
        """Search also matches full_name (case-insensitive)."""
        response = client.get(
            '/api/v1/organizations/my/members',
            params={'search': 'Test User 2'},
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data['items']) == 1
        assert data['items'][0]['email'] == 'test2@example.com'


@pytest.mark.integration
class TestHouseholdsUpdate:
    """Tests for updating organization."""

    def test_update_household_success(self, client, auth_headers, test_household):
        """Test successful organization update."""
        response = client.put(
            '/api/v1/organizations',
            headers=auth_headers,
            json={'name': 'Updated Organization Name'},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['name'] == 'Updated Organization Name'

    def test_update_household_not_in_household(
        self, client, auth_headers, db_session, test_user
    ):
        """Test updating organization when not in one."""
        test_user.organization_id = None
        db_session.commit()

        response = client.put(
            '/api/v1/organizations', headers=auth_headers, json={'name': 'Test'}
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.integration
class TestOrganizationIssuer:
    """issuer identity (tax_id, country, address) on the organization."""

    def test_update_issuer_fields(
        self, client, auth_headers, db_session, test_household
    ):
        response = client.put(
            '/api/v1/organizations',
            headers=auth_headers,
            json={
                'tax_id': 'PL1234567890',
                'country': 'PL',
                'address': {
                    'street': 'Warehouse St 1',
                    'city': 'Warsaw',
                    'postal_code': '00-001',
                },
            },
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['tax_id'] == 'PL1234567890'
        assert data['country'] == 'PL'
        assert data['address'] == {
            'street': 'Warehouse St 1',
            'city': 'Warsaw',
            'postal_code': '00-001',
        }
        db_session.refresh(test_household)
        assert test_household.tax_id == 'PL1234567890'

    def test_get_my_organization_returns_issuer_fields(
        self, client, auth_headers, db_session, test_household
    ):
        test_household.tax_id = 'PL1234567890'
        test_household.country = 'PL'
        test_household.address = {'street': 'Warehouse St 1', 'city': 'Warsaw'}
        db_session.commit()

        response = client.get('/api/v1/organizations/my', headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['tax_id'] == 'PL1234567890'
        assert data['country'] == 'PL'
        assert data['address']['street'] == 'Warehouse St 1'
        assert data['logo_url'] is None

    def test_update_issuer_country_normalized_to_upper(self, client, auth_headers):
        response = client.put(
            '/api/v1/organizations',
            headers=auth_headers,
            json={'country': 'pl'},
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()['country'] == 'PL'

    def test_update_issuer_rejects_invalid_country(self, client, auth_headers):
        response = client.put(
            '/api/v1/organizations',
            headers=auth_headers,
            json={'country': 'XX'},
        )

        # Pydantic validation → 422, same convention as partner addresses.
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_update_issuer_rejects_unknown_address_keys(self, client, auth_headers):
        response = client.put(
            '/api/v1/organizations',
            headers=auth_headers,
            json={'address': {'street': 'X', 'country': 'PL'}},
        )

        # extra='forbid' → 422 from pydantic validation.
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


@pytest.mark.integration
class TestOrganizationLogo:
    """logo upload/delete and serving through /uploads."""

    @staticmethod
    def _png_bytes() -> bytes:
        # 1x1 transparent PNG.
        return (
            b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
            b'\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01'
            b'\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
        )

    def test_upload_logo_then_serve_then_delete(
        self, client, auth_headers, test_household
    ):
        upload = client.post(
            '/api/v1/organizations/logo',
            headers=auth_headers,
            files={'image': ('logo.png', self._png_bytes(), 'image/png')},
        )

        assert upload.status_code == status.HTTP_200_OK, upload.text
        logo_url = upload.json()['logo_url']
        assert logo_url == f'{test_household.id}/organizations/logo.png'

        # The logo is servable through the uploads route (resolver ownership).
        served = client.get(f'/uploads/{logo_url}', headers=auth_headers)
        assert served.status_code == status.HTTP_200_OK
        assert served.headers['content-type'] == 'image/png'
        assert len(served.content) > 0

        # Visible on the organization.
        mine = client.get('/api/v1/organizations/my', headers=auth_headers)
        assert mine.json()['logo_url'] == logo_url

        # Removing it clears the field and the file is gone.
        deleted = client.delete('/api/v1/organizations/logo', headers=auth_headers)
        assert deleted.status_code == status.HTTP_204_NO_CONTENT
        mine = client.get('/api/v1/organizations/my', headers=auth_headers)
        assert mine.json()['logo_url'] is None
        gone = client.get(f'/uploads/{logo_url}', headers=auth_headers)
        assert gone.status_code == status.HTTP_404_NOT_FOUND

    def test_upload_logo_rejects_non_image(self, client, auth_headers):
        response = client.post(
            '/api/v1/organizations/logo',
            headers=auth_headers,
            files={'image': ('logo.txt', b'not an image', 'text/plain')},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_upload_logo_rejects_signature_mismatch(self, client, auth_headers):
        response = client.post(
            '/api/v1/organizations/logo',
            headers=auth_headers,
            files={'image': ('logo.png', b'not really a png', 'image/png')},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.integration
class TestHouseholdsLeave:
    """Tests for leaving organization."""

    def test_leave_household_success(
        self, client, auth_headers_user2, db_session, test_user2
    ):
        """Test successful leaving organization."""
        response = client.post(
            '/api/v1/organizations/my/leave', headers=auth_headers_user2
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert 'Left' in data['message']

        # Verify user is no longer in organization
        db_session.refresh(test_user2)
        assert test_user2.organization_id is None

    def test_leave_household_not_in_household(
        self, client, auth_headers_user2, db_session, test_user2
    ):
        """Test leaving when not in organization."""
        test_user2.organization_id = None
        db_session.commit()

        response = client.post(
            '/api/v1/organizations/my/leave', headers=auth_headers_user2
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_leave_household_only_admin(
        self, client, auth_headers, db_session, test_user, test_household
    ):
        """Test that sole admin cannot leave."""
        # Set created_by to test_user so the check passes
        test_household.created_by = test_user.id
        db_session.commit()

        response = client.post('/api/v1/organizations/my/leave', headers=auth_headers)

        assert response.status_code == status.HTTP_409_CONFLICT
        detail = response.json().get('detail', {})
        assert 'sole administrator' in detail.get('message', str(detail))


@pytest.mark.integration
class TestHouseholdsRemoveMember:
    """Tests for removing members."""

    def test_remove_member_success(
        self, client, auth_headers, db_session, test_user, test_user2
    ):
        """Test successful member removal."""
        response = client.post(
            f'/api/v1/organizations/my/remove-member/{test_user2.id}',
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert 'removed' in data['message']

        # Verify user is removed
        db_session.refresh(test_user2)
        assert test_user2.organization_id is None

    def test_remove_member_not_admin(
        self, client, auth_headers_user2, db_session, test_user, test_user2
    ):
        """Test that non-admin cannot remove members."""
        response = client.post(
            f'/api/v1/organizations/my/remove-member/{test_user.id}',
            headers=auth_headers_user2,
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_remove_member_self(self, client, auth_headers, test_user):
        """Test that user cannot remove themselves."""
        response = client.post(
            f'/api/v1/organizations/my/remove-member/{test_user.id}',
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        detail = response.json().get('detail', {})
        assert 'yourself' in detail.get('message', str(detail))


@pytest.mark.integration
class TestOrganizationMemberRole:
    """Changing what a member of the organization is allowed to do.

    The `manager` role gates real endpoints — closing an inventory period,
    editing the document profile, cancelling a purchase order — and appears in
    the approval-stage picker, but nothing in the product could grant it:
    registration produces `admin` or `user`, and the CLI produces `admin`.
    """

    def test_admin_promotes_a_member_to_manager(
        self, client, auth_headers, db_session, test_user2
    ):
        response = client.patch(
            f'/api/v1/organizations/my/members/{test_user2.id}/role',
            headers=auth_headers,
            json={'role': 'manager'},
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()['role'] == 'manager'
        db_session.refresh(test_user2)
        assert test_user2.role == 'manager'

    def test_unknown_role_is_rejected(self, client, auth_headers, test_user2):
        response = client.patch(
            f'/api/v1/organizations/my/members/{test_user2.id}/role',
            headers=auth_headers,
            json={'role': 'wizard'},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_admin_cannot_change_their_own_role(self, client, auth_headers, test_user):
        response = client.patch(
            f'/api/v1/organizations/my/members/{test_user.id}/role',
            headers=auth_headers,
            json={'role': 'user'},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_demoting_another_admin_is_allowed_while_one_remains(
        self, client, auth_headers, db_session, test_user2
    ):
        """The caller is an admin, so demoting a second one leaves one behind."""
        test_user2.role = 'admin'
        db_session.commit()

        response = client.patch(
            f'/api/v1/organizations/my/members/{test_user2.id}/role',
            headers=auth_headers,
            json={'role': 'user'},
        )

        assert response.status_code == status.HTTP_200_OK
        db_session.refresh(test_user2)
        assert test_user2.role == 'user'

    def test_a_member_cannot_change_roles(self, client, auth_headers_user2, test_user):
        response = client.patch(
            f'/api/v1/organizations/my/members/{test_user.id}/role',
            headers=auth_headers_user2,
            json={'role': 'admin'},
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_member_with_admin_access_custom_role_can_change_roles(
        self, client, auth_headers_user2, db_session, test_user, test_user2
    ):
        """A custom role carrying admin:access reaches the org-admin endpoints
               the built-in admin level reaches — the guard checks the permission,
        not the role name."""
        import uuid as _uuid

        from app.models.role import Role, UserRole
        from app.models.user import User
        from app.services.token_service import get_password_hash

        role = Role(
            organization_id=test_user.organization_id,
            name='Org Administrator',
            permissions=['admin:access'],
            is_system=False,
        )
        db_session.add(role)
        db_session.flush()
        db_session.add(UserRole(user_id=test_user2.id, role_id=role.id))
        # A third member as the target: demoting the sole enum admin would hit
        # the last-administrator guard instead of proving the permission gate.
        target = User(
            email=f'rol10_target_{_uuid.uuid4().hex[:8]}@example.com',
            hashed_password=get_password_hash('pass'),
            organization_id=test_user.organization_id,
            role='user',
            is_active=True,
        )
        db_session.add(target)
        db_session.commit()

        response = client.patch(
            f'/api/v1/organizations/my/members/{target.id}/role',
            headers=auth_headers_user2,
            json={'role': 'manager'},
        )

        assert response.status_code == status.HTTP_200_OK, response.text
        db_session.refresh(target)
        assert target.role == 'manager'


@pytest.mark.integration
@pytest.mark.asyncio
class TestChangeMemberRoleService:
    """The guard the endpoint cannot reach.

    Through the API the caller is always an administrator, so the member being
    demoted is never the last one. The service is the layer that will be
    called from elsewhere — a CLI, a bulk import — and an organization with no
    administrator left cannot manage its own modules, members or approvals.
    """

    async def test_refuses_to_demote_the_only_administrator(
        self, real_async_db_session
    ):
        from app.core.testing import ModuleTestHelper
        from app.models.organization import Organization
        from app.services._org_membership import change_member_role

        org = Organization(name='Solo Admin Org')
        real_async_db_session.add(org)
        await real_async_db_session.flush()
        admin = await ModuleTestHelper.create_user_async(
            real_async_db_session, org, email='solo-admin@example.com', role='admin'
        )

        with pytest.raises(ConflictException):
            await change_member_role(real_async_db_session, admin, 'user', org.id)

    async def test_allows_the_demotion_when_another_administrator_remains(
        self, real_async_db_session
    ):
        from app.core.testing import ModuleTestHelper
        from app.models.organization import Organization
        from app.services._org_membership import change_member_role

        org = Organization(name='Two Admin Org')
        real_async_db_session.add(org)
        await real_async_db_session.flush()
        await ModuleTestHelper.create_user_async(
            real_async_db_session, org, email='admin-one@example.com', role='admin'
        )
        second = await ModuleTestHelper.create_user_async(
            real_async_db_session, org, email='admin-two@example.com', role='admin'
        )

        await change_member_role(real_async_db_session, second, 'manager', org.id)

        assert second.role == 'manager'


@pytest.mark.integration
class TestMemberCustomRole:
    """Org-scoped custom roles on the member list and in role changes (/4).

    A member carries either a built-in level (enum ``user.role``) or one
    org-scoped custom role. Picking the enum clears custom role links; picking
    a custom role replaces whichever custom role the member held, and the enum
    stays as the base level the built-in guards still read.
    """

    @staticmethod
    def _create_role(client, auth_headers, name='Magazynier', permissions=None):
        response = client.post(
            '/api/v1/roles',
            headers=auth_headers,
            json={'name': name, 'permissions': permissions or ['items:read']},
        )
        assert response.status_code == status.HTTP_201_CREATED
        return response.json()

    @staticmethod
    def _members_by_email(client, auth_headers):
        response = client.get('/api/v1/organizations/my/members', headers=auth_headers)
        assert response.status_code == status.HTTP_200_OK
        return {m['email']: m for m in response.json()['items']}

    def test_members_list_includes_assigned_custom_role(
        self, client, auth_headers, test_user2
    ):
        role = self._create_role(client, auth_headers)
        assign = client.post(
            f'/api/v1/roles/users/{test_user2.id}/{role["id"]}', headers=auth_headers
        )
        assert assign.status_code == status.HTTP_200_OK

        members = self._members_by_email(client, auth_headers)

        custom = members['test2@example.com']['custom_role']
        assert custom['id'] == role['id']
        assert custom['name'] == 'Magazynier'
        assert custom['permissions'] == ['items:read']
        assert members['test@example.com']['custom_role'] is None

    def test_role_change_accepts_role_id_and_keeps_enum_base_level(
        self, client, auth_headers, db_session, test_user2
    ):
        role = self._create_role(client, auth_headers)

        response = client.patch(
            f'/api/v1/organizations/my/members/{test_user2.id}/role',
            headers=auth_headers,
            json={'role_id': role['id']},
        )

        assert response.status_code == status.HTTP_200_OK
        db_session.refresh(test_user2)
        assert test_user2.role == 'user'  # base level untouched
        members = self._members_by_email(client, auth_headers)
        assert members['test2@example.com']['custom_role']['id'] == role['id']

    def test_role_change_to_enum_clears_custom_role_links(
        self, client, auth_headers, db_session, test_user2
    ):
        role = self._create_role(client, auth_headers)
        client.patch(
            f'/api/v1/organizations/my/members/{test_user2.id}/role',
            headers=auth_headers,
            json={'role_id': role['id']},
        )

        response = client.patch(
            f'/api/v1/organizations/my/members/{test_user2.id}/role',
            headers=auth_headers,
            json={'role': 'manager'},
        )

        assert response.status_code == status.HTTP_200_OK
        db_session.refresh(test_user2)
        assert test_user2.role == 'manager'
        members = self._members_by_email(client, auth_headers)
        assert members['test2@example.com']['custom_role'] is None

    def test_role_change_with_role_id_replaces_previous_custom_role(
        self, client, auth_headers, test_user2
    ):
        role_a = self._create_role(client, auth_headers, name='Role A')
        role_b = self._create_role(client, auth_headers, name='Role B')
        client.patch(
            f'/api/v1/organizations/my/members/{test_user2.id}/role',
            headers=auth_headers,
            json={'role_id': role_a['id']},
        )

        client.patch(
            f'/api/v1/organizations/my/members/{test_user2.id}/role',
            headers=auth_headers,
            json={'role_id': role_b['id']},
        )

        members = self._members_by_email(client, auth_headers)
        assert members['test2@example.com']['custom_role']['id'] == role_b['id']

    def test_role_change_rejects_role_from_other_organization(
        self, client, auth_headers, db_session, test_household, test_user2
    ):
        from app.models.organization import Organization
        from app.models.role import Role

        other_org = Organization(name='Other Org', enabled_modules=[])
        db_session.add(other_org)
        db_session.flush()
        foreign_role = Role(
            organization_id=other_org.id, name='Foreign', permissions=[]
        )
        db_session.add(foreign_role)
        db_session.commit()

        response = client.patch(
            f'/api/v1/organizations/my/members/{test_user2.id}/role',
            headers=auth_headers,
            json={'role_id': str(foreign_role.id)},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_rejected_role_change_leaves_the_previous_custom_role(
        self, client, auth_headers, db_session, test_user2
    ):
        """A refused assignment must not cost the member the role they had.

        Assigning a custom role forgets the member's previous links before it
        adds the new one, so between those two writes the member holds nothing.
        When the second write refuses, only the request's rollback puts the old
        link back — a property of the session dependency, not of this code, and
        one that a reordering here would silently lose.
        """
        from app.models.organization import Organization
        from app.models.role import Role

        held = self._create_role(client, auth_headers, name='Held')
        client.patch(
            f'/api/v1/organizations/my/members/{test_user2.id}/role',
            headers=auth_headers,
            json={'role_id': held['id']},
        )

        other_org = Organization(name='Other Org', enabled_modules=[])
        db_session.add(other_org)
        db_session.flush()
        foreign_role = Role(
            organization_id=other_org.id, name='Foreign', permissions=[]
        )
        db_session.add(foreign_role)
        db_session.commit()

        refused = client.patch(
            f'/api/v1/organizations/my/members/{test_user2.id}/role',
            headers=auth_headers,
            json={'role_id': str(foreign_role.id)},
        )

        assert refused.status_code == status.HTTP_400_BAD_REQUEST
        members = self._members_by_email(client, auth_headers)
        assert members['test2@example.com']['custom_role']['id'] == held['id']

    def test_role_change_requires_exactly_one_of_role_or_role_id(
        self, client, auth_headers, test_user2
    ):
        role = self._create_role(client, auth_headers)

        neither = client.patch(
            f'/api/v1/organizations/my/members/{test_user2.id}/role',
            headers=auth_headers,
            json={},
        )
        both = client.patch(
            f'/api/v1/organizations/my/members/{test_user2.id}/role',
            headers=auth_headers,
            json={'role': 'user', 'role_id': role['id']},
        )

        # Body-shape violations are request validation — FastAPI's 422, not
        # the 400 the business checks raise.
        assert neither.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        assert both.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_custom_role_assigned_to_admin_replaces_the_level(
        self, client, auth_headers, db_session, test_household
    ):
        """a custom role replaces the admin level, it does not
        decorate it. While another administrator remains the move is allowed
        (the sole-admin guard is covered elsewhere), and afterwards the
        member's authority is exactly what the role grants — admin endpoints
        answer 403 and the member list shows the same truth."""
        import uuid as _uuid

        from app.models.user import User
        from app.services.token_service import create_access_token, get_password_hash

        role = self._create_role(client, auth_headers)  # grants items:read only
        second_admin = User(
            email=f'rol13_admin_{_uuid.uuid4().hex[:8]}@example.com',
            hashed_password=get_password_hash('pass'),
            organization_id=test_household.id,
            role='admin',
            is_active=True,
        )
        db_session.add(second_admin)
        db_session.commit()
        admin_headers = {
            'Authorization': f'Bearer {create_access_token(data={"sub": str(second_admin.id)})}'
        }

        before = client.get(
            '/api/v1/organizations/my/invitations', headers=admin_headers
        )
        assert before.status_code == status.HTTP_200_OK

        response = client.patch(
            f'/api/v1/organizations/my/members/{second_admin.id}/role',
            headers=auth_headers,
            json={'role_id': role['id']},
        )

        assert response.status_code == status.HTTP_200_OK, response.text
        assert response.json()['role'] == 'user'
        db_session.refresh(second_admin)
        assert second_admin.role == 'user'

        after = client.get(
            '/api/v1/organizations/my/invitations', headers=admin_headers
        )
        assert after.status_code == status.HTTP_403_FORBIDDEN
        members = self._members_by_email(client, auth_headers)
        assert members[second_admin.email]['custom_role']['id'] == role['id']


@pytest.mark.integration
@pytest.mark.asyncio
class TestChangeMemberRoleCustomRoleGuard:
    """The last-administrator guard also covers 'enum admin -> custom role'."""

    async def test_refuses_custom_role_for_the_only_administrator(
        self, real_async_db_session
    ):
        from app.core.testing import ModuleTestHelper
        from app.models.organization import Organization
        from app.models.role import Role
        from app.services._org_membership import change_member_role

        org = Organization(name='Solo Admin Custom Role Org')
        real_async_db_session.add(org)
        await real_async_db_session.flush()
        admin = await ModuleTestHelper.create_user_async(
            real_async_db_session, org, email='solo-admin-cr@example.com', role='admin'
        )
        role = Role(organization_id=org.id, name='Limited', permissions=[])
        real_async_db_session.add(role)
        await real_async_db_session.flush()

        with pytest.raises(ConflictException):
            await change_member_role(
                real_async_db_session,
                admin,
                None,
                org.id,
                role_id=role.id,
                actor_user_id=admin.id,
            )


@pytest.mark.integration
class TestInvitationCustomRole:
    """Invitation codes may carry an org-scoped custom role."""

    def test_invitation_code_with_role_id_joins_with_custom_role(
        self, client, auth_headers, db_session
    ):
        from app.models.user import User
        from app.services.token_service import create_access_token, get_password_hash

        role_response = client.post(
            '/api/v1/roles',
            headers=auth_headers,
            json={'name': 'Magazynier', 'permissions': ['items:read']},
        )
        role_id = role_response.json()['id']

        invite = client.post(
            '/api/v1/organizations/my/invitation-code',
            headers=auth_headers,
            json={'role_id': role_id},
        )
        assert invite.status_code == status.HTTP_200_OK
        assert invite.json()['role_id'] == role_id

        newcomer = User(
            email='newcomer@example.com',
            hashed_password=get_password_hash('testpassword123'),
            full_name='New Comer',
            organization_id=None,
            role='user',
            is_active=True,
        )
        db_session.add(newcomer)
        db_session.commit()
        newcomer_headers = {
            'Authorization': f'Bearer {create_access_token(data={"sub": str(newcomer.id)})}'
        }

        join = client.post(
            '/api/v1/organizations/join',
            headers=newcomer_headers,
            json={'code': invite.json()['code']},
        )
        assert join.status_code == status.HTTP_200_OK

        members_response = client.get(
            '/api/v1/organizations/my/members', headers=auth_headers
        )
        members = {m['email']: m for m in members_response.json()['items']}
        joined = members['newcomer@example.com']
        assert joined['role'] == 'user'  # base level
        assert joined['custom_role']['id'] == role_id

    def test_every_invitation_carries_the_role_it_was_asked_for(
        self, client, auth_headers
    ):
        def create_role(name):
            return client.post(
                '/api/v1/roles', headers=auth_headers, json={'name': name}
            ).json()['id']

        role_a = create_role('Scope Role A')
        role_b = create_role('Scope Role B')

        first = client.post(
            '/api/v1/organizations/my/invitation-code',
            headers=auth_headers,
            json={'role_id': role_a},
        ).json()
        same_role = client.post(
            '/api/v1/organizations/my/invitation-code',
            headers=auth_headers,
            json={'role_id': role_a},
        ).json()
        other_role = client.post(
            '/api/v1/organizations/my/invitation-code',
            headers=auth_headers,
            json={'role_id': role_b},
        ).json()
        plain_enum = client.post(
            '/api/v1/organizations/my/invitation-code',
            headers=auth_headers,
            json={'role': 'user'},
        ).json()

        # Every call mints its own code, and each one carries the role it was
        # asked for — the next arrival must not land with permissions chosen
        # for somebody else.
        assert len({first['code'], same_role['code'], other_role['code']}) == 3
        assert first['role_id'] == same_role['role_id'] == role_a
        assert other_role['role_id'] == role_b
        assert plain_enum['role_id'] is None

    def test_invitation_code_rejects_role_from_other_organization(
        self, client, auth_headers, db_session
    ):
        from app.models.organization import Organization
        from app.models.role import Role

        other_org = Organization(name='Other Org', enabled_modules=[])
        db_session.add(other_org)
        db_session.flush()
        foreign_role = Role(
            organization_id=other_org.id, name='Foreign', permissions=[]
        )
        db_session.add(foreign_role)
        db_session.commit()

        response = client.post(
            '/api/v1/organizations/my/invitation-code',
            headers=auth_headers,
            json={'role_id': str(foreign_role.id)},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.integration
class TestInvitationMailQueue:
    """``email_sent`` says the queue took the row, not that mail arrived.

    A configured but dead SMTP accepts an invitation exactly like a healthy
    one, and an installation without SMTP accepts none — so the field answers
    "was this handed over for delivery", which is what the screen needs to
    decide whether the administrator has to carry the link themselves.
    """

    def test_a_configured_but_dead_smtp_reports_the_invitation_queued(
        self, client, auth_headers, db_session, async_engine_fixture, monkeypatch
    ):
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

        from app.models.email_job import EmailJob

        # Production rides the queue; the TESTING fast-path sends through a
        # real socket and would report the truth for the wrong reason. The
        # mail server is stated rather than inherited from the machine.
        monkeypatch.setattr('app.services.email_service.settings.TESTING', False)
        for name, value in (
            ('SMTP_HOST', 'smtp.test.invalid'),
            ('SMTP_PORT', 587),
            ('SMTP_ENCRYPTION', 'starttls'),
            ('SMTP_USER', 'queue@test.invalid'),
            ('SMTP_PASSWORD', 'secret'),
        ):
            monkeypatch.setattr(f'app.services.email_service.settings.{name}', value)

        # The enqueuer opens a session of its own through the facade; pointed
        # at the test database so the row it writes is the one asserted below.
        # Patched on app.database, which the facade forwards to: monkeypatch
        # on the facade itself leaves a real attribute behind when it undoes.
        monkeypatch.setattr(
            'app.database.AsyncSessionLocal',
            async_sessionmaker(
                async_engine_fixture, class_=AsyncSession, expire_on_commit=False
            ),
        )

        response = client.post(
            '/api/v1/organizations/my/invitation-code',
            headers=auth_headers,
            json={'role': 'user', 'email': 'queued@example.com'},
        )

        assert response.status_code == status.HTTP_200_OK, response.text
        assert response.json()['email_sent'] is True

        # Nothing has been delivered: the invitation is a pending row waiting
        # for the worker, and no attempt against the dead relay has been made.
        job = db_session.scalar(
            select(EmailJob).where(EmailJob.to_email == 'queued@example.com')
        )
        assert job is not None
        assert job.status == 'pending'
        assert job.attempts == 0


@pytest.mark.integration
class TestFailedEmails:
    """Mail that exhausted its retries, seen from the organization it belongs to.

    The queue marked the row ``failed`` and stopped. Nothing read that table:
    no endpoint, no screen, no notification — so an invitation nobody
    received and a password-reset link that locked its user out both ended
    as one line in a container log.
    """

    def _job(self, organization_id, **overrides):
        from app.models.email_job import EmailJob

        fields = {
            'organization_id': organization_id,
            'to_email': 'invitee@example.com',
            'subject': 'You have been invited',
            'html_content': '<p>join us</p>',
            'status': 'failed',
            'attempts': 5,
            'max_attempts': 5,
            'last_error': '[Errno 111] Connection refused',
        }
        fields.update(overrides)
        return EmailJob(**fields)

    def test_lists_only_this_organizations_exhausted_mail(
        self, client, auth_headers, db_session, test_user
    ):
        from uuid import uuid4

        db_session.add_all(
            [
                self._job(test_user.organization_id),
                # Another tenant's failure is not this administrator's to read:
                # the address and the subject are that organization's own.
                self._job(uuid4(), to_email='stranger@example.com'),
                # Still retrying — it has not been lost yet, and listing it
                # would ask for action on a message that may still arrive.
                self._job(
                    test_user.organization_id,
                    to_email='pending@example.com',
                    status='pending',
                    attempts=2,
                ),
            ]
        )
        db_session.commit()

        response = client.get(
            '/api/v1/organizations/my/failed-emails', headers=auth_headers
        )

        assert response.status_code == status.HTTP_200_OK
        rows = response.json()['items']
        assert [row['to_email'] for row in rows] == ['invitee@example.com']
        assert rows[0]['subject'] == 'You have been invited'
        assert 'Connection refused' in rows[0]['last_error']
        assert rows[0]['attempts'] == 5

    def test_an_ordinary_member_cannot_read_the_failures(
        self, client, auth_headers_user2, db_session, test_user2
    ):
        db_session.add(self._job(test_user2.organization_id))
        db_session.commit()

        response = client.get(
            '/api/v1/organizations/my/failed-emails', headers=auth_headers_user2
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

"""
Integration tests for Partners API.
TDD RED phase — all tests are expected to FAIL until implementation is complete.
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.user import User
from app.services.token_service import create_access_token, get_password_hash

# ---------------------------------------------------------------------------
# Helpers / shared payload factories
# ---------------------------------------------------------------------------


def _supplier_payload(**overrides) -> dict:
    base = {
        'name': 'Hurtownia ABC',
        'type': 'SUPPLIER',
        'tax_id': 'PL1234567890',
        'email': 'contact@wholesaler.example.org',
        'phone': '+48 123 456 789',
        'website': 'https://wholesaler.example.org',
        'contact_person': 'Jan Kowalski',
        'address': {
            'street': 'ul. Testowa 1',
            'city': 'Warszawa',
            'postal_code': '00-001',
            'country': 'PL',
        },
        'notes': 'Sprawdzony dostawca',
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Extra fixtures for multi-tenancy tests
# ---------------------------------------------------------------------------


@pytest.fixture
def other_org(db_session: Session) -> Organization:
    """Creates a second organisation (different tenant)."""
    org = Organization(
        name='Other Organisation',
        enabled_modules=['core'],
    )
    db_session.add(org)
    db_session.commit()
    db_session.refresh(org)
    return org


@pytest.fixture
def other_org_user(db_session: Session, other_org: Organization) -> User:
    """Creates a user belonging to the other organisation."""
    user = User(
        email='other@example.com',
        hashed_password=get_password_hash('password123'),
        full_name='Other User',
        organization_id=other_org.id,
        role='admin',
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def other_org_auth_headers(other_org_user: User) -> dict:
    """Returns auth headers for the other-org user."""
    token = create_access_token(data={'sub': str(other_org_user.id)})
    return {'Authorization': f'Bearer {token}'}


# ---------------------------------------------------------------------------
# TestPartnersCreate
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestPartnersCreate:
    def test_create_supplier_returns_201(self, client: TestClient, auth_headers: dict):
        """POST /api/v1/partners → 201, response has id, name, type, is_active=True"""
        resp = client.post(
            '/api/v1/partners', json=_supplier_payload(), headers=auth_headers
        )
        assert resp.status_code == 201
        data = resp.json()
        assert 'id' in data
        assert data['name'] == 'Hurtownia ABC'
        assert data['type'] == 'SUPPLIER'
        assert data['is_active'] is True
        assert 'organization_id' in data
        assert 'created_at' in data

    def test_create_all_types_accepted(self, client: TestClient, auth_headers: dict):
        """POST with each type → 201"""
        for i, ptype in enumerate(
            ['SUPPLIER', 'CUSTOMER', 'BOTH', 'SERVICE_PROVIDER', 'MANUFACTURER']
        ):
            resp = client.post(
                '/api/v1/partners',
                json=_supplier_payload(name=f'Partner {i}', type=ptype),
                headers=auth_headers,
            )
            assert resp.status_code == 201, f'Failed for type={ptype}: {resp.text}'
            assert resp.json()['type'] == ptype

    def test_create_duplicate_name_type_same_org_returns_409(
        self, client: TestClient, auth_headers: dict
    ):
        """POST same (name, type) twice → 409 Conflict"""
        payload = _supplier_payload()
        assert (
            client.post(
                '/api/v1/partners', json=payload, headers=auth_headers
            ).status_code
            == 201
        )
        resp = client.post('/api/v1/partners', json=payload, headers=auth_headers)
        assert resp.status_code == 409

    def test_create_same_name_different_type_allowed(
        self, client: TestClient, auth_headers: dict
    ):
        """POST same name but different type → 201 (uniqueness is org+name+type)"""
        name = 'Universal Dostawca'
        assert (
            client.post(
                '/api/v1/partners',
                json=_supplier_payload(name=name, type='SUPPLIER'),
                headers=auth_headers,
            ).status_code
            == 201
        )
        resp = client.post(
            '/api/v1/partners',
            json=_supplier_payload(name=name, type='CUSTOMER'),
            headers=auth_headers,
        )
        assert resp.status_code == 201

    def test_create_invalid_type_returns_422(
        self, client: TestClient, auth_headers: dict
    ):
        """POST with type='INVALID' → 422"""
        resp = client.post(
            '/api/v1/partners',
            json=_supplier_payload(type='INVALID'),
            headers=auth_headers,
        )
        assert resp.status_code == 422

    def test_create_rejects_unknown_address_keys(
        self, client: TestClient, auth_headers: dict
    ):
        """POST with an address key outside the schema → 422 (extra='forbid')."""
        resp = client.post(
            '/api/v1/partners',
            json=_supplier_payload(
                address={
                    'street': 'ul. Testowa 1',
                    'city': 'Warszawa',
                    'postal_code': '00-001',
                    'country': 'PL',
                    'floor': '3',
                }
            ),
            headers=auth_headers,
        )
        assert resp.status_code == 422

    def test_create_rejects_invalid_country_code(
        self, client: TestClient, auth_headers: dict
    ):
        """POST with a free-text country → 422."""
        resp = client.post(
            '/api/v1/partners',
            json=_supplier_payload(
                address={
                    'street': 'ul. Testowa 1',
                    'city': 'Warszawa',
                    'country': 'Polska',
                }
            ),
            headers=auth_headers,
        )
        assert resp.status_code == 422

    def test_create_normalizes_country_code_to_uppercase(
        self, client: TestClient, auth_headers: dict
    ):
        """POST with lowercase country → 201, stored and returned uppercase."""
        resp = client.post(
            '/api/v1/partners',
            json=_supplier_payload(
                address={
                    'street': 'ul. Testowa 1',
                    'city': 'Warszawa',
                    'country': 'pl',
                }
            ),
            headers=auth_headers,
        )
        assert resp.status_code == 201
        assert resp.json()['address']['country'] == 'PL'

    def test_create_missing_name_returns_422(
        self, client: TestClient, auth_headers: dict
    ):
        """POST without name → 422"""
        payload = _supplier_payload()
        del payload['name']
        resp = client.post('/api/v1/partners', json=payload, headers=auth_headers)
        assert resp.status_code == 422

    def test_create_without_auth_returns_401(self, client: TestClient):
        """POST without token → 401"""
        resp = client.post('/api/v1/partners', json=_supplier_payload())
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# TestPartnersList
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestPartnersList:
    def test_list_empty_returns_200(self, client: TestClient, auth_headers: dict):
        """GET /api/v1/partners → 200, {items: [], total: 0}"""
        resp = client.get('/api/v1/partners', headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data['items'] == []
        assert data['total'] == 0

    def test_list_returns_created_partners(
        self, client: TestClient, auth_headers: dict
    ):
        """Create 3 partners, GET → total=3, all present"""
        for i in range(3):
            client.post(
                '/api/v1/partners',
                json=_supplier_payload(name=f'Partner {i}'),
                headers=auth_headers,
            )
        resp = client.get('/api/v1/partners', headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data['total'] == 3
        assert len(data['items']) == 3

    def test_list_answers_with_the_page_envelope(
        self, client: TestClient, auth_headers: dict
    ):
        """GET ?limit=2 → items, total, limit, offset and has_more, as every list"""
        for i in range(3):
            client.post(
                '/api/v1/partners',
                json=_supplier_payload(name=f'Partner {i}'),
                headers=auth_headers,
            )
        first = client.get('/api/v1/partners?limit=2', headers=auth_headers).json()
        assert (first['total'], first['limit'], first['offset']) == (3, 2, 0)
        assert len(first['items']) == 2
        assert first['has_more'] is True
        last = client.get(
            '/api/v1/partners?limit=2&offset=2', headers=auth_headers
        ).json()
        assert len(last['items']) == 1
        assert last['has_more'] is False

    def test_list_search_by_name(self, client: TestClient, auth_headers: dict):
        """GET ?search=hurtownia → only matching partner returned"""
        client.post(
            '/api/v1/partners',
            json=_supplier_payload(name='Hurtownia Wielka'),
            headers=auth_headers,
        )
        client.post(
            '/api/v1/partners',
            json=_supplier_payload(
                name='Sklep ABC',
                type='CUSTOMER',
                email='info@shop.example.org',
                website='https://shop.example.org',
                contact_person='Anna Nowak',
            ),
            headers=auth_headers,
        )
        resp = client.get('/api/v1/partners?search=hurtownia', headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data['total'] == 1
        assert data['items'][0]['name'] == 'Hurtownia Wielka'

    def test_list_search_by_tax_id(self, client: TestClient, auth_headers: dict):
        """GET ?search=PL999 → matches on tax_id"""
        client.post(
            '/api/v1/partners',
            json=_supplier_payload(name='Firma X', tax_id='PL9998887776'),
            headers=auth_headers,
        )
        client.post(
            '/api/v1/partners',
            json=_supplier_payload(
                name='Firma Y', type='CUSTOMER', tax_id='DE111222333'
            ),
            headers=auth_headers,
        )
        resp = client.get('/api/v1/partners?search=PL999', headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data['total'] == 1
        assert data['items'][0]['name'] == 'Firma X'

    def test_list_filter_by_type(self, client: TestClient, auth_headers: dict):
        """GET ?type=SUPPLIER → only suppliers"""
        client.post(
            '/api/v1/partners',
            json=_supplier_payload(name='Supplier A', type='SUPPLIER'),
            headers=auth_headers,
        )
        client.post(
            '/api/v1/partners',
            json=_supplier_payload(name='Customer B', type='CUSTOMER'),
            headers=auth_headers,
        )
        resp = client.get('/api/v1/partners?type=SUPPLIER', headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data['total'] == 1
        assert data['items'][0]['type'] == 'SUPPLIER'

    def test_list_filter_by_multiple_types(
        self, client: TestClient, auth_headers: dict
    ):
        """GET ?types=SUPPLIER&types=MANUFACTURER → the supplier role set."""
        client.post(
            '/api/v1/partners',
            json=_supplier_payload(name='Supplier A', type='SUPPLIER'),
            headers=auth_headers,
        )
        client.post(
            '/api/v1/partners',
            json=_supplier_payload(name='Maker M', type='MANUFACTURER'),
            headers=auth_headers,
        )
        client.post(
            '/api/v1/partners',
            json=_supplier_payload(name='Customer B', type='CUSTOMER'),
            headers=auth_headers,
        )
        resp = client.get(
            '/api/v1/partners?types=SUPPLIER&types=MANUFACTURER',
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data['total'] == 2
        assert {p['type'] for p in data['items']} == {
            'SUPPLIER',
            'MANUFACTURER',
        }

    def test_list_filter_active_only_default(
        self, client: TestClient, auth_headers: dict
    ):
        """Deactivated partners excluded by default"""
        client.post(
            '/api/v1/partners',
            json=_supplier_payload(name='Active Partner'),
            headers=auth_headers,
        )
        r2 = client.post(
            '/api/v1/partners',
            json=_supplier_payload(name='Inactive Partner', type='CUSTOMER'),
            headers=auth_headers,
        )
        partner_id = r2.json()['id']
        client.patch(f'/api/v1/partners/{partner_id}/deactivate', headers=auth_headers)

        resp = client.get('/api/v1/partners', headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data['total'] == 1
        assert data['items'][0]['name'] == 'Active Partner'

    def test_list_filter_inactive(self, client: TestClient, auth_headers: dict):
        """GET ?is_active=false → only deactivated"""
        client.post(
            '/api/v1/partners',
            json=_supplier_payload(name='Active'),
            headers=auth_headers,
        )
        r2 = client.post(
            '/api/v1/partners',
            json=_supplier_payload(name='Inactive', type='CUSTOMER'),
            headers=auth_headers,
        )
        partner_id = r2.json()['id']
        client.patch(f'/api/v1/partners/{partner_id}/deactivate', headers=auth_headers)

        resp = client.get('/api/v1/partners?is_active=false', headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data['total'] == 1
        assert data['items'][0]['name'] == 'Inactive'

    def test_list_pagination(self, client: TestClient, auth_headers: dict):
        """Create 5; GET ?limit=2&offset=2 → 2 results, total=5"""
        types = ['SUPPLIER', 'CUSTOMER', 'BOTH', 'SERVICE_PROVIDER', 'MANUFACTURER']
        for i, t in enumerate(types):
            client.post(
                '/api/v1/partners',
                json=_supplier_payload(name=f'P{i}', type=t),
                headers=auth_headers,
            )
        resp = client.get('/api/v1/partners?limit=2&offset=2', headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data['total'] == 5
        assert len(data['items']) == 2

    def test_list_sort_by_name_asc(self, client: TestClient, auth_headers: dict):
        """GET ?sort_by=name&sort_order=asc → alphabetical"""
        for name in ['Zebra Corp', 'Apple Ltd', 'Mercury GmbH']:
            client.post(
                '/api/v1/partners',
                json=_supplier_payload(name=name),
                headers=auth_headers,
            )
        resp = client.get(
            '/api/v1/partners?sort_by=name&sort_order=asc', headers=auth_headers
        )
        assert resp.status_code == 200
        names = [p['name'] for p in resp.json()['items']]
        assert names == sorted(names)


# ---------------------------------------------------------------------------
# TestPartnersGet
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestPartnersGet:
    def test_get_partner_returns_200(self, client: TestClient, auth_headers: dict):
        """GET /api/v1/partners/{id} → 200, full partner data"""
        created = client.post(
            '/api/v1/partners', json=_supplier_payload(), headers=auth_headers
        ).json()
        resp = client.get(f'/api/v1/partners/{created["id"]}', headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data['id'] == created['id']
        assert data['name'] == 'Hurtownia ABC'
        assert data['tax_id'] == 'PL1234567890'

    def test_get_nonexistent_returns_404(self, client: TestClient, auth_headers: dict):
        """GET /api/v1/partners/{random_uuid} → 404"""
        resp = client.get(f'/api/v1/partners/{uuid.uuid4()}', headers=auth_headers)
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# TestPartnersUpdate
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestPartnersUpdate:
    def test_update_partner_returns_200(self, client: TestClient, auth_headers: dict):
        """PUT /api/v1/partners/{id} with partial data → 200, merged data"""
        created = client.post(
            '/api/v1/partners', json=_supplier_payload(), headers=auth_headers
        ).json()
        resp = client.put(
            f'/api/v1/partners/{created["id"]}',
            json={'name': 'Hurtownia ABC Updated', 'email': 'new@example.org'},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data['name'] == 'Hurtownia ABC Updated'
        assert data['email'] == 'new@example.org'

    def test_update_name_only_keeps_other_fields(
        self, client: TestClient, auth_headers: dict
    ):
        """PUT with {name: 'New'} → type, email, etc. unchanged"""
        payload = _supplier_payload()
        created = client.post(
            '/api/v1/partners', json=payload, headers=auth_headers
        ).json()
        resp = client.put(
            f'/api/v1/partners/{created["id"]}',
            json={'name': 'Only Name Changed'},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data['name'] == 'Only Name Changed'
        assert data['type'] == payload['type']
        assert data['email'] == payload['email']

    @pytest.mark.parametrize('field', ['name', 'type', 'is_consumer'])
    def test_update_with_null_for_a_required_field_is_refused(
        self, client: TestClient, auth_headers: dict, field: str
    ):
        """A named null on a NOT NULL column is a 400 naming it, not a 500."""
        payload = _supplier_payload()
        created = client.post(
            '/api/v1/partners', json=payload, headers=auth_headers
        ).json()
        resp = client.put(
            f'/api/v1/partners/{created["id"]}',
            json={field: None, 'notes': 'must not land'},
            headers=auth_headers,
        )
        assert resp.status_code == 400, resp.text
        assert field in resp.text
        again = client.get(
            f'/api/v1/partners/{created["id"]}', headers=auth_headers
        ).json()
        assert again[field] == created[field]
        assert again['notes'] == created['notes']

    def test_update_not_found_returns_404(self, client: TestClient, auth_headers: dict):
        """PUT /api/v1/partners/{random_uuid} → 404"""
        resp = client.put(
            f'/api/v1/partners/{uuid.uuid4()}',
            json={'name': 'Whatever'},
            headers=auth_headers,
        )
        assert resp.status_code == 404

    def test_update_to_duplicate_name_type_returns_409(
        self, client: TestClient, auth_headers: dict
    ):
        """PUT changing name to one that already exists (same org+type) → 409"""
        _ = client.post(
            '/api/v1/partners',
            json=_supplier_payload(name='First'),
            headers=auth_headers,
        )
        p2 = client.post(
            '/api/v1/partners',
            json=_supplier_payload(name='Second'),
            headers=auth_headers,
        ).json()
        resp = client.put(
            f'/api/v1/partners/{p2["id"]}',
            json={'name': 'First'},
            headers=auth_headers,
        )
        assert resp.status_code == 409


# ---------------------------------------------------------------------------
# TestPartnersDeactivateActivate
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestPartnersDeactivateActivate:
    def test_deactivate_partner_returns_200(
        self, client: TestClient, auth_headers: dict
    ):
        """PATCH /api/v1/partners/{id}/deactivate → 200, is_active=False"""
        created = client.post(
            '/api/v1/partners', json=_supplier_payload(), headers=auth_headers
        ).json()
        resp = client.patch(
            f'/api/v1/partners/{created["id"]}/deactivate', headers=auth_headers
        )
        assert resp.status_code == 200
        assert resp.json()['is_active'] is False

    def test_deactivate_already_inactive_is_idempotent(
        self, client: TestClient, auth_headers: dict
    ):
        """PATCH deactivate twice → 200 both times"""
        created = client.post(
            '/api/v1/partners', json=_supplier_payload(), headers=auth_headers
        ).json()
        pid = created['id']
        assert (
            client.patch(
                f'/api/v1/partners/{pid}/deactivate', headers=auth_headers
            ).status_code
            == 200
        )
        assert (
            client.patch(
                f'/api/v1/partners/{pid}/deactivate', headers=auth_headers
            ).status_code
            == 200
        )

    def test_activate_partner_returns_200(self, client: TestClient, auth_headers: dict):
        """PATCH /api/v1/partners/{id}/activate → 200, is_active=True"""
        created = client.post(
            '/api/v1/partners', json=_supplier_payload(), headers=auth_headers
        ).json()
        pid = created['id']
        client.patch(f'/api/v1/partners/{pid}/deactivate', headers=auth_headers)
        resp = client.patch(f'/api/v1/partners/{pid}/activate', headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()['is_active'] is True


# ---------------------------------------------------------------------------
# TestPartnerItems
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestPartnerItems:
    def test_get_partner_items_returns_linked_items(
        self, client: TestClient, auth_headers: dict, test_item, db_session: Session
    ):
        """Create partner, link item via partner_id → GET /partners/{id}/items → item in list"""
        from app.models.item import Item

        created = client.post(
            '/api/v1/partners', json=_supplier_payload(), headers=auth_headers
        ).json()
        partner_id = uuid.UUID(created['id'])

        # Directly attach partner_id to existing test_item
        db_session.execute(
            update(Item).where(Item.id == test_item.id).values(partner_id=partner_id)
        )
        db_session.commit()

        resp = client.get(
            f'/api/v1/partners/{created["id"]}/items', headers=auth_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data['total'] == 1
        assert data['items'][0]['id'] == str(test_item.id)
        assert (data['limit'], data['offset'], data['has_more']) == (100, 0, False)

    def test_the_items_page_says_whether_more_follow(
        self, client: TestClient, auth_headers: dict, test_item, db_session: Session
    ):
        """A page that stops short of the total reports has_more, the one past it not."""
        from app.models.item import Item

        created = client.post(
            '/api/v1/partners', json=_supplier_payload(), headers=auth_headers
        ).json()
        db_session.execute(
            update(Item)
            .where(Item.id == test_item.id)
            .values(partner_id=uuid.UUID(created['id']))
        )
        db_session.commit()
        url = f'/api/v1/partners/{created["id"]}/items'

        past_the_end = client.get(f'{url}?limit=1&offset=1', headers=auth_headers)

        assert past_the_end.status_code == 200
        body = past_the_end.json()
        assert (body['items'], body['total'], body['has_more']) == ([], 1, False)
        assert (body['limit'], body['offset']) == (1, 1)

    def test_get_partner_items_empty(self, client: TestClient, auth_headers: dict):
        """Partner with no items → {items: [], total: 0}"""
        created = client.post(
            '/api/v1/partners', json=_supplier_payload(), headers=auth_headers
        ).json()
        resp = client.get(
            f'/api/v1/partners/{created["id"]}/items', headers=auth_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data['items'] == []
        assert data['total'] == 0


# ---------------------------------------------------------------------------
# TestPartnerMultiTenancy
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestPartnerMultiTenancy:
    def test_cannot_see_other_org_partners(
        self, client: TestClient, auth_headers: dict, other_org_auth_headers: dict
    ):
        """Org A creates partner → Org B GET list → partner not visible"""
        client.post('/api/v1/partners', json=_supplier_payload(), headers=auth_headers)
        resp = client.get('/api/v1/partners', headers=other_org_auth_headers)
        assert resp.status_code == 200
        assert resp.json()['total'] == 0

    def test_cannot_update_other_org_partner(
        self, client: TestClient, auth_headers: dict, other_org_auth_headers: dict
    ):
        """Org A creates partner → Org B PUT → 404"""
        created = client.post(
            '/api/v1/partners', json=_supplier_payload(), headers=auth_headers
        ).json()
        resp = client.put(
            f'/api/v1/partners/{created["id"]}',
            json={'name': 'Hacked'},
            headers=other_org_auth_headers,
        )
        assert resp.status_code == 404

    def test_cannot_deactivate_other_org_partner(
        self, client: TestClient, auth_headers: dict, other_org_auth_headers: dict
    ):
        """Org A creates partner → Org B PATCH deactivate → 404"""
        created = client.post(
            '/api/v1/partners', json=_supplier_payload(), headers=auth_headers
        ).json()
        resp = client.patch(
            f'/api/v1/partners/{created["id"]}/deactivate',
            headers=other_org_auth_headers,
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# TestPartnersDelete
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestPartnersDelete:
    def test_delete_partner_returns_204(self, client: TestClient, auth_headers: dict):
        """DELETE /api/v1/partners/{id} → 204"""
        created = client.post(
            '/api/v1/partners', json=_supplier_payload(), headers=auth_headers
        ).json()
        resp = client.delete(f'/api/v1/partners/{created["id"]}', headers=auth_headers)
        assert resp.status_code == 204

    def test_delete_not_found_returns_404(self, client: TestClient, auth_headers: dict):
        """DELETE /api/v1/partners/{random_uuid} → 404"""
        resp = client.delete(f'/api/v1/partners/{uuid.uuid4()}', headers=auth_headers)
        assert resp.status_code == 404

    def test_delete_blocked_by_open_po_returns_409(
        self,
        client: TestClient,
        auth_headers: dict,
        db_session: Session,
        test_user: User,
        test_household: Organization,
    ):
        """DELETE partner referenced by an open PO → 409 (not 500).

        Regression: ValueError from service must be wrapped as ConflictException.
        """
        from app.modules.purchase_orders.models import PurchaseOrder

        created = client.post(
            '/api/v1/partners', json=_supplier_payload(), headers=auth_headers
        ).json()
        partner_id = created['id']

        po = PurchaseOrder(
            organization_id=test_household.id,
            number='PO/TEST/409/1',
            status='CONFIRMED',
            partner_id=partner_id,
            currency='PLN',
            created_by=test_user.id,
        )
        db_session.add(po)
        db_session.commit()

        resp = client.delete(f'/api/v1/partners/{partner_id}', headers=auth_headers)
        assert resp.status_code == 409
        assert resp.json()['detail']['code'] == 'PARTNER_DELETE_OPEN_PURCHASE_ORDERS'


# ---------------------------------------------------------------------------
# TestPartnerAddressLegacyRead
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestPartnerAddressLegacyRead:
    def test_get_returns_legacy_free_text_country_and_extra_keys(
        self,
        client: TestClient,
        auth_headers: dict,
        db_session: Session,
        test_household: Organization,
        test_user: User,
    ):
        """A legacy record (free-text country + unknown keys) still reads."""
        from app.models.partner import Partner

        partner = Partner(
            organization_id=test_household.id,
            created_by=test_user.id,
            name='Legacy Partner',
            type='SUPPLIER',
            address={
                'street': 'Old St 1',
                'city': 'Warsaw',
                'postal_code': '00-001',
                'country': 'Polska',
                'floor': '2',
            },
        )
        db_session.add(partner)
        db_session.commit()
        db_session.refresh(partner)

        resp = client.get(f'/api/v1/partners/{partner.id}', headers=auth_headers)
        assert resp.status_code == 200
        address = resp.json()['address']
        assert address['country'] == 'Polska'
        assert address['floor'] == '2'

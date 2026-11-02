"""A product without a manufacturer's code gets one from the app.

The barcode field on the product form had nothing to fill it with, so a
product a small warehouse makes itself stayed unscannable. "Generate code"
asks for an internal EAN-13 in GS1's restricted-circulation range and the
form saves it like any typed code.
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.barcode import validate_checksum
from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.user import User
from app.services.auth_service import get_password_hash
from app.services.token_service import create_access_token

_URL = '/api/v1/items/product-templates/generate-barcode'
#: The first code an organization is given: 20, the number 1, check digit 5.
_FIRST = '2000000000015'


def _generate(client: TestClient, headers: dict[str, str]) -> str:
    resp = client.post(_URL, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()['barcode']


@pytest.mark.integration
class TestGenerateProductCode:
    def test_generate_code_returns_restricted_circulation_ean13(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        code = _generate(client, auth_headers)

        assert code == _FIRST
        assert len(code) == 13
        assert code.isdigit()
        assert code.startswith('20')
        assert validate_checksum(code)

    def test_generate_code_twice_returns_two_codes(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """A number is spent on the call, so two open forms never share one."""
        first = _generate(client, auth_headers)
        second = _generate(client, auth_headers)

        assert first != second
        assert validate_checksum(second)

    def test_generate_code_skips_a_code_a_product_already_has(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_storage_location,
    ) -> None:
        typed = client.post(
            '/api/v1/items',
            headers=auth_headers,
            json={
                'name': 'Hand-labelled crate',
                'barcode': _FIRST,
                'location_id': str(test_storage_location.id),
                'quantity': 1,
            },
        )
        assert typed.status_code == 201, typed.text

        code = _generate(client, auth_headers)

        assert code != _FIRST
        assert code.startswith('20')
        assert validate_checksum(code)

    def test_generate_code_counts_per_organization(
        self,
        client: TestClient,
        db_session: Session,
        auth_headers: dict[str, str],
    ) -> None:
        """Another organization's product with the code does not take it here."""
        h = ModuleTestHelper(db_session)
        other = h.create_org('Other workshop', ['core', 'items', 'locations'])
        h.create_template(other, name='Their crate', barcode=_FIRST)

        assert _generate(client, auth_headers) == _FIRST

    def test_viewer_cannot_generate_code(
        self, client: TestClient, db_session: Session, test_user: User
    ) -> None:
        org = db_session.get(Organization, test_user.organization_id)
        assert org is not None
        viewer = User(
            email=f'viewer_{uuid.uuid4().hex[:8]}@test.com',
            hashed_password=get_password_hash('pass'),
            organization_id=org.id,
            role='viewer',
            is_active=True,
        )
        db_session.add(viewer)
        db_session.commit()
        token = create_access_token(data={'sub': str(viewer.id)})

        resp = client.post(_URL, headers={'Authorization': f'Bearer {token}'})

        assert resp.status_code == 403

"""
Penetration Tests for Recipes Module.

Covers:
- Input validation & boundary conditions
- Authentication & authorization bypass attempts
- Injection attacks (SQL injection, XSS, path traversal)
- Error handling & edge cases
- Picking/cooking flow vulnerabilities
- Meal plan CRUD edge cases
- Import/export vulnerabilities
- Cross-organization data isolation
"""

import uuid
from decimal import Decimal
from typing import Any, cast

import pytest
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.limiter import limiter
from app.i18n import SUPPORTED_LANGUAGES
from app.models.item import Item
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.uom import Uom
from app.models.user import User
from app.services.token_service import create_access_token
from tests.integration._shelf import anchor_pending_records, post_on_shelf

RECIPE_URL = '/api/v1/recipes'


def _real_image(fmt: str = 'PNG') -> bytes:
    """A file whose decoder reaches the end of it.

    Correct magic bytes on the front of forty zero bytes satisfy the
    signature check and nothing after it — a cover is now decoded and written
    out again, so these have to be pictures.
    """
    from io import BytesIO

    from PIL import Image

    buffer = BytesIO()
    Image.new('RGB', (8, 6), (120, 20, 20)).save(buffer, format=fmt)
    return buffer.getvalue()


def _recipe_payload(**overrides: Any) -> dict[str, Any]:
    base = {
        'name': 'Pen Test Recipe',
        'description': 'Test description',
        'servings': 2,
        'prep_time_minutes': 30,
        'tags': ['test'],
        'is_favorite': False,
        'ingredients': [],
    }
    base.update(overrides)
    return base


# ══════════════════════════════════════════════════════════════════════════════
# 1. INPUT VALIDATION & BOUNDARY CONDITIONS
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestInputValidation:
    """Boundary and input validation tests."""

    def test_create_recipe_empty_name_rejected(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """FIXED: Empty name is now rejected by min_length=1."""
        r = client.post(RECIPE_URL, json=_recipe_payload(name=''), headers=auth_headers)
        assert r.status_code == 422

    def test_create_recipe_very_long_name_rejected(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """FIXED: Name >255 chars is now rejected by max_length=255."""
        long_name = 'A' * 1000
        r = client.post(
            RECIPE_URL, json=_recipe_payload(name=long_name), headers=auth_headers
        )
        assert r.status_code == 422

    def test_create_recipe_name_at_limit(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Name exactly 255 chars — should succeed."""
        name_255 = 'B' * 255
        r = client.post(
            RECIPE_URL, json=_recipe_payload(name=name_255), headers=auth_headers
        )
        assert r.status_code == 201

    def test_create_recipe_negative_servings_rejected(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """FIXED: Negative servings now rejected by ge=1."""
        r = client.post(
            RECIPE_URL, json=_recipe_payload(servings=-1), headers=auth_headers
        )
        assert r.status_code == 422

    def test_create_recipe_zero_servings_rejected(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """FIXED: Zero servings now rejected by ge=1 — no more DivisionByZero."""
        r = client.post(
            RECIPE_URL, json=_recipe_payload(servings=0), headers=auth_headers
        )
        assert r.status_code == 422

    def test_create_recipe_negative_prep_time_rejected(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """FIXED: Negative prep time now rejected by ge=0."""
        r = client.post(
            RECIPE_URL,
            json=_recipe_payload(prep_time_minutes=-10),
            headers=auth_headers,
        )
        assert r.status_code == 422

    def test_create_recipe_negative_quantity_ingredient_rejected(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """FIXED: Negative ingredient quantity now rejected by ge=0."""
        r = client.post(
            RECIPE_URL,
            json=_recipe_payload(
                ingredients=[
                    {'name': 'Flour', 'quantity': '-100', 'is_optional': False}
                ]
            ),
            headers=auth_headers,
        )
        assert r.status_code == 422

    def test_create_recipe_zero_quantity_ingredient(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Zero quantity ingredient — boundary case."""
        r = client.post(
            RECIPE_URL,
            json=_recipe_payload(
                ingredients=[{'name': 'Salt', 'quantity': '0', 'is_optional': False}]
            ),
            headers=auth_headers,
        )
        # quantity is Field(ge=0), so zero clears the schema — "a pinch of
        # salt" is a recipe line like any other.
        assert r.status_code == 201

    def test_create_recipe_overflow_quantity_unhandled(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """BUG: Quantity >9999999.999 causes unhandled DB overflow — no schema validation."""
        with pytest.raises(DBAPIError):
            client.post(
                RECIPE_URL,
                json=_recipe_payload(
                    ingredients=[
                        {
                            'name': 'Mega ingredient',
                            'quantity': '999999999999999',
                            'is_optional': False,
                        }
                    ]
                ),
                headers=auth_headers,
            )
        # NumericValueOutOfRangeError: numeric field overflow
        # Should be caught at schema level and return 422

    def test_create_recipe_missing_required_body(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Empty JSON body should be rejected."""
        r = client.post(RECIPE_URL, json={}, headers=auth_headers)
        assert r.status_code in (400, 422)

    def test_create_recipe_invalid_json(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Malformed JSON body."""
        r = client.post(
            RECIPE_URL,
            content=b'not json at all',
            headers={**auth_headers, 'Content-Type': 'application/json'},
        )
        assert r.status_code == 422

    def test_create_recipe_invalid_uuid_ingredient_template(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Invalid UUID format for template_id."""
        r = client.post(
            RECIPE_URL,
            json=_recipe_payload(
                ingredients=[
                    {
                        'name': 'Flour',
                        'template_id': 'not-a-uuid',
                        'quantity': '100',
                        'is_optional': False,
                    }
                ]
            ),
            headers=auth_headers,
        )
        assert r.status_code == 422

    def test_create_recipe_invalid_image_url(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """image_url with javascript: protocol should be rejected."""
        r = client.post(
            RECIPE_URL,
            json=_recipe_payload(image_url='javascript:alert(1)'),
            headers=auth_headers,
        )
        assert r.status_code == 422

    def test_create_recipe_101_ingredients_exceeds_limit(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """More than 100 ingredients should be rejected (max_length=100)."""
        ingredients = [
            {'name': f'Ing{i}', 'quantity': '1', 'is_optional': False}
            for i in range(101)
        ]
        r = client.post(
            RECIPE_URL,
            json=_recipe_payload(ingredients=ingredients),
            headers=auth_headers,
        )
        assert r.status_code == 422

    def test_list_recipes_negative_limit(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Negative limit query param."""
        r = client.get(f'{RECIPE_URL}?limit=-1', headers=auth_headers)
        assert r.status_code == 422

    def test_list_recipes_zero_limit(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Zero limit query param."""
        r = client.get(f'{RECIPE_URL}?limit=0', headers=auth_headers)
        assert r.status_code == 422

    def test_list_recipes_huge_limit(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Limit > 200 should be rejected."""
        r = client.get(f'{RECIPE_URL}?limit=10000', headers=auth_headers)
        assert r.status_code == 422

    def test_list_recipes_negative_offset(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Negative offset."""
        r = client.get(f'{RECIPE_URL}?offset=-5', headers=auth_headers)
        assert r.status_code == 422

    def test_get_recipe_invalid_uuid_format(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Non-UUID string as recipe_id."""
        r = client.get(f'{RECIPE_URL}/not-a-uuid', headers=auth_headers)
        assert r.status_code == 422

    def test_get_recipe_nil_uuid(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Nil UUID as recipe_id."""
        r = client.get(
            f'{RECIPE_URL}/00000000-0000-0000-0000-000000000000',
            headers=auth_headers,
        )
        assert r.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
# 2. AUTHENTICATION & AUTHORIZATION
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestAuthenticationAuthorization:
    """Auth bypass and permission tests."""

    def test_no_token_all_endpoints(self, client: TestClient) -> None:
        """All critical endpoints must reject unauthenticated requests."""
        fake_id = str(uuid.uuid4())
        endpoints = [
            ('GET', RECIPE_URL),
            ('POST', RECIPE_URL),
            ('GET', f'{RECIPE_URL}/{fake_id}'),
            ('PUT', f'{RECIPE_URL}/{fake_id}'),
            ('DELETE', f'{RECIPE_URL}/{fake_id}'),
            ('GET', f'{RECIPE_URL}/tags'),
            ('GET', f'{RECIPE_URL}/unit-conversions'),
            ('GET', f'{RECIPE_URL}/available'),
            ('GET', f'{RECIPE_URL}/{fake_id}/availability'),
            ('GET', f'{RECIPE_URL}/{fake_id}/nutrition'),
            ('GET', f'{RECIPE_URL}/{fake_id}/history'),
            ('GET', f'{RECIPE_URL}/{fake_id}/export'),
            ('POST', f'{RECIPE_URL}/import'),
        ]
        for method, url in endpoints:
            if method == 'GET':
                r = client.get(url)
            elif method == 'POST':
                r = client.post(url, json={})
            elif method == 'PUT':
                r = client.put(url, json={})
            elif method == 'DELETE':
                r = client.delete(url)
            assert r.status_code == 401, f'{method} {url} should return 401'

    def test_invalid_token_rejected(self, client: TestClient) -> None:
        """Bearer token with garbage value → 401."""
        r = client.get(
            RECIPE_URL, headers={'Authorization': 'Bearer invalid.token.here'}
        )
        assert r.status_code == 401

    def test_empty_bearer_token_rejected(self, client: TestClient) -> None:
        """Empty Bearer → 401."""
        r = client.get(RECIPE_URL, headers={'Authorization': 'Bearer '})
        assert r.status_code == 401

    def test_malformed_auth_header(self, client: TestClient) -> None:
        """No 'Bearer' prefix."""
        r = client.get(RECIPE_URL, headers={'Authorization': 'Token abc123'})
        assert r.status_code == 401

    def test_cross_org_recipe_access_denied(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        db_session: Session,
    ) -> None:
        """User from org A cannot access recipe from org B."""
        # Create recipe as test_user (org A)
        create_r = client.post(
            RECIPE_URL,
            json=_recipe_payload(name='Org A Recipe'),
            headers=auth_headers,
        )
        recipe_id = create_r.json()['id']

        # Create a user in a DIFFERENT organization
        from app.models.organization import Organization

        org_b = Organization(name='Org B', enabled_modules=['recipes'])
        db_session.add(org_b)
        db_session.flush()

        user_b = User(
            email='orgb@example.com',
            hashed_password='dummy',
            full_name='User B',
            organization_id=org_b.id,
            role='admin',
            is_active=True,
        )
        db_session.add(user_b)
        db_session.commit()

        token_b = create_access_token(data={'sub': str(user_b.id)})
        headers_b = {'Authorization': f'Bearer {token_b}'}

        # Try to access org A recipe from org B
        r = client.get(f'{RECIPE_URL}/{recipe_id}', headers=headers_b)
        assert r.status_code == 404

        # Try to update
        r = client.put(
            f'{RECIPE_URL}/{recipe_id}',
            json={'name': 'Hacked'},
            headers=headers_b,
        )
        assert r.status_code == 404

        # Try to delete
        r = client.delete(f'{RECIPE_URL}/{recipe_id}', headers=headers_b)
        assert r.status_code == 404

    def test_cross_org_picking_session_denied(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        db_session: Session,
    ) -> None:
        """User from org B cannot start picking on org A recipe."""
        create_r = client.post(
            RECIPE_URL,
            json=_recipe_payload(name='Org A Recipe'),
            headers=auth_headers,
        )
        recipe_id = create_r.json()['id']

        from app.models.organization import Organization

        org_b = Organization(name='Org B Picking', enabled_modules=['recipes'])
        db_session.add(org_b)
        db_session.flush()

        user_b = User(
            email='orgb_pick@example.com',
            hashed_password='dummy',
            full_name='User B Pick',
            organization_id=org_b.id,
            role='admin',
            is_active=True,
        )
        db_session.add(user_b)
        db_session.commit()

        token_b = create_access_token(data={'sub': str(user_b.id)})
        headers_b = {'Authorization': f'Bearer {token_b}'}

        r = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/start',
            json={'servings': 1},
            headers=headers_b,
        )
        assert r.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
# 3. INJECTION ATTACKS
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestInjectionAttacks:
    """SQL injection, XSS, and path traversal tests."""

    def test_sql_injection_in_search(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """SQL injection via search parameter."""
        r = client.get(
            f"{RECIPE_URL}?search=' OR 1=1 --",
            headers=auth_headers,
        )
        assert r.status_code == 200
        # Should return empty list, not all recipes
        assert r.json()['items'] == []

    def test_sql_injection_in_search_union(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """UNION-based SQL injection."""
        r = client.get(
            f"{RECIPE_URL}?search=' UNION SELECT NULL --",
            headers=auth_headers,
        )
        assert r.status_code == 200

    def test_sql_injection_in_recipe_name(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """SQL injection in recipe name field."""
        r = client.post(
            RECIPE_URL,
            json=_recipe_payload(name="'; DROP TABLE recipes; --"),
            headers=auth_headers,
        )
        # The name validator refuses NUL bytes and nothing else, so this is
        # stored as a literal string: created, not rejected. The check below
        # is the real subject — the table is still there afterwards.
        assert r.status_code == 201
        # Verify table still exists
        list_r = client.get(RECIPE_URL, headers=auth_headers)
        assert list_r.status_code == 200

    def test_xss_in_recipe_name(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """XSS payload in recipe name — must be stored safely."""
        xss_payload = '<script>alert("xss")</script>'
        r = client.post(
            RECIPE_URL,
            json=_recipe_payload(name=xss_payload),
            headers=auth_headers,
        )
        assert r.status_code == 201
        data = r.json()
        # Name should be stored as-is (escaping happens at render time)
        assert data['name'] == xss_payload

        # Verify it doesn't break the list endpoint
        list_r = client.get(RECIPE_URL, headers=auth_headers)
        assert list_r.status_code == 200

    def test_xss_in_description(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """XSS in description field."""
        xss = '<img src=x onerror=alert(1)>'
        r = client.post(
            RECIPE_URL,
            json=_recipe_payload(description=xss),
            headers=auth_headers,
        )
        assert r.status_code == 201
        assert r.json()['description'] == xss

    def test_xss_in_instructions(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """XSS in markdown instructions."""
        xss = '![img](javascript:alert(1))'
        r = client.post(
            RECIPE_URL,
            json=_recipe_payload(instructions=xss),
            headers=auth_headers,
        )
        assert r.status_code == 201

    def test_xss_in_ingredient_name(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """XSS in ingredient name."""
        r = client.post(
            RECIPE_URL,
            json=_recipe_payload(
                ingredients=[
                    {'name': '<b onmouseover=alert(1)>Flour</b>', 'quantity': '100'}
                ]
            ),
            headers=auth_headers,
        )
        assert r.status_code == 201

    def test_path_traversal_image_url(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Path traversal in image_url."""
        r = client.post(
            RECIPE_URL,
            json=_recipe_payload(image_url='http://example.com/../../../etc/passwd'),
            headers=auth_headers,
        )
        # Should be accepted as URL (not used as file path directly)
        if r.status_code == 201:
            assert r.json()['image_url'] == 'http://example.com/../../../etc/passwd'

    def test_path_traversal_image_url_relative(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Relative path traversal in image_url."""
        r = client.post(
            RECIPE_URL,
            json=_recipe_payload(image_url='../../etc/passwd'),
            headers=auth_headers,
        )
        # Should be rejected (not starting with http/https//)
        assert r.status_code == 422

    def test_ssrf_localhost_url_import(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """SSRF: Import from localhost should be blocked."""
        r = client.post(
            f'{RECIPE_URL}/import',
            json={'format': 'url', 'url': 'http://localhost:8000/api/v1/recipes'},
            headers=auth_headers,
        )
        assert r.status_code == 400

    def test_ssrf_private_ip_import(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """SSRF: Import from private IP should be blocked."""
        r = client.post(
            f'{RECIPE_URL}/import',
            json={'format': 'url', 'url': 'http://192.168.1.1/admin'},
            headers=auth_headers,
        )
        assert r.status_code == 400

    def test_ssrf_loopback_import(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """SSRF: Import from loopback should be blocked."""
        r = client.post(
            f'{RECIPE_URL}/import',
            json={'format': 'url', 'url': 'http://127.0.0.1/internal'},
            headers=auth_headers,
        )
        assert r.status_code == 400

    def test_ssrf_0_0_0_0_import(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """SSRF: Import from 0.0.0.0 should be blocked."""
        r = client.post(
            f'{RECIPE_URL}/import',
            json={'format': 'url', 'url': 'http://0.0.0.0/internal'},
            headers=auth_headers,
        )
        assert r.status_code == 400

    def test_ssrf_localdomain_import(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """SSRF: Import from *.local should be blocked."""
        r = client.post(
            f'{RECIPE_URL}/import',
            json={'format': 'url', 'url': 'http://evil.local/steal'},
            headers=auth_headers,
        )
        assert r.status_code == 400

    def test_ssrf_internal_import(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """SSRF: Import from *.internal should be blocked."""
        r = client.post(
            f'{RECIPE_URL}/import',
            json={'format': 'url', 'url': 'http://metadata.internal/'},
            headers=auth_headers,
        )
        assert r.status_code == 400

    def test_ssrf_link_local_import(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """SSRF: Import from link-local address should be blocked."""
        r = client.post(
            f'{RECIPE_URL}/import',
            json={'format': 'url', 'url': 'http://169.254.169.254/metadata'},
            headers=auth_headers,
        )
        assert r.status_code == 400

    def test_ssrf_preview_also_blocked(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """SSRF: Preview endpoint must also block private IPs."""
        r = client.post(
            f'{RECIPE_URL}/import/preview',
            json={'format': 'url', 'url': 'http://10.0.0.1/secret'},
            headers=auth_headers,
        )
        assert r.status_code == 400

    def test_ftp_protocol_rejected(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """FTP protocol should be rejected."""
        r = client.post(
            f'{RECIPE_URL}/import',
            json={'format': 'url', 'url': 'ftp://example.com/recipe.txt'},
            headers=auth_headers,
        )
        assert r.status_code == 400

    def test_file_protocol_rejected(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """file:// protocol should be rejected."""
        r = client.post(
            f'{RECIPE_URL}/import',
            json={'format': 'url', 'url': 'file:///etc/passwd'},
            headers=auth_headers,
        )
        assert r.status_code == 400

    def test_tag_sql_injection(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """SQL injection via tag filter."""
        r = client.get(
            f"{RECIPE_URL}?tags=' OR '1'='1",
            headers=auth_headers,
        )
        assert r.status_code == 200

    def test_unicode_in_recipe_name(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Unicode characters in recipe name."""
        r = client.post(
            RECIPE_URL,
            json=_recipe_payload(name='Рецепт 中文 🍕 العربية'),
            headers=auth_headers,
        )
        assert r.status_code == 201
        assert r.json()['name'] == 'Рецепт 中文 🍕 العربية'

    def test_unicode_in_tags(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Unicode in tags."""
        r = client.post(
            RECIPE_URL,
            json=_recipe_payload(tags=['晚餐', 'Abendessen', 'dîner']),
            headers=auth_headers,
        )
        assert r.status_code == 201

    def test_newline_in_recipe_name(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Newline characters in name."""
        r = client.post(
            RECIPE_URL,
            json=_recipe_payload(name='Line1\nLine2'),
            headers=auth_headers,
        )
        # The name carries only min_length and max_length, so a newline is
        # part of the string rather than a reason to refuse it.
        assert r.status_code == 201

    def test_null_bytes_in_name_rejected(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """FIXED: Null bytes now rejected by field_validator."""
        r = client.post(
            RECIPE_URL,
            json=_recipe_payload(name='Recipe\x00Name'),
            headers=auth_headers,
        )
        assert r.status_code == 422


# ══════════════════════════════════════════════════════════════════════════════
# 4. ERROR HANDLING & EDGE CASES
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestErrorHandling:
    """Edge cases and double操作."""

    def test_get_nonexistent_recipe(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """GET non-existent recipe → 404."""
        r = client.get(f'{RECIPE_URL}/{uuid.uuid4()}', headers=auth_headers)
        assert r.status_code == 404

    def test_update_nonexistent_recipe(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """PUT non-existent recipe → 404."""
        r = client.put(
            f'{RECIPE_URL}/{uuid.uuid4()}',
            json={'name': 'Updated'},
            headers=auth_headers,
        )
        assert r.status_code == 404

    def test_delete_nonexistent_recipe(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """DELETE non-existent recipe → 404."""
        r = client.delete(f'{RECIPE_URL}/{uuid.uuid4()}', headers=auth_headers)
        assert r.status_code == 404

    def test_double_delete_recipe(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Deleting same recipe twice → second should be 404."""
        create_r = client.post(
            RECIPE_URL, json=_recipe_payload(name='Double Delete'), headers=auth_headers
        )
        recipe_id = create_r.json()['id']

        r1 = client.delete(f'{RECIPE_URL}/{recipe_id}', headers=auth_headers)
        assert r1.status_code == 204

        r2 = client.delete(f'{RECIPE_URL}/{recipe_id}', headers=auth_headers)
        assert r2.status_code == 404

    def test_update_recipe_with_ingredients_replaces_all(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Updating recipe with new ingredients should replace, not append."""
        create_r = client.post(
            RECIPE_URL,
            json=_recipe_payload(
                ingredients=[
                    {'name': 'Flour', 'quantity': '100'},
                    {'name': 'Sugar', 'quantity': '50'},
                ]
            ),
            headers=auth_headers,
        )
        recipe_id = create_r.json()['id']
        assert len(create_r.json()['ingredients']) == 2

        # Update with only 1 ingredient
        r = client.put(
            f'{RECIPE_URL}/{recipe_id}',
            json={'ingredients': [{'name': 'Salt', 'quantity': '10'}]},
            headers=auth_headers,
        )
        assert r.status_code == 200
        assert len(r.json()['ingredients']) == 1
        assert r.json()['ingredients'][0]['name'] == 'Salt'

    def test_update_recipe_partial_fields(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Partial update should only change specified fields."""
        create_r = client.post(
            RECIPE_URL,
            json=_recipe_payload(
                name='Original', description='Original desc', servings=4
            ),
            headers=auth_headers,
        )
        recipe_id = create_r.json()['id']

        r = client.put(
            f'{RECIPE_URL}/{recipe_id}',
            json={'name': 'Updated'},
            headers=auth_headers,
        )
        assert r.status_code == 200
        assert r.json()['name'] == 'Updated'
        assert r.json()['description'] == 'Original desc'
        assert r.json()['servings'] == 4

    def test_get_availability_nonexistent_recipe(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Availability for non-existent recipe → 404."""
        r = client.get(
            f'{RECIPE_URL}/{uuid.uuid4()}/availability', headers=auth_headers
        )
        assert r.status_code == 404

    def test_get_nutrition_nonexistent_recipe(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Nutrition for non-existent recipe → 404."""
        r = client.get(f'{RECIPE_URL}/{uuid.uuid4()}/nutrition', headers=auth_headers)
        assert r.status_code == 404

    def test_export_nonexistent_recipe(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Export non-existent recipe → 404."""
        r = client.get(
            f'{RECIPE_URL}/{uuid.uuid4()}/export?format=json', headers=auth_headers
        )
        assert r.status_code == 404

    def test_history_nonexistent_recipe_returns_404(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """History for non-existent recipe → 404."""
        r = client.get(f'{RECIPE_URL}/{uuid.uuid4()}/history', headers=auth_headers)
        assert r.status_code == 404

    def test_create_recipe_many_unicode_tags(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Many unicode tags."""
        r = client.post(
            RECIPE_URL,
            json=_recipe_payload(tags=['晚餐', 'Abendessen', 'dîner', ' cena', 'ужин']),
            headers=auth_headers,
        )
        assert r.status_code == 201

    def test_duplicate_tag_names(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Duplicate tag names should be stored (dedup is at list level)."""
        r = client.post(
            RECIPE_URL,
            json=_recipe_payload(tags=['dinner', 'dinner', 'Dinner']),
            headers=auth_headers,
        )
        assert r.status_code == 201

    def test_empty_tags_list(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Empty tags list should work."""
        r = client.post(RECIPE_URL, json=_recipe_payload(tags=[]), headers=auth_headers)
        assert r.status_code == 201

    def test_null_tags(self, client: TestClient, auth_headers: dict[str, str]) -> None:
        """Null tags should work."""
        r = client.post(
            RECIPE_URL, json=_recipe_payload(tags=None), headers=auth_headers
        )
        assert r.status_code == 201

    def test_update_does_not_leak_other_org_data(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_user: User,
        db_session: Session,
    ) -> None:
        """Verify update query is scoped to org."""
        # Create recipe as test_user
        client.post(
            RECIPE_URL,
            json=_recipe_payload(name='Isolated Recipe'),
            headers=auth_headers,
        )

        # Create recipe in different org
        from app.models.organization import Organization

        org_b = Organization(name='Org B Isolation', enabled_modules=['recipes'])
        db_session.add(org_b)
        db_session.flush()

        user_b = User(
            email='orgb_iso@example.com',
            hashed_password='dummy',
            full_name='User B Iso',
            organization_id=org_b.id,
            role='admin',
            is_active=True,
        )
        db_session.add(user_b)
        db_session.commit()

        token_b = create_access_token(data={'sub': str(user_b.id)})
        headers_b = {'Authorization': f'Bearer {token_b}'}

        # Create recipe in org B
        create_b = client.post(
            RECIPE_URL,
            json=_recipe_payload(name='Org B Recipe'),
            headers=headers_b,
        )
        assert create_b.status_code == 201

        # Verify org A can't see org B recipe in list
        list_r = client.get(RECIPE_URL, headers=auth_headers)
        names = [r['name'] for r in list_r.json()['items']]
        assert 'Org B Recipe' not in names


# ══════════════════════════════════════════════════════════════════════════════
# 5. PICKING/COOKING FLOW VULNERABILITIES
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestPickingFlowVulnerabilities:
    """Security and edge-case tests for the picking/cooking flow."""

    def _create_recipe_with_item(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> tuple[str, Any]:
        grams = db_session.scalar(select(Uom.id).where(Uom.symbol == 'g'))
        assert grams is not None, "'g' is not seeded"
        template = ProductTemplate(
            id=uuid.uuid4(),
            organization_id=test_user.organization_id,
            name='Picking Test Ingredient',
            uom_id=grams,
        )
        db_session.add(template)
        db_session.commit()
        record = post_on_shelf(
            client, auth_headers, template, test_storage_location.id, '500'
        )

        payload = _recipe_payload(
            name='Picking Security Recipe',
            servings=2,
            ingredients=[
                {
                    'name': 'Picking Test Ingredient',
                    'template_id': str(template.id),
                    'uom_id': str(grams),
                    'quantity': '200',
                    'is_optional': False,
                }
            ],
        )
        r = client.post(RECIPE_URL, json=payload, headers=auth_headers)
        return r.json()['id'], uuid.UUID(record['id'])

    def test_start_picking_nonexistent_recipe(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Start picking for non-existent recipe → 404."""
        r = client.post(
            f'{RECIPE_URL}/{uuid.uuid4()}/picking/start',
            json={'servings': 1},
            headers=auth_headers,
        )
        assert r.status_code == 404

    def test_scan_neither_barcode_nor_item_id_simple(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        """Scan with neither barcode nor item_id → 400."""
        recipe_id, _ = self._create_recipe_with_item(
            client, auth_headers, db_session, test_user, test_storage_location
        )
        start_r = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/start',
            json={'servings': 1},
            headers=auth_headers,
        )
        session_id = start_r.json()['picking_session_id']

        scan_r = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/{session_id}/scan',
            json={},
            headers=auth_headers,
        )
        assert scan_r.status_code == 400

    def test_scan_on_cancelled_session(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        """Scanning after cancel should fail."""
        recipe_id, item_id = self._create_recipe_with_item(
            client, auth_headers, db_session, test_user, test_storage_location
        )
        start_r = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/start',
            json={'servings': 1},
            headers=auth_headers,
        )
        session_id = start_r.json()['picking_session_id']

        # Cancel
        client.delete(
            f'{RECIPE_URL}/{recipe_id}/picking/{session_id}',
            headers=auth_headers,
        )

        # Try to scan
        scan_r = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/{session_id}/scan',
            json={'item_id': str(item_id)},
            headers=auth_headers,
        )
        assert scan_r.status_code == 404

    def test_complete_already_completed_session(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        """Completing an already-completed session."""
        recipe_id, item_id = self._create_recipe_with_item(
            client, auth_headers, db_session, test_user, test_storage_location
        )
        start_r = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/start',
            json={'servings': 1},
            headers=auth_headers,
        )
        session_id = start_r.json()['picking_session_id']

        # Complete
        c1 = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/{session_id}/complete',
            headers=auth_headers,
        )
        assert c1.status_code == 200

        # Complete again. The sheet closes the session on the last ingredient
        # and its "Finish" button can still arrive afterwards, so the endpoint
        # answers the same thing twice instead of turning a finished session
        # into a 404 nobody can act on.
        c2 = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/{session_id}/complete',
            headers=auth_headers,
        )
        assert c2.status_code == 200
        assert c2.json()['status'] == 'completed'

    def test_undo_already_completed_session(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        """Undo after session completion should fail."""
        recipe_id, item_id = self._create_recipe_with_item(
            client, auth_headers, db_session, test_user, test_storage_location
        )
        start_r = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/start',
            json={'servings': 2},
            headers=auth_headers,
        )
        session_id = start_r.json()['picking_session_id']
        ingredient_id = start_r.json()['items_to_pick'][0]['ingredient_id']

        # Pick
        client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/{session_id}/scan',
            json={'item_id': str(item_id)},
            headers=auth_headers,
        )

        # Complete
        client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/{session_id}/complete',
            headers=auth_headers,
        )

        # Try undo after completion
        undo_r = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/{session_id}/undo',
            json={'ingredient_id': str(ingredient_id)},
            headers=auth_headers,
        )
        # Should fail (session no longer active)
        assert undo_r.status_code in (400, 404)

    def test_picking_start_hands_back_an_unfinished_session(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        """Starting again resumes the unfinished session instead of voiding it.

        Cancelling on sight put every ingredient of a meal that had already
        been cooked back on the shelf, silently, on the next tap of "Get
        ingredients".
        """
        recipe_id, item_id = self._create_recipe_with_item(
            client, auth_headers, db_session, test_user, test_storage_location
        )

        s1 = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/start',
            json={'servings': 1},
            headers=auth_headers,
        )
        session1_id = s1.json()['picking_session_id']
        assert s1.json()['resumed'] is False

        s2 = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/start',
            json={'servings': 1},
            headers=auth_headers,
        )
        assert s2.json()['picking_session_id'] == session1_id
        assert s2.json()['resumed'] is True

        # And it is the same session, still able to take a scan.
        scan_r = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/{session1_id}/scan',
            json={'item_id': str(item_id)},
            headers=auth_headers,
        )
        assert scan_r.status_code == 200

    def test_scan_nonexistent_item_id(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        """Scan with item_id that doesn't exist → 404."""
        recipe_id, _ = self._create_recipe_with_item(
            client, auth_headers, db_session, test_user, test_storage_location
        )
        start_r = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/start',
            json={'servings': 1},
            headers=auth_headers,
        )
        session_id = start_r.json()['picking_session_id']

        scan_r = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/{session_id}/scan',
            json={'item_id': str(uuid.uuid4())},
            headers=auth_headers,
        )
        assert scan_r.status_code == 404

    def test_picking_with_very_large_servings_rejected(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        """FIX: Very large servings multiplier is now rejected with validation error."""
        recipe_id, item_id = self._create_recipe_with_item(
            client, auth_headers, db_session, test_user, test_storage_location
        )

        r = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/start',
            json={'servings': 1000},
            headers=auth_headers,
        )
        assert r.status_code == 422  # Now rejected by servings cap

    def test_cooking_history_limit_boundaries(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        """History with limit=0 and negative offset."""
        create_r = client.post(
            RECIPE_URL,
            json=_recipe_payload(ingredients=[]),
            headers=auth_headers,
        )
        recipe_id = create_r.json()['id']

        r = client.get(
            f'{RECIPE_URL}/{recipe_id}/history?limit=0', headers=auth_headers
        )
        # The page size is declared on the route like every other list's: a
        # page of zero rows is refused instead of served as an empty page.
        assert r.status_code == 422

    def test_patch_history_rating_boundary_values(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
        test_storage_location: StorageLocation,
    ) -> None:
        """Rating boundary: 0, 6 should fail; 1, 5 should succeed."""
        # Create and complete a session
        template = ProductTemplate(
            id=uuid.uuid4(),
            organization_id=test_user.organization_id,
            name='Rating Test Ingredient',
        )
        db_session.add(template)
        db_session.flush()

        item = Item(
            id=uuid.uuid4(),
            organization_id=test_user.organization_id,
            storage_location_id=test_storage_location.id,
            name='Rating Test Item',
            template_id=template.id,
            quantity=Decimal('500'),
        )
        db_session.add(item)
        anchor_pending_records(db_session)
        db_session.commit()

        recipe_id = _create_recipe_with_template(
            client,
            auth_headers,
            str(template.id),
            name='Rating Test Recipe',
            qty='100',
        )

        start_r = client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/start',
            json={'servings': 1},
            headers=auth_headers,
        )
        session_id = start_r.json()['picking_session_id']

        client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/{session_id}/scan',
            json={'item_id': str(item.id)},
            headers=auth_headers,
        )
        client.post(
            f'{RECIPE_URL}/{recipe_id}/picking/{session_id}/complete',
            headers=auth_headers,
        )

        # Rating 0 — should fail
        r0 = client.patch(
            f'{RECIPE_URL}/{recipe_id}/history/{session_id}',
            json={'rating': 0},
            headers=auth_headers,
        )
        assert r0.status_code == 422

        # Rating 6 — should fail
        r6 = client.patch(
            f'{RECIPE_URL}/{recipe_id}/history/{session_id}',
            json={'rating': 6},
            headers=auth_headers,
        )
        assert r6.status_code == 422

        # Rating 1 — should succeed
        r1 = client.patch(
            f'{RECIPE_URL}/{recipe_id}/history/{session_id}',
            json={'rating': 1},
            headers=auth_headers,
        )
        assert r1.status_code == 200

        # Rating 5 — should succeed
        r5 = client.patch(
            f'{RECIPE_URL}/{recipe_id}/history/{session_id}',
            json={'rating': 5},
            headers=auth_headers,
        )
        assert r5.status_code == 200

        # Negative rating — should fail
        rneg = client.patch(
            f'{RECIPE_URL}/{recipe_id}/history/{session_id}',
            json={'rating': -1},
            headers=auth_headers,
        )
        assert rneg.status_code == 422


# ══════════════════════════════════════════════════════════════════════════════
# 6. IMPORT/EXPORT VULNERABILITIES
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestImportExportSecurity:
    """Security tests for import/export endpoints."""

    def test_import_json_missing_name(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Import JSON without name → 400 (canonical ValueError mapping)."""
        r = client.post(
            f'{RECIPE_URL}/import',
            json={'format': 'json', 'data': {'servings': 2}},
            headers=auth_headers,
        )
        assert r.status_code == 400

    def test_import_json_empty_data(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Import with empty data dict → 400."""
        r = client.post(
            f'{RECIPE_URL}/import',
            json={'format': 'json', 'data': {}},
            headers=auth_headers,
        )
        assert r.status_code == 400

    def test_import_unsupported_format(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Import with unsupported format."""
        r = client.post(
            f'{RECIPE_URL}/import',
            json={'format': 'yaml', 'data': {}},
            headers=auth_headers,
        )
        assert r.status_code == 400

    def test_import_url_without_url_field(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """URL import without url field."""
        r = client.post(
            f'{RECIPE_URL}/import',
            json={'format': 'url'},
            headers=auth_headers,
        )
        assert r.status_code == 400

    def test_import_url_with_ftp(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """URL import with FTP protocol."""
        r = client.post(
            f'{RECIPE_URL}/import',
            json={'format': 'url', 'url': 'ftp://example.com/recipe.txt'},
            headers=auth_headers,
        )
        assert r.status_code == 400

    def test_import_preview_unsupported_format(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Preview with unsupported format."""
        r = client.post(
            f'{RECIPE_URL}/import/preview',
            json={'format': 'xml', 'data': {}},
            headers=auth_headers,
        )
        assert r.status_code == 400

    def test_export_unsupported_format(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Export with unsupported format."""
        create_r = client.post(RECIPE_URL, json=_recipe_payload(), headers=auth_headers)
        recipe_id = create_r.json()['id']

        r = client.get(
            f'{RECIPE_URL}/{recipe_id}/export?format=csv', headers=auth_headers
        )
        assert r.status_code == 400

    def test_export_json_content_structure(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Exported JSON should have correct structure."""
        payload = _recipe_payload(
            name='Export Security Test',
            ingredients=[{'name': 'Flour', 'quantity': '200', 'is_optional': False}],
        )
        create_r = client.post(RECIPE_URL, json=payload, headers=auth_headers)
        recipe_id = create_r.json()['id']

        r = client.get(
            f'{RECIPE_URL}/{recipe_id}/export?format=json', headers=auth_headers
        )
        assert r.status_code == 200
        data = r.json()
        assert '_export_version' in data
        assert data['name'] == 'Export Security Test'
        assert isinstance(data['ingredients'], list)

    def test_import_json_ingredient_without_name_handled(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """FIXED: Import with ingredient missing name now skips the ingredient gracefully."""
        r = client.post(
            f'{RECIPE_URL}/import',
            json={
                'format': 'json',
                'data': {
                    'name': 'Partial Ingredients',
                    'ingredients': [{'quantity': 100}],
                },
            },
            headers=auth_headers,
        )
        # The import payload is a free-form dict, so a nameless ingredient is
        # not a schema error: the import is created and skips that line.
        assert r.status_code == 201

    def test_preview_rate_limit_refuses_the_twenty_first_call(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """The 20/minute limit on import preview is real, and this says so.

        What stood here was named for the limit and measured its absence: the
        docstring promised "verify it's enforced", the comment a line below
        admitted "rate limiter is disabled in tests", and the assertion took
        `in (200, 422)` after three requests. The limiter guarding this
        endpoint (`_router_crud.py:194`) therefore had no cover at all —
        deleting the decorator changed nothing anywhere in the suite.

        The limiter is off suite-wide on purpose, so that every other test can
        hammer the API without counting. This test turns it on for its own
        duration and puts it back in ``finally``.

        It deliberately does not reset the limiter's storage. The bucket comes
        from the Bearer token — ``get_client_key`` reads the subject and keys
        on ``user:<id>`` — and ``auth_headers`` signs a token for a
        function-scoped user, so these twenty-one calls land in a bucket no
        other test shares. Resetting would be the opposite of isolation: the
        storage is one Redis shared by every xdist worker, and wiping it
        mid-run is precisely what would flake
        ``tests/integration/test_auth_rate_limit.py``, which counts there too.
        """
        payload = {'format': 'json', 'data': {'name': 'Test', 'ingredients': []}}

        limiter.enabled = True
        try:
            codes = [
                client.post(
                    f'{RECIPE_URL}/import/preview', json=payload, headers=auth_headers
                ).status_code
                for _ in range(21)
            ]
        finally:
            limiter.enabled = False

        # Whatever the first twenty answer, none of them is a refusal to
        # answer — the limit is 20, and it is spent exactly on the 21st.
        assert 429 not in codes[:20]
        assert codes[20] == 429


# ══════════════════════════════════════════════════════════════════════════════
# 7. TAG MANAGEMENT EDGE CASES
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestTagManagementSecurity:
    """Security tests for tag management."""

    def test_merge_tag_into_self(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Merging a tag into itself."""
        client.post(
            RECIPE_URL,
            json=_recipe_payload(name='Self Merge', tags=['same']),
            headers=auth_headers,
        )
        r = client.post(
            f'{RECIPE_URL}/tags/merge',
            json={'old_tag': 'same', 'new_tag': 'same'},
            headers=auth_headers,
        )
        # The tag exists, so the 404 branch is never taken; merging it into
        # itself walks an empty rename loop and answers 200.
        assert r.status_code == 200

    def test_merge_tags_empty_names(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Merging with empty tag names."""
        r = client.post(
            f'{RECIPE_URL}/tags/merge',
            json={'old_tag': '', 'new_tag': ''},
            headers=auth_headers,
        )
        assert r.status_code in (400, 404)

    def test_tag_color_invalid_hex(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Invalid hex color values."""
        client.post(
            RECIPE_URL,
            json=_recipe_payload(tags=['testcolor']),
            headers=auth_headers,
        )
        for color in ['red', '#GGG', '12345', '', '#1234567']:
            r = client.patch(
                f'{RECIPE_URL}/tags/testcolor/color',
                json={'color': color},
                headers=auth_headers,
            )
            assert r.status_code == 422, f'Color {color!r} should be rejected'

    def test_tag_color_valid_hex_formats(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Valid hex color formats."""
        client.post(
            RECIPE_URL,
            json=_recipe_payload(tags=['goodcolor']),
            headers=auth_headers,
        )
        for color in ['#FFF', '#FFFFFF', '#ff0000', '#00ff00']:
            r = client.patch(
                f'{RECIPE_URL}/tags/goodcolor/color',
                json={'color': color},
                headers=auth_headers,
            )
            assert r.status_code == 200, f'Color {color!r} should be accepted'

    def test_set_color_on_nonexistent_tag(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Set color on a tag that doesn't exist in any recipe."""
        r = client.patch(
            f'{RECIPE_URL}/tags/nonexistent/color',
            json={'color': '#FF0000'},
            headers=auth_headers,
        )
        # Setting a colour upserts the config row, so a tag that no recipe
        # uses is created rather than refused.
        assert r.status_code == 200


# ══════════════════════════════════════════════════════════════════════════════
# 8. UNIT CONVERSION EDGE CASES
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestUnitConversionSecurity:
    """Security tests for unit conversion CRUD."""

    def test_create_conversion_negative_metric_quantity_rejected(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Negative metric quantity → 422."""
        r = client.post(
            f'{RECIPE_URL}/unit-conversions',
            json={
                'ingredient_key': 'flour',
                'ingredient_name': 'Flour',
                'source_unit': 'cup',
                'metric_quantity': '-120',
                'metric_unit': 'g',
            },
            headers=auth_headers,
        )
        assert r.status_code == 422

    def test_create_conversion_empty_fields_rejected(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Conversion with empty required fields → 422."""
        r = client.post(
            f'{RECIPE_URL}/unit-conversions',
            json={
                'ingredient_key': '',
                'ingredient_name': '',
                'source_unit': '',
                'metric_quantity': '100',
                'metric_unit': '',
            },
            headers=auth_headers,
        )
        assert r.status_code == 422

    def test_update_nonexistent_conversion(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Update non-existent conversion → 404."""
        r = client.put(
            f'{RECIPE_URL}/unit-conversions/{uuid.uuid4()}',
            json={'metric_quantity': '250'},
            headers=auth_headers,
        )
        assert r.status_code == 404

    def test_delete_nonexistent_conversion(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Delete non-existent conversion → 404."""
        r = client.delete(
            f'{RECIPE_URL}/unit-conversions/{uuid.uuid4()}',
            headers=auth_headers,
        )
        assert r.status_code == 404

    def test_list_conversions_with_various_langs(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """List conversions with different language codes."""
        for lang in SUPPORTED_LANGUAGES:
            r = client.get(
                f'{RECIPE_URL}/unit-conversions?lang={lang}',
                headers=auth_headers,
            )
            assert r.status_code == 200

    def test_list_conversions_invalid_lang(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Invalid lang code."""
        r = client.get(
            f'{RECIPE_URL}/unit-conversions?lang=xyz',
            headers=auth_headers,
        )
        # Should still return 200 (falls back to default)
        assert r.status_code == 200


# ══════════════════════════════════════════════════════════════════════════════
# 9. IMAGE UPLOAD SECURITY
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestImageUploadSecurity:
    """Security tests for recipe image upload."""

    def test_upload_non_image_file(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Upload non-image content type."""
        create_r = client.post(RECIPE_URL, json=_recipe_payload(), headers=auth_headers)
        recipe_id = create_r.json()['id']

        from io import BytesIO

        r = client.post(
            f'{RECIPE_URL}/{recipe_id}/image',
            files={'image': ('test.txt', BytesIO(b'not an image'), 'text/plain')},
            headers=auth_headers,
        )
        assert r.status_code == 400

    def test_upload_oversized_image(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Upload image exceeding the 10MB image limit."""
        create_r = client.post(RECIPE_URL, json=_recipe_payload(), headers=auth_headers)
        recipe_id = create_r.json()['id']

        from io import BytesIO

        # Create 11MB fake content
        big_data = BytesIO(b'\x89PNG' + b'\x00' * (11 * 1024 * 1024))
        r = client.post(
            f'{RECIPE_URL}/{recipe_id}/image',
            files={'image': ('big.png', big_data, 'image/png')},
            headers=auth_headers,
        )
        assert r.status_code == 413

    def test_upload_image_nonexistent_recipe(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Upload image to non-existent recipe → 404."""
        from io import BytesIO

        r = client.post(
            f'{RECIPE_URL}/{uuid.uuid4()}/image',
            files={'image': ('test.png', BytesIO(b'\x89PNG'), 'image/png')},
            headers=auth_headers,
        )
        assert r.status_code == 404

    def test_delete_image_nonexistent_recipe(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Delete image from non-existent recipe → 404."""
        r = client.delete(f'{RECIPE_URL}/{uuid.uuid4()}/image', headers=auth_headers)
        assert r.status_code == 404

    def test_filename_extension_detection(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Upload with various image types (each with correct magic bytes)."""
        create_r = client.post(RECIPE_URL, json=_recipe_payload(), headers=auth_headers)
        recipe_id = create_r.json()['id']

        from io import BytesIO

        # Each image type must carry its real magic-byte signature
        # (validate_signature rejects spoofed Content-Type).
        image_samples = [
            ('jpg', 'image/jpeg', _real_image('JPEG')),
            ('png', 'image/png', _real_image('PNG')),
            ('webp', 'image/webp', _real_image('WEBP')),
        ]
        for ext, ct, payload in image_samples:
            r = client.post(
                f'{RECIPE_URL}/{recipe_id}/image',
                files={'image': (f'test.{ext}', BytesIO(payload), ct)},
                headers=auth_headers,
            )
            assert r.status_code == 200


# ══════════════════════════════════════════════════════════════════════════════
# 10. SHOPPING LIST INTEGRATION EDGE CASES
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestShoppingListIntegration:
    """Edge cases for add-to-shopping-list endpoint."""

    def test_add_to_shopping_list_nonexistent_recipe(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Add to shopping list for non-existent recipe → 404."""
        r = client.post(
            f'{RECIPE_URL}/{uuid.uuid4()}/add-to-shopping-list',
            json={'servings': 1},
            headers=auth_headers,
        )
        assert r.status_code == 404

    def test_add_to_shopping_list_negative_servings_rejected(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        db_session: Session,
        test_user: User,
    ) -> None:
        """Negative servings for shopping list → 422."""
        template = ProductTemplate(
            id=uuid.uuid4(),
            organization_id=test_user.organization_id,
            name='Shopping Test Ingredient',
        )
        db_session.add(template)
        db_session.commit()

        create_r = client.post(
            RECIPE_URL,
            json=_recipe_payload(
                name='Shopping Test Recipe',
                ingredients=[
                    {
                        'name': 'Shopping Test Ingredient',
                        'template_id': str(template.id),
                        'quantity': '100',
                    }
                ],
            ),
            headers=auth_headers,
        )
        recipe_id = create_r.json()['id']

        r = client.post(
            f'{RECIPE_URL}/{recipe_id}/add-to-shopping-list',
            json={'servings': -1},
            headers=auth_headers,
        )
        assert r.status_code == 422


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════


def _create_recipe_with_template(
    client: TestClient,
    auth_headers: dict[str, str],
    template_id: str,
    name: str = 'Test Recipe',
    servings: int = 1,
    qty: str = '100',
) -> str:
    """Creates a recipe whose ingredient is linked to a ProductTemplate."""
    payload = _recipe_payload(
        name=name,
        servings=servings,
        ingredients=[
            {
                'name': 'Test ingredient',
                'template_id': template_id,
                'quantity': qty,
                'is_optional': False,
            }
        ],
    )
    r = client.post(RECIPE_URL, json=payload, headers=auth_headers)
    assert r.status_code == 201
    return cast(str, r.json()['id'])

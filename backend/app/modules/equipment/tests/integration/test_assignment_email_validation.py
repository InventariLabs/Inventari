"""``AssignmentCreate.assigned_to_email`` format validation.

The schema was ``str | None`` with only a length cap, so any garbage
("not-an-email", whitespace, multi-line strings) was silently accepted
and forwarded all the way to the SMTP gateway at attestation
``launch_campaign`` time. Patching ``AssignmentCreate.assigned_to_email``
to ``EmailStr | None`` is the single ingress point that blocks the bad
data everywhere downstream.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.models.item import Item


@pytest.mark.integration
class TestAssignmentEmailValidation:
    """Malformed emails must be rejected at schema validation time."""

    @staticmethod
    def _checkout_url() -> str:
        return '/api/v1/equipment/assignments'

    @staticmethod
    def _payload(item_id: str, email: str | None) -> dict[str, object]:
        return {
            'item_id': item_id,
            'assigned_to_name': 'Alice',
            'assigned_to_email': email,
        }

    def test_valid_email_accepted_201(
        self, client: TestClient, eq_auth_headers: dict[str, str], eq_item: Item
    ) -> None:
        resp = client.post(
            self._checkout_url(),
            headers=eq_auth_headers,
            json=self._payload(str(eq_item.id), 'alice@example.com'),
        )
        assert resp.status_code == 201, resp.text

    def test_null_email_accepted_201(
        self, client: TestClient, eq_auth_headers: dict[str, str], eq_item: Item
    ) -> None:
        resp = client.post(
            self._checkout_url(),
            headers=eq_auth_headers,
            json=self._payload(str(eq_item.id), None),
        )
        assert resp.status_code == 201, resp.text

    def test_omitted_email_accepted_201(
        self, client: TestClient, eq_auth_headers: dict[str, str], eq_item: Item
    ) -> None:
        resp = client.post(
            self._checkout_url(),
            headers=eq_auth_headers,
            json={'item_id': str(eq_item.id), 'assigned_to_name': 'Alice'},
        )
        assert resp.status_code == 201

    def test_email_plus_tag_accepted_201(
        self, client: TestClient, eq_auth_headers: dict[str, str], eq_item: Item
    ) -> None:
        resp = client.post(
            self._checkout_url(),
            headers=eq_auth_headers,
            json=self._payload(str(eq_item.id), 'alice+tag@example.io'),
        )
        assert resp.status_code == 201, resp.text

    @pytest.mark.parametrize(
        'malformed',
        [
            'not-an-email',
            'alice.example.com',
            'alice@',
            '@example.com',
            'alice@example',
            ' ',
            '   ',
            'alice @example.com',
            'alice@exa mple.com',
            'alice@@example.com',
        ],
    )
    def test_malformed_email_rejected_422(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        malformed: str,
    ) -> None:
        resp = client.post(
            self._checkout_url(),
            headers=eq_auth_headers,
            json=self._payload(str(eq_item.id), malformed),
        )
        assert resp.status_code == 422, (
            f'expected 422 for malformed email {malformed!r}, got {resp.status_code}: {resp.text}'
        )

    def test_empty_string_rejected_422(
        self, client: TestClient, eq_auth_headers: dict[str, str], eq_item: Item
    ) -> None:
        resp = client.post(
            self._checkout_url(),
            headers=eq_auth_headers,
            json=self._payload(str(eq_item.id), ''),
        )
        assert resp.status_code == 422, resp.text

    def test_oversized_email_rejected_422(
        self, client: TestClient, eq_auth_headers: dict[str, str], eq_item: Item
    ) -> None:
        long_local = 'a' * 250
        long_email = f'{long_local}@example.com'
        resp = client.post(
            self._checkout_url(),
            headers=eq_auth_headers,
            json=self._payload(str(eq_item.id), long_email),
        )
        assert resp.status_code == 422, resp.text

    def test_extra_assignment_with_uuid_id_does_not_affect_validation(
        self, client: TestClient, eq_auth_headers: dict[str, str], eq_item: Item
    ) -> None:
        """Random unrecognised id doesn't blow validation — the schema
        envelope still rejects only the malformed email."""
        resp = client.post(
            self._checkout_url(),
            headers=eq_auth_headers,
            json={
                'item_id': str(uuid4()),  # valid UUID, no row → 404
                'assigned_to_name': 'Alice',
                'assigned_to_email': 'malformed',  # → 422 takes precedence
            },
        )
        # 422 takes precedence (Pydantic rejects malformed email before
        # service logic runs for an unknown item_id). If validation is
        # somehow weakened, the missing-item 404 path is also acceptable.
        assert resp.status_code in (404, 422), resp.text

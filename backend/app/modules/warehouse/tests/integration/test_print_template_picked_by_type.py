"""The printout answers to the document's type, not to one org-wide choice.

The template's ``document_type`` column used to be decorative: the PDF
endpoint read the profile's single ``default_template_id`` and printed
every document through it — a receipt wearing a scrap layout, because
that happened to be the template the profile named. The data model
already kept one default per (organization, module, document_type);
these tests pin the reading that honours it.
"""

import asyncio
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation

pytestmark = pytest.mark.integration


def _create_template(
    client: TestClient,
    headers: dict[str, str],
    name: str,
    document_type: str,
    body_html: str,
    is_default: bool = False,
) -> str:
    resp = client.post(
        '/api/v1/warehouse/templates',
        headers=headers,
        json={
            'module': 'warehouse',
            'name': name,
            'document_type': document_type,
            'body_html': body_html,
            'is_default': is_default,
        },
    )
    assert resp.status_code == 201, resp.text
    return str(resp.json()['id'])


@pytest.mark.integration
class TestThePrintAnswersToTheDocumentType:
    def _create_and_confirm_doc(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> str:
        """Create + confirm a receipt, returns doc_id (same flow as the
        PDF endpoint tests beside this file)."""
        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 3,
                        'unit': 'pcs',
                    }
                ],
            },
        )
        assert resp.status_code == 201
        doc_id = resp.json()['id']
        confirm_resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm',
            headers=doc_auth_headers,
        )
        assert confirm_resp.status_code == 200
        return str(doc_id)

    def _capture_pdf_template(self, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
        """Route the PDF generator into a capture — the route imports the
        generator from its module at call time, so the captured kwarg is
        the template the ROUTE picked, not a helper's."""
        captured: dict[str, Any] = {}

        async def fake_generate_pdf(*args: Any, **kwargs: Any) -> bytes:
            captured['user_template_html'] = kwargs.get('user_template_html')
            return b'%PDF-fake'

        monkeypatch.setattr(
            'app.modules.warehouse.document_pdf_service.generate_pdf_async',
            fake_generate_pdf,
        )
        return captured

    def test_type_default_wins_over_the_profile_choice(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A receipt prints the receipt template even though the profile
        points somewhere else — the per-type promise is the more specific
        one, and it is the one the column always claimed to make."""
        profile_template = _create_template(
            client,
            doc_auth_headers,
            'Org-wide layout',
            'STANDARD',
            '<html>PROFILE-MARKER {{ doc.number }}</html>',
        )
        _create_template(
            client,
            doc_auth_headers,
            'Receipt layout',
            'IN',
            '<html>RECEIPT-MARKER</html>',
            is_default=True,
        )
        resp = client.put(
            '/api/v1/warehouse/profile',
            headers=doc_auth_headers,
            json={'default_template_id': profile_template},
        )
        assert resp.status_code == 200

        captured = self._capture_pdf_template(monkeypatch)
        doc_id = self._create_and_confirm_doc(
            client, doc_auth_headers, doc_partner, doc_target_location, doc_template
        )
        resp = client.get(
            f'/api/v1/warehouse/documents/{doc_id}/pdf', headers=doc_auth_headers
        )
        assert resp.status_code == 200
        assert 'RECEIPT-MARKER' in str(captured['user_template_html'])
        assert 'PROFILE-MARKER' not in str(captured['user_template_html'])

    def test_types_without_their_own_template_print_the_profile_choice(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The profile's org-wide layout keeps working: a type without a
        template of its own falls back to it, instead of losing the choice
        the profile screen still advertises."""
        profile_template = _create_template(
            client,
            doc_auth_headers,
            'Org-wide layout',
            'STANDARD',
            '<html>PROFILE-MARKER {{ doc.number }}</html>',
        )
        resp = client.put(
            '/api/v1/warehouse/profile',
            headers=doc_auth_headers,
            json={'default_template_id': profile_template},
        )
        assert resp.status_code == 200

        captured = self._capture_pdf_template(monkeypatch)
        doc_id = self._create_and_confirm_doc(
            client, doc_auth_headers, doc_partner, doc_target_location, doc_template
        )
        resp = client.get(
            f'/api/v1/warehouse/documents/{doc_id}/pdf', headers=doc_auth_headers
        )
        assert resp.status_code == 200
        assert 'PROFILE-MARKER' in str(captured['user_template_html'])

    def test_resolver_reads_the_type_then_the_profile_then_none(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The selection order, pinned on its own: the type's default, then
        the profile's choice, then nothing — the built-in family, exactly
        as before either of the two exists."""
        from app.core.public_api import core_api
        from app.modules.warehouse._print_template_pick import (
            pick_print_template_html,
        )

        async def fake_get_default(
            db: Any, org_id: Any, module: str, document_type: str
        ) -> Any:
            if document_type == 'SCRAP':

                class Typed:
                    body_html = '<html>SCRAP-MARKER</html>'

                return Typed()
            return None

        monkeypatch.setattr(
            core_api.templates,
            'get_default_async',
            AsyncMock(side_effect=fake_get_default),
        )
        monkeypatch.setattr(
            core_api.templates,
            'get_async',
            AsyncMock(return_value=None),
        )

        class Profile:
            default_template_id = None

        # The stubbed core_api reads neither the session nor the org id,
        # so the resolver gets placeholders typed as Any.
        no_db = cast(Any, None)
        no_org = cast(Any, None)

        html = asyncio.run(pick_print_template_html(no_db, no_org, Profile(), 'SCRAP'))
        assert html == '<html>SCRAP-MARKER</html>'

        html = asyncio.run(pick_print_template_html(no_db, no_org, Profile(), 'IN'))
        assert html is None

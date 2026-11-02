"""
Integration tests for equipment protocol generation and document templates.

Covers:
- GET  /equipment/assignments/{id}/protocol/html — render HTML
- GET  /equipment/assignments/{id}/protocol/pdf  — render PDF
- GET  /equipment/protocol/placeholders           — list placeholders
- CRUD /equipment/templates                        — template management
"""

import re
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from fastapi import status
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models.item import Item


@pytest.mark.integration
class TestProtocolGeneration:
    """Tests for protocol HTML and PDF generation."""

    def _checkout(
        self, client: TestClient, eq_auth_headers: dict[str, str], eq_item: Item
    ) -> str:
        """Helper: create an assignment and return its ID."""
        resp = client.post(
            '/api/v1/equipment/assignments',
            headers=eq_auth_headers,
            json={
                'item_id': str(eq_item.id),
                'assigned_to_name': 'Jan Kowalski',
                'assigned_to_email': 'jan@example.com',
                'checkout_notes': 'Standard issue for new employee',
            },
        )
        assert resp.status_code == status.HTTP_201_CREATED
        return cast(str, resp.json()['id'])

    def test_render_html_checkout_protocol(
        self, client: TestClient, eq_auth_headers: dict[str, str], eq_item: Item
    ) -> None:
        """HTML protocol renders with default template for checkout."""
        assignment_id = self._checkout(client, eq_auth_headers, eq_item)

        resp = client.get(
            f'/api/v1/equipment/assignments/{assignment_id}/protocol/html',
            headers=eq_auth_headers,
        )

        assert resp.status_code == status.HTTP_200_OK
        assert 'text/html' in resp.headers['content-type']
        html = resp.text
        assert 'Equipment Handover Protocol' in html
        assert 'Jan Kowalski' in html
        assert 'ThinkPad X1 Carbon' in html
        assert 'SN-001' in html

    def test_render_pdf_checkout_protocol(
        self, client: TestClient, eq_auth_headers: dict[str, str], eq_item: Item
    ) -> None:
        """PDF protocol is generated from the same data."""
        assignment_id = self._checkout(client, eq_auth_headers, eq_item)

        resp = client.get(
            f'/api/v1/equipment/assignments/{assignment_id}/protocol/pdf',
            headers=eq_auth_headers,
        )

        assert resp.status_code == status.HTTP_200_OK
        assert resp.headers['content-type'] == 'application/pdf'
        assert resp.headers['content-disposition'].startswith(
            'attachment; filename="protocol-'
        )
        # Verify it's a valid PDF (starts with %PDF)
        assert resp.content[:5] == b'%PDF-'

    def test_render_html_checkin_protocol(
        self, client: TestClient, eq_auth_headers: dict[str, str], eq_item: Item
    ) -> None:
        """After check-in, the default template switches to the return protocol."""
        assignment_id = self._checkout(client, eq_auth_headers, eq_item)

        # Check in
        client.post(
            f'/api/v1/equipment/assignments/{assignment_id}/checkin',
            headers=eq_auth_headers,
            json={
                'checkin_notes': 'Returned in good condition',
                'checkin_condition': 'GOOD',
            },
        )

        resp = client.get(
            f'/api/v1/equipment/assignments/{assignment_id}/protocol/html',
            headers=eq_auth_headers,
        )

        assert resp.status_code == status.HTTP_200_OK
        html = resp.text
        assert 'Equipment Return Protocol' in html
        assert 'Jan Kowalski' in html
        assert 'Good' in html

    def test_render_protocol_not_found(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        """Missing assignment returns 404."""
        import uuid

        fake_id = str(uuid.uuid4())
        resp = client.get(
            f'/api/v1/equipment/assignments/{fake_id}/protocol/html',
            headers=eq_auth_headers,
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_render_protocol_with_custom_template(
        self, client: TestClient, eq_auth_headers: dict[str, str], eq_item: Item
    ) -> None:
        """Custom template is used when template_id is provided."""
        assignment_id = self._checkout(client, eq_auth_headers, eq_item)

        # Create custom template
        tpl_resp = client.post(
            '/api/v1/equipment/templates',
            headers=eq_auth_headers,
            json={
                'name': 'Custom Protocol',
                'document_type': 'CHECKOUT',
                'module': 'equipment',
                'body_html': '<html><body><h1>Custom: {{item_name}}</h1><p>To: {{assigned_to_name}}</p></body></html>',
            },
        )
        assert tpl_resp.status_code == status.HTTP_201_CREATED
        template_id = tpl_resp.json()['id']

        resp = client.get(
            f'/api/v1/equipment/assignments/{assignment_id}/protocol/html',
            headers=eq_auth_headers,
            params={'template_id': template_id},
        )

        assert resp.status_code == status.HTTP_200_OK
        html = resp.text
        assert 'Custom: ThinkPad X1 Carbon' in html
        assert 'To: Jan Kowalski' in html
        assert 'Equipment Handover Protocol' not in html  # default content not present


@pytest.mark.integration
class TestTheProtocolHtmlIsSanitized:
    """The organization authors the template; every member opens the page.

    The documents and purchase-order paths render this same kind of template
    through the shared engine, which cleans the rendered output with nh3.
    The equipment protocol rendered its own sandboxed Jinja and returned the
    output unsanitized: a sandbox stops template injection, not markup the
    template's author wrote on purpose. These tests pin the sanitized path.
    """

    def _checkout(
        self, client: TestClient, eq_auth_headers: dict[str, str], eq_item: Item
    ) -> str:
        resp = client.post(
            '/api/v1/equipment/assignments',
            headers=eq_auth_headers,
            json={
                'item_id': str(eq_item.id),
                'assigned_to_name': 'Jan Kowalski',
                'assigned_to_email': 'jan@example.com',
            },
        )
        assert resp.status_code == status.HTTP_201_CREATED
        return cast(str, resp.json()['id'])

    def test_script_and_event_handlers_are_stripped_from_custom_template(
        self, client: TestClient, eq_auth_headers: dict[str, str], eq_item: Item
    ) -> None:
        """A hostile template renders its honest content and nothing executable."""
        assignment_id = self._checkout(client, eq_auth_headers, eq_item)

        tpl_resp = client.post(
            '/api/v1/equipment/templates',
            headers=eq_auth_headers,
            json={
                'name': 'Hostile Protocol',
                'document_type': 'CHECKOUT',
                'module': 'equipment',
                'body_html': (
                    '<html><body><h1>Custom: {{item_name}}</h1>'
                    "<img src=x onerror=\"fetch('/api/v1/items', {credentials:'include'})\">"
                    '<script>alert(1)</script>'
                    '<p>To: {{assigned_to_name}}</p></body></html>'
                ),
            },
        )
        assert tpl_resp.status_code == status.HTTP_201_CREATED
        template_id = tpl_resp.json()['id']

        resp = client.get(
            f'/api/v1/equipment/assignments/{assignment_id}/protocol/html',
            headers=eq_auth_headers,
            params={'template_id': template_id},
        )

        assert resp.status_code == status.HTTP_200_OK
        html = resp.text
        assert '<script' not in html
        assert 'onerror' not in html
        assert 'alert(1)' not in html
        # The honest content of the template still renders.
        assert 'Custom: ThinkPad X1 Carbon' in html
        assert 'To: Jan Kowalski' in html

    def test_a_hostile_document_shell_dies_but_the_shell_survives(
        self, client: TestClient, eq_auth_headers: dict[str, str], eq_item: Item
    ) -> None:
        """Script in the head and onload on the body tag are stripped,
        while an honest full document keeps doctype/head/meta/body — the
        sanitized protocol must stay a document, not fall into quirks mode.

        The HTML endpoint serves this markup as a page of its own, not
        only inside the sandboxed preview iframe, so a script hiding in
        the head is the same class as one in the body.
        """
        assignment_id = self._checkout(client, eq_auth_headers, eq_item)

        tpl_resp = client.post(
            '/api/v1/equipment/templates',
            headers=eq_auth_headers,
            json={
                'name': 'Hostile Shell Protocol',
                'document_type': 'CHECKOUT',
                'module': 'equipment',
                'body_html': (
                    '<!DOCTYPE html>\n<html lang="pl">\n<head>\n'
                    '<meta charset="utf-8">\n'
                    '<script>alert(1)</script>\n'
                    '<style>.sig-line { border-top: 1px solid #333; }</style>\n'
                    '</head>\n'
                    '<body onload="alert(2)">\n'
                    '<h1>Custom: {{item_name}}</h1>\n'
                    '</body>\n</html>\n'
                ),
            },
        )
        assert tpl_resp.status_code == status.HTTP_201_CREATED
        template_id = tpl_resp.json()['id']

        resp = client.get(
            f'/api/v1/equipment/assignments/{assignment_id}/protocol/html',
            headers=eq_auth_headers,
            params={'template_id': template_id},
        )

        assert resp.status_code == status.HTTP_200_OK
        html = resp.text
        # The executable parts die, wherever they sat.
        assert '<script' not in html
        assert 'alert(1)' not in html
        assert 'onload' not in html
        # The document shell survives — no quirks mode on the wire.
        assert html.lstrip().lower().startswith('<!doctype html')
        assert '<html lang="pl">' in html
        assert '<meta charset="utf-8">' in html
        assert '<style>' in html
        assert '<h1>Custom: ThinkPad X1 Carbon</h1>' in html

    def test_default_template_keeps_its_style_block(
        self, client: TestClient, eq_auth_headers: dict[str, str], eq_item: Item
    ) -> None:
        """Sanitization does not strip the print styling of the built-in template."""
        assignment_id = self._checkout(client, eq_auth_headers, eq_item)

        resp = client.get(
            f'/api/v1/equipment/assignments/{assignment_id}/protocol/html',
            headers=eq_auth_headers,
        )

        assert resp.status_code == status.HTTP_200_OK
        assert '<style>' in resp.text
        assert 'Equipment Handover Protocol' in resp.text


@pytest.mark.integration
class TestTheProtocolReadsInTheSignersLanguage:
    """The dates in a document a worker signs.

    The decision lives in ``app/core/datetimes.py``: the wire keeps the
    canonical ``2026-09-18``, and a document printed for a signature is
    written the way the reader's language writes a date — the same date the
    screen they opened it from showed them. The reference number is an
    identifier, not a date, so it stays canonical in both.
    """

    def _checkout(
        self, client: TestClient, eq_auth_headers: dict[str, str], eq_item: Item
    ) -> str:
        resp = client.post(
            '/api/v1/equipment/assignments',
            headers=eq_auth_headers,
            json={
                'item_id': str(eq_item.id),
                'assigned_to_name': 'Jan Kowalski',
                'assigned_to_email': 'jan@example.com',
            },
        )
        assert resp.status_code == status.HTTP_201_CREATED
        return cast(str, resp.json()['id'])

    def test_polish_protocol_writes_polish_dates(
        self, client: TestClient, eq_auth_headers: dict[str, str], eq_item: Item
    ) -> None:
        assignment_id = self._checkout(client, eq_auth_headers, eq_item)

        resp = client.get(
            f'/api/v1/equipment/assignments/{assignment_id}/protocol/html',
            headers={**eq_auth_headers, 'Accept-Language': 'pl'},
        )

        assert resp.status_code == status.HTTP_200_OK
        html = resp.text
        assert 'Protokół przekazania sprzętu' in html
        # "Data wydania 18.09.2026 18:10" — the day first, as the interface
        # writes it, and not the wire's 2026-09-18 that used to be printed.
        assert re.search(r'\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}', html)
        assert 'Data wydania' in html
        # The reference number keeps its canonical shape.
        assert re.search(r'EQ-\d{8}-[0-9A-F]{8}', html)

    def test_the_model_stands_alone_when_no_manufacturer_was_recorded(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        # "— Latitude 5540" reads like a mangled value rather than like a
        # manufacturer nobody wrote down: the pair is joined first now, and
        # the missing marker stands only for what the pair has none of.
        eq_item.meta_data = {
            'equipment': {
                'serial_number': 'SN-001',
                'equipment_status': 'AVAILABLE',
                'model': 'Latitude 5540',
            }
        }
        db_session.add(eq_item)
        db_session.commit()

        assignment_id = self._checkout(client, eq_auth_headers, eq_item)
        resp = client.get(
            f'/api/v1/equipment/assignments/{assignment_id}/protocol/html',
            headers=eq_auth_headers,
        )

        assert resp.status_code == status.HTTP_200_OK
        assert 'Latitude 5540' in resp.text
        assert '— Latitude 5540' not in resp.text

    def test_the_pair_reads_together_when_both_are_recorded(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        eq_item.meta_data = {
            'equipment': {
                'serial_number': 'SN-001',
                'equipment_status': 'AVAILABLE',
                'manufacturer': 'Dell',
                'model': 'Latitude 5540',
            }
        }
        db_session.add(eq_item)
        db_session.commit()

        assignment_id = self._checkout(client, eq_auth_headers, eq_item)
        resp = client.get(
            f'/api/v1/equipment/assignments/{assignment_id}/protocol/html',
            headers=eq_auth_headers,
        )

        assert 'Dell Latitude 5540' in resp.text


@pytest.mark.integration
class TestPlaceholders:
    """Tests for placeholder listing endpoint."""

    def test_list_placeholders(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        resp = client.get(
            '/api/v1/equipment/protocol/placeholders',
            headers=eq_auth_headers,
        )
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert len(data) > 0
        keys = [p['key'] for p in data]
        assert '{{item_name}}' in keys
        assert '{{assigned_to_name}}' in keys
        assert '{{document_date}}' in keys


@pytest.mark.integration
class TestDocumentTemplates:
    """Tests for document template CRUD."""

    def test_create_template(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        resp = client.post(
            '/api/v1/equipment/templates',
            headers=eq_auth_headers,
            json={
                'name': 'Test Template',
                'document_type': 'CHECKOUT',
                'module': 'equipment',
                'body_html': '<h1>{{item_name}}</h1>',
            },
        )
        assert resp.status_code == status.HTTP_201_CREATED
        data = resp.json()
        assert data['name'] == 'Test Template'
        assert data['document_type'] == 'CHECKOUT'
        assert data['is_default'] is False

    def test_list_templates(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        # Create two templates
        for i in range(2):
            client.post(
                '/api/v1/equipment/templates',
                headers=eq_auth_headers,
                json={
                    'name': f'Template {i}',
                    'module': 'equipment',
                    'body_html': f'<p>Body {i}</p>',
                },
            )

        resp = client.get(
            '/api/v1/equipment/templates',
            headers=eq_auth_headers,
        )
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.json()) >= 2

    def test_get_template(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        create_resp = client.post(
            '/api/v1/equipment/templates',
            headers=eq_auth_headers,
            json={
                'name': 'Detail Test',
                'module': 'equipment',
                'body_html': '<p>Detail</p>',
            },
        )
        tpl_id = create_resp.json()['id']

        resp = client.get(
            f'/api/v1/equipment/templates/{tpl_id}',
            headers=eq_auth_headers,
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()['name'] == 'Detail Test'

    def test_update_template(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        create_resp = client.post(
            '/api/v1/equipment/templates',
            headers=eq_auth_headers,
            json={
                'name': 'Original',
                'module': 'equipment',
                'body_html': '<p>Original</p>',
            },
        )
        tpl_id = create_resp.json()['id']

        resp = client.put(
            f'/api/v1/equipment/templates/{tpl_id}',
            headers=eq_auth_headers,
            json={
                'name': 'Updated',
                'module': 'equipment',
                'body_html': '<p>New content</p>',
            },
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()['name'] == 'Updated'

    def test_delete_template(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        create_resp = client.post(
            '/api/v1/equipment/templates',
            headers=eq_auth_headers,
            json={
                'name': 'To Delete',
                'module': 'equipment',
                'body_html': '<p>bye</p>',
            },
        )
        tpl_id = create_resp.json()['id']

        resp = client.delete(
            f'/api/v1/equipment/templates/{tpl_id}',
            headers=eq_auth_headers,
        )
        assert resp.status_code == status.HTTP_204_NO_CONTENT

        # Verify it's gone
        resp = client.get(
            f'/api/v1/equipment/templates/{tpl_id}',
            headers=eq_auth_headers,
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_set_default_template_unsets_previous(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        """Setting a template as default should unset any existing default."""
        r1 = client.post(
            '/api/v1/equipment/templates',
            headers=eq_auth_headers,
            json={
                'name': 'Default 1',
                'module': 'equipment',
                'body_html': '<p>1</p>',
                'is_default': True,
            },
        )
        id1 = r1.json()['id']

        r2 = client.post(
            '/api/v1/equipment/templates',
            headers=eq_auth_headers,
            json={
                'name': 'Default 2',
                'module': 'equipment',
                'body_html': '<p>2</p>',
                'is_default': True,
            },
        )
        id2 = r2.json()['id']

        # First template should no longer be default
        check1 = client.get(
            f'/api/v1/equipment/templates/{id1}',
            headers=eq_auth_headers,
        )
        assert check1.json()['is_default'] is False

        check2 = client.get(
            f'/api/v1/equipment/templates/{id2}',
            headers=eq_auth_headers,
        )
        assert check2.json()['is_default'] is True

    def test_get_template_not_found(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        import uuid

        resp = client.get(
            f'/api/v1/equipment/templates/{uuid.uuid4()}',
            headers=eq_auth_headers,
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.integration
class TestTheProtocolPrintsTheReturnDayOnTheOrgClock:
    """The document a worker signs prints the day the organization picked.

    The stored return day is an instant pinned to the end of its day on the
    organization's clock. Printing it as a UTC wall clock moved it a day
    forward for every organization west of UTC: the handover sheet said
    "10/01/2026" while the screen said "Sep 30, 2026" (review 2026-09-23).
    """

    def test_a_west_orgs_return_day_prints_the_day_it_picked(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        eq_org: Any,
        db_session: Session,
    ) -> None:
        from app.modules.equipment.models import EquipmentAssignment

        eq_org.timezone = 'America/Los_Angeles'
        db_session.commit()

        r = client.post(
            '/api/v1/equipment/assignments',
            headers=eq_auth_headers,
            json={
                'item_id': str(eq_item.id),
                'assigned_to_name': 'Jan Kowalski',
            },
        )
        assert r.status_code == status.HTTP_201_CREATED
        assignment_id = r.json()['id']

        assignment = (
            db_session.query(EquipmentAssignment)
            .filter(EquipmentAssignment.id == assignment_id)
            .one()
        )
        # What a checkout of "Sep 30" writes on this organization's clock:
        # the last microsecond of Sep 30 in Los Angeles, in UTC.
        assignment.expected_return_at = datetime(
            2026, 10, 1, 6, 59, 59, 999999, tzinfo=UTC
        )
        db_session.commit()

        resp = client.get(
            f'/api/v1/equipment/assignments/{assignment_id}/protocol/html',
            headers=eq_auth_headers,
        )

        assert resp.status_code == status.HTTP_200_OK
        # The row, not the whole document: the checkout timestamp prints
        # today's date and would collide with a bare "not in" assertion.
        cell = re.search(r'Expected Return</th>\s*<td>([^<]+)</td>', resp.text)
        assert cell is not None
        assert cell.group(1).strip() == 'Sep 30, 2026'

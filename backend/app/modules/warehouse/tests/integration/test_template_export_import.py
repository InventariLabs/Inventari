"""A template leaves as one file and arrives on another instance unchanged.

The export/import pair exists so a layout crafted on one installation can
circulate to another. The file is untrusted data: the import
reads it, renders it on the example document, and saves it through the
ordinary create path — nothing else ever executes it.
"""

import json
from pathlib import Path
from typing import cast

import pytest
from fastapi import status
from httpx import Response
from starlette.testclient import TestClient

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization

pytestmark = pytest.mark.integration

URL = '/api/v1/warehouse/templates'
EXPORT_KIND = 'inventari.document-template'
EXPORT_VERSION = 1

_BODY = (
    '<table><tbody>'
    '{% for line in document.lines %}'
    '<tr><td>{{ line.name }}</td><td>{{ partner.name }}</td></tr>'
    '{% endfor %}'
    '</tbody></table>'
)

_TEMPLATES_DIR = Path(__file__).resolve().parents[2] / 'templates'


def _export_payload(
    name: str = 'German receipt',
    body: str = _BODY,
    document_type: str = 'IN',
    is_default: bool = False,
) -> dict[str, object]:
    return {
        'kind': EXPORT_KIND,
        'version': EXPORT_VERSION,
        'name': name,
        'document_type': document_type,
        'is_default': is_default,
        'body_html': body,
    }


def _create_template(
    client: TestClient,
    headers: dict[str, str],
    name: str = 'German receipt',
    body: str = _BODY,
    document_type: str = 'IN',
    is_default: bool = False,
) -> str:
    resp = client.post(
        URL,
        headers=headers,
        json={
            'module': 'warehouse',
            'name': name,
            'document_type': document_type,
            'body_html': body,
            'is_default': is_default,
        },
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    return str(resp.json()['id'])


def _import_file(
    client: TestClient,
    headers: dict[str, str],
    payload: dict[str, object] | bytes,
) -> Response:
    raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    # TestClient's own annotation answers Any; the object on the wire is
    # the httpx response.
    return cast(
        Response,
        client.post(
            f'{URL}/import',
            headers=headers,
            files={'file': ('template.json', raw, 'application/json')},
        ),
    )


def _error_message(resp: Response) -> str:
    detail = resp.json()['detail']
    return detail['message'] if isinstance(detail, dict) else str(detail)


class TestExport:
    def test_export_is_one_json_file(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        template_id = _create_template(client, doc_auth_headers, is_default=True)

        resp = client.get(f'{URL}/{template_id}/export', headers=doc_auth_headers)

        assert resp.status_code == status.HTTP_200_OK
        assert resp.headers['content-type'].startswith('application/json')
        disposition = resp.headers['content-disposition']
        assert disposition.startswith('attachment')
        assert 'filename' in disposition

        payload = json.loads(resp.content)
        assert payload['kind'] == EXPORT_KIND
        assert payload['version'] == EXPORT_VERSION
        assert payload['name'] == 'German receipt'
        assert payload['document_type'] == 'IN'
        assert payload['is_default'] is True
        assert payload['body_html'] == _BODY

    def test_export_of_an_unknown_template_is_404(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        resp = client.get(
            f'{URL}/00000000-0000-0000-0000-00000000000f/export',
            headers=doc_auth_headers,
        )

        assert resp.status_code == status.HTTP_404_NOT_FOUND


class TestImportRoundTrip:
    def test_the_file_recreates_the_template_on_another_instance(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        doc_org: Organization,
        doc_auth_headers: dict[str, str],
    ) -> None:
        template_id = _create_template(client, doc_auth_headers)
        exported = client.get(f'{URL}/{template_id}/export', headers=doc_auth_headers)
        assert exported.status_code == status.HTTP_200_OK

        other_org = h.create_org('Other Instance', ['core', 'items', 'warehouse'])
        other_user = h.create_user(other_org, email='other@example.com')
        other_headers = h.get_auth_headers(other_user)
        assert client.get(URL, headers=other_headers).json()['items'] == []

        resp = _import_file(client, other_headers, exported.content)

        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        created = resp.json()
        assert created['name'] == 'German receipt'
        assert created['document_type'] == 'IN'
        assert created['is_default'] is False
        # Byte-identical body: what rendered there renders here, with no
        # manual edit — that is the whole point of the file.
        assert created['body_html'] == _BODY
        assert created['id'] != template_id

        listed = client.get(URL, headers=other_headers).json()['items']
        assert [tpl['name'] for tpl in listed] == ['German receipt']


class TestImportValidation:
    def test_an_unknown_placeholder_is_rejected_and_named(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        before = client.get(URL, headers=doc_auth_headers).json()['items']

        resp = _import_file(
            client,
            doc_auth_headers,
            _export_payload(body='<p>{{ nonexistent_field }}</p>'),
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert 'nonexistent_field' in _error_message(resp)

        # The refusal left nothing behind.
        assert client.get(URL, headers=doc_auth_headers).json()['items'] == before

    def test_an_unknown_nested_root_is_rejected_and_named(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        resp = _import_file(
            client,
            doc_auth_headers,
            _export_payload(body='<p>{{ madeup.name }}</p>'),
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert 'madeup' in _error_message(resp)

    def test_an_unknown_attribute_on_a_known_root_is_rejected_and_named(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        """The catalog speaks in dotted keys (``{{partner.tax_id}}``), so a
        reference like ``{{partner.nonexistent_field}}`` is a typo the author
        wants named — not an empty paragraph on the paper.
        """
        resp = _import_file(
            client,
            doc_auth_headers,
            _export_payload(body='<p>{{ partner.nonexistent_field }}</p>'),
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert 'partner.nonexistent_field' in _error_message(resp)

    def test_an_unknown_attribute_on_a_loop_variable_is_rejected_and_named(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        """``line`` comes from ``{% for line in document.lines %}`` — the
        check binds the loop variable to an example line before it judges
        the attributes read off it.
        """
        body = (
            '{% for line in document.lines %}'
            '<tr><td>{{ line.bogus_column }}</td></tr>'
            '{% endfor %}'
        )
        resp = _import_file(client, doc_auth_headers, _export_payload(body=body))

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert 'line.bogus_column' in _error_message(resp)

    def test_a_body_over_the_editor_ceiling_is_refused(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        """Import enforces what the editor's save does: a file whose body
        sails past the create schema's ceiling must not become a template
        the editor itself can no longer save.
        """
        body = '<p>' + 'x' * 51200 + '</p>'
        resp = _import_file(client, doc_auth_headers, _export_payload(body=body))

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert 'body_html' in _error_message(resp)

    def test_copies_of_the_built_in_layouts_import(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        """A seeded copy references internal context keys (``doc_variant``,
        ``discrepancy_map``) — they render, so they import. The round trip
        exists so exactly these layouts circulate.
        """
        builtins = sorted(_TEMPLATES_DIR.glob('*.html'))
        assert builtins, 'the warehouse module ships no layouts'

        for path in builtins:
            resp = _import_file(
                client,
                doc_auth_headers,
                _export_payload(
                    name=f'copy of {path.stem}', body=path.read_text('utf-8')
                ),
            )
            assert resp.status_code == status.HTTP_201_CREATED, (
                f'{path.name} refused: {resp.status_code} '
                f'{_error_message(resp) if resp.status_code != 500 else resp.text}'
            )

    def test_a_layout_with_its_own_macro_imports(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        """A macro is a name the layout defines itself, not a placeholder —
        the shipped pl_pz totals row is one, and a copy of it must import.
        """
        body = (
            '{% macro qty(value) %}<td>{{ value | format_qty }}</td>{% endmacro %}'
            '<table><tbody>{% for line in document.lines %}'
            '<tr>{{ qty(line.expected_quantity) }}</tr>{% endfor %}</tbody></table>'
        )

        resp = _import_file(client, doc_auth_headers, _export_payload(body=body))

        assert resp.status_code == status.HTTP_201_CREATED, resp.text

    def test_a_file_that_is_not_json_is_refused(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        resp = _import_file(client, doc_auth_headers, b'this is not json')

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert 'json' in _error_message(resp).lower()

    def test_a_file_of_the_wrong_kind_is_refused(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        payload = _export_payload()
        payload['kind'] = 'some.other.export'

        resp = _import_file(client, doc_auth_headers, payload)

        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_a_newer_file_version_is_refused(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        payload = _export_payload()
        payload['version'] = EXPORT_VERSION + 100

        resp = _import_file(client, doc_auth_headers, payload)

        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_a_missing_field_is_refused_and_named(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        payload = _export_payload()
        del payload['body_html']

        resp = _import_file(client, doc_auth_headers, payload)

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert 'body_html' in _error_message(resp)

    def test_a_template_that_does_not_render_is_refused(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        resp = _import_file(
            client,
            doc_auth_headers,
            _export_payload(body='{% for line in document.lines %}<tr>'),
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_an_include_outside_the_module_is_refused(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        """The file is untrusted data: an include reaching past the
        module's own partials gets no filesystem."""
        resp = _import_file(
            client,
            doc_auth_headers,
            _export_payload(body="{% include '../../../../etc/passwd' %}"),
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_a_sandbox_probe_imports_and_prints_nothing(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        """An attribute probe is what the sandbox is for, not what the
        import refuses: the editor takes the same body from a hand, and the
        sandboxed render — the only thing that ever executes either —
        turns the probe into an empty cell. The import stays no stricter
        than the editor; the safety property is pinned on the output.
        """
        body = "<p>{{ ''.__class__ }}</p>"

        resp = _import_file(client, doc_auth_headers, _export_payload(body=body))

        assert resp.status_code == status.HTTP_201_CREATED, resp.text

        preview = client.post(
            f'{URL}/preview', headers=doc_auth_headers, json={'body_html': body}
        )
        assert preview.status_code == status.HTTP_200_OK
        assert 'class' not in preview.json()['html']

    def test_a_failed_import_names_nothing_new_afterwards(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        before = client.get(URL, headers=doc_auth_headers).json()['items']

        _import_file(
            client,
            doc_auth_headers,
            _export_payload(body='<p>{{ no_such_field }}</p>'),
        )

        after = client.get(URL, headers=doc_auth_headers).json()['items']
        assert after == before

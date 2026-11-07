"""the placeholders catalog is derived from the render context.

A template author needs more than a field name: what the field contains,
when it is empty and for which document types it makes sense. The catalog is
generated from ``build_pdf_context`` (the same code that renders the PDF),
so it cannot drift from what a template really receives — a new context key
without an annotation would surface automatically, and the coverage test
below forces the annotation to be written.
"""

from fastapi import status
from starlette.testclient import TestClient

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.modules.warehouse.documents_templates_router import (
    _INTERNAL_CONTEXT_KEYS,
    _NESTED_PLACEHOLDERS,
    _PLACEHOLDER_META,
    _build_placeholders_catalog,
    _example_context,
)


class TestPlaceholdersCatalog:
    """The catalog itself."""

    def test_every_non_internal_context_key_is_annotated(self) -> None:
        """No render-context key may lack meta — new fields must be described.

        The catalog can auto-surface an unannotated key, but the description
        would be a name guess; a real annotation is required. The
        issuer's nested keys come from the dataclass itself, so a new
        IssuerContext field lands in the catalog *and* must be annotated.
        """
        from dataclasses import fields

        from app.core.print_identity import IssuerContext

        context = _example_context()
        nested_keys = {
            f'{parent}.{attr}'
            for parent, attrs in _NESTED_PLACEHOLDERS.items()
            for attr in attrs
        } | {f'issuer.{field.name}' for field in fields(IssuerContext)}
        flat_keys = {
            key
            for key in context
            if key not in _INTERNAL_CONTEXT_KEYS and key not in _NESTED_PLACEHOLDERS
        }

        assert flat_keys | nested_keys == set(_PLACEHOLDER_META), (
            'Every render-context key needs a _PLACEHOLDER_META entry; '
            'missing: '
            f'{sorted((flat_keys | nested_keys) - set(_PLACEHOLDER_META))} '
            'or annotated-but-absent: '
            f'{sorted(set(_PLACEHOLDER_META) - (flat_keys | nested_keys))}'
        )

    def test_catalog_covers_issuer_and_partner(self) -> None:
        catalog = {entry.key: entry for entry in _build_placeholders_catalog()}

        assert '{{issuer.name}}' in catalog
        assert '{{issuer.tax_id}}' in catalog
        assert '{{issuer.address}}' in catalog
        assert '{{issuer.logo}}' in catalog
        assert catalog['{{issuer.logo}}'].possibly_empty is True
        assert '{{partner.tax_id}}' in catalog

    def test_every_entry_has_description_and_example(self) -> None:
        for entry in _build_placeholders_catalog():
            assert entry.description, entry.key
            assert entry.example is not None, entry.key
            assert entry.key.startswith('{{') and entry.key.endswith('}}')

    def test_empty_marked_fields_are_flagged(self) -> None:
        catalog = {entry.key: entry for entry in _build_placeholders_catalog()}

        # The example document is an IN — a receipt: no source location,
        # and corrections-only fields are absent.
        assert catalog['{{source_location}}'].possibly_empty is True
        assert catalog['{{corrected_doc_number}}'].possibly_empty is True
        assert catalog['{{corrected_doc_number}}'].document_types == ['CORRECTION']

    def test_example_values_are_representative(self) -> None:
        catalog = {entry.key: entry for entry in _build_placeholders_catalog()}

        assert catalog['{{doc_title}}'].example
        assert catalog['{{partner.name}}'].example == 'Acme Supplies'
        assert catalog['{{total_expected}}'].example == '2'
        # Data URIs are summarized, not dumped into the editor.
        assert catalog['{{code128_img}}'].example == '[embedded image data URI]'


class TestPlaceholdersEndpoint:
    """GET /placeholders exposes the catalog with the new fields."""

    def test_endpoint_returns_annotated_catalog(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        resp = client.get(
            '/api/v1/warehouse/templates/placeholders',
            headers=doc_auth_headers,
        )

        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        keys = {entry['key'] for entry in data}
        assert '{{issuer.name}}' in keys
        assert '{{doc_title}}' in keys
        assert all('description' in entry and 'example' in entry for entry in data)
        # The old hand-maintained names are gone — they never matched the
        # render context.
        assert '{{document_number}}' not in keys
        assert '{{organization_name}}' not in keys

    def test_the_catalogue_speaks_the_layouts_own_dialect(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        """A template author copies a built-in layout and looks its parts up.

        Every shipped layout is written in terms of `document` — the number,
        the dates, the loop over the lines — and `document` used to be
        excluded from the catalogue as internal. So the list described one
        dialect and the file being copied was written in another.
        """
        resp = client.get(
            '/api/v1/warehouse/templates/placeholders',
            headers=doc_auth_headers,
        )

        keys = {entry['key'] for entry in resp.json()}
        assert '{{document.number}}' in keys
        assert '{{document.lines}}' in keys
        assert '{{document.created_at}}' in keys

    def test_no_example_is_the_repr_of_a_python_object(self) -> None:
        """The help is for a template author, not for someone debugging the
        service: ``{{document.lines}}`` used to show
        ``[<...DocumentLine object at 0x7be5...>]`` — a module path and a
        memory address where the other placeholders show a readable value.
        Fails without the fix on every list-valued entry."""
        catalog = {entry.key: entry.example for entry in _build_placeholders_catalog()}

        assert 'object at 0x' not in ''.join(value or '' for value in catalog.values())
        assert catalog['{{document.lines}}'] == 'Example Item × 2'

    def test_a_list_of_records_reads_as_values_not_as_python_literals(self) -> None:
        """``{{totals_by_unit}}`` showed ``{'symbol': None, 'expected':
        Decimal('2'), 'done': Decimal('0')}`` — dict braces, ``None`` and a
        ``Decimal(...)`` wrapper in a help meant for a template author."""
        catalog = {entry.key: entry.example for entry in _build_placeholders_catalog()}
        text = ''.join(value or '' for value in catalog.values())

        assert 'Decimal(' not in text
        assert "{'" not in text
        assert 'None' not in text
        assert catalog['{{totals_by_unit}}'] == 'expected: 2, done: 0'

    def test_the_examples_follow_the_readers_language(self) -> None:
        """``doc_title`` and ``print_status`` were English demo values in a
        Polish editor, next to a Polish description."""
        pl = {entry.key: entry.example for entry in _build_placeholders_catalog('pl')}

        assert 'Przyjęcie' in (pl['{{doc_title}}'] or '')
        assert pl['{{print_status}}'] != 'Draft'

    def test_the_endpoint_answers_in_the_callers_language(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        resp = client.get(
            '/api/v1/warehouse/templates/placeholders',
            headers={**doc_auth_headers, 'Accept-Language': 'pl'},
        )

        examples = {entry['key']: entry['example'] for entry in resp.json()}
        assert 'Przyjęcie' in examples['{{doc_title}}']


class TestTemplatePreviewEndpoint:
    """POST /preview answers "what will this print", not "what does it say"."""

    URL = '/api/v1/warehouse/templates/preview'

    def test_a_layout_comes_back_rendered(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        resp = client.post(
            self.URL,
            headers=doc_auth_headers,
            json={'body_html': '<p>Number: {{ document.number }}</p>'},
        )

        assert resp.status_code == status.HTTP_200_OK
        html = resp.json()['html']
        assert '{{' not in html
        assert '{%' not in html
        assert 'Number: ' in html

    def test_the_example_is_rendered_in_the_callers_language(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        body = '<h1>{{ print_title }}</h1>'
        en = client.post(self.URL, headers=doc_auth_headers, json={'body_html': body})
        pl = client.post(
            self.URL,
            headers={**doc_auth_headers, 'Accept-Language': 'pl'},
            json={'body_html': body},
        )

        assert 'Goods Receipt' in en.json()['html']
        assert 'Przyjęcie' in pl.json()['html']

    def test_a_layout_with_a_fixed_language_previews_in_it_alone(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        """PL PZ is a Polish form: its own wording is Polish whatever the
        editor's language, so the header it includes must be Polish too —
        the preview used to put "Goods Receipt Note" above "DOSTAWCA"."""
        from pathlib import Path

        templates_dir = Path(__file__).resolve().parents[2] / 'templates'
        body = (templates_dir / 'pl_pz.html').read_text(encoding='utf-8')

        resp = client.post(self.URL, headers=doc_auth_headers, json={'body_html': body})

        assert resp.status_code == status.HTTP_200_OK, resp.text
        html = resp.json()['html']
        assert 'Nazwa towaru' in html
        assert 'Przyjęcie Zewnętrzne' in html
        assert 'Goods Receipt' not in html
        assert 'DRAFT' not in html
        # The example issuer's country is named like the partner's.
        assert 'Poland' not in html

    def test_the_built_in_pick_list_previews_with_a_row_of_its_own(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        from pathlib import Path

        templates_dir = Path(__file__).resolve().parents[2] / 'templates'
        body = (templates_dir / 'pick_list.html').read_text(encoding='utf-8')

        resp = client.post(self.URL, headers=doc_auth_headers, json={'body_html': body})

        assert resp.status_code == status.HTTP_200_OK, resp.text
        html = resp.json()['html']
        assert 'Pick List' in html
        assert 'A-01' in html
        assert 'Example Item' in html

    def test_a_read_only_account_gets_the_preview(
        self, client: TestClient, h: ModuleTestHelper, doc_org: Organization
    ) -> None:
        viewer = h.create_user(
            doc_org, email='preview-viewer@example.com', role='viewer'
        )
        headers = h.get_auth_headers(viewer)

        preview = client.post(self.URL, headers=headers, json={'body_html': '<p>x</p>'})
        assert preview.status_code == status.HTTP_200_OK, preview.text

        # The exemption is the preview alone: saving a layout still needs write.
        save = client.post(
            '/api/v1/warehouse/templates',
            headers=headers,
            json={'name': 'x', 'document_type': 'IN', 'body_html': '<p>x</p>'},
        )
        assert save.status_code == status.HTTP_403_FORBIDDEN, save.text

    def test_a_loop_over_the_lines_produces_rows(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        body = (
            '<table><tbody>'
            '{% for line in document.lines %}'
            '<tr><td>{{ line.name }}</td></tr>{% endfor %}'
            '</tbody></table>'
        )

        resp = client.post(self.URL, headers=doc_auth_headers, json={'body_html': body})

        assert resp.status_code == status.HTTP_200_OK
        html = resp.json()['html']
        assert '{% for' not in html
        assert '<tr>' in html

    def test_every_builtin_layout_renders_through_the_preview(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        """The preview passes the module's template directory, so a shipped
        layout's `{% include 'print_header.html' %}` resolves the same way it
        does on the PDF path — every built-in renders 200.
        """
        from pathlib import Path

        templates_dir = Path(__file__).resolve().parents[2] / 'templates'
        builtins = sorted(templates_dir.glob('*.html'))
        assert builtins, 'the warehouse module ships no layouts'

        for path in builtins:
            resp = client.post(
                self.URL,
                headers=doc_auth_headers,
                json={'body_html': path.read_text(encoding='utf-8')},
            )
            assert resp.status_code == status.HTTP_200_OK, (
                f'{path.name} failed: {resp.status_code} {resp.text[:300]}'
            )
            # The shared partial resolved — the include is gone from the
            # rendered page.
            assert '{% include' not in resp.json()['html']

    def test_a_builtin_layout_previews_with_both_codes(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        """The preview shows the barcode and the QR the paper carries.

        The rendered page is cleaned before it is returned; a cleaner that
        drops the `data:` image leaves two empty `<img>` tags, which the
        editor draws as a page the printer would not produce.
        """
        from pathlib import Path

        body = (
            Path(__file__).resolve().parents[2] / 'templates' / 'standard.html'
        ).read_text(encoding='utf-8')

        resp = client.post(self.URL, headers=doc_auth_headers, json={'body_html': body})

        assert resp.status_code == status.HTTP_200_OK
        html = resp.json()['html']
        assert 'class="code128"' in html
        assert 'src="data:image/svg+xml;base64,' in html
        assert 'src="data:image/png;base64,' in html

    def test_a_half_written_layout_says_what_is_wrong(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        """The editor's normal state is a template mid-sentence."""
        resp = client.post(
            self.URL,
            headers=doc_auth_headers,
            json={'body_html': '{% for line in document.lines %}<tr>'},
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        detail = resp.json()['detail']
        message = detail['message'] if isinstance(detail, dict) else detail
        assert 'render' in message.lower()

    def test_an_empty_layout_renders_to_nothing(
        self, client: TestClient, doc_auth_headers: dict[str, str]
    ) -> None:
        resp = client.post(self.URL, headers=doc_auth_headers, json={'body_html': ''})

        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()['html'] == ''

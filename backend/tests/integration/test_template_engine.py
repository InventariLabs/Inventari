"""Tests for shared template engine, CRUD, and sanitization."""

import pytest
from jinja2 import TemplateSyntaxError
from jinja2.sandbox import SecurityError

from app.core.exceptions import NotFoundException
from app.services.template_engine import TemplateEngine, sanitize_html


@pytest.mark.integration
class TestHTMLSanitization:
    def test_strips_script_tag(self):
        html = '<p>Hello</p><script>alert("xss")</script><p>World</p>'
        result = sanitize_html(html)
        assert '<script' not in result
        assert 'alert' not in result
        assert '<p>Hello</p>' in result
        assert '<p>World</p>' in result

    def test_strips_iframe_tag(self):
        html = '<iframe src="evil.com"></iframe><p>Safe</p>'
        result = sanitize_html(html)
        assert '<iframe' not in result
        assert '<p>Safe</p>' in result

    def test_strips_event_handlers(self):
        html = '<img src="x.png" onerror="alert(1)">'
        result = sanitize_html(html)
        assert 'onerror' not in result

    def test_strips_onclick(self):
        html = '<div onclick="steal()">Click me</div>'
        result = sanitize_html(html)
        assert 'onclick' not in result
        assert 'Click me' in result

    def test_strips_javascript_href(self):
        html = '<a href="javascript:alert(1)">Link</a>'
        result = sanitize_html(html)
        assert 'javascript:' not in result

    def test_strips_object_and_embed(self):
        html = '<object data="x"></object><embed src="y">'
        result = sanitize_html(html)
        assert '<object' not in result
        assert '<embed' not in result

    def test_strips_form_elements(self):
        html = '<form><input type="text"><button>Submit</button></form>'
        result = sanitize_html(html)
        assert '<form' not in result
        assert '<input' not in result
        assert '<button' not in result

    def test_preserves_safe_html(self):
        html = (
            '<div class="container"><h1>Title</h1><p style="color:red">Text</p></div>'
        )
        result = sanitize_html(html)
        assert result == html

    def test_preserves_table_html(self):
        html = '<table><thead><tr><th>Name</th></tr></thead><tbody><tr><td>Test</td></tr></tbody></table>'
        result = sanitize_html(html)
        assert result == html

    def test_preserves_img_without_events(self):
        html = '<img src="logo.png" alt="Logo" style="width:100px">'
        result = sanitize_html(html)
        assert result == html

    # ── The seeded copy of a built-in must stay a working template

    def test_preserves_jinja_comparisons(self):
        """nh3 escapes ``>`` in text nodes; Jinja expressions must survive.

        ``{% if line.expected_quantity >= 0 %}`` sanitized to
        ``&gt;=`` fails to render with TemplateSyntaxError — a seeded copy
        of standard.html would be dead on arrival.
        """
        html = '{% if line.expected_quantity >= 0 %}<p>OK</p>{% endif %}'
        result = sanitize_html(html)
        assert '{% if line.expected_quantity >= 0 %}' in result
        assert '&gt;' not in result
        assert '<p>OK</p>' in result

    def test_preserves_jinja_in_attribute(self):
        html = (
            "<table><tr><td class=\"{% if line.line_status == 'DONE' %}"
            'done{% endif %}">x</td></tr></table>'
        )
        result = sanitize_html(html)
        assert "{% if line.line_status == 'DONE' %}" in result

    def test_preserves_style_tag(self):
        """The built-in layouts carry their CSS in a <style> block; the copy
        must keep it or the printout loses all formatting."""
        html = '<style>.doc-title { color: red; }</style><p class="doc-title">X</p>'
        result = sanitize_html(html)
        assert '<style>.doc-title { color: red; }</style>' in result
        assert '<p class="doc-title">X</p>' in result

    def test_still_strips_script_inside_style_adjacent_content(self):
        html = '<style>p{}</style><script>alert(1)</script><p>ok</p>'
        result = sanitize_html(html)
        assert '<script' not in result
        assert 'alert' not in result
        assert '<style>p{}</style>' in result

    def test_seeded_built_in_copy_renders_without_edits(self):
        """The criterion end to end: a verbatim copy of standard.html
        renders through the sandboxed engine and keeps its structure."""
        from pathlib import Path

        from app.modules.warehouse.document_pdf_service import (
            IssuerContext,
            build_pdf_context,
        )
        from app.modules.warehouse.models import Document, DocumentLine

        templates_dir = (
            Path(__file__).resolve().parents[2]
            / 'app'
            / 'modules'
            / 'warehouse'
            / 'templates'
        )
        source = (templates_dir / 'standard.html').read_text(encoding='utf-8')

        doc = Document(
            organization_id='00000000-0000-0000-0000-000000000001',
            type='IN',
            number='IN/2026/001',
            status='CONFIRMED',
        )
        doc.lines.append(
            DocumentLine(
                name='Example Item',
                quantity=2,
                expected_quantity=2,
                done_quantity=0,
                line_number=1,
            )
        )
        context = build_pdf_context(
            doc,
            None,
            lang='en',
            issuer=IssuerContext(name='Acme Supplies'),
        )
        # The copy is stored verbatim (no source-level sanitizer pass); the
        # render resolves {% include %} from the module templates directory
        # and sanitizes the output.
        html = TemplateEngine(templates_dir=templates_dir).render(source, context)
        assert 'IN/2026/001' in html
        assert 'Acme Supplies' in html
        assert '<style>' in html  # stylesheet survives the render-time pass
        assert 'line-status-pending' in html  # line table loop rendered

    def test_render_sanitizes_output(self):
        """Cleaning at render time still strips markup the template emits.

        ``| safe`` is needed because autoescape already escapes plain
        ``{{ payload }}`` — the sanitizer guards markup that actually
        reaches the output.
        """
        html = TemplateEngine().render(
            '{{ payload | safe }}', {'payload': '<script>alert(1)</script><p>ok</p>'}
        )
        assert '<script' not in html
        assert '<p>ok</p>' in html

    def test_render_keeps_table_loops_intact(self):
        """The regression the render-time move exists for: a Jinja loop inside
        a table must not be foster-parented out of it by the cleaner."""
        tpl = (
            '<table><tbody>'
            '{% for i in items %}<tr><td>{{ i }}</td></tr>{% endfor %}'
            '</tbody></table>'
        )
        html = TemplateEngine().render(tpl, {'items': [1, 2]})
        assert '<td>1</td>' in html
        assert '<td>2</td>' in html


@pytest.mark.integration
class TestTemplateEngine:
    def test_render_simple_template(self):
        engine = TemplateEngine()
        result = engine.render('<p>Hello {{ name }}</p>', {'name': 'World'})
        assert result == '<p>Hello World</p>'

    def test_render_none_returns_empty(self):
        engine = TemplateEngine()
        result = engine.render(None, {})
        assert result == ''

    def test_render_empty_string(self):
        engine = TemplateEngine()
        result = engine.render('', {})
        assert result == ''

    def test_render_uses_autoescape(self):
        engine = TemplateEngine()
        result = engine.render(
            '<p>{{ content }}</p>', {'content': '<script>alert(1)</script>'}
        )
        assert '<script>' not in result
        assert '&lt;script&gt;' in result

    def test_render_with_filter(self):
        engine = TemplateEngine()
        result = engine.render(
            '<p>{{ value | format_qty }}</p>',
            {'value': '1.50'},
        )
        assert '1.5' in result

    def test_render_sandboxed_no_import(self):
        engine = TemplateEngine()
        with pytest.raises((SecurityError, TemplateSyntaxError)):
            engine.render('{% import os %}{{ os }}', {})

    def test_inline_includes_static(self):
        engine = TemplateEngine()
        partials = {
            'header.html': '<h1>Header</h1>',
            'footer.html': '<footer>Foot</footer>',
        }
        result = engine.inline_includes(
            "{% include 'header.html' %}<main>Content</main>{% include 'footer.html' %}",
            partials,
        )
        assert '<h1>Header</h1>' in result
        assert '<footer>Foot</footer>' in result
        assert '{% include' not in result

    def test_inline_includes_missing_partial_removes_tag(self):
        engine = TemplateEngine()
        result = engine.inline_includes("{% include 'missing.html' %}", {})
        assert '{% include' not in result

    def test_inline_includes_nested(self):
        engine = TemplateEngine()
        partials = {
            'outer.html': '{% include "inner.html" %}',
            'inner.html': '<span>Nested</span>',
        }
        result = engine.inline_includes('{% include "outer.html" %}', partials)
        assert '<span>Nested</span>' in result

    def test_render_with_filesystem_loader(self):
        """An include resolves against the family's directory on disk.

        The path used to point at backend/modules/, which has never existed,
        and the test skipped on it; the template it then rendered touched no
        file anyway. The include below lives only in the documents family, so
        an engine that does not read that directory raises TemplateNotFound.
        """
        from pathlib import Path

        templates_dir = (
            Path(__file__).resolve().parents[2]
            / 'app'
            / 'modules'
            / 'warehouse'
            / 'templates'
        )
        assert templates_dir.is_dir(), templates_dir
        engine = TemplateEngine(templates_dir=templates_dir)
        result = engine.render(
            "{% include 'standard/signatures/correction.html' %}",
            {'labels': {'sig_approved': 'Approved by', 'sig_hint': 'sign here'}},
        )
        assert 'Approved by' in result
        assert 'sign here' in result


@pytest.mark.integration
class TestTemplateCRUD:
    @pytest.fixture
    async def org_and_user(self, real_async_db_session):
        import uuid as _uuid

        from app.models.organization import Organization
        from app.models.user import User
        from app.services.auth_service import get_password_hash

        org = Organization(
            name='Template Test Org',
            enabled_modules=['core', 'items', 'locations', 'categories', 'warehouse'],
        )
        real_async_db_session.add(org)
        await real_async_db_session.flush()
        user = User(
            email=f'tpl_test_{_uuid.uuid4().hex[:8]}@example.com',
            hashed_password=get_password_hash('testpassword123'),
            full_name='Template User',
            organization_id=org.id,
            role='admin',
            is_active=True,
        )
        real_async_db_session.add(user)
        await real_async_db_session.flush()
        await real_async_db_session.refresh(org)
        await real_async_db_session.refresh(user)
        return org, user

    async def test_create_template(self, real_async_db_session, org_and_user):
        from app.services.template_crud import create_template_async

        org, user = org_and_user
        tpl = await create_template_async(
            db=real_async_db_session,
            org_id=org.id,
            module='warehouse',
            user_id=user.id,
            name='Test Template',
            body_html='<p>Hello {{ name }}</p>',
            document_type='STANDARD',
        )
        assert tpl.id is not None
        assert tpl.name == 'Test Template'
        assert tpl.module == 'warehouse'

    async def test_list_templates_filtered_by_module(
        self, real_async_db_session, org_and_user
    ):
        from app.services.template_crud import (
            create_template_async,
            list_templates_async,
        )

        org, user = org_and_user
        await create_template_async(
            real_async_db_session,
            org.id,
            'warehouse',
            user.id,
            'Doc Template',
            '<p>Doc</p>',
        )
        await create_template_async(
            real_async_db_session,
            org.id,
            'purchase_orders',
            user.id,
            'PO Template',
            '<p>PO</p>',
        )

        doc_templates = await list_templates_async(
            real_async_db_session, org.id, 'warehouse'
        )
        po_templates = await list_templates_async(
            real_async_db_session, org.id, 'purchase_orders'
        )

        assert len(doc_templates) == 1
        assert len(po_templates) == 1
        assert doc_templates[0].name == 'Doc Template'
        assert po_templates[0].name == 'PO Template'

    async def test_get_template_scoped_to_org(
        self, real_async_db_session, org_and_user
    ):
        from app.services.template_crud import create_template_async, get_template_async

        org, user = org_and_user
        tpl = await create_template_async(
            real_async_db_session,
            org.id,
            'warehouse',
            user.id,
            'Scoped',
            '<p>Test</p>',
        )
        found = await get_template_async(
            real_async_db_session, org.id, tpl.id, 'warehouse'
        )
        assert found is not None
        assert found.name == 'Scoped'

    async def test_get_template_wrong_org_returns_none(self, real_async_db_session):
        from uuid import uuid4

        from app.services.template_crud import get_template_async

        found = await get_template_async(
            real_async_db_session, uuid4(), uuid4(), 'warehouse'
        )
        assert found is None

    async def test_update_template(self, real_async_db_session, org_and_user):
        from app.services.template_crud import (
            create_template_async,
            update_template_async,
        )

        org, user = org_and_user
        tpl = await create_template_async(
            real_async_db_session,
            org.id,
            'warehouse',
            user.id,
            'Original',
            '<p>Original</p>',
        )
        updated = await update_template_async(
            real_async_db_session,
            org.id,
            tpl.id,
            'warehouse',
            name='Updated',
        )
        assert updated.name == 'Updated'

    async def test_delete_template(self, real_async_db_session, org_and_user):
        from app.services.template_crud import (
            create_template_async,
            delete_template_async,
            get_template_async,
        )

        org, user = org_and_user
        tpl = await create_template_async(
            real_async_db_session,
            org.id,
            'warehouse',
            user.id,
            'To Delete',
            '<p>Delete</p>',
        )
        await delete_template_async(real_async_db_session, org.id, tpl.id, 'warehouse')
        found = await get_template_async(
            real_async_db_session, org.id, tpl.id, 'warehouse'
        )
        assert found is None

    async def test_delete_nonexistent_raises(self, real_async_db_session):
        from uuid import uuid4

        from app.services.template_crud import delete_template_async

        with pytest.raises(NotFoundException):
            await delete_template_async(
                real_async_db_session, uuid4(), uuid4(), 'warehouse'
            )

    async def test_create_default_unsets_previous_default(
        self, real_async_db_session, org_and_user
    ):
        from app.services.template_crud import create_template_async

        org, user = org_and_user
        first = await create_template_async(
            real_async_db_session,
            org.id,
            'warehouse',
            user.id,
            'First',
            '<p>1</p>',
            document_type='STANDARD',
            is_default=True,
        )
        assert first.is_default is True

        second = await create_template_async(
            real_async_db_session,
            org.id,
            'warehouse',
            user.id,
            'Second',
            '<p>2</p>',
            document_type='STANDARD',
            is_default=True,
        )
        await real_async_db_session.refresh(first)
        assert first.is_default is False
        assert second.is_default is True

    async def test_seed_default_templates_idempotent(
        self, real_async_db_session, org_and_user
    ):
        from app.services.template_crud import seed_default_templates_async

        org, user = org_and_user
        built_ins = [
            ('Template A', 'STANDARD', '<p>A</p>'),
            ('Template B', 'PL_PZ', '<p>B</p>'),
        ]
        result1 = await seed_default_templates_async(
            real_async_db_session,
            org.id,
            'warehouse',
            user.id,
            built_ins,
        )
        assert len(result1) == 2

        result2 = await seed_default_templates_async(
            real_async_db_session,
            org.id,
            'warehouse',
            user.id,
            built_ins,
        )
        assert len(result2) == 0

    async def test_sanitize_on_create(self, real_async_db_session, org_and_user):
        """The source is stored verbatim; the *rendered* output is cleaned.

        A source-level sanitizer pass reorders HTML around Jinja spans
        (html5lib foster-parenting breaks table loops), so cleaning moved to
        render time — where it cannot mangle the template but still guards
        the output that reaches a browser or the PDF.
        """
        from app.services.template_crud import create_template_async
        from app.services.template_engine import TemplateEngine

        org, user = org_and_user
        tpl = await create_template_async(
            real_async_db_session,
            org.id,
            'warehouse',
            user.id,
            'Unsafe',
            '<p>Hello</p><script>alert(1)</script><img onerror="x" src="a">',
        )
        # Stored verbatim — the author's code, like any source file.
        assert '<script' in tpl.body_html
        assert '<p>Hello</p>' in tpl.body_html

        # Rendered output is sanitized.
        rendered = TemplateEngine().render(tpl.body_html, {})
        assert '<script' not in rendered
        assert 'onerror' not in rendered
        assert '<p>Hello</p>' in rendered


@pytest.mark.asyncio
@pytest.mark.integration
class TestDocumentsTemplateEndpoints:
    @pytest.fixture
    async def doc_fixtures(self, real_async_db_session):
        import uuid as _uuid

        from app.models.organization import Organization
        from app.models.user import User
        from app.services.auth_service import get_password_hash
        from app.services.token_service import create_access_token

        org = Organization(
            name=f'DocTpl Test Org {_uuid.uuid4().hex[:6]}',
            enabled_modules=['core', 'items', 'locations', 'categories', 'warehouse'],
        )
        real_async_db_session.add(org)
        await real_async_db_session.commit()
        await real_async_db_session.refresh(org)

        user = User(
            email=f'doctpl_{_uuid.uuid4().hex[:8]}@example.com',
            hashed_password=get_password_hash('testpassword123'),
            full_name='DocTpl User',
            organization_id=org.id,
            role='admin',
            is_active=True,
        )
        real_async_db_session.add(user)
        await real_async_db_session.commit()
        await real_async_db_session.refresh(user)

        token = create_access_token(data={'sub': str(user.id)})
        headers = {'Authorization': f'Bearer {token}'}
        return org, user, headers

    async def test_crud_cycle(self, real_async_client, doc_fixtures):
        org, user, headers = doc_fixtures

        resp = await real_async_client.post(
            '/api/v1/warehouse/templates',
            json={
                'name': 'My Template',
                'module': 'warehouse',
                'document_type': 'STANDARD',
                'body_html': '<p>{{ document_number }}</p>',
                'is_default': False,
            },
            headers=headers,
        )
        assert resp.status_code == 201
        tpl_id = resp.json()['id']

        resp = await real_async_client.get(
            '/api/v1/warehouse/templates', headers=headers
        )
        assert resp.status_code == 200
        assert len(resp.json()['items']) == 1

        resp = await real_async_client.get(
            f'/api/v1/warehouse/templates/{tpl_id}', headers=headers
        )
        assert resp.status_code == 200
        assert resp.json()['name'] == 'My Template'

        resp = await real_async_client.put(
            f'/api/v1/warehouse/templates/{tpl_id}',
            json={'name': 'Updated Template'},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()['name'] == 'Updated Template'

        resp = await real_async_client.delete(
            f'/api/v1/warehouse/templates/{tpl_id}', headers=headers
        )
        assert resp.status_code == 204

        resp = await real_async_client.get(
            '/api/v1/warehouse/templates', headers=headers
        )
        assert len(resp.json()['items']) == 0

    async def test_seed_defaults(self, real_async_client, doc_fixtures):
        _, _, headers = doc_fixtures

        resp = await real_async_client.post(
            '/api/v1/warehouse/templates/seed-defaults', headers=headers
        )
        assert resp.status_code == 201
        data = resp.json()
        assert len(data) >= 1

        resp2 = await real_async_client.post(
            '/api/v1/warehouse/templates/seed-defaults', headers=headers
        )
        assert len(resp2.json()) == 0

    async def test_placeholders(self, real_async_client, doc_fixtures):
        _, _, headers = doc_fixtures

        resp = await real_async_client.get(
            '/api/v1/warehouse/templates/placeholders', headers=headers
        )
        if resp.status_code != 200:
            pytest.fail(f'Expected 200, got {resp.status_code}: {resp.text}')
        assert len(resp.json()) > 0
        # the catalog mirrors the real render context — the old
        # hand-maintained names ({{document_number}}, {{organization_name}})
        # never matched anything a template could render.
        assert any(p['key'] == '{{doc_title}}' for p in resp.json())
        assert any(p['key'] == '{{partner.name}}' for p in resp.json())
        assert any(p['key'] == '{{issuer.name}}' for p in resp.json())
        assert all('example' in p and 'description' in p for p in resp.json())

    async def test_create_rejects_wrong_module(self, real_async_client, doc_fixtures):
        _, _, headers = doc_fixtures

        resp = await real_async_client.post(
            '/api/v1/warehouse/templates',
            json={
                'name': 'Bad Module',
                'module': 'equipment',
                'body_html': '<p>Test</p>',
            },
            headers=headers,
        )
        assert resp.status_code == 400


@pytest.mark.asyncio
@pytest.mark.integration
class TestPOTemplateEndpoints:
    @pytest.fixture
    async def po_fixtures(self, real_async_db_session):
        import uuid as _uuid

        from app.models.organization import Organization
        from app.models.user import User
        from app.services.auth_service import get_password_hash
        from app.services.token_service import create_access_token

        org = Organization(
            name=f'POTpl Test Org {_uuid.uuid4().hex[:6]}',
            enabled_modules=[
                'core',
                'items',
                'locations',
                'categories',
                'purchase_orders',
                'warehouse',
            ],
        )
        real_async_db_session.add(org)
        await real_async_db_session.commit()
        await real_async_db_session.refresh(org)

        user = User(
            email=f'potpl_{_uuid.uuid4().hex[:8]}@example.com',
            hashed_password=get_password_hash('testpassword123'),
            full_name='PO Tpl User',
            organization_id=org.id,
            role='admin',
            is_active=True,
        )
        real_async_db_session.add(user)
        await real_async_db_session.commit()
        await real_async_db_session.refresh(user)

        token = create_access_token(data={'sub': str(user.id)})
        headers = {'Authorization': f'Bearer {token}'}
        return org, user, headers

    async def test_crud_cycle(self, real_async_client, po_fixtures):
        org, user, headers = po_fixtures

        resp = await real_async_client.post(
            '/api/v1/purchase-orders/templates',
            json={
                'name': 'PO Template',
                'module': 'purchase_orders',
                'document_type': 'STANDARD',
                'body_html': '<p>{{ po_number }}</p>',
                'is_default': False,
            },
            headers=headers,
        )
        assert resp.status_code == 201
        tpl_id = resp.json()['id']

        resp = await real_async_client.get(
            '/api/v1/purchase-orders/templates', headers=headers
        )
        assert resp.status_code == 200
        assert len(resp.json()['items']) == 1

        resp = await real_async_client.delete(
            f'/api/v1/purchase-orders/templates/{tpl_id}', headers=headers
        )
        assert resp.status_code == 204

    async def test_seed_defaults(self, real_async_client, po_fixtures):
        _, _, headers = po_fixtures

        resp = await real_async_client.post(
            '/api/v1/purchase-orders/templates/seed-defaults', headers=headers
        )
        assert resp.status_code == 201
        assert len(resp.json()) >= 1

    async def test_placeholders(self, real_async_client, po_fixtures):
        _, _, headers = po_fixtures

        resp = await real_async_client.get(
            '/api/v1/purchase-orders/templates/placeholders', headers=headers
        )
        assert resp.status_code == 200
        assert any(p['key'] == '{{po_number}}' for p in resp.json())

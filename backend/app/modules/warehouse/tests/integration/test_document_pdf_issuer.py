"""document printouts carry the issuer identity.

The built-in templates never referenced the issuing organization — a
warehouse document without the issuer's name, tax ID, address and logo
cannot circulate outside the app in any country. The issuer data lives on
``Organization`` (one copy for every print family), is folded into the
render context, and the templates print it as a letterhead block. Missing
data renders an empty block, never a placeholder text or a crash.
"""

import asyncio
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.print_identity import IssuerContext, build_issuer_context
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.warehouse.document_pdf_service import (
    _svc,
    build_pdf_context,
)
from app.modules.warehouse.models import Document, DocumentStatus


def _render(template_name: str, context: dict[str, Any]) -> str:
    """Render a built-in template with a context — no WeasyPrint needed."""
    return _svc.render_filesystem_template(template_name, context)


@pytest.mark.integration
class TestIssuerContext:
    """Building the issuer context from the organization."""

    def test_from_organization_folds_country_into_address(
        self, db_session: Session, doc_org: Organization
    ) -> None:
        """The country lives in the ISO column; the address string ends with
        the localised country name instead of a free-text duplicate."""
        doc_org.tax_id = 'PL1234567890'
        doc_org.country = 'PL'
        doc_org.address = {'street': 'Warehouse St 1', 'city': 'Warsaw'}
        db_session.commit()

        ctx = IssuerContext.from_organization(doc_org, lang='en')

        assert ctx.name == doc_org.name
        assert ctx.tax_id == 'PL1234567890'
        assert ctx.address is not None
        assert 'Warehouse St 1' in ctx.address
        assert 'Warsaw' in ctx.address
        assert ctx.address.endswith('Poland')
        assert ctx.logo is None

    def test_from_organization_empty_is_empty(
        self, db_session: Session, doc_org: Organization
    ) -> None:
        doc_org.tax_id = None
        doc_org.country = None
        doc_org.address = None
        db_session.commit()

        ctx = IssuerContext.from_organization(doc_org, lang='en')

        assert ctx.name == doc_org.name  # org always has a name
        assert ctx.tax_id is None
        assert ctx.address is None
        assert ctx.logo is None

    def test_from_organization_none_is_safe(self) -> None:
        ctx = IssuerContext.from_organization(None, lang='en')
        assert ctx.name is None
        assert ctx.tax_id is None
        assert ctx.address is None
        assert ctx.logo is None


@pytest.mark.integration
class TestIssuerInTemplates:
    """Both built-in families print the issuer block."""

    def test_standard_prints_issuer_fields(
        self, db_session: Session, doc_org: Organization, doc_draft_pz: Document
    ) -> None:
        doc_org.tax_id = 'PL1234567890'
        doc_org.country = 'DE'
        doc_org.address = {'street': 'Lagerstr. 1', 'city': 'Berlin'}
        db_session.commit()

        issuer = IssuerContext.from_organization(doc_org, lang='en')
        context = build_pdf_context(doc_draft_pz, None, lang='en', issuer=issuer)
        html = _render('standard.html', context)

        assert doc_org.name in html
        assert 'PL1234567890' in html
        assert 'Lagerstr. 1' in html
        assert 'Berlin' in html
        assert 'Germany' in html

    def test_pl_pz_prints_issuer_fields(
        self, db_session: Session, doc_org: Organization, doc_draft_pz: Document
    ) -> None:
        doc_org.tax_id = 'PL1234567890'
        doc_org.country = 'PL'
        doc_org.address = {'street': 'Magazynowa 5', 'city': 'Warszawa'}
        db_session.commit()

        # pl_pz renders in Polish regardless of the UI language.
        issuer = IssuerContext.from_organization(doc_org, lang='en')
        context = build_pdf_context(doc_draft_pz, None, lang='en', issuer=issuer)
        html = _render('pl_pz.html', context)

        assert doc_org.name in html
        assert 'PL1234567890' in html
        assert 'Magazynowa 5' in html
        assert 'Warszawa' in html
        assert 'Poland' in html or 'Polska' in html

    def test_an_organizations_copy_of_pl_pz_prints_in_one_language(
        self,
        monkeypatch: pytest.MonkeyPatch,
        doc_org: Organization,
        doc_draft_pz: Document,
    ) -> None:
        """A copy of PL PZ prints through the user-template path, which
        follows the UI language — the header came out in English above a
        body written in Polish. The layout declares its language, and the
        whole sheet follows it."""
        from pathlib import Path

        from app.core.pdf_base_service import PdfServiceBase
        from app.modules.warehouse import document_pdf_service

        body = (
            Path(document_pdf_service.__file__).parent / 'templates' / 'pl_pz.html'
        ).read_text(encoding='utf-8')
        monkeypatch.setattr(
            PdfServiceBase, 'render_to_pdf', staticmethod(lambda html: html.encode())
        )

        html = asyncio.run(
            document_pdf_service.generate_pdf_async(
                doc_draft_pz,
                None,
                lang='en',
                organization=doc_org,
                user_template_html=body,
            )
        ).decode()

        assert 'Nazwa towaru' in html
        assert 'Przyjęcie Zewnętrzne' in html
        assert 'Goods Receipt' not in html

    def test_missing_issuer_data_prints_empty_block(
        self, db_session: Session, doc_org: Organization, doc_draft_pz: Document
    ) -> None:
        """No data → empty space, no placeholder text, no crash."""
        doc_org.tax_id = None
        doc_org.country = None
        doc_org.address = None
        db_session.commit()

        context = build_pdf_context(doc_draft_pz, None, lang='en')
        for template_name in ('standard.html', 'pl_pz.html'):
            html = _render(template_name, context)
            assert 'Warehouse St 1' not in html  # no phantom values
            assert 'PL1234567890' not in html

    def test_pdf_generates_with_issuer(
        self, db_session: Session, doc_org: Organization, doc_draft_pz: Document
    ) -> None:
        """End-to-end smoke: WeasyPrint accepts the issuer block."""
        from app.modules.warehouse.document_pdf_service import generate_pdf_async

        doc_org.tax_id = 'PL1234567890'
        doc_org.country = 'PL'
        doc_org.address = {'street': 'Magazynowa 5', 'city': 'Warszawa'}
        db_session.commit()

        pdf = asyncio.run(
            generate_pdf_async(doc_draft_pz, None, lang='en', organization=doc_org)
        )
        assert pdf.startswith(b'%PDF')


@pytest.mark.integration
class TestIssuerLogo:
    """The logo is embedded server-side as a data URI."""

    async def test_logo_is_embedded_as_data_uri(
        self, real_async_db_session: AsyncSession, async_test_user: User
    ) -> None:
        from app.core.public_api import core_api

        db = real_async_db_session
        org = async_test_user.organization
        # 1x1 transparent PNG.
        png = (
            b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
            b'\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01'
            b'\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
        )
        path = await core_api.file_storage.save_for_org_async(
            org.id, 'organizations', 'logo.png', png, 'image/png'
        )
        org.logo_url = path
        await db.commit()

        ctx = await build_issuer_context(org, lang='en')

        assert ctx.logo is not None
        assert ctx.logo.startswith('data:image/png;base64,')

    async def test_missing_logo_file_degrades_gracefully(
        self, real_async_db_session: AsyncSession, async_test_user: User
    ) -> None:
        db = real_async_db_session
        org = async_test_user.organization
        org.logo_url = f'{org.id}/organizations/logo.png'  # never saved
        await db.commit()

        ctx = await build_issuer_context(org, lang='en')

        assert ctx.logo is None


@pytest.mark.integration
class TestIssuerInDocumentList:
    """The context keys the placeholders catalog will expose."""

    def test_context_carries_issuer_key(
        self, db_session: Session, doc_draft_pz: Document
    ) -> None:
        context = build_pdf_context(doc_draft_pz, None, lang='en')
        assert 'issuer' in context
        assert isinstance(context['issuer'], IssuerContext)
        # DRAFT document context is intact after the refactor.
        assert context['doc_variant'] == 'external_in'
        assert doc_draft_pz.status == DocumentStatus.DRAFT.value


@pytest.mark.integration
class TestUserTemplatePrinting:
    """The organization's own template replaces the built-in family.

    The templates screen promises "copy a built-in to change the printout";
    the promise used to be hollow — generate_pdf rendered only the
    filesystem file and ``default_template_id`` was never read.
    """

    @staticmethod
    def _extract_pdf_text(pdf_bytes: bytes) -> str:
        from io import BytesIO

        from pypdf import PdfReader

        reader = PdfReader(BytesIO(pdf_bytes))
        return '\n'.join(page.extract_text() or '' for page in reader.pages)

    def test_user_template_replaces_builtin_on_printout(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        # A template with a distinctive marker.
        created = client.post(
            '/api/v1/warehouse/templates',
            headers=doc_auth_headers,
            json={
                'name': 'Custom Layout',
                'module': 'warehouse',
                'document_type': 'STANDARD',
                'body_html': (
                    '<html><body><style>h1 { color: red; }</style>'
                    '<h1>CUSTOMLAYOUTMARKER</h1>'
                    '<p>{{ doc_title }} {{ document.number }}</p>'
                    '</body></html>'
                ),
                'is_default': False,
            },
        )
        assert created.status_code == 201, created.text
        tpl_id = created.json()['id']

        # Select it on the profile.
        resp = client.put(
            '/api/v1/warehouse/profile',
            headers=doc_auth_headers,
            json={'default_template_id': tpl_id},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()['default_template_id'] == tpl_id

        # A confirmed document prints through the user template.
        doc = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 5,
                    }
                ],
            },
        )
        doc_id = doc.json()['id']
        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )

        pdf = client.get(
            f'/api/v1/warehouse/documents/{doc_id}/pdf', headers=doc_auth_headers
        )
        assert pdf.status_code == 200
        text = self._extract_pdf_text(pdf.content)
        # pypdf may split a word across lines inside the PDF — compare
        # whitespace-normalized.
        flat = ' '.join(text.split())
        assert 'CUSTOMLAYOUTMARKER' in flat, text
        assert 'IN/2026/001' in flat

    def test_builtin_family_used_without_user_template(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        """No default_template_id → the preset family prints as before."""
        resp = client.put(
            '/api/v1/warehouse/profile',
            headers=doc_auth_headers,
            json={'default_template_id': None},
        )
        assert resp.status_code == 200

        doc = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 5,
                    }
                ],
            },
        )
        doc_id = doc.json()['id']
        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )

        pdf = client.get(
            f'/api/v1/warehouse/documents/{doc_id}/pdf', headers=doc_auth_headers
        )
        assert pdf.status_code == 200
        text = self._extract_pdf_text(pdf.content)
        assert 'CUSTOMLAYOUTMARKER' not in text
        # The built-in family still prints its title.
        assert 'IN/2026/001' in text

    def test_seeded_copy_prints_unchanged(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        """Through the print path: a seeded copy of the built-in layout,
        selected on the profile, prints like the built-in — including its
        stylesheet (regression guard)."""
        seeded = client.post(
            '/api/v1/warehouse/templates/seed-defaults',
            headers=doc_auth_headers,
        )
        assert seeded.status_code == 201
        templates = client.get(
            '/api/v1/warehouse/templates', headers=doc_auth_headers
        ).json()['items']
        # By name: the built-ins also hold the packing slip, which lays out
        # packages rather than the document.
        tpl_id = next(t['id'] for t in templates if t['name'] == 'Standard Template')

        client.put(
            '/api/v1/warehouse/profile',
            headers=doc_auth_headers,
            json={'default_template_id': tpl_id},
        )

        doc = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 5,
                    }
                ],
            },
        )
        doc_id = doc.json()['id']
        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )

        pdf = client.get(
            f'/api/v1/warehouse/documents/{doc_id}/pdf', headers=doc_auth_headers
        )
        assert pdf.status_code == 200
        text = self._extract_pdf_text(pdf.content)
        assert 'IN/2026/001' in text

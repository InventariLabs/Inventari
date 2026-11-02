"""The paper a printout goes on is the organization's, not the layout's.

Every PDF template opened with ``@page { size: A4 }`` and no door to change
it, so a customer outside Europe — the US, Canada, Mexico — printed on
paper their tray does not hold, on every surface at once: warehouse
documents, purchase orders, equipment protocols and the stock-on-a-day
report.

Paper size is a property of the printer standing in the office, not of the
document type, so it belongs to the organization: the country answers by
default, and an organization that prints differently than its country says
so explicitly. The measurement reads the page box out of the generated PDF
— a gate that grepped template text would only ever check a literal.

A template saved in the database before the change still carries a baked-in
``size: A4``; the organization's answer is applied after the body is
rendered, so saved layouts follow the organization too.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4

from httpx import AsyncClient
from pypdf import PdfReader
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import StockAsOfReportDTO, StockAsOfRowDTO
from app.core.print_page_size import apply_page_size, page_size_of
from app.core.testing import ModuleTestHelper
from app.models.item import Item
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.user import User
from app.modules.equipment.models import EquipmentAssignment
from app.modules.equipment.protocol_service import render_protocol_pdf_async
from app.modules.purchase_orders.models import PurchaseOrder
from app.modules.purchase_orders.po_pdf_service import generate_po_pdf
from app.modules.warehouse.document_pdf_service import generate_pdf_async
from app.modules.warehouse.models import Document, DocumentLine
from app.modules.warehouse.models.profile import DocumentProfile
from app.services.stock_report_pdf_service import generate_stock_as_of_pdf
from app.services.token_service import create_access_token

#: PostScript points, as WeasyPrint writes them into the MediaBox.
_A4_PT = (595.3, 841.9)
_LETTER_PT = (612.0, 792.0)

#: A body copied into the database before the change — the page size was
#: part of what a copy took with it, so old copies still say A4 outright.
_OLD_SAVED_BODY = """<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8" />
<style>@page { size: A4; margin: 15mm; }</style>
</head>
<body><p>{{ print_number }}</p></body>
</html>
"""


def _page_box(pdf: bytes) -> tuple[float, float]:
    page = PdfReader(BytesIO(pdf)).pages[0]
    return round(float(page.mediabox.width), 1), round(float(page.mediabox.height), 1)


def _assert_paper(pdf: bytes, expected: tuple[float, float], surface: str) -> None:
    box = _page_box(pdf)
    assert all(abs(a - b) <= 0.6 for a, b in zip(box, expected, strict=True)), (
        f'{surface}: expected {expected} pt, the PDF says {box} pt'
    )


def _auth(user: User) -> dict[str, str]:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


async def _an_org(
    db: AsyncSession,
    *,
    country: str | None,
    print_page_size: str | None = None,
) -> tuple[Organization, User]:
    org = Organization(
        name=f'Paper {uuid4().hex[:6]}',
        enabled_modules=[
            'core',
            'items',
            'locations',
            'warehouse',
            'purchase_orders',
            'equipment',
        ],
        country=country,
        print_page_size=print_page_size,
    )
    db.add(org)
    await db.commit()
    await db.refresh(org)
    # The page-size column is deferred; the render paths read it off this
    # instance, so it arrives loaded — the way the production DTO does.
    await db.refresh(org, ['print_page_size'])
    user = await ModuleTestHelper.create_user_async(
        db, org, email=f'paper_{uuid4().hex[:8]}@test.com'
    )
    await db.commit()
    return org, user


async def _a_document(db: AsyncSession, org: Organization, user: User) -> Document:
    """One draft receipt with one line — enough ink to fill a page box."""
    template = ProductTemplate(name=f'Flour {uuid4().hex[:6]}', organization_id=org.id)
    db.add(template)
    await db.flush()

    doc = Document(
        organization_id=org.id,
        type='IN',
        number=f'IN/{uuid4().hex[:6]}',
        status='DRAFT',
        created_by=user.id,
    )
    doc.lines.append(
        DocumentLine(
            product_template_id=template.id,
            quantity=Decimal('5'),
            expected_quantity=Decimal('5'),
            done_quantity=Decimal('0'),
            line_number=1,
        )
    )
    db.add(doc)
    await db.commit()
    # generate_pdf reads the whole relationship fan-out synchronously inside
    # a thread, so the instance arrives with every branch already loaded.
    await db.refresh(
        doc,
        [
            'lines',
            'partner',
            'source_location',
            'target_location',
            'corrected_document',
        ],
    )
    return doc


def _a_report() -> StockAsOfReportDTO:
    return StockAsOfReportDTO(
        as_of=datetime(2026, 9, 30, tzinfo=UTC),
        generated_at=datetime(2026, 10, 2, tzinfo=UTC),
        complete_from=datetime(2026, 1, 1, tzinfo=UTC),
        organization_name='Whatever Warehouse',
        currency='USD',
        items=[
            StockAsOfRowDTO(
                product_template_id=uuid4(),
                product_name='Rye flour',
                uom_symbol='kg',
                quantity=Decimal('20'),
                value=Decimal('60'),
            )
        ],
        total_value=Decimal('60'),
    )


async def _render_every_surface(
    db: AsyncSession, *, country: str | None, print_page_size: str | None = None
) -> dict[str, bytes]:
    """One PDF per print family — all six layouts the app ships with."""
    org, user = await _an_org(db, country=country, print_page_size=print_page_size)
    doc = await _a_document(db, org, user)

    surfaces: dict[str, bytes] = {}
    surfaces['warehouse document (standard)'] = await generate_pdf_async(
        doc, None, lang='en', organization=org
    )

    pl_pz_profile = DocumentProfile(
        organization_id=org.id, name='Receipt layout', print_template='pl_pz'
    )
    db.add(pl_pz_profile)
    await db.commit()
    surfaces['warehouse document (pl_pz)'] = await generate_pdf_async(
        doc, pl_pz_profile, lang='en', organization=org
    )

    po = PurchaseOrder(
        organization_id=org.id,
        number=f'PO/{uuid4().hex[:6]}',
        status='DRAFT',
        created_by=user.id,
    )
    db.add(po)
    await db.commit()
    await db.refresh(po, ['lines', 'partner'])
    po.organization = org
    surfaces['purchase order'] = await generate_po_pdf(
        po, lang='en', db=db, org_id=org.id
    )

    storage_type = StorageType(
        name='Shelf', type_code=f'SHELF_{uuid4().hex[:6]}', behavior_mode='NONE'
    )
    db.add(storage_type)
    await db.flush()
    location = StorageLocation(
        name='Aisle 1',
        organization_id=org.id,
        storage_type_id=storage_type.id,
        created_by=user.id,
    )
    db.add(location)
    await db.flush()
    asset = Item(
        organization_id=org.id,
        storage_location_id=location.id,
        name='Laptop',
        quantity=1,
    )
    db.add(asset)
    await db.flush()
    checkout = EquipmentAssignment(
        organization_id=org.id,
        item_id=asset.id,
        assigned_to_name='Robin',
        checked_out_by=user.id,
    )
    checkin = EquipmentAssignment(
        organization_id=org.id,
        item_id=asset.id,
        assigned_to_name='Robin',
        checked_out_by=user.id,
        checked_in_at=datetime.now(UTC),
        checked_in_by=user.id,
    )
    db.add_all([checkout, checkin])
    await db.commit()
    surfaces['equipment protocol (checkout)'] = await render_protocol_pdf_async(
        db, org.id, checkout.id, lang='en'
    )
    surfaces['equipment protocol (checkin)'] = await render_protocol_pdf_async(
        db, org.id, checkin.id, lang='en'
    )

    surfaces['stock-on-a-day report'] = await generate_stock_as_of_pdf(
        _a_report(), org, lang='en'
    )
    return surfaces


class TestEveryPrintFamily:
    """Both papers, both countries, all six surfaces, one test."""

    async def test_the_organization_decides_for_every_surface(
        self, real_async_db_session: AsyncSession
    ) -> None:
        db = real_async_db_session
        for country, expected in (('US', _LETTER_PT), ('PL', _A4_PT)):
            surfaces = await _render_every_surface(db, country=country)
            assert len(surfaces) == 6, 'the app ships six print surfaces'
            for surface, pdf in surfaces.items():
                _assert_paper(pdf, expected, f'{surface} · country={country}')

    async def test_an_explicit_override_wins_over_the_country(
        self, real_async_db_session: AsyncSession
    ) -> None:
        db = real_async_db_session
        # A Polish organization whose office printer holds Letter.
        surfaces = await _render_every_surface(
            db, country='PL', print_page_size='letter'
        )
        for surface, pdf in surfaces.items():
            _assert_paper(pdf, _LETTER_PT, f'{surface} · PL printing Letter')
        # An American one that bought A4 paper anyway.
        surfaces = await _render_every_surface(db, country='US', print_page_size='a4')
        for surface, pdf in surfaces.items():
            _assert_paper(pdf, _A4_PT, f'{surface} · US printing A4')


class TestSavedTemplates:
    """A layout saved before the change still says A4 in its body."""

    async def test_a_saved_body_with_a_baked_in_a4_follows_the_organization(
        self, real_async_db_session: AsyncSession
    ) -> None:
        db = real_async_db_session
        org, user = await _an_org(db, country='US')
        doc = await _a_document(db, org, user)

        pdf = await generate_pdf_async(
            doc,
            None,
            lang='en',
            organization=org,
            user_template_html=_OLD_SAVED_BODY,
        )
        _assert_paper(pdf, _LETTER_PT, 'saved template with a baked-in A4')


class TestTheOverrideIsSettable:
    """The organization is where an administrator says which paper it has."""

    async def test_the_endpoint_takes_the_override(
        self,
        real_async_db_session: AsyncSession,
        real_async_client: AsyncClient,
    ) -> None:
        # A committed org and admin of my own — the endpoint reads through
        # its own connection, so an uncommitted fixture user is nobody.
        org, user = await _an_org(
            real_async_db_session, country='PL', print_page_size='a4'
        )
        response = await real_async_client.put(
            '/api/v1/organizations',
            json={'print_page_size': 'letter'},
            headers=_auth(user),
        )
        assert response.status_code == 200, response.text
        assert response.json()['print_page_size'] == 'letter'

        refused = await real_async_client.put(
            '/api/v1/organizations',
            json={'print_page_size': 'tabloid'},
            headers=_auth(user),
        )
        assert refused.status_code == 422


class TestPageResolution:
    """The one place that answers 'which paper does this org print on?'."""

    def test_the_country_answers_by_default(self) -> None:
        for country in ('US', 'CA', 'MX'):
            assert (
                page_size_of(SimpleNamespace(country=country, print_page_size=None))
                == 'letter'
            )
        for country in ('PL', 'DE', 'JP'):
            assert (
                page_size_of(SimpleNamespace(country=country, print_page_size=None))
                == 'a4'
            )

    def test_no_country_is_a4(self) -> None:
        assert page_size_of(SimpleNamespace(country=None, print_page_size=None)) == 'a4'
        assert page_size_of(None) == 'a4'

    def test_the_override_wins(self) -> None:
        org = SimpleNamespace(country='US', print_page_size='a4')
        assert page_size_of(org) == 'a4'

    def test_apply_puts_the_rule_after_the_body(self) -> None:
        html = apply_page_size('<html><body><p>x</p></body></html>', 'letter')
        assert html.index('</body>') > html.index('@page')
        assert 'Letter' in html

    def test_apply_appends_when_there_is_no_body_tag(self) -> None:
        html = apply_page_size('<p>x</p>', 'a4')
        assert '@page' in html and 'A4' in html

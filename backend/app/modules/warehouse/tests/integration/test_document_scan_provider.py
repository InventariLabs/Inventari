"""76: document numbers printed on PDFs resolve through the scan chain.

The PDF printout carries ``document.number`` in Code128 and QR
(``document_pdf_service``); before this feature no provider in the scan
registry understood document numbers, so the code fell through every
provider and the API answered 404 — with a *label* message. The module's
provider claims broadly and the ``(organization_id, number)`` lookup decides:
a miss returns None and the code keeps flowing (product barcodes, OFF, …).
"""

from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserContextDTO
from app.core.scan_registry import scan_registry
from app.models.organization import Organization
from app.models.user import User
from app.modules.warehouse._document_scan_provider import DocumentScanProvider
from app.modules.warehouse.models import Document, DocumentStatus
from app.services.auth_service import get_password_hash
from app.services.token_service import create_access_token


def _auth(user: User) -> dict[str, str]:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


def _ctx(user: User) -> UserContextDTO:
    """The scan chain receives a context DTO, not the ORM user."""
    return UserContextDTO(
        id=user.id, organization_id=user.organization_id, role='admin'
    )


async def _make_org(db: AsyncSession, name: str, modules: list[str]) -> Organization:
    org = Organization(name=name, enabled_modules=modules)
    db.add(org)
    await db.commit()
    await db.refresh(org)
    return org


async def _make_user(db: AsyncSession, org: Organization) -> User:
    user = User(
        email=f'scan_{uuid4().hex[:8]}@test.com',
        hashed_password=get_password_hash('pass'),
        full_name='Scan User',
        organization_id=org.id,
        role='admin',
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _make_document(
    db: AsyncSession,
    org: Organization,
    user: User,
    *,
    number: str = 'IN/2026/001',
    status: str = DocumentStatus.DRAFT.value,
) -> Document:
    doc = Document(
        organization_id=org.id,
        type='IN',
        number=number,
        status=status,
        created_by=user.id,
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)
    return doc


@pytest.mark.integration
class TestDocumentScanProvider:
    """The provider itself: broad claim, org-scoped lookup, safe fallthrough."""

    async def test_handle_draft_document_returns_continuation(
        self, real_async_db_session: AsyncSession
    ) -> None:
        db = real_async_db_session
        org = await _make_org(
            db,
            'Doc Scan Org',
            ['core', 'items', 'locations', 'categories', 'warehouse'],
        )
        user = await _make_user(db, org)
        doc = await _make_document(db, org, user)

        result = await DocumentScanProvider().handle(
            doc.number,
            _ctx(user),
            db,
        )

        assert result is not None
        assert result.status == 'document'
        assert result.action == 'open_document'
        assert result.label_code == doc.number
        assert result.document == {
            'id': str(doc.id),
            'number': doc.number,
            'status': 'DRAFT',
            'type': 'IN',
        }
        # An in-progress document opens straight into continuation.
        assert result.document_mode == 'continue'

    async def test_handle_completed_document_returns_preview(
        self, real_async_db_session: AsyncSession
    ) -> None:
        db = real_async_db_session
        org = await _make_org(
            db,
            'Doc Scan Org',
            ['core', 'items', 'locations', 'categories', 'warehouse'],
        )
        user = await _make_user(db, org)
        await _make_document(db, org, user, status=DocumentStatus.COMPLETED.value)

        result = await DocumentScanProvider().handle(
            'IN/2026/001',
            _ctx(user),
            db,
        )

        assert result is not None
        assert result.document_mode == 'preview'

    async def test_handle_confirmed_executable_document_returns_execute(
        self, real_async_db_session: AsyncSession
    ) -> None:
        """A CONFIRMED IN/OUT document is floor work — the scan of its
        printout opens the receiving/picking flow, not a passive preview."""
        db = real_async_db_session
        org = await _make_org(
            db,
            'Doc Scan Org',
            ['core', 'items', 'locations', 'categories', 'warehouse'],
        )
        user = await _make_user(db, org)
        await _make_document(db, org, user, status=DocumentStatus.CONFIRMED.value)

        result = await DocumentScanProvider().handle(
            'IN/2026/001',
            _ctx(user),
            db,
        )

        assert result is not None
        assert result.document_mode == 'execute'

    async def test_handle_confirmed_non_executable_document_returns_preview(
        self, real_async_db_session: AsyncSession
    ) -> None:
        """A CONFIRMED CORRECTION has no floor flow — plain preview."""
        db = real_async_db_session
        org = await _make_org(
            db,
            'Doc Scan Org',
            ['core', 'items', 'locations', 'categories', 'warehouse'],
        )
        user = await _make_user(db, org)
        doc = await _make_document(
            db,
            org,
            user,
            number='COR/2026/001',
            status=DocumentStatus.CONFIRMED.value,
        )
        doc.type = 'CORRECTION'
        await db.commit()

        result = await DocumentScanProvider().handle(
            'COR/2026/001',
            _ctx(user),
            db,
        )

        assert result is not None
        assert result.document_mode == 'preview'

    async def test_handle_unknown_number_returns_none(
        self, real_async_db_session: AsyncSession
    ) -> None:
        db = real_async_db_session
        org = await _make_org(
            db,
            'Doc Scan Org',
            ['core', 'items', 'locations', 'categories', 'warehouse'],
        )
        user = await _make_user(db, org)

        result = await DocumentScanProvider().handle(
            'IN/2026/999',
            _ctx(user),
            db,
        )

        # A miss must fall through (None), not claim the code — the registry
        # then hands it to the next provider (product barcode, OFF, …).
        assert result is None

    async def test_handle_module_disabled_returns_none(
        self, real_async_db_session: AsyncSession
    ) -> None:
        """With the warehouse module off, the code falls through quietly."""
        db = real_async_db_session
        org = await _make_org(
            db, 'No Docs Org', ['core', 'items', 'locations', 'categories']
        )
        user = await _make_user(db, org)

        result = await DocumentScanProvider().handle(
            'IN/2026/001',
            _ctx(user),
            db,
        )

        assert result is None

    async def test_handle_foreign_org_document_returns_none(
        self, real_async_db_session: AsyncSession
    ) -> None:
        """A document of another org must not leak."""
        db = real_async_db_session
        org = await _make_org(
            db,
            'Doc Scan Org',
            ['core', 'items', 'locations', 'categories', 'warehouse'],
        )
        user = await _make_user(db, org)
        other_org = await _make_org(
            db,
            'Other Org',
            ['core', 'items', 'locations', 'categories', 'warehouse'],
        )
        other_user = await _make_user(db, other_org)
        await _make_document(db, other_org, other_user, number='IN/2026/007')

        result = await DocumentScanProvider().handle(
            'IN/2026/007',
            _ctx(user),
            db,
        )

        assert result is None


@pytest.mark.integration
class TestDocumentScanThroughRegistry:
    """End-to-end through the real registry and HTTP API."""

    async def test_provider_registered_with_priority_30(
        self, real_async_db_session: AsyncSession
    ) -> None:
        """The module registers its own provider; Core does not know documents."""
        providers = [
            provider.__class__.__name__
            for provider, priority in scan_registry._providers
            if priority == 30
        ]
        assert 'DocumentScanProvider' in providers

    async def test_document_number_resolves_through_registry(
        self, real_async_db_session: AsyncSession
    ) -> None:
        """The number a PDF prints (document.number) finds its document.

        ``document_pdf_service`` embeds exactly ``document.number`` in both
        the Code128 and the QR of the printout — this is that value coming
        back in through the scan chain.
        """
        db = real_async_db_session
        org = await _make_org(
            db,
            'Doc Scan Org',
            ['core', 'items', 'locations', 'categories', 'warehouse'],
        )
        user = await _make_user(db, org)
        doc = await _make_document(db, org, user)

        result = await scan_registry.scan(
            doc.number,
            _ctx(user),
            db,
        )

        assert result is not None
        assert result.status == 'document'
        assert result.document['id'] == str(doc.id)

    async def test_pure_digit_numbering_does_not_break_barcode_scan(
        self, real_async_db_session: AsyncSession
    ) -> None:
        """A digit-only numbering_format must not swallow product barcodes.

               The org numbers documents as pure digits ('{SEQ:010d}' → e.g.
               '0000000001'). A product barcode with the same value, where no
               document exists with that number, must still resolve to the product:
               the document lookup misses and the code flows to the barcode
        provider.
        """
        from datetime import date, timedelta

        from app.models.category import Category
        from app.models.item import Item
        from app.models.storage_location import LocationUsage, StorageLocation
        from app.models.storage_type import StorageType

        db = real_async_db_session
        org = await _make_org(
            db, 'Digit Org', ['core', 'items', 'locations', 'categories', 'warehouse']
        )
        user = await _make_user(db, org)

        storage_type = StorageType(
            name='Warehouse', type_code='WAREHOUSE', behavior_mode='NONE'
        )
        db.add(storage_type)
        await db.flush()
        storage = StorageLocation(
            organization_id=org.id,
            created_by=user.id,
            storage_type_id=storage_type.id,
            name='Shelf A',
            short_code=f'LOC-{uuid4().hex[:8].upper()}',
            usage=LocationUsage.INTERNAL,
        )
        db.add(storage)
        category = Category(name='Dry Goods', icon='📦')
        db.add(category)
        await db.flush()
        item = Item(
            organization_id=org.id,
            storage_location_id=storage.id,
            category_id=category.id,
            name='Digit Product',
            barcode='0000000001',
            quantity=2,
            expiry_date=date.today() + timedelta(days=30),
        )
        db.add(item)
        await db.commit()

        # No document exists with number '0000000001' — the lookup must miss
        # and the code must land on the product, not on a document.
        result = await scan_registry.scan(
            '0000000001',
            _ctx(user),
            db,
        )

        assert result is not None
        assert result.status == 'product_stock'
        assert result.action == 'show_stock_actions'

    async def test_scan_api_404_distinguishes_unrecognized_code(
        self, real_async_client: AsyncClient, real_async_db_session: AsyncSession
    ) -> None:
        """a code no provider claims must not be called a label."""
        db = real_async_db_session
        org = await _make_org(
            db,
            'Doc Scan Org',
            ['core', 'items', 'locations', 'categories', 'warehouse'],
        )
        user = await _make_user(db, org)

        response = await real_async_client.get(
            '/api/v1/labels/scan/ZZZ-NOT-LABEL', headers=_auth(user)
        )

        assert response.status_code == 404
        body = response.json()['detail']
        assert body['code'] == 'SCAN_UNRECOGNIZED'
        # The message talks about the code, not about a label.
        assert body['message'].startswith('Code not recognized')

    async def test_scan_api_404_label_format_miss_is_unrecognized(
        self, real_async_client: AsyncClient, real_async_db_session: AsyncSession
    ) -> None:
        """a label-shaped miss is also a SKU or barcode miss: the search is offered."""
        db = real_async_db_session
        org = await _make_org(
            db,
            'Doc Scan Org',
            ['core', 'items', 'locations', 'categories', 'warehouse'],
        )
        user = await _make_user(db, org)

        response = await real_async_client.get(
            '/api/v1/labels/scan/STM-NOTFOUND', headers=_auth(user)
        )

        assert response.status_code == 404
        body = response.json()['detail']
        assert body['code'] == 'SCAN_UNRECOGNIZED'

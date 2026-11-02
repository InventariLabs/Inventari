"""Fixtures for warehouse module integration tests."""

import uuid
from decimal import Decimal

import pytest
from fastapi import status
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.testing import ModuleTestHelper
from app.models.item import Item
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.stock_valuation_layer import (
    StockValuationLayer,  # noqa: F401 - ensure table is registered
)
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.uom import Uom
from app.models.user import User
from app.modules.approvals.models import ApprovalWorkflow
from app.modules.warehouse.models import Document, DocumentLine, DocumentStatus
from tests.integration._shelf import (
    put_on_shelf,
    run_in_async_session,
    shelf_keeper,
)


@pytest.fixture
def h(db_session: Session) -> ModuleTestHelper:
    return ModuleTestHelper(db_session)


@pytest.fixture
def doc_org(h: ModuleTestHelper) -> Organization:
    org = h.create_org(
        'Documents Test Org',
        ['core', 'items', 'locations', 'categories', 'warehouse', 'approvals'],
    )
    # One user raises and decides in these scenarios; admin self-approval is
    # an organization setting since, off by default.
    h.set_module_settings(org, 'approvals', {'allow_admin_self_approve': True})
    return org


@pytest.fixture
def doc_user(h: ModuleTestHelper, doc_org: Organization) -> User:
    return h.create_user(doc_org, email='documents@example.com')


@pytest.fixture
def doc_auth_headers(h: ModuleTestHelper, doc_user: User) -> dict[str, str]:
    return h.get_auth_headers(doc_user)


@pytest.fixture
def doc_storage_type(h: ModuleTestHelper, doc_org: Organization) -> StorageType:
    # Owned by the organization: storage types have a tenant since, and
    # a putaway rule may only name one of its own organization's types.
    return h.create_storage_type('Warehouse', 'WAREHOUSE', organization_id=doc_org.id)


@pytest.fixture
def doc_source_location(
    h: ModuleTestHelper,
    doc_org: Organization,
    doc_storage_type: StorageType,
    doc_user: User,
) -> StorageLocation:
    return h.create_storage_location(
        doc_org, doc_storage_type, doc_user, name='Source Warehouse'
    )


@pytest.fixture
def doc_target_location(
    h: ModuleTestHelper,
    doc_org: Organization,
    doc_storage_type: StorageType,
    doc_user: User,
) -> StorageLocation:
    return h.create_storage_location(
        doc_org, doc_storage_type, doc_user, name='Target Warehouse'
    )


@pytest.fixture
def doc_partner(h: ModuleTestHelper, doc_org: Organization, doc_user: User) -> Partner:
    return h.create_partner(doc_org, doc_user, name='Acme Supplies')


@pytest.fixture
def doc_item(
    db_session: Session,
    doc_org: Organization,
    doc_target_location: StorageLocation,
) -> Item:
    item = Item(
        name='Widget A',
        organization_id=doc_org.id,
        storage_location_id=doc_target_location.id,
        quantity=Decimal('10'),
    )
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)
    return item


@pytest.fixture
def doc_template(h: ModuleTestHelper, doc_org: Organization) -> ProductTemplate:
    return h.create_template(doc_org, name='New Product X', barcode='5901234123457')


@pytest.fixture
def doc_stock_item(
    db_session: Session,
    async_engine_fixture: AsyncEngine,
    doc_org: Organization,
    doc_source_location: StorageLocation,
    doc_template: ProductTemplate,
) -> Item:
    """Stock of ``doc_template`` standing in the source warehouse.

    A document that takes goods off a shelf names the record it takes them
    from, not just the product — the stock executors move stock by record.
    Tests that only need such a document to exist reach for this. The stock
    arrives through the items service, so the quant on the shelf is the
    bridge's, standing behind this record.
    """
    db_session.commit()

    async def _put(session: AsyncSession) -> uuid.UUID:
        keeper = await shelf_keeper(session, doc_org.id)
        record = await put_on_shelf(
            session, keeper, doc_template, doc_source_location.id, Decimal('100')
        )
        return record.id

    record_id = run_in_async_session(async_engine_fixture, _put)
    db_session.expire_all()
    item = db_session.get(Item, record_id)
    assert item is not None
    return item


@pytest.fixture
def doc_draft_pz(
    db_session: Session,
    doc_org: Organization,
    doc_user: User,
    doc_partner: Partner,
    doc_target_location: StorageLocation,
    doc_template: ProductTemplate,
) -> Document:
    doc = Document(
        organization_id=doc_org.id,
        type='IN',
        number='IN/2026/001',
        status=DocumentStatus.DRAFT.value,
        partner_id=doc_partner.id,
        target_location_id=doc_target_location.id,
        created_by=doc_user.id,
    )
    line = DocumentLine(
        product_template_id=doc_template.id,
        quantity=Decimal('5'),
        expected_quantity=Decimal('5'),
        done_quantity=Decimal('0'),
        line_number=1,
    )
    doc.lines.append(line)
    db_session.add(doc)
    db_session.commit()
    db_session.refresh(doc)
    return doc


@pytest.fixture
def doc_uom_pcs(h: ModuleTestHelper) -> Uom:
    return h.get_uom('pcs')


@pytest.fixture
def doc_uom_kg(h: ModuleTestHelper) -> Uom:
    return h.get_uom('kg')


@pytest.fixture
def doc_template_with_uom(
    h: ModuleTestHelper, doc_org: Organization, doc_uom_kg: Uom
) -> ProductTemplate:
    return h.create_template(
        doc_org, name='Rice 5kg', barcode='5909999123456', uom_id=str(doc_uom_kg.id)
    )


@pytest.fixture
def doc_approval_workflow(
    client: TestClient,
    doc_auth_headers: dict[str, str],
    db_session: Session,
) -> ApprovalWorkflow:
    """Seed a single-stage document approval workflow via the HTTP API.

    Approvals services are async-only, so fixtures create the
    workflow through the router and re-load the ORM row for the tests.
    """
    resp = client.post(
        '/api/v1/approvals/workflows',
        headers=doc_auth_headers,
        json={
            'target_type': 'document',
            'requester_scope': {'everyone': True},
            'is_active': True,
            'expected_scope': {'holds': 'all'},
            'name': 'Test Document Approval',
            'stages': [
                {
                    'order': 1,
                    'role': 'manager',
                    'label': 'Manager Approval',
                    'approver_user_ids': [],
                },
            ],
        },
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    from app.modules.approvals.models import ApprovalWorkflow

    workflow = db_session.get(ApprovalWorkflow, resp.json()['id'])
    assert workflow is not None
    return workflow

"""Fixtures for purchase_orders module integration tests."""

from collections.abc import Iterator
from typing import cast

import pytest
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.uom import Uom
from app.models.user import User


@pytest.fixture(autouse=True)
def _po_event_subscription() -> Iterator[None]:
    """Set up DOCUMENT_CANCELLED + DOCUMENT_COMPLETED event subscriptions for tests.

    In production, this is handled by module.run_startup() during lifespan.
    Tests skip the full startup, so we subscribe manually.
    """
    from app.core.context import ModuleContext
    from app.core.events import event_bus
    from app.core.module_registry import module_registry

    po_module = next(
        (m for m in module_registry.get_all() if m.metadata.name == 'purchase_orders'),
        None,
    )
    if po_module is None:
        yield
        return

    from app.modules.purchase_orders.module import PurchaseOrdersModule

    po_module = cast(PurchaseOrdersModule, po_module)

    context = ModuleContext(event_bus=event_bus)
    po_module._context = context

    async def _wrapper_cancel(payload: object) -> None:
        await po_module._handle_document_cancelled(payload)

    async def _wrapper_complete(payload: object) -> None:
        await po_module._handle_document_completed(payload)

    # By string, exactly as PurchaseOrdersModule.register subscribes: the
    # documents events are the warehouse module's, and a subscriber names
    # them by their wire name rather than importing another module's enum.
    event_bus.subscribe('document.cancelled', _wrapper_cancel)
    event_bus.subscribe('document.completed', _wrapper_complete)

    yield

    for event_type in ('document.cancelled', 'document.completed'):
        listeners = event_bus._listeners.get(event_type, [])
        event_bus._listeners[event_type] = [
            (cb, pri, org)
            for cb, pri, org in listeners
            if cb not in (_wrapper_cancel, _wrapper_complete)
        ]


@pytest.fixture
def h(db_session: Session) -> ModuleTestHelper:
    return ModuleTestHelper(db_session)


@pytest.fixture
def po_org(h: ModuleTestHelper) -> Organization:
    return h.create_org(
        'Purchase Orders Test Org',
        ['core', 'items', 'locations', 'categories', 'warehouse', 'purchase_orders'],
    )


@pytest.fixture
def po_user(h: ModuleTestHelper, po_org: Organization) -> User:
    return h.create_user(po_org, email='po@example.com')


@pytest.fixture
def po_auth_headers(h: ModuleTestHelper, po_user: User) -> dict[str, str]:
    return h.get_auth_headers(po_user)


@pytest.fixture
def po_storage_type(h: ModuleTestHelper) -> StorageType:
    return h.create_storage_type('Warehouse', 'WAREHOUSE')


@pytest.fixture
def po_location(
    h: ModuleTestHelper,
    po_org: Organization,
    po_storage_type: StorageType,
    po_user: User,
) -> StorageLocation:
    return h.create_storage_location(
        po_org, po_storage_type, po_user, name='Main Warehouse'
    )


@pytest.fixture
def po_partner(h: ModuleTestHelper, po_org: Organization, po_user: User) -> Partner:
    return h.create_partner(
        po_org, po_user, name='Test Supplier', email='supplier@example.com'
    )


@pytest.fixture
def po_template(h: ModuleTestHelper, po_org: Organization) -> ProductTemplate:
    return h.create_template(po_org, name='Test Product', sku='PO-TEST-001')


@pytest.fixture
def po_uom_pcs(h: ModuleTestHelper) -> Uom:
    return h.get_uom('pcs')


@pytest.fixture
def po_uom_kg(h: ModuleTestHelper) -> Uom:
    return h.get_uom('kg')


@pytest.fixture
def po_template_with_uom(
    h: ModuleTestHelper, po_org: Organization, po_uom_kg: Uom
) -> ProductTemplate:
    return h.create_template(
        po_org, name='Sunflower Seeds', sku='PO-UOM-001', uom_id=str(po_uom_kg.id)
    )

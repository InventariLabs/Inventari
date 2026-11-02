"""
Unit tests for misc equipment services: interceptors, email builder,
_bulk_service, and services.py helpers.
"""

from datetime import UTC, date, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.modules.equipment._attestation_email import (
    _build_email_html,
    _get_email_label,
)
from app.modules.equipment.interceptors import EquipmentItemInterceptor


@pytest.mark.unit
class TestInterceptor:
    async def test_before_create_seeds_default_available_status(self) -> None:
        # A freshly-created equipment asset must receive a default
        # ``equipment_status`` of AVAILABLE so the dashboard does not
        # surface UNKNOWN on new items. The interceptor only fires when
        # an ``equipment`` namespace already exists (set by bulk-create,
        # import, or the AddEquipment page).
        interceptor = EquipmentItemInterceptor()
        data: dict[str, Any] = {
            'name': 'test',
            'meta_data': {'equipment': {'serial_number': 'SN-1'}},
        }
        ctx = MagicMock()
        result = await interceptor.before_create(data, ctx)
        assert result['meta_data']['equipment']['equipment_status'] == 'AVAILABLE'
        # Other namespace keys must survive.
        assert result['meta_data']['equipment']['serial_number'] == 'SN-1'

    async def test_before_create_preserves_explicit_status(self) -> None:
        # Caller-supplied status must not be overwritten.
        interceptor = EquipmentItemInterceptor()
        data: dict[str, Any] = {
            'name': 'test',
            'meta_data': {'equipment': {'equipment_status': 'RETIRED'}},
        }
        ctx = MagicMock()
        result = await interceptor.before_create(data, ctx)
        assert result['meta_data']['equipment']['equipment_status'] == 'RETIRED'

    async def test_before_create_leaves_neutral_items_untouched(self) -> None:
        # Regression: a non-equipment item (e.g. a food item from the
        # core items tests) must NOT receive an ``equipment`` namespace —
        # otherwise we pollute neutral metadata and break those tests
        # (see test_create_item_normalizes_metadata_and_units).
        interceptor = EquipmentItemInterceptor()
        data: dict[str, Any] = {
            'name': 'Mąka',
            'meta_data': {'source': 'test-suite'},
        }
        ctx = MagicMock()
        result = await interceptor.before_create(data, ctx)
        assert result == data
        assert 'equipment' not in (result.get('meta_data') or {})

    async def test_before_create_noop_without_metadata(self) -> None:
        # Items without any metadata must not be mutated at all.
        interceptor = EquipmentItemInterceptor()
        data: dict[str, Any] = {'name': 'Pusty'}
        ctx = MagicMock()
        result = await interceptor.before_create(data, ctx)
        assert result == data

    async def test_before_create_merges_into_existing_meta(self) -> None:
        # Existing meta_data namespaces must not be wiped out.
        interceptor = EquipmentItemInterceptor()
        data: dict[str, Any] = {
            'name': 'test',
            'meta_data': {
                'other': {'keep': True},
                'equipment': {'serial_number': 'X'},
            },
        }
        ctx = MagicMock()
        result = await interceptor.before_create(data, ctx)
        assert result['meta_data']['other'] == {'keep': True}
        assert result['meta_data']['equipment']['equipment_status'] == 'AVAILABLE'
        assert result['meta_data']['equipment']['serial_number'] == 'X'

    async def test_before_update_passthrough(self) -> None:
        interceptor = EquipmentItemInterceptor()
        changes = {'name': 'updated'}
        ctx = MagicMock()
        result = await interceptor.before_update(uuid4(), changes, ctx)
        assert result == changes

    async def test_before_delete_no_org(self) -> None:
        interceptor = EquipmentItemInterceptor()
        ctx = MagicMock()
        ctx.organization_id = None
        await interceptor.before_delete(uuid4(), ctx)

    async def test_before_delete_no_db(self) -> None:
        interceptor = EquipmentItemInterceptor()
        ctx = MagicMock()
        ctx.organization_id = uuid4()
        ctx._db = None
        await interceptor.before_delete(uuid4(), ctx)

    async def test_before_delete_active_assignment_blocks(self) -> None:
        from app.core.interceptors import InterceptorError

        interceptor = EquipmentItemInterceptor()
        ctx = MagicMock()
        ctx.organization_id = uuid4()
        db = MagicMock()
        result_mock = MagicMock()
        result_mock.scalars.return_value.first.return_value = MagicMock()
        db.execute = AsyncMock(return_value=result_mock)
        ctx._db = db
        # Message comes from the i18n catalog now; the code is the contract.
        with pytest.raises(InterceptorError) as exc_info:
            await interceptor.before_delete(uuid4(), ctx)

        assert exc_info.value.error_code == 'EQUIPMENT_ASSIGNED'

    async def test_before_delete_no_active_assignment(self) -> None:
        interceptor = EquipmentItemInterceptor()
        ctx = MagicMock()
        ctx.organization_id = uuid4()
        db = MagicMock()
        result_mock = MagicMock()
        result_mock.scalars.return_value.first.return_value = None
        db.execute = AsyncMock(return_value=result_mock)
        ctx._db = db
        await interceptor.before_delete(uuid4(), ctx)


@pytest.mark.unit
class TestEmailBuilder:
    def test_get_email_label_en(self) -> None:
        label = _get_email_label('en', 'heading')
        assert label  # non-empty
        assert 'Action Required' in label

    def test_get_email_label_unknown_lang_falls_back(self) -> None:
        label = _get_email_label('xx', 'heading')
        assert label == _get_email_label('en', 'heading')

    def test_get_email_label_pl(self) -> None:
        assert 'Atestacja' in _get_email_label('pl', 'heading')

    def test_build_email_html_default_body(self) -> None:
        html = _build_email_html(
            assignee_name='Alice',
            item_name='Laptop',
            attestation_url='https://example.com/confirm',
            deadline='2025-12-31',
            custom_body=None,
            lang='en',
        )
        assert 'Alice' in html
        assert 'Laptop' in html
        assert 'https://example.com/confirm' in html

    def test_build_email_html_custom_body(self) -> None:
        html = _build_email_html(
            assignee_name='Bob',
            item_name='Monitor',
            attestation_url='https://example.com/confirm',
            deadline=datetime(2025, 12, 31, tzinfo=UTC),
            custom_body='<b>Custom body</b>',
            lang='en',
        )
        assert 'Custom body' in html

    def test_build_email_html_escaping(self) -> None:
        html = _build_email_html(
            assignee_name='<script>alert("xss")</script>',
            item_name='Laptop',
            attestation_url='https://example.com/confirm',
            deadline='2025-12-31',
            custom_body=None,
            lang='en',
        )
        assert '<script>' not in html
        assert '&lt;script&gt;' in html


@pytest.mark.unit
class TestBulkServiceAsync:
    @patch('app.core.public_api.core_api')
    async def test_bulk_create_success(self, mock_core: Any) -> None:
        from app.core.contracts import UserContextDTO
        from app.modules.equipment._bulk_service import bulk_create_items
        from app.modules.equipment.schemas import (
            BulkEquipmentCreate,
            BulkEquipmentEntry,
        )

        org_id = uuid4()
        user = UserContextDTO(id=uuid4(), organization_id=org_id)
        mock_core.locations.get_async = AsyncMock(return_value=MagicMock())
        mock_core.items.list_existing_serials_async = AsyncMock(return_value=set())
        item = MagicMock()
        item.id = uuid4()
        mock_core.items.create_async = AsyncMock(return_value=item)
        data = BulkEquipmentCreate(
            name='Test',
            entries=[
                BulkEquipmentEntry(serial_number='SN-001', asset_tag=None),
            ],
            location_id=uuid4(),
            brand=None,
            purchase_price=None,
        )
        result = await bulk_create_items(MagicMock(), data, user)
        assert result.created == 1

    @patch('app.core.public_api.core_api')
    async def test_bulk_create_duplicate_serial(self, mock_core: Any) -> None:
        from app.core.contracts import UserContextDTO
        from app.modules.equipment._bulk_service import bulk_create_items
        from app.modules.equipment.schemas import (
            BulkEquipmentCreate,
            BulkEquipmentEntry,
        )

        org_id = uuid4()
        user = UserContextDTO(id=uuid4(), organization_id=org_id)
        mock_core.locations.get_async = AsyncMock(return_value=MagicMock())
        mock_core.items.list_existing_serials_async = AsyncMock(return_value={'SN-DUP'})
        data = BulkEquipmentCreate(
            name='Test',
            entries=[
                BulkEquipmentEntry(serial_number='SN-DUP', asset_tag=None),
            ],
            location_id=uuid4(),
            brand=None,
            purchase_price=None,
        )
        result = await bulk_create_items(MagicMock(), data, user)
        assert result.failed == 1

    @patch('app.core.public_api.core_api')
    async def test_bulk_create_no_org_raises_403(self, mock_core: Any) -> None:

        from app.core.contracts import UserContextDTO
        from app.modules.equipment._bulk_service import bulk_create_items
        from app.modules.equipment.schemas import (
            BulkEquipmentCreate,
            BulkEquipmentEntry,
        )

        user = UserContextDTO(id=uuid4(), organization_id=None)
        mock_core.items.list_existing_serials_async = AsyncMock(return_value=set())
        data = BulkEquipmentCreate(
            name='Test',
            entries=[
                BulkEquipmentEntry(serial_number='SN-001', asset_tag=None),
            ],
            location_id=uuid4(),
            brand=None,
            purchase_price=None,
        )
        with pytest.raises(PermissionError):
            await bulk_create_items(MagicMock(), data, user)

    @patch('app.core.public_api.core_api')
    async def test_bulk_create_db_error(self, mock_core: Any) -> None:
        from sqlalchemy.exc import SQLAlchemyError

        from app.core.contracts import UserContextDTO
        from app.modules.equipment._bulk_service import bulk_create_items
        from app.modules.equipment.schemas import (
            BulkEquipmentCreate,
            BulkEquipmentEntry,
        )

        org_id = uuid4()
        user = UserContextDTO(id=uuid4(), organization_id=org_id)
        mock_core.locations.get_async = AsyncMock(return_value=MagicMock())
        mock_core.items.list_existing_serials_async = AsyncMock(return_value=set())
        mock_core.items.create_async = AsyncMock(side_effect=SQLAlchemyError('fail'))
        data = BulkEquipmentCreate(
            name='Test',
            entries=[
                BulkEquipmentEntry(serial_number='SN-001', asset_tag=None),
            ],
            location_id=uuid4(),
            brand=None,
            purchase_price=None,
        )
        result = await bulk_create_items(MagicMock(), data, user)
        assert result.failed == 1


@pytest.mark.unit
class TestServicesHelpers:
    async def test_to_assignment_schema(self) -> None:
        from app.modules.equipment.services import _to_assignment_schema

        assignment = MagicMock()
        assignment.id = uuid4()
        assignment.item_id = uuid4()
        assignment.item.name = 'Laptop'
        assignment.item.serial_number = 'SN-1'
        assignment.item.meta_data = {'equipment': {'asset_tag': 'TAG-1'}}
        assignment.assignee_partner = None
        assignment.checkout_location = None
        assignment.assignee_partner_id = uuid4()
        assignment.checkout_location_id = None
        assignment.assigned_to_name = 'Alice'
        assignment.assigned_to_email = 'alice@example.com'
        assignment.checked_out_at = datetime.now(UTC)
        assignment.expected_return_at = None
        assignment.checked_in_at = None
        assignment.checked_out_by = uuid4()
        assignment.checked_in_by = None
        assignment.checkout_notes = None
        assignment.checkin_notes = None
        assignment.checkin_condition = None
        assignment.created_at = datetime.now(UTC)

        result = _to_assignment_schema(assignment)
        assert result.item_name == 'Laptop'
        # Which unit, not just which model.
        assert result.item_serial == 'SN-1'
        assert result.item_asset_tag == 'TAG-1'
        assert result.assigned_to_name == 'Alice'
        assert result.partner_name is None
        assert result.checkout_location_name is None

    async def test_to_maintenance_schema(self) -> None:
        from app.modules.equipment.services import _to_maintenance_schema

        log = MagicMock()
        log.id = uuid4()
        log.item_id = uuid4()
        log.item.name = 'Server'
        log.maintenance_type = 'PREVENTIVE'
        log.title = 'Annual checkup'
        log.description = 'Routine maintenance'
        log.cost = 100.0
        log.currency = 'USD'
        log.performed_at = date(2026, 6, 7)
        log.performed_by = 'Technician'
        log.service_partner_id = None
        log.next_maintenance_at = None
        log.created_by = uuid4()
        log.created_at = datetime.now(UTC)

        result = _to_maintenance_schema(log)
        assert result.item_name == 'Server'
        assert result.maintenance_type == 'PREVENTIVE'

"""
Unit tests for bulk_service — bulk_create_items and bulk_edit_items.
"""

from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

import app.core.public_api as public_api
from app.core.contracts import UserContextDTO
from app.modules.equipment import bulk_service
from app.modules.equipment._bulk_service import bulk_create_items
from app.modules.equipment.bulk_service import bulk_edit_items
from app.modules.equipment.schemas import BulkEquipmentCreate, BulkEquipmentEntry

from ._mocked_asset_read import asset_read_through


@pytest.fixture(autouse=True)
def _asset_read_through_the_mock() -> Iterator[None]:
    with asset_read_through(bulk_service, lambda: public_api.core_api):
        yield


def _db_mock() -> AsyncMock:
    """An ``AsyncSession`` stand-in whose savepoint behaves like one.

    ``AsyncSession.begin_nested()`` hands back a transaction object that is an
    async context manager. On a bare ``AsyncMock`` the same call returns a
    coroutine, which is not, so the loop under test cannot enter it.
    """
    db = AsyncMock()
    db.begin_nested = MagicMock(return_value=AsyncMock())
    return db


def _make_user(org_id: Any | None = None) -> UserContextDTO:
    return UserContextDTO(id=uuid4(), organization_id=org_id or uuid4())


def _make_entry(
    serial_number: str = 'SN-000', asset_tag: str | None = None
) -> BulkEquipmentEntry:
    return BulkEquipmentEntry(serial_number=serial_number, asset_tag=asset_tag)


def _make_create_data(
    entries: list[BulkEquipmentEntry],
    storage_location_id: UUID | None = None,
    **kwargs: Any,
) -> BulkEquipmentCreate:
    return BulkEquipmentCreate(
        name='Test Item',
        entries=entries,
        location_id=storage_location_id or uuid4(),
        category_id=kwargs.get('category_id'),
        brand=kwargs.get('brand'),
        description=kwargs.get('description'),
        purchase_price=kwargs.get('purchase_price'),
        metadata=kwargs.get('metadata', {}),
    )


@pytest.mark.unit
class TestBulkCreateItems:
    @patch('app.core.public_api.core_api')
    async def test_storage_location_not_found(self, mock_core: Any) -> None:
        org_id = uuid4()
        user = _make_user(org_id)
        loc_id = uuid4()
        mock_core.locations.get_async = AsyncMock(return_value=None)
        data = _make_create_data(
            entries=[_make_entry('SN-001')],
            storage_location_id=loc_id,
        )
        result = await bulk_create_items(MagicMock(), data, user)
        assert result.failed == 1
        assert result.created == 0

    @patch('app.core.public_api.core_api')
    async def test_duplicate_serial_number(self, mock_core: Any) -> None:
        org_id = uuid4()
        user = _make_user(org_id)
        mock_core.locations.get_async = AsyncMock(return_value=MagicMock())
        mock_core.items.list_existing_serials_async = AsyncMock(return_value={'SN-001'})
        data = _make_create_data(entries=[_make_entry('SN-001')])
        result = await bulk_create_items(MagicMock(), data, user)
        assert result.failed == 1
        assert 'already exists' in result.errors[0].error

    @patch('app.core.public_api.core_api')
    async def test_create_success(self, mock_core: Any) -> None:
        org_id = uuid4()
        user = _make_user(org_id)
        mock_core.locations.get_async = AsyncMock(return_value=MagicMock())
        mock_core.items.list_existing_serials_async = AsyncMock(return_value=set())
        item = MagicMock()
        item.id = uuid4()
        mock_core.items.create_async = AsyncMock(return_value=item)
        data = _make_create_data(entries=[_make_entry('SN-001')])
        result = await bulk_create_items(MagicMock(), data, user)
        assert result.created == 1
        assert result.failed == 0

    @patch('app.core.public_api.core_api')
    async def test_create_no_serials_skips_list_check(self, mock_core: Any) -> None:
        org_id = uuid4()
        user = _make_user(org_id)
        item = MagicMock()
        item.id = uuid4()
        mock_core.locations.get_async = AsyncMock(return_value=MagicMock())
        mock_core.items.create_async = AsyncMock(return_value=item)
        data = _make_create_data(
            entries=[
                BulkEquipmentEntry(serial_number='NO-SN', asset_tag=None),
            ],
        )
        data.entries[0].serial_number = ''
        mock_core.items.list_existing_serials_async = AsyncMock(return_value=set())
        result = await bulk_create_items(MagicMock(), data, user)
        assert result.created == 1

    @patch('app.core.public_api.core_api')
    async def test_create_with_metadata_and_asset_tag(self, mock_core: Any) -> None:
        org_id = uuid4()
        user = _make_user(org_id)
        item = MagicMock()
        item.id = uuid4()
        mock_core.locations.get_async = AsyncMock(return_value=MagicMock())
        mock_core.items.list_existing_serials_async = AsyncMock(return_value=set())
        mock_core.items.create_async = AsyncMock(return_value=item)
        data = _make_create_data(
            entries=[_make_entry(serial_number='SN-002', asset_tag='AT-002')],
            metadata={'equipment': {'brand': 'Dell'}},
        )
        result = await bulk_create_items(MagicMock(), data, user)
        assert result.created == 1
        call_args = mock_core.items.create_async.call_args
        item_in = call_args.kwargs.get('data') or call_args[1].get('data')
        assert item_in.metadata['equipment']['asset_tag'] == 'AT-002'

    @patch('app.core.public_api.core_api')
    async def test_create_db_error_continues(self, mock_core: Any) -> None:
        from sqlalchemy.exc import SQLAlchemyError

        org_id = uuid4()
        user = _make_user(org_id)
        mock_core.locations.get_async = AsyncMock(return_value=MagicMock())
        mock_core.items.list_existing_serials_async = AsyncMock(return_value=set())
        mock_core.items.create_async = AsyncMock(
            side_effect=SQLAlchemyError('db error')
        )
        data = _make_create_data(entries=[_make_entry('SN-003')])
        result = await bulk_create_items(MagicMock(), data, user)
        assert result.failed == 1
        assert 'db error' not in result.errors[0].error
        assert result.errors[0].error.strip() != ''

    @patch('app.core.public_api.core_api')
    async def test_mixed_success_and_failure(self, mock_core: Any) -> None:
        org_id = uuid4()
        user = _make_user(org_id)
        mock_core.locations.get_async = AsyncMock(return_value=MagicMock())
        mock_core.items.list_existing_serials_async = AsyncMock(return_value={'SN-DUP'})
        item = MagicMock()
        item.id = uuid4()
        mock_core.items.create_async = AsyncMock(return_value=item)
        data = _make_create_data(
            entries=[_make_entry('SN-DUP'), _make_entry('SN-NEW')],
        )
        result = await bulk_create_items(MagicMock(), data, user)
        assert result.created == 1
        assert result.failed == 1


@pytest.mark.unit
class TestBulkEditItems:
    @patch('app.core.public_api.core_api')
    async def test_change_status_success(self, mock_core: Any) -> None:
        org_id = uuid4()
        user_id = uuid4()
        item_id = uuid4()
        item = MagicMock()
        item.meta_data = {'equipment': {'equipment_status': 'AVAILABLE'}}
        mock_core.items.get_async = AsyncMock(return_value=item)
        mock_core.items.update_meta_data_async = AsyncMock()
        mock_core.item_history.log_async = AsyncMock()
        # The checkout consults the approvals queue; without the module
        # enabled the gate short-circuits, which is this test's subject.
        mock_core.organizations.is_module_enabled_async = AsyncMock(return_value=False)
        mock_core.audit_log.log_action_async = AsyncMock()
        db = _db_mock()
        _scalars_result = MagicMock()
        _scalars_result.first.return_value = None
        db.scalars = AsyncMock(return_value=_scalars_result)
        updated, errors = await bulk_edit_items(
            db,
            org_id,
            [item_id],
            'change_status',
            {'status': 'MAINTENANCE'},
            user_id,
        )
        assert updated == 1
        assert errors == []

    @patch('app.core.public_api.core_api')
    async def test_change_status_invalid_transition(self, mock_core: Any) -> None:
        org_id = uuid4()
        user_id = uuid4()
        item_id = uuid4()
        item = MagicMock()
        item.meta_data = {'equipment': {'equipment_status': 'DEPLOYED'}}
        mock_core.items.get_async = AsyncMock(return_value=item)
        db = _db_mock()
        _scalars_result = MagicMock()
        _scalars_result.first.return_value = None
        db.scalars = AsyncMock(return_value=_scalars_result)
        updated, errors = await bulk_edit_items(
            db,
            org_id,
            [item_id],
            'change_status',
            {'status': 'DEPLOYED'},
            user_id,
        )
        assert updated == 0
        assert len(errors) == 1

    @patch('app.core.public_api.core_api')
    async def test_change_status_missing_status(self, mock_core: Any) -> None:
        org_id = uuid4()
        user_id = uuid4()
        item_id = uuid4()
        item = MagicMock()
        item.meta_data = {'equipment': {}}
        mock_core.items.get_async = AsyncMock(return_value=item)
        db = _db_mock()
        _scalars_result = MagicMock()
        _scalars_result.first.return_value = None
        db.scalars = AsyncMock(return_value=_scalars_result)
        updated, errors = await bulk_edit_items(
            db,
            org_id,
            [item_id],
            'change_status',
            {},
            user_id,
        )
        assert updated == 0
        assert errors[0]['code'] == 'FIELD_REQUIRED'

    @patch('app.core.public_api.core_api')
    async def test_item_not_found(self, mock_core: Any) -> None:
        org_id = uuid4()
        user_id = uuid4()
        item_id = uuid4()
        mock_core.items.get_async = AsyncMock(return_value=None)
        db = _db_mock()
        _scalars_result = MagicMock()
        _scalars_result.first.return_value = None
        db.scalars = AsyncMock(return_value=_scalars_result)
        updated, errors = await bulk_edit_items(
            db,
            org_id,
            [item_id],
            'change_status',
            {'status': 'DEPLOYED'},
            user_id,
        )
        assert updated == 0
        assert errors[0]['code'] == 'ITEM_NOT_FOUND'
        assert 'not found' in errors[0]['error'].lower()

    @patch('app.core.public_api.core_api')
    async def test_change_location_success(self, mock_core: Any) -> None:
        org_id = uuid4()
        user_id = uuid4()
        item_id = uuid4()
        loc_id = uuid4()
        item = MagicMock()
        mock_core.items.get_async = AsyncMock(return_value=item)
        mock_core.locations.get_async = AsyncMock(return_value=MagicMock())
        mock_core.items.update_async = AsyncMock()
        db = _db_mock()
        _scalars_result = MagicMock()
        _scalars_result.first.return_value = None
        db.scalars = AsyncMock(return_value=_scalars_result)
        updated, errors = await bulk_edit_items(
            db,
            org_id,
            [item_id],
            'change_location',
            {'location_id': str(loc_id)},
            user_id,
        )
        assert updated == 1

    @patch('app.core.public_api.core_api')
    async def test_change_location_not_found(self, mock_core: Any) -> None:
        org_id = uuid4()
        user_id = uuid4()
        item_id = uuid4()
        loc_id = uuid4()
        item = MagicMock()
        mock_core.items.get_async = AsyncMock(return_value=item)
        mock_core.locations.get_async = AsyncMock(return_value=None)
        db = _db_mock()
        _scalars_result = MagicMock()
        _scalars_result.first.return_value = None
        db.scalars = AsyncMock(return_value=_scalars_result)
        updated, errors = await bulk_edit_items(
            db,
            org_id,
            [item_id],
            'change_location',
            {'location_id': str(loc_id)},
            user_id,
        )
        assert updated == 0
        assert errors[0]['code'] == 'STORAGE_NOT_FOUND'

    @patch('app.core.public_api.core_api')
    async def test_assign_to_success(self, mock_core: Any) -> None:
        org_id = uuid4()
        user_id = uuid4()
        item_id = uuid4()
        partner_id = uuid4()
        item = MagicMock()
        # The checkout event carries the asset's name.
        item.name = 'ThinkPad X1'
        partner = MagicMock()
        partner.name = 'Alice'
        mock_core.items.get_async = AsyncMock(return_value=item)
        mock_core.partners.get_async = AsyncMock(return_value=partner)
        mock_core.items.update_meta_data_async = AsyncMock()
        mock_core.item_history.log_async = AsyncMock()
        # The checkout consults the approvals queue; without the module
        # enabled the gate short-circuits, which is this test's subject.
        mock_core.organizations.is_module_enabled_async = AsyncMock(return_value=False)
        mock_core.audit_log.log_action_async = AsyncMock()
        db = _db_mock()
        db.add = MagicMock()  # Session.add() is synchronous
        # scalars() is async; its await result has .first()
        _scalars_result = MagicMock()
        _scalars_result.first.return_value = None
        db.scalars = AsyncMock(return_value=_scalars_result)
        updated, errors = await bulk_edit_items(
            db,
            org_id,
            [item_id],
            'assign_to',
            {'partner_id': str(partner_id)},
            user_id,
        )
        assert updated == 1
        db.add.assert_called_once()

    @patch('app.core.public_api.core_api')
    async def test_assign_to_already_active(self, mock_core: Any) -> None:
        org_id = uuid4()
        user_id = uuid4()
        item_id = uuid4()
        partner_id = uuid4()
        item = MagicMock()
        # The checkout event carries the asset's name.
        item.name = 'ThinkPad X1'
        partner = MagicMock()
        partner.name = 'Alice'
        mock_core.items.get_async = AsyncMock(return_value=item)
        mock_core.partners.get_async = AsyncMock(return_value=partner)
        db = _db_mock()
        _scalars_result = MagicMock()
        _scalars_result.first.return_value = None
        db.scalars = AsyncMock(return_value=_scalars_result)
        db.scalars.return_value.first.return_value = MagicMock()
        updated, errors = await bulk_edit_items(
            db,
            org_id,
            [item_id],
            'assign_to',
            {'partner_id': str(partner_id)},
            user_id,
        )
        assert updated == 0
        assert errors[0]['code'] == 'EQUIPMENT_ASSIGNMENT_ALREADY_ACTIVE'

    @patch('app.core.public_api.core_api')
    async def test_assign_to_missing_partner_id(self, mock_core: Any) -> None:
        org_id = uuid4()
        user_id = uuid4()
        item_id = uuid4()
        item = MagicMock()
        mock_core.items.get_async = AsyncMock(return_value=item)
        db = _db_mock()
        _scalars_result = MagicMock()
        _scalars_result.first.return_value = None
        db.scalars = AsyncMock(return_value=_scalars_result)
        updated, errors = await bulk_edit_items(
            db,
            org_id,
            [item_id],
            'assign_to',
            {},
            user_id,
        )
        assert updated == 0
        assert errors[0]['code'] == 'EQUIPMENT_ASSIGNMENT_NEEDS_PERSON_OR_LOCATION'

    @patch('app.core.public_api.core_api')
    async def test_assign_by_name_and_email_without_a_partner(
        self, mock_core: Any
    ) -> None:
        """An organization member holds the asset, so the record has to
        carry the email "My assets" matches on — a partner id alone can
        never point at them."""
        org_id = uuid4()
        user_id = uuid4()
        item_id = uuid4()
        item = MagicMock()
        # The checkout event carries the asset's name.
        item.name = 'ThinkPad X1'
        mock_core.items.get_async = AsyncMock(return_value=item)
        mock_core.items.update_meta_data_async = AsyncMock()
        mock_core.item_history.log_async = AsyncMock()
        # The checkout consults the approvals queue; without the module
        # enabled the gate short-circuits, which is this test's subject.
        mock_core.organizations.is_module_enabled_async = AsyncMock(return_value=False)
        mock_core.audit_log.log_action_async = AsyncMock()
        db = _db_mock()
        db.add = MagicMock()
        _scalars_result = MagicMock()
        _scalars_result.first.return_value = None
        db.scalars = AsyncMock(return_value=_scalars_result)
        updated, errors = await bulk_edit_items(
            db,
            org_id,
            [item_id],
            'assign_to',
            {
                'assigned_to_name': 'Anna Kowalska',
                'assigned_to_email': 'Anna.Kowalska@Example.org',
            },
            user_id,
        )
        assert updated == 1
        assert errors == []
        assignment = db.add.call_args[0][0]
        assert assignment.assignee_partner_id is None
        assert assignment.assigned_to_name == 'Anna Kowalska'
        # stored lowercase, so "My assets" matching stays on one form
        assert assignment.assigned_to_email == 'anna.kowalska@example.org'

    @patch('app.core.public_api.core_api')
    async def test_assign_rejects_a_malformed_email(self, mock_core: Any) -> None:
        org_id = uuid4()
        user_id = uuid4()
        item_id = uuid4()
        item = MagicMock()
        mock_core.items.get_async = AsyncMock(return_value=item)
        # The approvals gate runs before the assignment row is built, so the
        # double has to answer it even when the subject is the email.
        mock_core.organizations.is_module_enabled_async = AsyncMock(return_value=False)
        db = _db_mock()
        _scalars_result = MagicMock()
        _scalars_result.first.return_value = None
        db.scalars = AsyncMock(return_value=_scalars_result)
        updated, errors = await bulk_edit_items(
            db,
            org_id,
            [item_id],
            'assign_to',
            {'assigned_to_name': 'Anna', 'assigned_to_email': 'not-an-email'},
            user_id,
        )
        assert updated == 0
        assert errors[0]['code'] == 'INVALID_EMAIL'

    @patch('app.core.public_api.core_api')
    async def test_assign_to_partner_not_found(self, mock_core: Any) -> None:
        org_id = uuid4()
        user_id = uuid4()
        item_id = uuid4()
        partner_id = uuid4()
        item = MagicMock()
        mock_core.items.get_async = AsyncMock(return_value=item)
        mock_core.partners.get_async = AsyncMock(return_value=None)
        db = _db_mock()
        _scalars_result = MagicMock()
        _scalars_result.first.return_value = None
        db.scalars = AsyncMock(return_value=_scalars_result)
        updated, errors = await bulk_edit_items(
            db,
            org_id,
            [item_id],
            'assign_to',
            {'partner_id': str(partner_id)},
            user_id,
        )
        assert updated == 0
        assert errors[0]['code'] == 'PARTNER_NOT_FOUND'

    @patch('app.core.public_api.core_api')
    async def test_unknown_action(self, mock_core: Any) -> None:
        org_id = uuid4()
        user_id = uuid4()
        item_id = uuid4()
        item = MagicMock()
        mock_core.items.get_async = AsyncMock(return_value=item)
        db = _db_mock()
        _scalars_result = MagicMock()
        _scalars_result.first.return_value = None
        db.scalars = AsyncMock(return_value=_scalars_result)
        updated, errors = await bulk_edit_items(
            db,
            org_id,
            [item_id],
            'unknown_action',
            {},
            user_id,
        )
        assert updated == 0
        assert errors[0]['code'] == 'UNKNOWN_BULK_ACTION'
        assert 'unknown_action' in errors[0]['error']

    @patch('app.core.public_api.core_api')
    async def test_change_status_to_deployed_with_assignment(
        self, mock_core: Any
    ) -> None:
        org_id = uuid4()
        user_id = uuid4()
        item_id = uuid4()
        item = MagicMock()
        item.meta_data = {'equipment': {'equipment_status': 'AVAILABLE'}}
        mock_core.items.get_async = AsyncMock(return_value=item)
        mock_core.items.update_meta_data_async = AsyncMock()
        mock_core.item_history.log_async = AsyncMock()
        # The checkout consults the approvals queue; without the module
        # enabled the gate short-circuits, which is this test's subject.
        mock_core.organizations.is_module_enabled_async = AsyncMock(return_value=False)
        mock_core.audit_log.log_action_async = AsyncMock()
        db = _db_mock()
        # An active checkout exists — so setting DEPLOYED is the legitimate
        # success path (the guard rejects DEPLOYED only when there is none).
        _scalars_result = MagicMock()
        _scalars_result.first.return_value = MagicMock()
        db.scalars = AsyncMock(return_value=_scalars_result)
        updated, errors = await bulk_edit_items(
            db,
            org_id,
            [item_id],
            'change_status',
            {'status': 'DEPLOYED'},
            user_id,
        )
        assert updated == 1


@pytest.mark.unit
def test_the_row_failure_sentence_claims_nothing_about_the_rest_of_the_batch() -> None:
    from app.i18n.service import get_error_message

    assert (
        get_error_message('equipment_bulk_item_failed', 'pl')
        == 'Tego zasobu nie udało się zmienić.'
    )
    assert (
        get_error_message('equipment_bulk_item_failed', 'en')
        == 'This asset could not be changed.'
    )

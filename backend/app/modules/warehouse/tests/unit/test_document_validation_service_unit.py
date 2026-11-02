from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.core.exceptions import ServiceRejectionError
from app.modules.warehouse.document_validation_service import (
    validate_lines_data_async,
    validate_location_async,
    validate_locations_async,
    validate_partner_async,
)


def _mock_core_api(**overrides: object) -> MagicMock:
    mock = MagicMock()
    mock.locations.get_async = AsyncMock(return_value=MagicMock())
    mock.partners.get_async = AsyncMock(return_value=MagicMock())
    mock.items.get_async = AsyncMock(return_value=MagicMock())
    mock.product_templates.get_async = AsyncMock(return_value=MagicMock())
    for key, value in overrides.items():
        obj, method = key.split('.', 1)
        getattr(getattr(mock, obj), method).return_value = value
    return mock


def _make_line(item_id: object = None, product_template_id: object = None) -> MagicMock:
    line = MagicMock()
    line.item_id = item_id
    line.product_template_id = product_template_id
    return line


@pytest.mark.unit
class TestValidateLocationAsync:
    @pytest.mark.asyncio
    async def test_passes_when_location_exists(self) -> None:
        db = MagicMock()
        org_id = uuid4()
        loc_id = uuid4()
        with patch(
            'app.modules.warehouse.document_validation_service.core_api',
            _mock_core_api(),
        ):
            await validate_location_async(db, org_id, loc_id)

    @pytest.mark.asyncio
    async def test_raises_when_location_not_found(self) -> None:
        db = MagicMock()
        org_id = uuid4()
        loc_id = uuid4()
        with patch(
            'app.modules.warehouse.document_validation_service.core_api',
            _mock_core_api(**{'locations.get_async': None}),
        ):
            with pytest.raises(ValueError, match='not found'):
                await validate_location_async(db, org_id, loc_id)


@pytest.mark.unit
class TestValidateLocationsAsync:
    @pytest.mark.asyncio
    async def test_in_type_requires_target(self) -> None:
        db = MagicMock()
        org_id = uuid4()
        with pytest.raises(ValueError, match='needs a target location'):
            await validate_locations_async(db, org_id, 'IN', None, None)

    @pytest.mark.asyncio
    async def test_out_type_requires_source(self) -> None:
        db = MagicMock()
        org_id = uuid4()
        with pytest.raises(ValueError, match='needs a source location'):
            await validate_locations_async(db, org_id, 'OUT', None, None)

    @pytest.mark.asyncio
    async def test_int_type_requires_both(self) -> None:
        db = MagicMock()
        org_id = uuid4()
        with pytest.raises(ValueError, match='needs a target location'):
            await validate_locations_async(db, org_id, 'INT', uuid4(), None)

    @pytest.mark.asyncio
    async def test_valid_in_document(self) -> None:
        db = MagicMock()
        org_id = uuid4()
        target_id = uuid4()
        with patch(
            'app.modules.warehouse.document_validation_service.core_api',
            _mock_core_api(),
        ):
            await validate_locations_async(db, org_id, 'IN', None, target_id)

    @pytest.mark.asyncio
    async def test_optional_location_still_validated_if_provided(self) -> None:
        db = MagicMock()
        org_id = uuid4()
        fake_id = uuid4()
        with patch(
            'app.modules.warehouse.document_validation_service.core_api',
            _mock_core_api(**{'locations.get_async': None}),
        ):
            with pytest.raises(ValueError, match='not found'):
                await validate_locations_async(db, org_id, 'IN', fake_id, uuid4())

    @pytest.mark.asyncio
    async def test_pw_type_requires_target(self) -> None:
        db = MagicMock()
        org_id = uuid4()
        with pytest.raises(ValueError, match='needs a target location'):
            await validate_locations_async(db, org_id, 'INTERNAL_IN', None, None)

    @pytest.mark.asyncio
    async def test_rw_type_requires_source(self) -> None:
        db = MagicMock()
        org_id = uuid4()
        with pytest.raises(ValueError, match='needs a source location'):
            await validate_locations_async(db, org_id, 'INTERNAL_OUT', None, None)


@pytest.mark.unit
class TestValidatePartnerAsync:
    @pytest.mark.asyncio
    async def test_passes_when_partner_exists(self) -> None:
        db = MagicMock()
        org_id = uuid4()
        partner_id = uuid4()
        with patch(
            'app.modules.warehouse.document_validation_service.core_api',
            _mock_core_api(),
        ):
            await validate_partner_async(db, org_id, partner_id)

    @pytest.mark.asyncio
    async def test_raises_when_partner_not_found(self) -> None:
        db = MagicMock()
        org_id = uuid4()
        partner_id = uuid4()
        with patch(
            'app.modules.warehouse.document_validation_service.core_api',
            _mock_core_api(**{'partners.get_async': None}),
        ):
            with pytest.raises(ValueError, match='not found'):
                await validate_partner_async(db, org_id, partner_id)

    @pytest.mark.asyncio
    async def test_a_receipt_takes_the_customer_returning_the_goods(self) -> None:
        # A customer's return is received on a receipt of its own, and that
        # receipt names the customer: refusing the role would leave the
        # return with no partner to put on the office's document.
        db = MagicMock()
        org_id = uuid4()
        partner_id = uuid4()
        customer = MagicMock(type='CUSTOMER')
        with patch(
            'app.modules.warehouse.document_validation_service.core_api',
            _mock_core_api(**{'partners.get_async': customer}),
        ):
            partner = await validate_partner_async(db, org_id, partner_id, 'IN')
            assert partner is customer

    @pytest.mark.asyncio
    async def test_a_receipt_refuses_an_employee_as_its_partner(self) -> None:
        db = MagicMock()
        org_id = uuid4()
        partner_id = uuid4()
        with patch(
            'app.modules.warehouse.document_validation_service.core_api',
            _mock_core_api(**{'partners.get_async': MagicMock(type='EMPLOYEE')}),
        ):
            with pytest.raises(ServiceRejectionError) as refused:
                await validate_partner_async(db, org_id, partner_id, 'IN')
        assert refused.value.key == 'document_partner_must_be_supplier_or_manufacturer'


@pytest.mark.unit
class TestValidateLinesDataAsync:
    @pytest.mark.asyncio
    async def test_passes_with_no_item_or_template(self) -> None:
        db = MagicMock()
        org_id = uuid4()
        line = _make_line(item_id=None, product_template_id=None)
        with patch(
            'app.modules.warehouse.document_validation_service.core_api',
            _mock_core_api(),
        ):
            await validate_lines_data_async(db, org_id, [line], 'IN')

    @pytest.mark.asyncio
    async def test_validates_item_exists(self) -> None:
        db = MagicMock()
        org_id = uuid4()
        item_id = uuid4()
        line = _make_line(item_id=item_id)
        with patch(
            'app.modules.warehouse.document_validation_service.core_api',
            _mock_core_api(**{'items.get_async': None}),
        ):
            with pytest.raises(ValueError, match='Item not found'):
                await validate_lines_data_async(db, org_id, [line], 'IN')

    @pytest.mark.asyncio
    async def test_validates_template_exists(self) -> None:
        db = MagicMock()
        org_id = uuid4()
        tpl_id = uuid4()
        line = _make_line(product_template_id=tpl_id)
        with patch(
            'app.modules.warehouse.document_validation_service.core_api',
            _mock_core_api(**{'product_templates.get_async': None}),
        ):
            with pytest.raises(ValueError, match='Product template not found'):
                await validate_lines_data_async(db, org_id, [line], 'IN')

    @pytest.mark.asyncio
    async def test_validates_multiple_lines(self) -> None:
        db = MagicMock()
        org_id = uuid4()
        line1 = _make_line()
        line2 = _make_line(item_id=uuid4())
        with patch(
            'app.modules.warehouse.document_validation_service.core_api',
            _mock_core_api(**{'items.get_async': None}),
        ):
            with pytest.raises(ValueError, match='not found'):
                await validate_lines_data_async(db, org_id, [line1, line2], 'IN')

    @pytest.mark.asyncio
    async def test_empty_lines_passes(self) -> None:
        db = MagicMock()
        org_id = uuid4()
        with patch(
            'app.modules.warehouse.document_validation_service.core_api',
            _mock_core_api(),
        ):
            await validate_lines_data_async(db, org_id, [], 'IN')

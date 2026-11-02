"""
Unit tests for my_assets_service.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.modules.equipment.my_assets_service import (
    get_my_active_assets,
    get_my_assignment_history,
)


@pytest.mark.unit
class TestGetMyActiveAssets:
    @pytest.mark.asyncio
    @patch('app.core.public_api.core_api')
    async def test_returns_empty_when_no_partners_and_no_email_match(
        self, mock_core: Any
    ) -> None:
        mock_core.partners.list_by_email_async = AsyncMock(return_value=[])
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=mock_result)
        result = await get_my_active_assets(db, uuid4(), 'user@example.com')
        assert result == []

    @pytest.mark.asyncio
    @patch('app.core.public_api.core_api')
    async def test_returns_empty_when_partners_none_and_no_email_match(
        self, mock_core: Any
    ) -> None:
        mock_core.partners.list_by_email_async = AsyncMock(return_value=None)
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=mock_result)
        result = await get_my_active_assets(db, uuid4(), 'user@example.com')
        assert result == []

    @pytest.mark.asyncio
    @patch('app.core.public_api.core_api')
    async def test_returns_active_assignments(self, mock_core: Any) -> None:
        partner = MagicMock()
        partner.id = uuid4()
        mock_core.partners.list_by_email_async = AsyncMock(return_value=[partner])

        assignment = MagicMock()
        assignment.id = uuid4()
        assignment.item_id = uuid4()
        assignment.checked_out_at = '2025-01-01T00:00:00'
        assignment.expected_return_at = None
        assignment.checkout_notes = None
        assignment.assigned_to_name = 'Alice'

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [assignment]
        db = AsyncMock()
        db.execute = AsyncMock(return_value=mock_result)

        item = MagicMock()
        item.name = 'Laptop'
        item.barcode = 'BC-001'
        item.category = MagicMock()
        item.category.name = 'IT'
        item.meta_data = {'equipment': {'equipment_status': 'DEPLOYED'}}
        item.image_url = None
        mock_core.items.get_async = AsyncMock(return_value=item)

        result = await get_my_active_assets(db, uuid4(), 'alice@example.com')
        assert len(result) == 1
        assert result[0]['item_name'] == 'Laptop'

    @pytest.mark.asyncio
    @patch('app.core.public_api.core_api')
    async def test_carries_the_holder_the_return_dialog_prints(
        self, mock_core: Any
    ) -> None:
        """My Assets hands the unit back through the check-in dialog, whose
        holder line reads the resolved name — not a second fallback."""
        mock_core.partners.list_by_email_async = AsyncMock(return_value=[])

        assignment = MagicMock()
        assignment.id = uuid4()
        assignment.item_id = uuid4()
        assignment.assignee_partner = None
        assignment.checkout_location = None
        assignment.assigned_to_name = 'Alice'

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [assignment]
        db = AsyncMock()
        db.execute = AsyncMock(return_value=mock_result)

        item = MagicMock()
        item.name = 'Laptop'
        item.meta_data = {'equipment': {}}
        mock_core.items.get_async = AsyncMock(return_value=item)

        result = await get_my_active_assets(db, uuid4(), 'alice@example.com')
        assert result[0]['holder_name'] == 'Alice'
        assert result[0]['holder_kind'] == 'person'

    @pytest.mark.asyncio
    @patch('app.core.public_api.core_api')
    async def test_borrows_the_model_picture_when_the_unit_has_none(
        self, mock_core: Any
    ) -> None:
        model_id = uuid4()
        partner = MagicMock()
        partner.id = uuid4()
        mock_core.partners.list_by_email_async = AsyncMock(return_value=[partner])

        assignment = MagicMock()
        assignment.id = uuid4()
        assignment.item_id = uuid4()

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [assignment]
        db = AsyncMock()
        db.execute = AsyncMock(return_value=mock_result)

        item = MagicMock()
        item.name = 'Laptop'
        item.image_url = None
        item.meta_data = {'equipment': {'model_id': str(model_id)}}
        mock_core.items.get_async = AsyncMock(return_value=item)

        model = MagicMock()
        model.image_url = 'https://files/model.png'
        mock_core.product_templates.get_async = AsyncMock(return_value=model)

        result = await get_my_active_assets(db, uuid4(), 'alice@example.com')
        assert result[0]['image_url'] is None
        assert result[0]['model_image_url'] == 'https://files/model.png'

    @pytest.mark.asyncio
    @patch('app.core.public_api.core_api')
    async def test_no_model_picture_for_a_unit_that_came_from_no_model(
        self, mock_core: Any
    ) -> None:
        partner = MagicMock()
        partner.id = uuid4()
        mock_core.partners.list_by_email_async = AsyncMock(return_value=[partner])

        assignment = MagicMock()
        assignment.id = uuid4()
        assignment.item_id = uuid4()

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [assignment]
        db = AsyncMock()
        db.execute = AsyncMock(return_value=mock_result)

        item = MagicMock()
        item.name = 'Laptop'
        item.image_url = None
        item.meta_data = {'equipment': {}}
        mock_core.items.get_async = AsyncMock(return_value=item)
        mock_core.product_templates.get_async = AsyncMock()

        result = await get_my_active_assets(db, uuid4(), 'alice@example.com')
        assert result[0]['model_image_url'] is None
        mock_core.product_templates.get_async.assert_not_called()

    @pytest.mark.asyncio
    @patch('app.core.public_api.core_api')
    async def test_skips_deleted_items(self, mock_core: Any) -> None:
        partner = MagicMock()
        partner.id = uuid4()
        mock_core.partners.list_by_email_async = AsyncMock(return_value=[partner])

        assignment = MagicMock()
        assignment.id = uuid4()
        assignment.item_id = uuid4()

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [assignment]
        db = AsyncMock()
        db.execute = AsyncMock(return_value=mock_result)

        mock_core.items.get_async = AsyncMock(return_value=None)
        result = await get_my_active_assets(db, uuid4(), 'alice@example.com')
        assert result == []


@pytest.mark.unit
class TestGetMyAssignmentHistory:
    @pytest.mark.asyncio
    @patch('app.core.public_api.core_api')
    async def test_returns_empty_when_no_partners_and_no_email_match(
        self, mock_core: Any
    ) -> None:
        mock_core.partners.list_by_email_async = AsyncMock(return_value=[])
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=mock_result)
        db.scalar = AsyncMock(return_value=0)
        result, total = await get_my_assignment_history(db, uuid4(), 'user@example.com')
        assert result == []
        assert total == 0

    @pytest.mark.asyncio
    @patch('app.core.public_api.core_api')
    async def test_returns_history(self, mock_core: Any) -> None:
        partner = MagicMock()
        partner.id = uuid4()
        mock_core.partners.list_by_email_async = AsyncMock(return_value=[partner])

        assignment = MagicMock()
        assignment.id = uuid4()
        assignment.item_id = uuid4()
        assignment.checked_out_at = '2025-01-01T00:00:00'
        assignment.checked_in_at = '2025-01-15T00:00:00'
        assignment.checkin_condition = 'GOOD'

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [assignment]
        db = AsyncMock()
        db.execute = AsyncMock(return_value=mock_result)
        db.scalar = AsyncMock(return_value=1)

        item = MagicMock()
        item.name = 'Monitor'
        mock_core.items.get_any_async = AsyncMock(return_value=item)

        result, total = await get_my_assignment_history(db, uuid4(), 'user@example.com')
        assert total == 1
        assert len(result) == 1
        assert result[0]['item_name'] == 'Monitor'
        assert result[0]['checkin_condition'] == 'GOOD'

"""
Unit tests for model_service — direct service layer tests using mock core_api.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.core.exceptions import NotFoundException
from app.modules.equipment.model_service import (
    clone_equipment_model,
    create_equipment_model,
    delete_equipment_model,
    list_equipment_models,
    update_equipment_model,
)


def _mock_template(**kwargs: Any) -> MagicMock:
    tpl = MagicMock()
    tpl.id = kwargs.get('id', uuid4())
    tpl.name = kwargs.get('name', 'Test Model')
    tpl.brand = kwargs.get('brand', 'Dell')
    tpl.image_url = kwargs.get('image_url', None)
    tpl.description = kwargs.get('description', None)
    tpl.organization_id = kwargs.get('org_id', uuid4())
    tpl.meta_data = kwargs.get('meta_data', {'equipment': {'cpu': 'i7'}})
    return tpl


@pytest.mark.unit
class TestListModelService:
    @pytest.mark.asyncio
    @patch('app.core.public_api.core_api')
    async def test_list_empty(self, mock_core: Any) -> None:
        mock_core.product_templates.list_for_org_async = AsyncMock(return_value=[])
        mock_core.categories.list_async = AsyncMock(return_value=[])
        db = AsyncMock()
        mock_core.audit_log.log_action_async = AsyncMock()
        result = await list_equipment_models(db, uuid4())
        assert result == []

    @pytest.mark.asyncio
    @patch('app.core.public_api.core_api')
    async def test_list_filters_non_equipment(self, mock_core: Any) -> None:
        t1 = _mock_template(name='Food Item', meta_data={'food': {}})
        t2 = _mock_template(name='Laptop', meta_data={'equipment': {'gen': '3'}})
        mock_core.product_templates.list_for_org_async = AsyncMock(
            return_value=[t1, t2]
        )
        mock_core.categories.list_async = AsyncMock(return_value=[])
        db = AsyncMock()
        mock_core.audit_log.log_action_async = AsyncMock()
        result = await list_equipment_models(db, uuid4())
        assert len(result) == 1
        assert result[0].name == 'Laptop'

    @pytest.mark.asyncio
    @patch('app.core.public_api.core_api')
    async def test_list_sorted_by_name(self, mock_core: Any) -> None:
        t1 = _mock_template(name='Zebra Model', meta_data={'equipment': {}})
        t2 = _mock_template(name='Alpha Model', meta_data={'equipment': {}})
        mock_core.product_templates.list_for_org_async = AsyncMock(
            return_value=[t1, t2]
        )
        mock_core.categories.list_async = AsyncMock(return_value=[])
        db = AsyncMock()
        mock_core.audit_log.log_action_async = AsyncMock()
        result = await list_equipment_models(db, uuid4())
        assert result[0].name == 'Alpha Model'
        assert result[1].name == 'Zebra Model'


@pytest.mark.unit
class TestCreateModelService:
    @pytest.mark.asyncio
    @patch('app.core.public_api.core_api')
    async def test_create_success(self, mock_core: Any) -> None:
        mock_core.product_templates.create_async = AsyncMock(
            return_value=_mock_template(name='New Model')
        )
        db = AsyncMock()
        mock_core.audit_log.log_action_async = AsyncMock()
        result = await create_equipment_model(
            db,
            uuid4(),
            'New Model',
            brand='Dell',
            equipment_meta={'cpu': 'i7'},
            user_id=uuid4(),
        )
        assert result.name == 'New Model'
        mock_core.product_templates.create_async.assert_called_once()


@pytest.mark.unit
class TestUpdateModelService:
    @pytest.mark.asyncio
    @patch('app.core.public_api.core_api')
    async def test_update_name(self, mock_core: Any) -> None:
        existing = _mock_template(meta_data={'equipment': {'cpu': 'i7'}})
        mock_core.product_templates.get_async = AsyncMock(return_value=existing)
        mock_core.product_templates.update_async = AsyncMock(
            return_value=_mock_template(name='Updated')
        )
        db = AsyncMock()
        mock_core.audit_log.log_action_async = AsyncMock()
        result = await update_equipment_model(
            db, uuid4(), uuid4(), name='Updated', user_id=uuid4()
        )
        assert result.name == 'Updated'

    @pytest.mark.asyncio
    @patch('app.core.public_api.core_api')
    async def test_update_equipment_meta(self, mock_core: Any) -> None:
        existing = _mock_template(meta_data={'equipment': {'cpu': 'i7'}})
        mock_core.product_templates.get_async = AsyncMock(return_value=existing)
        updated = _mock_template(
            meta_data={'equipment': {'cpu': 'i9'}, 'other': 'data'}
        )
        mock_core.product_templates.update_async = AsyncMock(return_value=updated)
        db = AsyncMock()
        mock_core.audit_log.log_action_async = AsyncMock()
        await update_equipment_model(
            db, uuid4(), uuid4(), equipment_meta={'cpu': 'i9'}, user_id=uuid4()
        )
        mock_core.product_templates.update_async.assert_called_once()

    @pytest.mark.asyncio
    @patch('app.core.public_api.core_api')
    async def test_update_no_existing_meta(self, mock_core: Any) -> None:
        mock_core.product_templates.get_async = AsyncMock(
            return_value=_mock_template(meta_data=None)
        )
        mock_core.product_templates.update_async = AsyncMock(
            return_value=_mock_template()
        )
        db = AsyncMock()
        mock_core.audit_log.log_action_async = AsyncMock()
        model_id = uuid4()
        org_id = uuid4()
        user_id = uuid4()
        result = await update_equipment_model(
            db, org_id, model_id, equipment_meta={'cpu': 'i9'}, user_id=user_id
        )
        # Fresh equipment meta must still be namespaced when no template exists.
        mock_core.product_templates.update_async.assert_awaited_once_with(
            db,
            model_id,
            org_id,
            name=None,
            brand=None,
            description=None,
            image_url=None,
            meta_data={'equipment': {'cpu': 'i9'}},
            user_id=user_id,
        )
        assert result.equipment_meta == {'cpu': 'i7'}

    @pytest.mark.asyncio
    @patch('app.core.public_api.core_api')
    async def test_update_without_equipment_meta(self, mock_core: Any) -> None:
        mock_core.product_templates.get_async = AsyncMock(return_value=_mock_template())
        mock_core.product_templates.update_async = AsyncMock(
            return_value=_mock_template(name='New Name', meta_data={'food': {}})
        )
        db = AsyncMock()
        mock_core.audit_log.log_action_async = AsyncMock()
        model_id = uuid4()
        org_id = uuid4()
        user_id = uuid4()
        result = await update_equipment_model(
            db, org_id, model_id, name='New Name', user_id=user_id
        )
        assert result.name == 'New Name'
        assert result.equipment_meta == {}
        # The module's own block travels on every update, because the
        # category lives inside it: `meta_data=None` means "leave it", and a
        # request that changes only the category would have been dropped in
        # silence. What was already there is carried over, not replaced.
        mock_core.product_templates.update_async.assert_awaited_once_with(
            db,
            model_id,
            org_id,
            name='New Name',
            brand=None,
            description=None,
            image_url=None,
            meta_data={'equipment': {'cpu': 'i7'}},
            user_id=user_id,
        )

    @pytest.mark.asyncio
    @patch('app.core.public_api.core_api')
    async def test_update_not_found_raises_404(self, mock_core: Any) -> None:
        """update_equipment_model fails fast with NotFoundException for missing template."""
        mock_core.product_templates.get_async = AsyncMock(return_value=None)
        db = AsyncMock()
        mock_core.audit_log.log_action_async = AsyncMock()
        with pytest.raises(NotFoundException):
            await update_equipment_model(
                db, uuid4(), uuid4(), name='X', user_id=uuid4()
            )


@pytest.mark.unit
class TestDeleteModelService:
    @pytest.mark.asyncio
    @patch('app.core.public_api.core_api')
    async def test_delete_existing(self, mock_core: Any) -> None:
        org_id = uuid4()
        mock_core.product_templates.get_async = AsyncMock(
            return_value=_mock_template(org_id=org_id)
        )
        mock_core.product_templates.delete_async = AsyncMock()
        db = AsyncMock()
        mock_core.audit_log.log_action_async = AsyncMock()
        result = await delete_equipment_model(db, org_id, uuid4(), uuid4())
        assert result is True
        mock_core.product_templates.delete_async.assert_called_once()

    @pytest.mark.asyncio
    @patch('app.core.public_api.core_api')
    async def test_delete_not_found(self, mock_core: Any) -> None:
        mock_core.product_templates.get_async = AsyncMock(return_value=None)
        db = AsyncMock()
        mock_core.audit_log.log_action_async = AsyncMock()
        result = await delete_equipment_model(db, uuid4(), uuid4(), uuid4())
        assert result is False

    @pytest.mark.asyncio
    @patch('app.core.public_api.core_api')
    async def test_delete_wrong_org(self, mock_core: Any) -> None:
        other_org = uuid4()
        mock_core.product_templates.get_async = AsyncMock(
            return_value=_mock_template(org_id=other_org)
        )
        db = AsyncMock()
        mock_core.audit_log.log_action_async = AsyncMock()
        result = await delete_equipment_model(db, uuid4(), uuid4(), uuid4())
        assert result is False

    @pytest.mark.asyncio
    @patch('app.core.public_api.core_api')
    async def test_delete_no_equipment_meta(self, mock_core: Any) -> None:
        mock_core.product_templates.get_async = AsyncMock(
            return_value=_mock_template(meta_data={})
        )
        db = AsyncMock()
        mock_core.audit_log.log_action_async = AsyncMock()
        result = await delete_equipment_model(db, uuid4(), uuid4(), uuid4())
        assert result is False


@pytest.mark.unit
class TestCloneModelService:
    @pytest.mark.asyncio
    @patch('app.core.public_api.core_api')
    async def test_clone_success(self, mock_core: Any) -> None:
        org_id = uuid4()
        original = _mock_template(
            name='Original',
            brand='HP',
            org_id=org_id,
            meta_data={'equipment': {'gen': '3'}},
        )
        mock_core.product_templates.get_async = AsyncMock(return_value=original)
        mock_core.product_templates.create_async = AsyncMock(
            return_value=_mock_template(name='Cloned')
        )
        db = AsyncMock()
        mock_core.audit_log.log_action_async = AsyncMock()
        result = await clone_equipment_model(
            db, org_id, uuid4(), 'Cloned', user_id=uuid4()
        )
        assert result.name == 'Cloned'
        mock_core.product_templates.create_async.assert_called_once()

    @pytest.mark.asyncio
    @patch('app.core.public_api.core_api')
    async def test_clone_not_found(self, mock_core: Any) -> None:
        mock_core.product_templates.get_async = AsyncMock(return_value=None)
        db = AsyncMock()
        mock_core.audit_log.log_action_async = AsyncMock()
        with pytest.raises(NotFoundException):
            await clone_equipment_model(db, uuid4(), uuid4(), 'Cloned', user_id=uuid4())

    @pytest.mark.asyncio
    @patch('app.core.public_api.core_api')
    async def test_clone_wrong_org(self, mock_core: Any) -> None:
        other_org = uuid4()
        mock_core.product_templates.get_async = AsyncMock(
            return_value=_mock_template(org_id=other_org)
        )
        db = AsyncMock()
        mock_core.audit_log.log_action_async = AsyncMock()
        with pytest.raises(NotFoundException):
            await clone_equipment_model(db, uuid4(), uuid4(), 'Cloned', user_id=uuid4())

    @pytest.mark.asyncio
    @patch('app.core.public_api.core_api')
    async def test_clone_no_equipment_meta(self, mock_core: Any) -> None:
        org_id = uuid4()
        mock_core.product_templates.get_async = AsyncMock(
            return_value=_mock_template(org_id=org_id, meta_data={})
        )
        db = AsyncMock()
        mock_core.audit_log.log_action_async = AsyncMock()
        with pytest.raises(ValueError, match='Not an equipment model'):
            await clone_equipment_model(db, org_id, uuid4(), 'Cloned', user_id=uuid4())

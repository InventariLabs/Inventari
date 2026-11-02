"""
Unit tests for import_service — analyze and execute equipment import.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.core.contracts import UserContextDTO
from app.modules.equipment.import_service import (
    analyze_equipment_import,
    execute_equipment_import,
)


def _csv_bytes(headers: str, *rows: str) -> bytes:
    lines = [headers] + list(rows)
    return '\n'.join(lines).encode('utf-8')


@pytest.mark.unit
class TestAnalyzeEquipmentImport:
    async def test_returns_headers_and_preview(self) -> None:
        csv = _csv_bytes('name,serial_number\nLaptop,SN-001\nMouse,SN-002\n')
        result = await analyze_equipment_import(csv, 'test.csv')
        assert 'name' in result['headers']
        assert result['total_rows'] == 2
        assert len(result['preview_rows']) == 2
        assert 'suggested_mapping' in result


@pytest.mark.unit
class TestExecuteEquipmentImport:
    @patch('app.modules.equipment.import_service.read_rows')
    @patch('app.core.public_api.core_api')
    async def test_missing_name_fails_row(self, mock_core: Any, mock_read: Any) -> None:
        import pandas as pd

        df = pd.DataFrame({'name': [None], 'serial': ['SN-001']})
        mock_read.return_value = df
        db = AsyncMock()
        org_id = uuid4()
        user = UserContextDTO(id=uuid4(), organization_id=org_id)
        result = await execute_equipment_import(
            db,
            b'fake',
            'test.csv',
            {'name': 'name'},
            org_id,
            user,
        )
        assert result['failed'] == 1
        assert 'Missing asset name' in result['errors'][0]['error']

    @patch('app.modules.equipment.import_service.resolve_storage_location_async')
    @patch('app.modules.equipment.import_service.read_rows')
    @patch('app.core.public_api.core_api')
    async def test_no_storage_location_fails_row(
        self, mock_core: Any, mock_read: Any, mock_resolve: Any
    ) -> None:
        import pandas as pd

        df = pd.DataFrame({'name': ['Laptop']})
        mock_read.return_value = df
        mock_resolve.return_value = None
        db = AsyncMock()
        org_id = uuid4()
        user = UserContextDTO(id=uuid4(), organization_id=org_id)
        result = await execute_equipment_import(
            db,
            b'fake',
            'test.csv',
            {'name': 'name'},
            org_id,
            user,
        )
        assert result['failed'] == 1
        assert 'storage location' in result['errors'][0]['error'].lower()

    @patch('app.modules.equipment.import_service.resolve_storage_location_async')
    @patch('app.modules.equipment.import_service.resolve_category_async')
    @patch('app.modules.equipment.import_service.read_rows')
    @patch('app.core.public_api.core_api')
    async def test_success_import(
        self, mock_core: Any, mock_read: Any, mock_cat: Any, mock_loc: Any
    ) -> None:
        import pandas as pd

        df = pd.DataFrame(
            {
                'name': ['Laptop'],
                'serial_number': ['SN-001'],
                'brand': ['Dell'],
            }
        )
        mock_read.return_value = df
        loc_id = uuid4()
        mock_loc.return_value = str(loc_id)
        mock_cat.return_value = None
        mock_core.items.create_async = AsyncMock(return_value=MagicMock(id=uuid4()))
        db = AsyncMock()
        # the serial dedup lookup must report "no existing item".
        lookup_result = MagicMock()
        lookup_result.scalars.return_value.first.return_value = None
        db.execute.return_value = lookup_result
        org_id = uuid4()
        user = UserContextDTO(id=uuid4(), organization_id=org_id)
        result = await execute_equipment_import(
            db,
            b'fake',
            'test.csv',
            {'name': 'name', 'serial_number': 'serial_number', 'brand': 'brand'},
            org_id,
            user,
        )
        assert result['imported'] == 1
        assert result['failed'] == 0

    @patch('app.modules.equipment.import_service.resolve_storage_location_async')
    @patch('app.modules.equipment.import_service.resolve_category_async')
    @patch('app.modules.equipment.import_service.read_rows')
    @patch('app.core.public_api.core_api')
    async def test_import_with_price(
        self, mock_core: Any, mock_read: Any, mock_cat: Any, mock_loc: Any
    ) -> None:
        import pandas as pd

        df = pd.DataFrame(
            {
                'name': ['Monitor'],
                'price': ['199.99'],
            }
        )
        mock_read.return_value = df
        loc_id = uuid4()
        mock_loc.return_value = str(loc_id)
        mock_cat.return_value = None
        mock_core.items.create_async = AsyncMock(return_value=MagicMock(id=uuid4()))
        db = AsyncMock()
        org_id = uuid4()
        user = UserContextDTO(id=uuid4(), organization_id=org_id)
        result = await execute_equipment_import(
            db,
            b'fake',
            'test.csv',
            {'name': 'name', 'purchase_price': 'price'},
            org_id,
            user,
        )
        assert result['imported'] == 1

    @patch('app.modules.equipment.import_service.resolve_storage_location_async')
    @patch('app.modules.equipment.import_service.resolve_category_async')
    @patch('app.modules.equipment.import_service.read_rows')
    @patch('app.core.public_api.core_api')
    async def test_import_db_error_continues(
        self, mock_core: Any, mock_read: Any, mock_cat: Any, mock_loc: Any
    ) -> None:
        import pandas as pd
        from sqlalchemy.exc import SQLAlchemyError

        df = pd.DataFrame({'name': ['Laptop']})
        mock_read.return_value = df
        loc_id = uuid4()
        mock_loc.return_value = str(loc_id)
        mock_cat.return_value = None
        mock_core.items.create_async = AsyncMock(side_effect=SQLAlchemyError('db fail'))
        db = AsyncMock()
        org_id = uuid4()
        user = UserContextDTO(id=uuid4(), organization_id=org_id)
        result = await execute_equipment_import(
            db,
            b'fake',
            'test.csv',
            {'name': 'name'},
            org_id,
            user,
        )
        assert result['failed'] == 1

    @patch('app.modules.equipment.import_service.resolve_storage_location_async')
    @patch('app.modules.equipment.import_service.resolve_category_async')
    @patch('app.modules.equipment.import_service.read_rows')
    @patch('app.core.public_api.core_api')
    async def test_import_with_default_location_and_category(
        self, mock_core: Any, mock_read: Any, mock_cat: Any, mock_loc: Any
    ) -> None:
        import pandas as pd

        df = pd.DataFrame({'name': ['Server']})
        mock_read.return_value = df
        loc_id = uuid4()
        cat_id = uuid4()
        mock_loc.return_value = str(loc_id)
        mock_cat.return_value = str(cat_id)
        mock_core.items.create_async = AsyncMock(return_value=MagicMock(id=uuid4()))
        db = AsyncMock()
        org_id = uuid4()
        user = UserContextDTO(id=uuid4(), organization_id=org_id)
        result = await execute_equipment_import(
            db,
            b'fake',
            'test.csv',
            {'name': 'name'},
            org_id,
            user,
            default_location_id=str(loc_id),
            default_category_id=str(cat_id),
        )
        assert result['imported'] == 1

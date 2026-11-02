from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.modules.purchase_orders.po_import_service import import_lines_into_po


def _make_csv(content: str) -> bytes:
    return content.encode('utf-8')


def _make_po(status: str = 'DRAFT', lines: list[Any] | None = None) -> MagicMock:
    po = MagicMock()
    po.id = uuid4()
    po.organization_id = uuid4()
    po.status = status
    po.lines = lines or []
    return po


@pytest.mark.unit
class TestImportLinesIntoPo:
    @pytest.mark.asyncio
    async def test_raises_when_po_not_found(self) -> None:
        db = MagicMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        db.execute = AsyncMock(return_value=mock_result)
        csv = _make_csv('name,sku\nWidget,W-001\n')
        with pytest.raises(ValueError, match='not found'):
            await import_lines_into_po(db, uuid4(), csv, 'data.csv', {}, uuid4())

    @pytest.mark.asyncio
    async def test_raises_when_not_draft(self) -> None:
        db = MagicMock()
        po = _make_po(status='CONFIRMED')
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = po
        db.execute = AsyncMock(return_value=mock_result)
        csv = _make_csv('name,sku\nWidget,W-001\n')
        with pytest.raises(ValueError, match='DRAFT'):
            await import_lines_into_po(db, po.id, csv, 'data.csv', {}, uuid4())

    @pytest.mark.asyncio
    async def test_imports_rows_successfully(self) -> None:
        db = MagicMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        po = _make_po(status='DRAFT')
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = po
        db.execute = AsyncMock(return_value=mock_result)
        csv = _make_csv('name,quantity_ordered\nWidget A,10\nWidget B,5\n')
        mapping = {'name': 'name', 'quantity_ordered': 'quantity_ordered'}
        with (
            patch(
                'app.modules.purchase_orders.po_import_service.core_api',
                MagicMock(),
            ) as mock_api,
            patch(
                'app.modules.purchase_orders.po_import_service.UomResolverAsync',
            ) as mock_resolver_cls,
        ):
            mock_api.product_templates.lookup_by_sku_async = AsyncMock(
                return_value=None
            )
            mock_api.product_templates.lookup_by_barcode_async = AsyncMock(
                return_value=None
            )
            mock_resolver = MagicMock()
            mock_resolver.resolve = AsyncMock(return_value=None)
            mock_resolver_cls.return_value = mock_resolver
            result = await import_lines_into_po(
                db, po.id, csv, 'data.csv', mapping, uuid4()
            )
        assert result['imported'] == 2
        assert db.add.call_count == 2

    @pytest.mark.asyncio
    async def test_resolves_product_by_sku(self) -> None:
        db = MagicMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        po = _make_po(status='DRAFT')
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = po
        db.execute = AsyncMock(return_value=mock_result)
        csv = _make_csv('name,sku\nWidget,W-001\n')
        mapping = {'name': 'name', 'sku': 'sku'}
        template = MagicMock()
        template.id = uuid4()
        with (
            patch(
                'app.modules.purchase_orders.po_import_service.core_api',
                MagicMock(),
            ) as mock_api,
            patch(
                'app.modules.purchase_orders.po_import_service.UomResolverAsync',
            ) as mock_resolver_cls,
        ):
            mock_api.product_templates.lookup_by_sku_async = AsyncMock(
                return_value=template
            )
            mock_api.product_templates.lookup_by_barcode_async = AsyncMock(
                return_value=None
            )
            mock_resolver = MagicMock()
            mock_resolver.resolve = AsyncMock(return_value=None)
            mock_resolver_cls.return_value = mock_resolver
            result = await import_lines_into_po(
                db, po.id, csv, 'data.csv', mapping, uuid4()
            )
        assert result['matched'] == 1
        assert result['unmatched'] == 0

    @pytest.mark.asyncio
    async def test_falls_back_to_barcode(self) -> None:
        db = MagicMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        po = _make_po(status='DRAFT')
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = po
        db.execute = AsyncMock(return_value=mock_result)
        csv = _make_csv('name,barcode\nWidget,12345\n')
        mapping = {'name': 'name', 'barcode': 'barcode'}
        template = MagicMock()
        template.id = uuid4()
        with (
            patch(
                'app.modules.purchase_orders.po_import_service.core_api',
                MagicMock(),
            ) as mock_api,
            patch(
                'app.modules.purchase_orders.po_import_service.UomResolverAsync',
            ) as mock_resolver_cls,
        ):
            mock_api.product_templates.lookup_by_sku_async = AsyncMock(
                return_value=None
            )
            mock_api.product_templates.lookup_by_barcode_async = AsyncMock(
                return_value=template
            )
            mock_resolver = MagicMock()
            mock_resolver.resolve = AsyncMock(return_value=None)
            mock_resolver_cls.return_value = mock_resolver
            result = await import_lines_into_po(
                db, po.id, csv, 'data.csv', mapping, uuid4()
            )
        assert result['matched'] == 1

    @pytest.mark.asyncio
    async def test_invalid_csv_raises(self) -> None:
        db = MagicMock()
        po = _make_po(status='DRAFT')
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = po
        db.execute = AsyncMock(return_value=mock_result)
        with pytest.raises(ValueError, match='could not be read as a spreadsheet'):
            await import_lines_into_po(
                db, po.id, b'\xff\xfe\x00\x01', 'data.csv', {}, uuid4()
            )

    @pytest.mark.asyncio
    async def test_invalid_quantity_skips_row(self) -> None:
        """rows with non-numeric quantity are skipped, not defaulted to 1."""
        db = MagicMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        po = _make_po(status='DRAFT')
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = po
        db.execute = AsyncMock(return_value=mock_result)
        csv = _make_csv('name,quantity_ordered\nWidget A,abc\nWidget B,10\n')
        mapping = {
            'name': 'name',
            'quantity_ordered': 'quantity_ordered',
        }
        with (
            patch(
                'app.modules.purchase_orders.po_import_service.core_api',
                MagicMock(),
            ) as mock_api,
            patch(
                'app.modules.purchase_orders.po_import_service.UomResolverAsync',
            ) as mock_resolver_cls,
        ):
            mock_api.product_templates.lookup_by_sku_async = AsyncMock(
                return_value=None
            )
            mock_api.product_templates.lookup_by_barcode_async = AsyncMock(
                return_value=None
            )
            mock_resolver = MagicMock()
            mock_resolver.resolve = AsyncMock(return_value=None)
            mock_resolver_cls.return_value = mock_resolver
            result = await import_lines_into_po(
                db, po.id, csv, 'data.csv', mapping, uuid4()
            )
        assert result['imported'] == 1
        assert result['skipped'] == 1
        assert result['errors'] == [
            {
                'row': 1,
                'error': 'Column "quantity_ordered": "abc" is not a number',
                'code': 'IMPORT_COLUMN_NOT_A_NUMBER',
            }
        ]

    @pytest.mark.asyncio
    async def test_zero_or_negative_quantity_skips_row(self) -> None:
        """rows with zero or negative quantity are skipped."""
        db = MagicMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        po = _make_po(status='DRAFT')
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = po
        db.execute = AsyncMock(return_value=mock_result)
        csv = _make_csv('name,quantity_ordered\nWidget A,0\nWidget B,-5\nWidget C,3\n')
        mapping = {
            'name': 'name',
            'quantity_ordered': 'quantity_ordered',
        }
        with (
            patch(
                'app.modules.purchase_orders.po_import_service.core_api',
                MagicMock(),
            ) as mock_api,
            patch(
                'app.modules.purchase_orders.po_import_service.UomResolverAsync',
            ) as mock_resolver_cls,
        ):
            mock_api.product_templates.lookup_by_sku_async = AsyncMock(
                return_value=None
            )
            mock_api.product_templates.lookup_by_barcode_async = AsyncMock(
                return_value=None
            )
            mock_resolver = MagicMock()
            mock_resolver.resolve = AsyncMock(return_value=None)
            mock_resolver_cls.return_value = mock_resolver
            result = await import_lines_into_po(
                db, po.id, csv, 'data.csv', mapping, uuid4()
            )
        assert result['imported'] == 1
        assert result['skipped'] == 2
        assert [(e['row'], e['code']) for e in result['errors']] == [
            (1, 'IMPORT_QUANTITY_NOT_POSITIVE'),
            (2, 'IMPORT_QUANTITY_NOT_POSITIVE'),
        ]


@pytest.mark.unit
class TestTheRowLimit:
    @pytest.mark.asyncio
    async def test_a_sheet_over_the_row_limit_is_refused(self) -> None:
        """A sheet past the row cap is refused, not read row by row.

        The order-line import was the one reader left without the cap, so a
        million-row file sailed into the row loop while the item import
        refused the same file at the door.
        """
        from app.core.upload_validation import MAX_IMPORT_ROWS

        db = MagicMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        po = _make_po(status='DRAFT')
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = po
        db.execute = AsyncMock(return_value=mock_result)
        csv = _make_csv('name,sku\n' + ',\n' * (MAX_IMPORT_ROWS + 1))
        with pytest.raises(ValueError, match=f'the limit is {MAX_IMPORT_ROWS}'):
            await import_lines_into_po(db, po.id, csv, 'data.csv', {}, uuid4())


@pytest.mark.unit
class TestAWorkbookThatCannotBeOpenedIsRefused:
    @pytest.mark.asyncio
    async def test_a_truncated_workbook_is_a_refusal_not_a_crash(self) -> None:
        """A workbook cut off mid-download is a refused file, not a 500.

        The truncation surfaces as zipfile's BadZipFile, which none of the
        parse errors the reader words for — it used to escape the reader
        and answer the upload with an unhandled Internal Server Error.
        """
        db = MagicMock()
        po = _make_po(status='DRAFT')
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = po
        db.execute = AsyncMock(return_value=mock_result)
        with pytest.raises(ValueError, match='could not be read as a spreadsheet'):
            await import_lines_into_po(
                db, po.id, b'PK\x03\x04cut-off', 'data.xlsx', {}, uuid4()
            )

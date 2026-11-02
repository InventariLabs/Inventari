from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.core.file_import import analyze_import_file
from app.modules.warehouse.document_import_service import (
    analyze_pasted_text,
    import_lines_from_file,
    parse_pasted_text,
)


def _make_csv(content: str) -> bytes:
    return content.encode('utf-8')


def _make_doc(status: str = 'DRAFT', lines: list[object] | None = None) -> MagicMock:
    doc = MagicMock()
    doc.id = uuid4()
    doc.organization_id = uuid4()
    doc.status = status
    doc.lines = lines or []
    return doc


@pytest.mark.unit
class TestAnalyzeImportFile:
    @pytest.mark.asyncio
    async def test_analyze_csv(self) -> None:
        csv = _make_csv('name,quantity,price\nWidget A,10,5.50\nWidget B,5,3.00\n')
        result = await analyze_import_file(csv, 'products.csv')
        assert result['headers'] == ['name', 'quantity', 'price']
        assert result['total_rows'] == 2
        assert len(result['preview_rows']) == 2

    @pytest.mark.asyncio
    async def test_preview_limited_to_5_rows(self) -> None:
        rows = 'name,quantity\n' + '\n'.join(f'Item {i},{i}' for i in range(10))
        csv = _make_csv(rows)
        result = await analyze_import_file(csv, 'data.csv')
        assert len(result['preview_rows']) == 5
        assert result['total_rows'] == 10

    @pytest.mark.asyncio
    async def test_invalid_csv_raises(self) -> None:
        # Bytes invalid under every rung of the reader's encoding ladder
        # (utf-8-sig, cp1250) still come back as a refusal. The old payload
        # (\xff\xfe...) was merely not utf-8 — cp1250 names those bytes, so
        # a tolerant reader now parses them instead.
        with pytest.raises(ValueError):
            await analyze_import_file(b'\x81\x83\x88\x90\x98', 'data.csv')


@pytest.mark.unit
class TestImportLinesFromFile:
    @pytest.mark.asyncio
    async def test_raises_when_doc_not_found(self) -> None:
        db = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=mock_result)
        csv = _make_csv('name,quantity\nWidget,10\n')
        with pytest.raises((ValueError, HTTPException)):
            await import_lines_from_file(
                db, uuid4(), csv, 'data.csv', {'name': 'name'}, uuid4()
            )

    @pytest.mark.asyncio
    async def test_raises_when_not_draft(self) -> None:
        db = MagicMock()
        doc = _make_doc(status='CONFIRMED')
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = doc
        db.execute = AsyncMock(return_value=mock_result)
        csv = _make_csv('name,quantity\nWidget,10\n')
        with pytest.raises((ValueError, HTTPException)):
            await import_lines_from_file(
                db, doc.id, csv, 'data.csv', {'name': 'name'}, uuid4()
            )

    @pytest.mark.asyncio
    async def test_imports_rows_successfully(self) -> None:
        db = MagicMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        doc = _make_doc(status='DRAFT')
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = doc
        db.execute = AsyncMock(return_value=mock_result)
        csv = _make_csv('name,quantity\nWidget A,10\nWidget B,5\n')
        mapping = {'name': 'name', 'quantity': 'quantity'}
        with patch(
            'app.modules.warehouse._import_line_builder.core_api',
            MagicMock(),
        ) as mock_api:
            mock_api.uoms.get_by_symbol_async = AsyncMock(return_value=None)
            mock_api.product_templates.search_ranked_async = AsyncMock(return_value=[])
            mock_api.product_templates.lookup_by_barcode_async = AsyncMock(
                return_value=None
            )
            result = await import_lines_from_file(
                db, doc.id, csv, 'data.csv', mapping, uuid4()
            )
        assert result['imported'] == 2
        assert db.add.call_count == 2

    @pytest.mark.asyncio
    async def test_resolves_barcode_to_product_template(self) -> None:
        db = MagicMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        doc = _make_doc(status='DRAFT')
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = doc
        db.execute = AsyncMock(return_value=mock_result)
        csv = _make_csv('name,barcode,quantity\nWidget,123456789,10\n')
        mapping = {'name': 'name', 'barcode': 'barcode', 'quantity': 'quantity'}
        template = MagicMock()
        template.id = uuid4()
        template.name = 'Widget'
        template.brand = 'Brand'
        template.barcode = '123456789'
        template.uom_id = uuid4()
        template.image_url = None
        with patch(
            'app.modules.warehouse._import_line_builder.core_api',
            MagicMock(),
        ) as mock_api:
            mock_api.uoms.get_by_symbol_async = AsyncMock(return_value=None)
            mock_api.product_templates.search_ranked_async = AsyncMock(return_value=[])
            mock_api.product_templates.lookup_by_barcode_async = AsyncMock(
                return_value=template
            )
            result = await import_lines_from_file(
                db, doc.id, csv, 'data.csv', mapping, uuid4()
            )
        assert result['matched'] == 1
        assert result['unmatched'] == 0

    @pytest.mark.asyncio
    async def test_counts_unmatched_barcodes(self) -> None:
        db = MagicMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        doc = _make_doc(status='DRAFT')
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = doc
        db.execute = AsyncMock(return_value=mock_result)
        csv = _make_csv('name,barcode,quantity\nWidget,99999,10\n')
        mapping = {'name': 'name', 'barcode': 'barcode', 'quantity': 'quantity'}
        with patch(
            'app.modules.warehouse._import_line_builder.core_api',
            MagicMock(),
        ) as mock_api:
            mock_api.uoms.get_by_symbol_async = AsyncMock(return_value=None)
            mock_api.product_templates.search_ranked_async = AsyncMock(return_value=[])
            mock_api.product_templates.lookup_by_barcode_async = AsyncMock(
                return_value=None
            )
            result = await import_lines_from_file(
                db, doc.id, csv, 'data.csv', mapping, uuid4()
            )
        assert result['unmatched'] == 1

    @pytest.mark.asyncio
    async def test_a_spelled_out_unit_resolves_the_way_it_does_elsewhere(
        self,
    ) -> None:
        """A spelled-out unit is a unit here too, not an unknown one.

        Document import used to look the symbol up verbatim while purchase
        order import went through the shared alias map, so the same sheet
        carried its units into one importer and lost them in the other.
        """
        db = MagicMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        doc = _make_doc(status='DRAFT')
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = doc
        db.execute = AsyncMock(return_value=mock_result)
        csv = _make_csv('name,quantity,unit\nWidget A,10,kilograms\n')
        mapping = {'name': 'name', 'quantity': 'quantity', 'uom_symbol': 'unit'}
        kg = MagicMock()
        kg.id = uuid4()
        with (
            patch(
                'app.modules.warehouse._import_line_builder.core_api',
                MagicMock(),
            ) as mock_api,
            patch('app.core.uom_resolver.core_api', MagicMock()) as mock_core,
        ):
            mock_api.product_templates.search_ranked_async = AsyncMock(return_value=[])
            mock_api.product_templates.lookup_by_barcode_async = AsyncMock(
                return_value=None
            )
            mock_core.uoms.get_by_symbol_async = AsyncMock(return_value=kg)
            result = await import_lines_from_file(
                db, doc.id, csv, 'data.csv', mapping, uuid4()
            )

        assert result['imported'] == 1
        # the alias map turned "kilograms" into the symbol actually stored
        assert mock_core.uoms.get_by_symbol_async.await_args.args[1] == 'kg'
        assert db.add.call_args.args[0].uom_id == kg.id

    @pytest.mark.asyncio
    async def test_a_blank_unit_cell_does_not_break_the_row(self) -> None:
        """A blank in a unit column is no unit, not the word "nan"."""
        db = MagicMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        doc = _make_doc(status='DRAFT')
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = doc
        db.execute = AsyncMock(return_value=mock_result)
        csv = _make_csv('name,quantity,unit\nWidget A,10,\n')
        mapping = {'name': 'name', 'quantity': 'quantity', 'uom_symbol': 'unit'}
        with (
            patch(
                'app.modules.warehouse._import_line_builder.core_api',
                MagicMock(),
            ) as mock_api,
            patch('app.core.uom_resolver.core_api', MagicMock()) as mock_core,
        ):
            mock_api.product_templates.search_ranked_async = AsyncMock(return_value=[])
            mock_api.product_templates.lookup_by_barcode_async = AsyncMock(
                return_value=None
            )
            mock_core.uoms.get_by_symbol_async = AsyncMock(return_value=None)
            result = await import_lines_from_file(
                db, doc.id, csv, 'data.csv', mapping, uuid4()
            )

        assert result['imported'] == 1
        mock_core.uoms.get_by_symbol_async.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_quantity_that_is_not_a_number_refuses_the_row(self) -> None:
        # "abc" used to import as 1 in silence; an opening balance built on
        # that is wrong in a way nobody is told about.
        db = MagicMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        doc = _make_doc(status='DRAFT')
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = doc
        db.execute = AsyncMock(return_value=mock_result)
        csv = _make_csv('name,quantity\nWidget,abc\n')
        mapping = {'name': 'name', 'quantity': 'quantity'}
        with patch(
            'app.modules.warehouse._import_line_builder.core_api',
            MagicMock(),
        ) as mock_api:
            mock_api.uoms.get_by_symbol_async = AsyncMock(return_value=None)
            mock_api.product_templates.search_ranked_async = AsyncMock(return_value=[])
            mock_api.product_templates.lookup_by_barcode_async = AsyncMock(
                return_value=None
            )
            result = await import_lines_from_file(
                db, doc.id, csv, 'data.csv', mapping, uuid4()
            )
        assert result['imported'] == 0
        assert result['failed'] == 1
        assert 'abc' in result['errors'][0]['error']

    @pytest.mark.asyncio
    async def test_a_sheet_over_the_row_limit_is_refused(self) -> None:
        """A sheet past the row cap is refused, not read row by row.

        The document import read the whole file without the cap the item
        import has, so a million-row file was parsed and walked before the
        first refusal.
        """
        from app.core.upload_validation import MAX_IMPORT_ROWS

        db = MagicMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        doc = _make_doc(status='DRAFT')
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = doc
        db.execute = AsyncMock(return_value=mock_result)
        csv = _make_csv('name,quantity\n' + ',\n' * (MAX_IMPORT_ROWS + 1))
        with pytest.raises(ValueError, match=f'the limit is {MAX_IMPORT_ROWS}'):
            await import_lines_from_file(
                db, doc.id, csv, 'data.csv', {'name': 'name'}, uuid4()
            )


@pytest.mark.unit
class TestParsePastedLines:
    """5.1a — parse pasted text (from clipboard/Excel) into a DataFrame.

    The parser must auto-detect the delimiter (tab, comma, semicolon),
    skip blank lines, and return a DataFrame with the same shape as
    ``read_rows`` so the rest of the import pipeline is
    reusable for both file uploads and pasted text.
    """

    def test_unreadable_text_is_refused_without_pandas_text(self) -> None:
        with pytest.raises(ValueError) as excinfo:
            parse_pasted_text('a,b\n"x,1\n')
        assert 'could not be read as a table' in str(excinfo.value)
        assert 'tokenizing' not in str(excinfo.value)

    def test_parse_tab_separated(self) -> None:
        text = 'name\tquantity\tprice\nWidget A\t10\t5.50\nWidget B\t5\t3.00'
        df = parse_pasted_text(text)
        assert list(df.columns) == ['name', 'quantity', 'price']
        assert len(df) == 2
        assert str(df.iloc[0]['name']) == 'Widget A'

    def test_parse_comma_separated(self) -> None:
        text = 'name,quantity\nWidget,10\nOther,5'
        df = parse_pasted_text(text)
        assert list(df.columns) == ['name', 'quantity']
        assert len(df) == 2

    def test_parse_semicolon_separated(self) -> None:
        text = 'name;quantity\nWidget;10'
        df = parse_pasted_text(text)
        assert list(df.columns) == ['name', 'quantity']
        assert len(df) == 1

    def test_parse_skips_blank_lines(self) -> None:
        text = 'name,quantity\nWidget,10\n\n\nOther,5'
        df = parse_pasted_text(text)
        assert len(df) == 2

    def test_parse_empty_text_returns_empty_dataframe(self) -> None:
        df = parse_pasted_text('')
        assert df.empty
        assert list(df.columns) == []

    def test_parse_whitespace_only_returns_empty(self) -> None:
        df = parse_pasted_text('   \n  \n')
        assert df.empty

    def test_parse_strips_trailing_whitespace(self) -> None:
        text = 'name,quantity\n  Widget  , 10 \n'
        df = parse_pasted_text(text)
        assert str(df.iloc[0]['name']) == 'Widget'

    def test_a_comma_in_a_header_cell_does_not_steal_the_tab_split(self) -> None:
        """A paste from a spreadsheet is tabs; the comma inside a header
        cell is part of the name, not the delimiter."""
        text = 'Name, full\tQty\nWidget\t2'
        df = parse_pasted_text(text)
        assert list(df.columns) == ['Name, full', 'Qty']
        assert str(df.iloc[0]['Name, full']) == 'Widget'
        assert str(df.iloc[0]['Qty']) == '2'

    def test_a_comma_in_a_header_cell_does_not_steal_the_semicolon_split(self) -> None:
        text = 'Nazwa, opis;Ilosc\nWidżet;2'
        df = parse_pasted_text(text)
        assert list(df.columns) == ['Nazwa, opis', 'Ilosc']
        assert str(df.iloc[0]['Nazwa, opis']) == 'Widżet'

    def test_parse_single_column_no_delimiter(self) -> None:
        # Single column with header — common when pasting just names from Excel
        text = 'name\nWidget A\nWidget B'
        df = parse_pasted_text(text)
        assert len(df) == 2
        assert list(df.columns) == ['name']

    def test_parse_crlf_line_endings(self) -> None:
        text = 'name,qty\r\nWidget,10\r\nOther,5\r\n'
        df = parse_pasted_text(text)
        assert len(df) == 2
        assert list(df.columns) == ['name', 'qty']

    def test_a_paste_over_the_row_limit_is_refused(self) -> None:
        """A paste past the row cap is refused with the cap the file has.

        The paste went through its own pandas call with no limit, so the
        same sheet the file upload refuses sailed in through the clipboard.
        """
        from app.core.upload_validation import MAX_IMPORT_ROWS

        text = 'name,quantity\n' + '\n'.join(
            f'Item {i},{i}' for i in range(MAX_IMPORT_ROWS + 1)
        )
        with pytest.raises(ValueError, match=f'the limit is {MAX_IMPORT_ROWS}'):
            parse_pasted_text(text)


@pytest.mark.unit
class TestAnalyzePastedText:
    """5.1a — analyze endpoint shape: headers + preview_rows + total_rows.

    The response must match :func:`analyze_import_file` so the frontend
    can reuse the same preview UI for both file upload and paste.
    """

    @pytest.mark.asyncio
    async def test_analyze_returns_same_shape_as_file(self) -> None:
        text = 'name,quantity\nWidget A,10\nWidget B,5\nWidget C,3'
        result = await analyze_pasted_text(text)
        assert set(result.keys()) == {'headers', 'preview_rows', 'total_rows'}
        assert result['headers'] == ['name', 'quantity']
        assert result['total_rows'] == 3
        assert len(result['preview_rows']) == 3

    @pytest.mark.asyncio
    async def test_analyze_preview_capped_at_5(self) -> None:
        text = 'name,qty\n' + '\n'.join(f'Item {i},{i}' for i in range(10))
        result = await analyze_pasted_text(text)
        assert len(result['preview_rows']) == 5
        assert result['total_rows'] == 10

    @pytest.mark.asyncio
    async def test_analyze_empty_text(self) -> None:
        result = await analyze_pasted_text('')
        assert result['headers'] == []
        assert result['total_rows'] == 0
        assert result['preview_rows'] == []

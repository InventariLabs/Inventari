"""The mapping preview and the row count come from one read of the file.

An xlsx is a ZIP. Reading it twice — five rows for the preview, then the
whole thing again purely to count rows — pays the decompression cost twice
on a file somebody uploaded. The document importer had already fixed this
in a copy of its own, which left the shared helper the slower of the two.
"""

from __future__ import annotations

from typing import Any

import pytest
from pandas import DataFrame

from app.core import file_import


@pytest.mark.unit
@pytest.mark.asyncio
class TestAnImportFileIsParsedOnce:
    async def test_csv_is_read_once(self, monkeypatch: pytest.MonkeyPatch) -> None:
        reads: list[dict[str, Any]] = []
        original = file_import.pd.read_csv

        def counting_read_csv(*args: Any, **kwargs: Any) -> DataFrame:
            reads.append(kwargs)
            return original(*args, **kwargs)

        monkeypatch.setattr(file_import.pd, 'read_csv', counting_read_csv)

        rows = '\n'.join(f'Item {i},{i}' for i in range(12))
        result = await file_import.analyze_import_file(
            f'name,quantity\n{rows}\n'.encode(), 'data.csv'
        )

        assert len(reads) == 1, 'the file was parsed more than once'
        assert result['total_rows'] == 12
        assert len(result['preview_rows']) == file_import.PREVIEW_ROWS
        assert result['headers'] == ['name', 'quantity']

    async def test_a_file_that_cannot_be_read_refuses(self) -> None:
        """No half answer: a count of five from the preview alone is a
        number the reader would act on."""
        with pytest.raises(ValueError):
            await file_import.analyze_import_file(
                b'\xff\xfe\x00\x01\x02\x03', 'data.csv'
            )

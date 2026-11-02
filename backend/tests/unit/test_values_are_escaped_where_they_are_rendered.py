"""Three places a typed-in value decided how the output was parsed.

A filename goes into a header, an organization's name goes into someone
else's mail client, and a sort key went into an ORDER BY through getattr.
None of them were escaped where they were rendered; each was safe only for
as long as the value stayed ordinary.
"""

from __future__ import annotations

import pytest

from app.core.utils import content_disposition
from app.modules.warehouse.document_query_service import _SORTABLE_COLUMNS

pytestmark = pytest.mark.unit


class TestContentDisposition:
    def test_an_ordinary_name_still_reads_as_itself(self) -> None:
        header = content_disposition('invoice.pdf')

        assert 'filename="invoice.pdf"' in header
        assert header.startswith('attachment;')

    def test_a_quote_cannot_end_the_parameter_early(self) -> None:
        header = content_disposition('a".pdf')

        assert '"' not in header.split('filename="', 1)[1].split('"', 1)[0].replace(
            '_', ''
        )
        assert 'a_.pdf' in header

    @pytest.mark.parametrize('raw', ['a\r\nX-Evil: 1.pdf', 'a\nb.pdf', 'a\x00b.pdf'])
    def test_no_control_character_survives_into_the_header(self, raw: str) -> None:
        header = content_disposition(raw)

        assert '\r' not in header
        assert '\n' not in header
        assert '\x00' not in header

    def test_a_non_ascii_name_travels_in_the_starred_form(self) -> None:
        header = content_disposition('zamówienie.pdf')

        assert "filename*=UTF-8''zam%C3%B3wienie.pdf" in header
        # …and the plain parameter stays ASCII for clients that ignore it.
        plain = header.split('filename="', 1)[1].split('"', 1)[0]
        assert plain.isascii()

    def test_the_disposition_can_be_inline(self) -> None:
        assert content_disposition('a.png', 'inline').startswith('inline;')

    def test_no_name_means_no_parameters(self) -> None:
        assert content_disposition(None) == 'attachment'


class TestTheRegisterSortKey:
    def test_only_named_columns_are_orderable(self) -> None:
        assert set(_SORTABLE_COLUMNS) == {
            'number',
            'created_at',
            'completed_at',
            'type',
            'status',
        }

    def test_the_table_matches_the_routers_pattern(self) -> None:
        """The regex on the route and this table have to agree, or one of
        them is decoration. `document_date` is handled before the lookup."""
        import re

        from app.modules.warehouse import router as documents_router

        source = documents_router.__file__
        with open(source, encoding='utf-8') as handle:
            text = handle.read()
        pattern = re.search(r"pattern='\^\(([^)]+)\)\$'", text)
        assert pattern is not None
        allowed = set(pattern.group(1).split('|'))

        assert allowed == set(_SORTABLE_COLUMNS) | {'document_date'}

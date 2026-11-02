from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.dialects.postgresql import Insert

from app.modules.warehouse.document_numbering_service import (
    _get_type_label,
    _parse_seq_format,
    generate_number,
    highest_sequence,
    is_temporary_number,
    temporary_number,
)
from app.modules.warehouse.models.profile import DEFAULT_NUMBER_PADDING


@pytest.mark.unit
class TestGetTypeLabel:
    def test_returns_mapped_label(self) -> None:
        labels = {'IN': 'PZ', 'OUT': 'WZ'}
        assert _get_type_label('IN', labels) == 'PZ'

    def test_falls_back_to_the_short_code_when_the_type_has_no_label(self) -> None:
        """A table that skips a type must not leak the stored value.

        The label table names some types and not others; the one it skips
        used to print ``INTERNAL_OUT`` on a number whose screen said ``II``.
        """
        labels = {'IN': 'PZ'}
        assert _get_type_label('INTERNAL_OUT', labels) == 'II'

    def test_falls_back_to_the_short_code_when_labels_are_none(self) -> None:
        assert _get_type_label('INTERNAL_OUT', None) == 'II'

    def test_falls_back_to_the_short_code_when_labels_are_empty(self) -> None:
        assert _get_type_label('INTERNAL_OUT', {}) == 'II'


@pytest.mark.unit
class TestIsTemporaryNumber:
    def test_an_identifier_of_a_draft_is_temporary(self) -> None:
        assert is_temporary_number(temporary_number())

    def test_a_number_issued_under_a_draft_prefixed_format_is_not(self) -> None:
        """A format may print ``DRAFT-`` itself; its numbers are numbers.

        ``DRAFT-{TYPE}/{YEAR}/{SEQ:03d}`` is a legal profile format, so an
        issued number of the register can begin with ``DRAFT-``. Reading
        the prefix alone called that number an identifier, and the draft
        it belonged to was given a second number at confirmation — the
        register then held two numbers for one document and a gap where
        the first one was.
        """
        assert not is_temporary_number('DRAFT-IN/2026/0003')

    def test_an_issued_number_in_the_identifiers_whole_shape_is_not(self) -> None:
        """The identifier's shape in full can still be a number of the register.

        ``DRAFT-000000000{SEQ:03d}`` is a legal profile format: it issues
        ``DRAFT-000000000001``, twelve characters of hex, the identifier's
        shape entire. Confirmation read it as an identifier and drew a
        second number over one the register had already given out. What
        tells the two apart is where each one ends: the register appends
        the sequence last, so no number it issues ends on a letter, and
        the identifier does.
        """
        assert not is_temporary_number('DRAFT-000000000001')

    def test_the_identifier_ends_on_a_letter_no_number_can_end_on(self) -> None:
        """The half of the shape the register cannot print either.

        ``generate_number`` writes the sequence digits last, so a format
        ends every number it prints on a digit — whatever text it puts in
        front. The identifier ends on a hex letter, which is why no
        configured format can print one, and why an identifier stays
        recognisable whatever that format is.
        """
        identifier = temporary_number()
        assert identifier[-1] in 'ABCDEF'
        assert is_temporary_number(identifier)

    def test_a_number_of_the_register_is_not(self) -> None:
        assert not is_temporary_number('IN/2026/001')


@pytest.mark.unit
class TestParseSeqFormat:
    def test_parses_3_digits(self) -> None:
        placeholder, digits = _parse_seq_format('{TYPE}/{YEAR}/{SEQ:03d}')
        assert placeholder == '{SEQ:03d}'
        assert digits == 3

    def test_parses_5_digits(self) -> None:
        placeholder, digits = _parse_seq_format('{SEQ:05d}')
        assert placeholder == '{SEQ:05d}'
        assert digits == 5

    def test_defaults_when_no_match(self) -> None:
        placeholder, digits = _parse_seq_format('{TYPE}/{YEAR}/')
        assert placeholder == '{SEQ:03d}'
        assert digits == 3


def _stub_db(db: MagicMock, numbers: list[str]) -> None:
    """A session holding *numbers* and no counter row for this prefix yet.

    Seeding from the numbers already in use is what happens the first time a
    prefix is counted, which is the case every one of these tests is in.
    """
    db.execute = AsyncMock(return_value=MagicMock())

    async def scalar(statement: Any) -> int | None:
        # No counter to move; the one that is created answers with the number
        # it was started above, as the database would.
        if isinstance(statement, Insert):
            return int(statement.compile().params['next_value']) - 1
        return None

    db.scalar = scalar
    scalars = MagicMock()
    scalars.all.return_value = numbers
    db.scalars = AsyncMock(return_value=scalars)
    db.flush = AsyncMock()


def _make_profile(format_str: str, padding: int) -> MagicMock:
    profile = MagicMock()
    profile.numbering_format = format_str
    profile.number_padding = padding
    profile.type_labels = None
    return profile


@pytest.mark.unit
class TestGenerateNumber:
    @pytest.mark.asyncio
    async def test_first_document_starts_at_1(self) -> None:
        db = MagicMock()
        org_id = uuid4()

        mock_profile = _make_profile('{TYPE}/{YEAR}/{SEQ:03d}', 3)

        _stub_db(db, [])

        with patch(
            'app.modules.warehouse.document_numbering_service.get_profile',
            new_callable=AsyncMock,
            return_value=mock_profile,
        ):
            number = await generate_number(db, org_id, 'IN')

        assert number.endswith('/001')
        assert 'IN/' in number

    @pytest.mark.asyncio
    async def test_increments_from_last_number(self) -> None:
        db = MagicMock()
        org_id = uuid4()

        mock_profile = _make_profile('{TYPE}/{YEAR}/{SEQ:03d}', 3)

        _stub_db(db, ['IN/2026/042'])

        with patch(
            'app.modules.warehouse.document_numbering_service.get_profile',
            new_callable=AsyncMock,
            return_value=mock_profile,
        ):
            number = await generate_number(db, org_id, 'IN')

        assert number == 'IN/2026/043'

    @pytest.mark.asyncio
    async def test_default_format_when_no_profile(self) -> None:
        db = MagicMock()
        org_id = uuid4()

        _stub_db(db, [])

        with patch(
            'app.modules.warehouse.document_numbering_service.get_profile',
            new_callable=AsyncMock,
            return_value=None,
        ):
            number = await generate_number(db, org_id, 'IN')

        assert '/2026/' in number
        # The width the preset and the column use. It was 4 here and 3 there,
        # and which one an organization got depended on whether its profile
        # had been created yet.
        assert number.endswith(f'/{1:0{DEFAULT_NUMBER_PADDING}d}')

    @pytest.mark.asyncio
    async def test_type_label_substitution(self) -> None:
        db = MagicMock()
        org_id = uuid4()

        mock_profile = _make_profile('{TYPE_LABEL}/{YEAR}/{SEQ:04d}', 4)
        mock_profile.type_labels = {'IN': 'PZ', 'OUT': 'WZ'}

        _stub_db(db, [])

        with patch(
            'app.modules.warehouse.document_numbering_service.get_profile',
            new_callable=AsyncMock,
            return_value=mock_profile,
        ):
            number = await generate_number(db, org_id, 'IN')

        assert number.startswith('PZ/')

    @pytest.mark.asyncio
    async def test_5_digit_padding(self) -> None:
        db = MagicMock()
        org_id = uuid4()

        mock_profile = _make_profile('{TYPE}/{YEAR}/{SEQ:05d}', 5)

        _stub_db(db, [])

        with patch(
            'app.modules.warehouse.document_numbering_service.get_profile',
            new_callable=AsyncMock,
            return_value=mock_profile,
        ):
            number = await generate_number(db, org_id, 'IN')

        assert number.endswith('/00001')

    @pytest.mark.asyncio
    async def test_non_numeric_suffix_does_not_crash(self) -> None:
        """A legacy/manual number with a non-numeric suffix must not crash.

        Previously int(suffix) raised on e.g. 'IN/2026/999-MANUAL'; the next
        number is computed from the highest *numeric* suffix only.
        """
        db = MagicMock()
        org_id = uuid4()

        mock_profile = _make_profile('{TYPE}/{YEAR}/{SEQ:03d}', 3)

        # '999-MANUAL' sorts after '042' lexicographically but is non-numeric.
        _stub_db(
            db,
            [
                'IN/2026/999-MANUAL',
                'IN/2026/042',
            ],
        )

        with patch(
            'app.modules.warehouse.document_numbering_service.get_profile',
            new_callable=AsyncMock,
            return_value=mock_profile,
        ):
            number = await generate_number(db, org_id, 'IN')

        assert number == 'IN/2026/043'

    @pytest.mark.asyncio
    async def test_padding_overrides_format_token_width(self) -> None:
        """profile.number_padding wins over the {SEQ:Nd} token width.

        A raw format that encodes 3 digits must produce a 5-digit sequence
        when number_padding=5. This is the canonical case for org-wide
        alignment with purchase orders.
        """
        db = MagicMock()
        org_id = uuid4()

        mock_profile = _make_profile('{TYPE}/{YEAR}/{SEQ:03d}', 5)

        _stub_db(db, [])

        with patch(
            'app.modules.warehouse.document_numbering_service.get_profile',
            new_callable=AsyncMock,
            return_value=mock_profile,
        ):
            number = await generate_number(db, org_id, 'IN')

        assert number.endswith('/00001'), f'expected 5-digit padding, got {number!r}'

    @pytest.mark.asyncio
    async def test_padding_3_for_simple_preset(self) -> None:
        """Default Simple preset encodes number_padding=3 (matches {SEQ:03d})."""
        db = MagicMock()
        org_id = uuid4()

        mock_profile = _make_profile('{TYPE}/{YEAR}/{SEQ:03d}', 3)

        _stub_db(db, [])

        with patch(
            'app.modules.warehouse.document_numbering_service.get_profile',
            new_callable=AsyncMock,
            return_value=mock_profile,
        ):
            number = await generate_number(db, org_id, 'IN')

        assert number.endswith('/001'), f'expected 3-digit padding, got {number!r}'

    @pytest.mark.asyncio
    async def test_padding_6_produces_six_digit_sequence(self) -> None:
        """number_padding=6 must produce a 6-digit sequence even with {SEQ:04d}."""
        db = MagicMock()
        org_id = uuid4()

        mock_profile = _make_profile('{TYPE}/{YEAR}/{SEQ:04d}', 6)

        _stub_db(db, [])

        with patch(
            'app.modules.warehouse.document_numbering_service.get_profile',
            new_callable=AsyncMock,
            return_value=mock_profile,
        ):
            number = await generate_number(db, org_id, 'IN')

        assert number.endswith('/000001'), f'expected 6-digit padding, got {number!r}'


@pytest.mark.unit
class TestTheTypeTokenWritesAShortCode:
    """``{TYPE}`` writes a code a reader can say, never the stored value.

    The default format is ``{TYPE}/{YEAR}/{SEQ:03d}``, and the stored value
    is ``INTERNAL_OUT``: a fresh organization's internal issue came out
    ``INTERNAL_OUT/2026/001`` while every label on the screen said ``RW`` —
    and a search for ``OUT/2026/001`` found it, the one number containing
    the other.
    """

    @pytest.mark.parametrize(
        ('doc_type', 'code'),
        [
            ('IN', 'IN'),
            ('OUT', 'OUT'),
            ('INT', 'INT'),
            ('INTERNAL_IN', 'IR'),
            ('INTERNAL_OUT', 'II'),
            ('CORRECTION', 'COR'),
            ('ADJUSTMENT', 'ADJ'),
            ('SCRAP', 'SCR'),
        ],
    )
    @pytest.mark.asyncio
    async def test_every_type_writes_its_short_code(
        self, doc_type: str, code: str
    ) -> None:
        db = MagicMock()
        mock_profile = _make_profile('{TYPE}/{YEAR}/{SEQ:03d}', 3)
        _stub_db(db, [])

        with patch(
            'app.modules.warehouse.document_numbering_service.get_profile',
            new_callable=AsyncMock,
            return_value=mock_profile,
        ):
            number = await generate_number(db, uuid4(), doc_type)

        assert number.startswith(f'{code}/{datetime.now(UTC).year}/')

    @pytest.mark.asyncio
    async def test_a_legacy_spelling_numbers_under_its_canonical_code(self) -> None:
        db = MagicMock()
        mock_profile = _make_profile('{TYPE}/{YEAR}/{SEQ:03d}', 3)
        _stub_db(db, [])

        with patch(
            'app.modules.warehouse.document_numbering_service.get_profile',
            new_callable=AsyncMock,
            return_value=mock_profile,
        ):
            number = await generate_number(db, uuid4(), 'RW')

        assert number.startswith(f'II/{datetime.now(UTC).year}/')


class TestHighestSequenceReadsThePrefix:
    """The prefix is matched, not just measured.

    `_extract_seq` used to cut by the prefix's *length*, so any number of
    the same shape counted: 'PZ/2026/999' answered for the prefix
    'PO/2026/'. Both callers filter with `LIKE 'prefix%'` in SQL, which is
    why nothing broke — but the function is part of the warehouse module's
    public API, so its contract now binds callers this repository cannot see.
    """

    def test_a_number_of_another_type_does_not_count(self) -> None:
        assert highest_sequence(['PZ/2026/999'], 'PO/2026/') == 0

    def test_the_matching_prefix_still_counts(self) -> None:
        assert highest_sequence(['PO/2026/007', 'PO/2026/012'], 'PO/2026/') == 12

    def test_a_mixed_list_takes_only_its_own(self) -> None:
        numbers = ['PZ/2026/999', 'PO/2026/003', 'WZ/2026/500']

        assert highest_sequence(numbers, 'PO/2026/') == 3

    def test_a_non_numeric_suffix_is_still_skipped(self) -> None:
        assert highest_sequence(['PO/2026/042-A', 'PO/2026/007'], 'PO/2026/') == 7

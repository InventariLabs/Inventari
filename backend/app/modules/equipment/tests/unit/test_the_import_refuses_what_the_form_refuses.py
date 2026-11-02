"""Equipment import asks the questions the rest of the module already asks.

``status_machine.validate_transition`` is the gate three write paths call
before an asset changes state; import did not call it, so a cell reading
``BANANA`` became the status badge on the list and on the asset card — by
the same door the ``UNKNOWN_STATUS`` contract closed for the word
"UNKNOWN". Beside it, an unreadable price was swallowed by a bare ``pass``
and an unreadable date travelled into ``meta_data`` as text, in a field the
rest of the module reads as a date.

Each test here fails on the previous behaviour: the row counted as
imported.
"""

from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pandas as pd
import pytest

from app.core.contracts import UserContextDTO
from app.modules.equipment.import_service import execute_equipment_import


def _run(df: pd.DataFrame, mapping: dict[str, str]) -> Any:
    """Import *df* with every dependency but the row logic stubbed out."""
    org_id = uuid4()
    user = UserContextDTO(id=uuid4(), organization_id=org_id)
    return execute_equipment_import(
        AsyncMock(),
        b'fake',
        'test.csv',
        mapping,
        org_id,
        user,
    )


@pytest.mark.unit
class TestImportRefusesWhatTheFormRefuses:
    @pytest.fixture(autouse=True)
    def _stubs(self) -> Any:
        with (
            patch('app.modules.equipment.import_service.read_rows') as read_file,
            patch(
                'app.modules.equipment.import_service.resolve_storage_location_async',
                return_value=str(uuid4()),
            ),
            patch(
                'app.modules.equipment.import_service.resolve_category_async',
                return_value=None,
            ),
            patch('app.core.public_api.core_api') as core,
        ):
            core.items.create_async = AsyncMock(return_value=MagicMock(id=uuid4()))
            yield read_file

    async def test_a_status_outside_the_four_fails_the_row(self, _stubs: Any) -> None:
        _stubs.return_value = pd.DataFrame(
            {'name': ['Tester statusu'], 'status': ['BANANA']}
        )
        result = await _run(
            _stubs.return_value, {'name': 'name', 'equipment_status': 'status'}
        )
        assert result['imported'] == 0
        assert result['failed'] == 1
        assert 'BANANA' in result['errors'][0]['error']

    async def test_a_library_error_reaches_the_row_as_the_generic_sentence(
        self, _stubs: Any
    ) -> None:
        """A DTO's validation text names classes and echoes input; it stays in the log."""
        from sqlalchemy.exc import SQLAlchemyError

        _stubs.return_value = pd.DataFrame({'name': ['Laptop']})
        with patch(
            'app.core.public_api.core_api.items.create_async',
            AsyncMock(side_effect=SQLAlchemyError('INSERT INTO items secret')),
        ):
            result = await _run(_stubs.return_value, {'name': 'name'})
        assert result['failed'] == 1
        assert 'INSERT' not in result['errors'][0]['error']
        assert result['errors'][0]['error'] == 'An internal error occurred'

    async def test_a_malformed_location_id_does_not_echo_the_parser(
        self, _stubs: Any
    ) -> None:
        """``UUID()`` raises a plain ``ValueError`` in a library's words."""
        _stubs.return_value = pd.DataFrame({'name': ['Laptop']})
        with patch(
            'app.modules.equipment.import_service.resolve_storage_location_async',
            return_value='invalid-uuid',
        ):
            result = await _run(_stubs.return_value, {'name': 'name'})
        assert result['failed'] == 1
        error = result['errors'][0]['error']
        assert 'hexadecimal' not in error
        assert error == 'Could not resolve storage location'

    async def test_a_known_status_still_imports(self, _stubs: Any) -> None:
        _stubs.return_value = pd.DataFrame(
            {'name': ['Laptop'], 'status': ['MAINTENANCE']}
        )
        result = await _run(
            _stubs.return_value, {'name': 'name', 'equipment_status': 'status'}
        )
        assert result['imported'] == 1
        assert result['failed'] == 0

    async def test_the_refused_row_is_numbered_as_the_preview_numbers_it(
        self, _stubs: Any
    ) -> None:
        """Data rows from 1, the header not counted — one numbering per screen.

        The mapping step now shows the first rows and numbers them; a refusal
        counting the header pointed one row past the row it meant.
        """
        _stubs.return_value = pd.DataFrame(
            {'name': ['Dobry', 'Zly'], 'status': ['AVAILABLE', 'BANANA']}
        )
        result = await _run(
            _stubs.return_value, {'name': 'name', 'equipment_status': 'status'}
        )
        assert [error['row'] for error in result['errors']] == [2]

    async def test_a_price_that_is_not_a_number_fails_the_row(
        self, _stubs: Any
    ) -> None:
        """It used to be dropped in silence and the row counted as imported."""
        _stubs.return_value = pd.DataFrame({'name': ['Laptop'], 'cena': ['ABC']})
        result = await _run(
            _stubs.return_value, {'name': 'name', 'purchase_price': 'cena'}
        )
        assert result['imported'] == 0
        assert result['failed'] == 1
        assert 'ABC' in result['errors'][0]['error']

    async def test_a_date_that_is_not_a_date_fails_the_row(self, _stubs: Any) -> None:
        _stubs.return_value = pd.DataFrame(
            {'name': ['Laptop'], 'gwarancja': ['byle kiedy']}
        )
        result = await _run(
            _stubs.return_value, {'name': 'name', 'warranty_until': 'gwarancja'}
        )
        assert result['imported'] == 0
        assert result['failed'] == 1

    async def test_a_readable_date_lands_as_a_date(self, _stubs: Any) -> None:
        """What the row writes into ``meta_data`` is an ISO date, not the cell.

        The cell may say ``15.01.2026``; the field the rest of the module
        reads as a date has to hold ``2026-01-15``.
        """
        _stubs.return_value = pd.DataFrame(
            {'name': ['Laptop'], 'gwarancja': ['15.01.2026']}
        )
        from app.core.public_api import core_api

        result = await _run(
            _stubs.return_value, {'name': 'name', 'warranty_until': 'gwarancja'}
        )
        assert result['imported'] == 1
        create = cast(Any, core_api.items.create_async)
        payload = create.await_args.kwargs['data']
        assert payload.metadata['equipment']['warranty_until'] == '2026-01-15'

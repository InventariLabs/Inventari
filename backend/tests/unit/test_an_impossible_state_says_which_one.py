"""A database guard that fires says what it was guarding, not "500".

The CHECK constraints on the stock tables are the last line between a bug and
a shelf holding less than nothing. When one of them fires nothing recognised
it: the exception reached the outermost handler and the caller was told
"Internal Server Error", which is true and useless. The person who hit it
cannot tell a lost update from a network blip, and neither can the log.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy.exc import IntegrityError

from app.main import integrity_error_handler

pytestmark = pytest.mark.unit


def _violation(constraint: str) -> IntegrityError:
    """The exception shape asyncpg produces for a failed CHECK."""
    return IntegrityError(
        'UPDATE items ...',
        {},
        Exception(
            f'new row for relation "items" violates check constraint "{constraint}"'
        ),
    )


def _outgrown_hold() -> IntegrityError:
    """What the hold guard raises at commit when a grain promises more than it holds."""
    return IntegrityError(
        'COMMIT',
        {},
        Exception(
            'ck_stock_holds_within_stock: 6.000 reserved of a grain holding 5.000'
        ),
    )


class TestAGuardNamesItself:
    @pytest.mark.asyncio
    async def test_a_negative_quantity_is_a_conflict_with_a_message(self) -> None:
        response = await integrity_error_handler(
            None, _violation('ck_items_quantity_nonneg')
        )
        assert response.status_code == 409
        body = json.loads(bytes(response.body))
        assert body['detail']['code'] == 'STOCK_STATE_IMPOSSIBLE'
        assert body['detail']['message']
        assert 'Internal Server Error' not in body['detail']['message']

    @pytest.mark.asyncio
    async def test_holding_more_than_there_is_says_so(self) -> None:
        """The two failures are different questions and get different answers."""
        negative = await integrity_error_handler(
            None, _violation('ck_items_quantity_nonneg')
        )
        over_held = await integrity_error_handler(None, _outgrown_hold())
        assert (
            json.loads(bytes(negative.body))['detail']['message']
            != json.loads(bytes(over_held.body))['detail']['message']
        )

    @pytest.mark.asyncio
    async def test_an_unrecognised_violation_is_still_a_server_error(self) -> None:
        """The control: this handler claims only what it knows.

        A unique-key clash is somebody else's problem and a different bug;
        dressing it up as a stock conflict would be worse than the 500.
        """
        response = await integrity_error_handler(
            None,
            IntegrityError(
                'INSERT ...',
                {},
                Exception('duplicate key value violates unique constraint "ix_x"'),
            ),
        )
        assert response.status_code == 500

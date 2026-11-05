"""A sheet over the item limit says why every row failed.

The gate refuses the form and the scan with a sentence naming the limit;
the sheet meets the same gate row by row, and the importer's translator
had no branch for that refusal — it is not a row error, a value, a
validation or an application exception — so every row came back as "The
row could not be imported" and the reason went to the server log as a
traceback instead of to the reader. The batch keeps its own manners: it
does not stop half way and it leaves nothing behind. What it owes the
reader is a count that matches the sheet and a reason per row it names.
"""

import json
import logging

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.item import Item
from app.models.organization import Organization
from app.models.storage_location import StorageLocation

pytestmark = pytest.mark.integration

#: The sentence the gate gives the form and the scan; a sheet over the
#: limit must hand the reader the same one, row by row.
LIMIT_MESSAGE = 'Item limit reached for this organization. Upgrade to Inventari Cloud.'

MAPPING = {'name': 'Name', 'quantity': 'Quantity'}


def _rows(count: int) -> list[dict]:
    return [{'Name': f'Item {n}', 'Quantity': n} for n in range(1, count + 1)]


def _csv(count: int) -> bytes:
    return pd.DataFrame(_rows(count)).to_csv(index=False).encode()


def _import(client: TestClient, headers: dict, content: bytes, **form: str):
    return client.post(
        '/api/v1/items/import',
        files={'file': ('stock.csv', content, 'text/csv')},
        data={'mapping_json': json.dumps(MAPPING), **form},
        headers=headers,
    )


@pytest.mark.integration
class TestASheetOverTheItemLimitSaysWhy:
    def test_every_refused_row_names_the_limit(
        self,
        client: TestClient,
        auth_headers: dict,
        test_household: Organization,
        test_storage_location: StorageLocation,
        put_on_item_limit,
        caplog,
    ) -> None:
        """The cause travels with the row: five rows refused, five reasons,
        none of them the catch-all only the server log could explain — and
        no traceback in that log either, because an expected refusal is not
        a fault."""
        put_on_item_limit(test_household.id)

        with caplog.at_level(logging.ERROR, logger='app.core.import_sheet'):
            resp = _import(
                client,
                auth_headers,
                _csv(5),
                create_missing_locations='false',
                create_missing_categories='false',
            )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert (body['total'], body['imported'], body['updated'], body['failed']) == (
            5,
            0,
            0,
            5,
        )
        assert [e['row'] for e in body['errors']] == [1, 2, 3, 4, 5]
        assert [e['error'] for e in body['errors']] == [LIMIT_MESSAGE] * 5
        assert [
            r.message for r in caplog.records if 'Import row failed' in r.message
        ] == []

    def test_the_failure_count_is_the_servers_even_when_the_error_list_is_capped(
        self,
        client: TestClient,
        auth_headers: dict,
        test_household: Organization,
        test_storage_location: StorageLocation,
        put_on_item_limit,
    ) -> None:
        """A sheet of twelve over the limit: the report says twelve failed —
        the server's number, not the length of the capped list — and every
        row the list does carry names the limit, so the reader knows what
        to do from the response alone."""
        put_on_item_limit(test_household.id)

        resp = _import(
            client,
            auth_headers,
            _csv(12),
            create_missing_locations='false',
            create_missing_categories='false',
        )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body['failed'] == 12
        assert len(body['errors']) == 10
        assert [e['error'] for e in body['errors']] == [LIMIT_MESSAGE] * 10

    def test_below_the_limit_the_same_sheet_lands(
        self,
        client: TestClient,
        auth_headers: dict,
        test_household: Organization,
        test_storage_location: StorageLocation,
        db_session: Session,
    ) -> None:
        """The control the two refusals above rest on: the same sheet, the
        same door, no organization held at its limit — every row imports,
        so the refusals are the limit's doing and nothing else's."""
        resp = _import(
            client,
            auth_headers,
            _csv(3),
            create_missing_locations='false',
            create_missing_categories='false',
        )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert (body['total'], body['imported'], body['failed']) == (3, 3, 0)

        db_session.expire_all()
        names = {
            item.name
            for item in db_session.scalars(
                select(Item).where(Item.organization_id == test_household.id)
            ).all()
        }
        assert names == {'Item 1', 'Item 2', 'Item 3'}

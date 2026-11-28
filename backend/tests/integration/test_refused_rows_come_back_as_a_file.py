"""The product and partner imports hand the refused rows back as a file.

Every refusal is counted, the listed ones are the first few, and the file
holds all of them: corrected and uploaded alone, it adds what was missing.
"""

import base64
import io
import json

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.core.import_sheet import read_rows


def _csv(rows: list[dict]) -> bytes:
    return pd.DataFrame(rows).to_csv(index=False).encode()


def _post(client: TestClient, headers: dict, door: str, content: bytes, mapping):
    resp = client.post(
        f'/api/v1/{door}/import',
        files={'file': ('sheet.csv', content, 'text/csv')},
        data={'mapping_json': json.dumps(mapping)},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _refused(body: dict) -> pd.DataFrame:
    answer = body['refused_file']
    assert answer['filename'] == 'sheet-refused.csv'
    return read_rows(base64.b64decode(answer['content_base64']), answer['filename'])


def _again(frame: pd.DataFrame) -> bytes:
    buffer = io.BytesIO()
    frame.to_csv(buffer, index=False)
    return buffer.getvalue()


@pytest.mark.integration
class TestTheRefusedRowsComeBackAsAFile:
    def test_products(self, client: TestClient, auth_headers: dict):
        mapping = {
            'name': 'Item',
            'quantity': 'Qty',
            'unit': 'UoM',
            'location': 'Shelf',
        }
        rows = [{'Item': 'Good', 'Qty': 1, 'UoM': 'pcs', 'Shelf': 'x'}] + [
            {'Item': f'Bad {n}', 'Qty': 2, 'UoM': 'Units?', 'Shelf': f's{n}'}
            for n in range(12)
        ]

        body = _post(client, auth_headers, 'items', _csv(rows), mapping)

        assert (body['imported'], body['failed'], len(body['errors'])) == (1, 12, 10)
        frame = _refused(body)
        assert list(frame.columns) == ['Item', 'Qty', 'UoM', 'Shelf', 'Reason refused']
        assert list(frame['Item']) == [f'Bad {n}' for n in range(12)]
        assert all('Units?' in reason for reason in frame['Reason refused'])

        frame['UoM'] = 'pcs'
        fixed = _post(client, auth_headers, 'items', _again(frame), mapping)
        assert (fixed['imported'], fixed['failed']) == (12, 0), fixed
        assert fixed['refused_file'] is None

    def test_partners(self, client: TestClient, auth_headers: dict):
        mapping = {'name': 'Company', 'country': 'Country', 'company': 'Parent'}
        rows = [
            {'Company': 'Acme', 'Country': 'PL', 'Parent': ''},
            {'Company': 'Broken', 'Country': 'Nowhere', 'Parent': ''},
            {'Company': 'Ann', 'Country': '', 'Parent': 'Broken'},
        ]

        body = _post(client, auth_headers, 'partners', _csv(rows), mapping)

        assert (body['imported'], body['failed']) == (1, 2), body
        frame = _refused(body)
        # The company and its contact person come back together.
        assert list(frame['Company']) == ['Broken', 'Ann']

        frame.loc[0, 'Country'] = 'DE'
        fixed = _post(client, auth_headers, 'partners', _again(frame), mapping)
        assert (fixed['imported'], fixed['contacts'], fixed['failed']) == (1, 1, 0)

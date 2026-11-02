"""The mapping step is told about the file, not about its first rows.

The analyze preview stops at five rows, and the warning the items mapping
step shows — "not a single row carries a code" — used to be decided by
scanning those five. A sheet whose codes start below them warned about a
coded sheet; the mode the reader picked for its codes then ran without a
word. The counts travel with the analysis now, counted over the whole
frame, and the warning reads them.
"""

import pandas as pd
import pytest
from fastapi.testclient import TestClient


def _csv(rows: list[dict]) -> bytes:
    return pd.DataFrame(rows).to_csv(index=False).encode()


def _analyze(client: TestClient, headers: dict, content: bytes):
    return client.post(
        '/api/v1/items/import/analyze',
        files={'file': ('stock.csv', content, 'text/csv')},
        headers=headers,
    )


@pytest.mark.integration
class TestTheAnalysisCountsTheWholeFile:
    def test_codes_below_the_preview_window_still_count(
        self, client: TestClient, auth_headers: dict
    ):
        # Eight rows, the codes on the last two: the preview (five rows)
        # shows a Label Code column empty in every row it holds.
        rows = [{'Name': f'Thing {i}', 'Label Code': ''} for i in range(6)]
        rows += [
            {'Name': 'Thing 6', 'Label Code': 'A-006'},
            {'Name': 'Thing 7', 'Label Code': 'A-007'},
        ]
        resp = _analyze(client, auth_headers, _csv(rows))
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # The preview holds five rows and none of them carries a code —
        # and the count says so about the file, not about the preview.
        assert len(body['preview_rows']) == 5
        assert all(row['Label Code'] == '' for row in body['preview_rows'])
        assert body['filled_counts'] == {'Name': 8, 'Label Code': 2}

    def test_whitespace_is_not_a_code(self, client: TestClient, auth_headers: dict):
        # A cell of spaces is empty the way the import reads it, so the
        # count must read it the same way — else the warning would stay
        # quiet over a sheet whose column looks dressed but matches nothing.
        rows = [{'Name': 'Flour', 'Label Code': '   '} for _ in range(3)]
        resp = _analyze(client, auth_headers, _csv(rows))
        assert resp.status_code == 200, resp.text
        assert resp.json()['filled_counts'] == {'Name': 3, 'Label Code': 0}

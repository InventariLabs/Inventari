"""The scale measurement waits for what it times and samples what it needs.

``load_tests/scale/measure.py`` is a stdlib script outside the application,
loaded here by path. Its import is a background job that the request only
queues, a shelf's list is paged and says nothing about which of its records
carry an expiry date, and a stock take is complete only when every record is
counted.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(
    os.environ.get('INVENTARI_REPO_ROOT') or Path(__file__).resolve().parents[3]
)
_SCRIPT = _ROOT / 'load_tests' / 'scale' / 'measure.py'


@pytest.fixture(scope='module')
def measure():
    spec = importlib.util.spec_from_file_location('scale_measure', _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Api:
    """Answers a list path from rows it pages like the server, and job reads from a script."""

    def __init__(self, rows=(), jobs=()):
        self.rows, self.jobs, self.calls = list(rows), list(jobs), []

    def get(self, path):
        self.calls.append(path)
        query = dict(part.split('=') for part in path.split('?')[1].split('&'))
        limit, offset = int(query['limit']), int(query['offset'])
        return {'items': self.rows[offset : offset + limit]}

    def call(self, method, path, *args, **kwargs):
        self.calls.append(path)
        return 200, self.jobs.pop(0), 0.0, 0


def test_records_without_an_expiry_are_found_past_the_first_page(measure) -> None:
    rows = [{'id': n, 'expiry_date': 'any date'} for n in range(300)]
    rows += [{'id': 300 + n, 'expiry_date': None} for n in range(30)]
    api = _Api(rows)

    found = measure._shelf_records(api, 'shelf', lambda r: not r['expiry_date'], 20)

    assert [r['id'] for r in found] == list(range(300, 320))


def test_every_record_of_a_paged_list_is_read(measure) -> None:
    api = _Api([{'id': n} for n in range(350)])

    assert len(list(measure._paged(api, '/api/v1/stock-takes/x/items'))) == 350


def test_an_import_job_is_waited_for_until_it_is_done(measure, monkeypatch) -> None:
    monkeypatch.setattr(measure.time, 'sleep', lambda _: None)
    api = _Api(jobs=[{'id': 'j', 'status': 'running'}, {'id': 'j', 'status': 'done'}])

    job = measure._wait_for_job(
        api, {'id': 'j', 'status': 'running'}, measure.time.perf_counter()
    )

    assert job['status'] == 'done'
    assert len(api.calls) == 2

"""The sizes production ships, and the ones the guide tells a host to set, fit.

``DEPLOYMENT.md`` ("Sizing the services to the host") states what one backend
worker needs and which variables to set for a host. Two of its promises were
broken by the compose file itself: the shipped memory limit held fewer
workers than the shipped worker count, so the workers were killed for
outgrowing it, and PgBouncer's client limit was fixed in the compose file at
exactly what the guide's largest row opens, with no way to raise it from
``.env``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(
    os.environ.get('INVENTARI_REPO_ROOT') or Path(__file__).resolve().parents[3]
)

#: Connections one worker opens: the sync pool (20 + 10 overflow) and the
#: async pool (10 + 10) of ``app/database.py``, as ``docs/SCALING.md`` counts.
_CONNECTIONS_PER_WORKER = 50


def _services() -> dict:
    text = (_REPO_ROOT / 'docker-compose.prod.yml').read_text(encoding='utf-8')
    return yaml.safe_load(text)['services']


def _guide() -> str:
    return (_REPO_ROOT / 'DEPLOYMENT.md').read_text(encoding='utf-8')


def _default(value: object, variable: str) -> str:
    """The default of ``${VARIABLE:-default}`` in a compose value."""
    found = re.search(rf'\$\{{{variable}:-([^}}]+)\}}', str(value))
    assert found, f'{variable} is not read from .env in {value!r}'
    return found.group(1)


def _megabytes(size: str) -> int:
    number, unit = re.fullmatch(r'(\d+)([mg])', size.strip('`')).groups()
    return int(number) * (1024 if unit == 'g' else 1)


def _worker_megabytes() -> int:
    """What the guide says one worker needs, start-up size plus allowed growth."""
    found = re.search(r'about (\d+) MB each', _guide())
    assert found, 'the guide no longer states what a worker needs'
    return int(found.group(1))


def _sizing_rows() -> list[dict[str, str]]:
    """The guide's per-host table, one dict per host, keyed by column."""
    section = _guide().split('## Sizing the services to the host', 1)[1]
    lines = [line for line in section.splitlines() if line.startswith('| ')]
    header_at = next(i for i, line in enumerate(lines) if line.startswith('| Host '))
    header = [cell.strip(' `') for cell in lines[header_at].strip('|').split('|')]
    rows = []
    for line in lines[header_at + 1 :]:
        cells = [cell.strip(' `') for cell in line.strip('|').split('|')]
        if not re.fullmatch(r'\d+ GB', cells[0]):
            break
        rows.append(dict(zip(header, cells, strict=True)))
    return rows


def _shipped() -> dict[str, str]:
    backend = _services()['backend']
    pgbouncer = _services()['pgbouncer-main']
    return {
        'BACKEND_MEM_LIMIT': _default(backend['mem_limit'], 'BACKEND_MEM_LIMIT'),
        'WEB_CONCURRENCY': _default(backend['command'], 'WEB_CONCURRENCY'),
        'PGBOUNCER_MAX_CLIENT_CONN': _default(
            pgbouncer['environment']['MAX_CLIENT_CONN'], 'PGBOUNCER_MAX_CLIENT_CONN'
        ),
    }


def test_the_shipped_memory_holds_the_shipped_workers() -> None:
    shipped = _shipped()

    workers = int(shipped['WEB_CONCURRENCY'])
    assert _megabytes(shipped['BACKEND_MEM_LIMIT']) >= workers * _worker_megabytes()


def test_the_shipped_workers_stay_below_the_client_limit() -> None:
    shipped = _shipped()

    opened = int(shipped['WEB_CONCURRENCY']) * _CONNECTIONS_PER_WORKER
    assert opened < int(shipped['PGBOUNCER_MAX_CLIENT_CONN'])


def test_every_host_the_guide_sizes_fits_its_memory_and_the_client_limit() -> None:
    rows = _sizing_rows()
    shipped_limit = int(_shipped()['PGBOUNCER_MAX_CLIENT_CONN'])

    assert [row['Host'] for row in rows] == ['4 GB', '8 GB', '16 GB']
    for row in rows:
        workers = int(row['WEB_CONCURRENCY'])
        memory = _megabytes(row['BACKEND_MEM_LIMIT'])
        client_limit = int(row.get('PGBOUNCER_MAX_CLIENT_CONN') or shipped_limit)
        assert memory >= workers * _worker_megabytes(), row
        assert workers * _CONNECTIONS_PER_WORKER < client_limit, row


def test_the_shipped_column_says_what_the_compose_file_ships() -> None:
    """The guide's "Shipped" column is read by whoever leaves a variable unset."""
    shipped = _shipped()
    guide = _guide()

    for variable, value in shipped.items():
        assert re.search(rf'^\| `{variable}` \|.*\| `{value}` \|$', guide, re.M), (
            variable
        )

"""The shipped ``.env.example`` must not hand the backend a dead products-database URL.

``make dev-up`` copies ``.env.example`` to ``.env`` and ``docker-compose.yml``
passes ``PRODUCTS_DATABASE_URL`` into the backend container verbatim. A value
whose host is ``localhost`` therefore points the backend at itself, where nothing
listens on 5432, and the products database is behind the opt-in ``food`` profile
anyway. The nutrition module then fails its startup hook on every boot and the
only trace is an ERROR line in the container log.

The variable is optional — unset, the module skips the products database — so
the template carries it commented out, with the host a Docker deployment needs.
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlsplit

import pytest

#: The checkout. ``docker-compose.yml`` mounts it at ``/repo`` and names it in
#: ``INVENTARI_REPO_ROOT``; on the host it is three levels above this file.
_ROOT = Path(
    os.environ.get('INVENTARI_REPO_ROOT') or Path(__file__).resolve().parents[3]
)
_TEMPLATE = _ROOT / '.env.example'

_LOOPBACK = {'localhost', '127.0.0.1', '::1'}


def _active_value(name: str) -> str | None:
    for line in _TEMPLATE.read_text().splitlines():
        key, sep, value = line.partition('=')
        if sep and key.strip() == name:
            return value.strip()
    return None


@pytest.mark.unit
def test_the_template_is_readable_from_here() -> None:
    # A template this test cannot see would make the check below pass over
    # nothing, so the absence is a failure rather than a skip.
    assert _TEMPLATE.is_file(), (
        f'{_TEMPLATE} is not reachable: run on the host, or point '
        'INVENTARI_REPO_ROOT at the checkout (docker-compose.yml mounts it).'
    )


@pytest.mark.unit
def test_an_active_products_database_url_does_not_point_at_loopback() -> None:
    value = _active_value('PRODUCTS_DATABASE_URL')
    if not value:
        return  # unset or commented out: the module skips the products database
    host = urlsplit(value).hostname
    assert host not in _LOOPBACK, (
        f'.env.example sets PRODUCTS_DATABASE_URL to host {host!r}. Under Docker '
        'that is the backend container itself, so the nutrition module fails to '
        'start on every boot. Leave the variable commented out in the template.'
    )

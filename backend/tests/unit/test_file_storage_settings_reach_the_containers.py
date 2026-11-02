"""Every `FILE_STORAGE_*` setting reaches the containers that open the storage.

No compose service has an `env_file:`, so a name its `environment:` block does
not carry never arrives: `FILE_STORAGE_BACKEND=s3` in `.env` left the backend
on local disk, and the guide that tells an operator to switch to S3 with those
names did nothing. The demo reset is a container of its own and opens the same
storage to empty it, so it needs the names too — otherwise it empties a local
directory while the backend writes to the bucket.

The names are read from the settings object, so a setting added there cannot
go unlisted here.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.config import Settings

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(
    os.environ.get('INVENTARI_REPO_ROOT') or Path(__file__).resolve().parents[3]
)


def _storage_settings() -> list[str]:
    return sorted(n for n in Settings.model_fields if n.startswith('FILE_STORAGE_'))


def _environment(compose_file: str, service: str) -> dict[str, Any]:
    document = yaml.safe_load((_REPO_ROOT / compose_file).read_text(encoding='utf-8'))
    environment = document['services'][service]['environment']
    assert isinstance(environment, dict)
    return environment


def test_the_settings_are_found() -> None:
    # An empty list would make every check below pass over nothing.
    assert 'FILE_STORAGE_BACKEND' in _storage_settings()


@pytest.mark.parametrize(
    ('compose_file', 'service'),
    [
        ('docker-compose.yml', 'backend'),
        ('docker-compose.prod.yml', 'backend'),
        ('docker-compose.demo.yml', 'demo-reset'),
    ],
)
def test_the_service_that_opens_the_storage_is_given_its_settings(
    compose_file: str, service: str
) -> None:
    environment = _environment(compose_file, service)

    for name in _storage_settings():
        assert name in environment, (
            f'{name} is not in the environment of {service} in {compose_file}; '
            'set in .env alone it never reaches the container'
        )
        assert f'${{{name}' in str(environment[name]), (
            f'{name} in {compose_file} is pinned, not taken from .env'
        )

"""The publisher keys `module install` trusts reach the backend container.

The backend service has no `env_file:`, so a name its `environment:` block does
not interpolate is a setting that documents itself and does nothing. For the
signing keys that meant the module quickstart's steps were followed to the
letter — key generated, listed in `.env`, package signed — and the install still
said "no trusted signing keys are configured": the variable never arrived.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

#: The checkout. `docker-compose.yml` mounts it at `/repo` and names it in
#: `INVENTARI_REPO_ROOT`; on the host it is three levels above this file.
_REPO_ROOT = Path(
    os.environ.get('INVENTARI_REPO_ROOT') or Path(__file__).resolve().parents[3]
)

_NAME = 'MODULE_SIGNING_PUBLIC_KEYS'


@pytest.mark.parametrize('compose', ['docker-compose.yml', 'docker-compose.prod.yml'])
def test_the_stack_hands_the_signing_keys_to_the_backend(compose: str) -> None:
    text = (_REPO_ROOT / compose).read_text(encoding='utf-8')

    assert re.search(r'^\s+' + _NAME + r':\s*\$\{' + _NAME + r'[}:?-]', text, re.M), (
        f'{compose} does not interpolate {_NAME} into the backend environment, '
        'so a key listed in .env never reaches `manage.py module install`.'
    )

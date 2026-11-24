"""The production `make` targets run the stack of the route the install runs.

A `.env` that names COMPOSE_FILE (the published images) already says which
files make the stack; `-f docker-compose.prod.yml` would override it with the
build file alone, so the backup image would be built on the server. The test
reads the Makefile as text (the test container has no `make`): the targets go
through one variable that drops the flag when `.env` carries COMPOSE_FILE.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

_REPO_ROOT = Path(
    os.environ.get('INVENTARI_REPO_ROOT') or Path(__file__).resolve().parents[3]
)

_MAKEFILE = (_REPO_ROOT / 'Makefile').read_text(encoding='utf-8')


def _recipe(target: str) -> str:
    match = re.search(
        rf'^{target}:.*\n((?:[\t].*\n|ifeq.*\n|else.*\n|endif.*\n)+)', _MAKEFILE, re.M
    )
    assert match, f'no recipe for {target}'
    return match.group(1)


def test_the_route_is_read_from_the_env_file() -> None:
    assert re.search(
        r"^PROD_ON_IMAGES := \$\(shell grep -qs '\^COMPOSE_FILE=' \.env",
        _MAKEFILE,
        re.M,
    )
    assert re.search(
        r'^PROD_COMPOSE := docker compose \$\(if \$\(PROD_ON_IMAGES\),,-f docker-compose\.prod\.yml\)$',
        _MAKEFILE,
        re.M,
    )


def test_the_prod_targets_name_no_compose_file_themselves() -> None:
    for target in ('deploy', 'backup-verify', 'backup-status'):
        recipe = _recipe(target)
        assert 'docker-compose.prod.yml' not in recipe, target
        assert 'docker compose' not in recipe, target
        assert '$(PROD_COMPOSE)' in recipe, target


def test_deploy_pulls_on_the_images_and_builds_otherwise() -> None:
    recipe = _recipe('deploy')

    assert re.search(
        r'ifeq \(\$\(PROD_ON_IMAGES\),yes\)\n\t@\$\(PROD_COMPOSE\) pull\n'
        r'else\n\t@\$\(PROD_COMPOSE\) build --parallel\nendif\n',
        recipe,
    )
    assert '$(PROD_COMPOSE) up -d --force-recreate --no-build' in recipe

"""The production stack's name does not depend on the directory it was cloned into.

Compose names every named volume ``<project>_<volume>`` and, left alone, takes
the project from the checkout directory. An administrator who cloned anywhere
but ``/opt/inventari`` therefore holds volumes under a name nothing in the
repository mentions — and pinning the name later would bring every such
installation up on empty volumes, its data still under the old names. So the
production file declares the name now, the demo (which layers on top of it,
usually on the same host) declares a different one, and the guide lists the
volumes by their real names and tells a differently-cloned install what to do.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(
    os.environ.get('INVENTARI_REPO_ROOT') or Path(__file__).resolve().parents[3]
)


def _compose(name: str) -> dict:
    return yaml.safe_load((_REPO_ROOT / name).read_text(encoding='utf-8'))


def test_the_production_file_pins_the_project_name():
    assert _compose('docker-compose.prod.yml')['name'] == 'inventari'


def test_the_demo_does_not_share_the_production_project():
    """Layered on the production file and started from its own directory on the
    same host, the demo would otherwise be the same project — same volumes,
    and its nightly reset would empty production's uploads."""
    assert _compose('docker-compose.demo.yml')['name'] == 'inventari-demo'


def test_the_development_files_leave_the_name_to_the_stack_wrappers():
    """The pool wrappers set COMPOSE_PROJECT_NAME per stack; a fixed name in
    the base file would only win where nobody set one, and the dev stacks
    must keep their own."""
    for name in ('docker-compose.yml', 'docker-compose.override.yml'):
        assert 'name' not in _compose(name)


class TestDeploymentGuide:
    @pytest.fixture(scope='class')
    def guide(self) -> str:
        return (_REPO_ROOT / 'DEPLOYMENT.md').read_text(encoding='utf-8')

    @pytest.mark.parametrize(
        'volume', sorted(_compose('docker-compose.prod.yml')['volumes'])
    )
    def test_every_production_volume_is_listed_by_its_full_name(
        self, guide: str, volume: str
    ):
        assert f'`inventari_{volume}`' in guide

    def test_an_install_cloned_elsewhere_is_told_what_to_do(self, guide: str):
        assert 'COMPOSE_PROJECT_NAME' in guide

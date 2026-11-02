"""The installer's next steps belong to the installation it ran on.

The production frontend is nginx serving a bundle built into the image, so
``docker compose exec frontend npm run build`` there is ``exec: "npm":
executable file not found`` — and a bare ``restart backend`` cannot load a
module whose files only ever existed inside the image. The development stack
is the opposite: the frontend is a Vite dev server and the backend tree is
bind-mounted, so what production needs (``build`` + ``up -d``) is wasted work
and ``npm run build`` writes a bundle nothing serves.

What the installer prints is what the operator types next, so each runtime
gets the commands that work on it. The production compose file also has a
name of its own (``docker-compose.prod.yml``); a bare ``docker compose``
command on that host would start the development stack instead.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app.cli import _module_meta, _module_upgrade, module_packaging

PROD = 'docker compose -f docker-compose.prod.yml'
DEV = 'docker compose'

_REPO_ROOT = Path(
    os.environ.get('INVENTARI_REPO_ROOT') or Path(__file__).resolve().parents[3]
)


class TestTheDeploymentGivesTheInstallerItsTrees:
    """With no mount, an install writes into the container layer and is gone
    at the next `up -d`; with no frontend mount, half the module never lands.
    The compose file is the whole mechanism, so a removal has to fail here."""

    def test_both_module_trees_and_the_tracking_record_are_mounted(self) -> None:
        compose = (_REPO_ROOT / 'docker-compose.prod.yml').read_text(encoding='utf-8')

        assert './backend/app/modules:/app/app/modules' in compose
        assert './frontend/src/modules:/frontend-modules' in compose
        assert 'INVENTARI_FRONTEND_MODULES_DIR: /frontend-modules' in compose
        assert 'module_data:/app/data' in compose
        # The top-level declaration, alongside the other named volumes.
        assert '\n  module_data:\n' in compose

    def test_the_container_says_which_stack_it_is(self) -> None:
        compose = (_REPO_ROOT / 'docker-compose.prod.yml').read_text(encoding='utf-8')

        assert 'INVENTARI_DEPLOYMENT: production' in compose

    @pytest.mark.parametrize('guide', ['DEPLOYMENT.md', 'MODULES_GUIDE.md'])
    def test_the_guide_gives_the_write_access_step(
        self, guide: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The mounts are refused to a root-owned (or otherwise other-owned)
        # checkout until the container's user can write them. The guides give
        # that one command; pin it to the helper the installer prints, or the
        # two drift and the operator reads a command nothing else knows.
        monkeypatch.setenv('INVENTARI_DEPLOYMENT', 'production')
        text = (_REPO_ROOT / guide).read_text(encoding='utf-8')

        assert _module_meta.module_tree_permissions_command() in text


class TestTheWriteAccessCommand:
    def test_production_grants_the_containers_group_not_a_host_uid(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv('INVENTARI_DEPLOYMENT', 'production')

        command = _module_meta.module_tree_permissions_command()

        assert command.startswith(f'{PROD} exec --user root backend sh -c')
        assert 'chgrp -R appuser /app/app/modules /frontend-modules' in command
        assert 'chmod -R g+rwX /app/app/modules /frontend-modules' in command
        # The checkout belongs to the deployment's user; taking ownership of
        # it would hand their next `git checkout` a tree they cannot write.
        assert 'chown' not in command

    def test_development_names_the_development_stack(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        command = _module_meta.module_tree_permissions_command()

        assert command.startswith(f'{DEV} exec --user root backend sh -c')


@pytest.fixture(autouse=True)
def development_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv('INVENTARI_DEPLOYMENT', raising=False)


class TestTheCommandsTheInstallerPrints:
    def test_development_restarts_the_two_services(self) -> None:
        assert _module_meta.deployment_steps(backend=True, frontend=True) == [
            f'{DEV} restart backend',
            f'{DEV} restart frontend',
        ]

    def test_production_rebuilds_the_frontend_image_and_restarts_the_backend(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv('INVENTARI_DEPLOYMENT', 'production')

        assert _module_meta.deployment_steps(backend=True, frontend=True) == [
            f'{PROD} restart backend',
            f'{PROD} build frontend && {PROD} up -d frontend',
        ]

    def test_the_marker_is_read_each_time_not_once_at_import(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The commands are printed by a CLI process that inherited the
        # container's environment; caching the answer at import time would
        # make a test (or a run with the marker exported later) lie.
        assert not _module_meta.uses_production_compose()
        monkeypatch.setenv('INVENTARI_DEPLOYMENT', 'production')
        assert _module_meta.uses_production_compose()

    def test_a_headless_module_does_not_ask_for_a_frontend_action(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv('INVENTARI_DEPLOYMENT', 'production')

        steps = _module_meta.deployment_steps(backend=True, frontend=False)

        assert steps == [f'{PROD} restart backend']


class TestInstallPrintsThem:
    def _print(self, monkeypatch: pytest.MonkeyPatch, capsys, *, production: bool):
        if production:
            monkeypatch.setenv('INVENTARI_DEPLOYMENT', 'production')
        module_packaging._print_next_steps(
            'probe_mod',
            copied_backend=True,
            copied_frontend=True,
            frontend_missing=False,
        )
        return capsys.readouterr().out

    def test_development_gets_no_image_rebuild(
        self, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        out = self._print(monkeypatch, capsys, production=False)

        assert f'{DEV} restart backend' in out
        assert f'{DEV} restart frontend' in out
        assert 'npm run build' not in out
        assert 'docker-compose.prod.yml' not in out

    def test_production_gets_the_frontend_image_rebuild(
        self, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        out = self._print(monkeypatch, capsys, production=True)

        assert f'{PROD} restart backend' in out
        assert f'{PROD} build frontend && {PROD} up -d frontend' in out
        # The production frontend image ships nginx, not npm: the old line
        # failed with `exec: "npm": executable file not found`.
        assert 'npm run build' not in out


def _minimal_package(root: Path) -> Path:
    source = root / 'pkg'
    (source / 'backend').mkdir(parents=True)
    (source / 'backend' / 'manifest.json').write_text(
        json.dumps(
            {
                'name': 'probe_mod',
                'version': '0.2.0',
                'display_name': 'Probe',
                'module_type': 'community',
                'capabilities': [],
            }
        ),
        encoding='utf-8',
    )
    (source / 'module.yaml').write_text(
        'name: probe_mod\n'
        'version: "0.2.0"\n'
        'inventari_min_version: "0.1.0"\n'
        'requires: []\n'
        'components:\n  backend: true\n  frontend: false\n',
        encoding='utf-8',
    )
    return source


def _upgrade(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, production: bool
) -> None:
    tracking = tmp_path / 'tracking.json'
    tracking.write_text(
        json.dumps(
            {
                'modules': {
                    'probe_mod': {
                        'version': '0.1.0',
                        'source': './pkg',
                        'has_backend': True,
                        'has_frontend': False,
                        'declares_frontend': False,
                        'requires': [],
                    }
                }
            }
        ),
        encoding='utf-8',
    )
    monkeypatch.setattr(_module_meta, 'TRACKING_FILE', tracking)
    monkeypatch.setattr(
        _module_upgrade, '_swap_module_files', lambda *a, **k: (True, True)
    )
    monkeypatch.setattr(
        _module_upgrade, '_run_module_migrations_after_upgrade', lambda *a: None
    )
    monkeypatch.setattr(
        'app.cli.module_packaging._verify_package_signature',
        lambda *a, **k: {
            'signature_status': 'unsigned',
            'signature_key_id': '',
            'signature_verified_at': None,
        },
    )
    monkeypatch.setattr(
        _module_upgrade,
        '_parse_module_yaml',
        lambda _dir: {
            'name': 'probe_mod',
            'version': '0.2.0',
            'components': {'backend': True, 'frontend': False},
            'requires': [],
            'inventari_min_version': '0.1.0',
        },
    )
    if production:
        monkeypatch.setenv('INVENTARI_DEPLOYMENT', 'production')

    _module_upgrade._do_upgrade(
        _minimal_package(tmp_path),
        original_source='./pkg',
        source_rev=None,
        source_commit=None,
        signature_file=None,
        allow_unsigned=True,
        force=False,
    )


class TestUpgradePrintsThem:
    def test_development(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        _upgrade(tmp_path, monkeypatch, production=False)
        out = capsys.readouterr().out

        assert f'{DEV} restart backend' in out
        assert 'npm run build' not in out

    def test_production(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        _upgrade(tmp_path, monkeypatch, production=True)
        out = capsys.readouterr().out

        assert f'{PROD} restart backend' in out
        assert f'{PROD} build frontend' in out
        assert 'npm run build' not in out


class TestAnUnwritableModuleTree:
    def test_the_refusal_names_the_write_access_command_instead_of_eacces(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        # The production bind mounts are the checkout's own directories, which
        # may belong to root or any other uid. The installer runs as appuser
        # and used to get halfway through the copy before `[Errno 13]`, which
        # names neither the cause nor the remedy.
        monkeypatch.setenv('INVENTARI_DEPLOYMENT', 'production')
        source = _minimal_package(tmp_path)
        dest = tmp_path / 'backend-modules'
        dest.mkdir()
        monkeypatch.setattr(module_packaging, 'BACKEND_MODULES_DIR', dest)
        monkeypatch.setattr(module_packaging.os, 'access', lambda *_a: False)

        with pytest.raises(SystemExit):
            module_packaging._copy_module_files(
                'probe_mod',
                source,
                meta=_module_meta._parse_module_yaml(source),
                has_backend=True,
                has_frontend=False,
            )

        out = capsys.readouterr().out
        assert _module_meta.module_tree_permissions_command() in out
        assert 'Errno 13' not in out
        # Refused before the first file landed, so there is nothing to roll
        # back and nothing half-installed.
        assert not (dest / 'probe_mod').exists()

    def test_a_writable_tree_is_not_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv('INVENTARI_DEPLOYMENT', 'production')
        source = _minimal_package(tmp_path)
        monkeypatch.setattr(module_packaging, 'BACKEND_MODULES_DIR', tmp_path / 'dest')
        (tmp_path / 'dest').mkdir()

        copied_backend, copied_frontend = module_packaging._copy_module_files(
            'probe_mod',
            source,
            meta=_module_meta._parse_module_yaml(source),
            has_backend=True,
            has_frontend=False,
        )

        assert copied_backend is True
        assert copied_frontend is False
        assert (tmp_path / 'dest' / 'probe_mod' / 'manifest.json').is_file()

    def test_upgrade_refuses_before_moving_the_installed_tree(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        # Moving the old tree aside needs the same write access as copying the
        # new one in, and the two moves sit outside the restore path: a failure
        # between them leaves the backend half in a temporary directory.
        monkeypatch.setenv('INVENTARI_DEPLOYMENT', 'production')
        source = _minimal_package(tmp_path)
        backend_root = tmp_path / 'backend-modules'
        frontend_root = tmp_path / 'frontend-modules'
        installed_backend = backend_root / 'probe_mod'
        installed_frontend = frontend_root / 'probe_mod'
        installed_backend.mkdir(parents=True)
        installed_frontend.mkdir(parents=True)
        (installed_backend / 'old.py').write_text('OLD = True\n', encoding='utf-8')
        (installed_frontend / 'old.ts').write_text('export {};\n', encoding='utf-8')
        monkeypatch.setattr(_module_upgrade, 'BACKEND_MODULES_DIR', backend_root)
        monkeypatch.setattr(_module_upgrade, 'FRONTEND_MODULES_DIR', frontend_root)
        monkeypatch.setattr(module_packaging.os, 'access', lambda *_a: False)
        moved: list[tuple[object, ...]] = []
        monkeypatch.setattr(
            _module_upgrade.shutil, 'move', lambda *args: moved.append(args)
        )

        with pytest.raises(SystemExit):
            _module_upgrade._swap_module_files(
                'probe_mod', source, meta=_module_meta._parse_module_yaml(source)
            )

        out = capsys.readouterr().out
        assert _module_meta.module_tree_permissions_command() in out
        assert moved == []
        assert (installed_backend / 'old.py').is_file()
        assert (installed_frontend / 'old.ts').is_file()

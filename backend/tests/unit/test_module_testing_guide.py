"""Run the community test loop documented in the module testing guide.

The block is read from docs/MODULE_TESTING_GUIDE.md — never copied from it —
and the two placeholders the guide tells the author to fill in are the only
substitutions. It then runs for real against a temporary package repository
and a temporary checkout, with `docker` replaced by a stub that records its
arguments and snapshots the staged half when the test step is called: no
stack, no container, no database. The park paths live in /tmp as the guide
writes them, under a module name unique to the run, and are removed on the
way out.
"""

import os
import re
import shutil
import subprocess
import uuid
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest

MARKER = '<!-- testing-guide-check: community-loop -->'
INSTALLED_BACKEND = 'installed backend v1\n'
INSTALLED_FRONTEND = '// installed frontend v1\n'
PACKAGE_BACKEND = 'package backend v2\n'
PACKAGE_FRONTEND = '// package frontend v2\n'
PARKED = {'backend': 'parked backend v0\n', 'frontend': '// parked frontend v0\n'}
STUB_DOCKER = r"""#!/bin/sh
printf '%s\n' "$*" >> "$DOCKER_LOG"
case "$*" in
  "compose run"*) cp "$STAGED_BACKEND" "$STAGED_PROBE" ;;
esac
exit 0
"""


def _repo_root() -> Path:
    return Path(os.environ.get('INVENTARI_REPO_ROOT', Path(__file__).parents[3]))


def _documented_loop() -> str:
    guide = _repo_root() / 'docs' / 'MODULE_TESTING_GUIDE.md'
    match = re.search(
        re.escape(MARKER) + r'\s*```bash\n(.*?)\n```',
        guide.read_text(encoding='utf-8'),
        re.DOTALL,
    )
    assert match, f'No bash block follows {MARKER} in {guide}'
    return match.group(1)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def _park_paths(script: str, name: str) -> tuple[Path, Path]:
    """The two paths the block parks the installed halves at, name substituted."""
    found = re.findall(r'mv \S+ "([^"]*installed-(?:backend|frontend))"', script)
    assert len(found) == 2, f'Expected two parking moves in the block, got {found}'
    first, second = found
    return Path(first.replace('$NAME', name)), Path(second.replace('$NAME', name))


def _calls(loop: '_Loop') -> list[str]:
    if not loop.docker_log.exists():
        return []
    return loop.docker_log.read_text(encoding='utf-8').splitlines()


@dataclass(frozen=True)
class _Loop:
    name: str
    inv: Path
    parks: tuple[Path, Path]
    probe: Path
    docker_log: Path
    run: Callable[[], 'subprocess.CompletedProcess[str]']

    def half(self, kind: str) -> Path:
        if kind == 'backend':
            return self.inv / 'backend' / 'app' / 'modules' / self.name
        return self.inv / 'frontend' / 'src' / 'modules' / self.name


@pytest.fixture
def loop(tmp_path: Path) -> Iterator[_Loop]:
    name = f'guide_loop_{uuid.uuid4().hex[:12]}'
    inv = tmp_path / 'inventari'
    pkg = tmp_path / 'package'
    installed_backend = inv / 'backend' / 'app' / 'modules' / name
    installed_frontend = inv / 'frontend' / 'src' / 'modules' / name
    _write(installed_backend / 'router.py', INSTALLED_BACKEND)
    _write(installed_frontend / 'module.ts', INSTALLED_FRONTEND)
    _write(pkg / 'backend' / 'router.py', PACKAGE_BACKEND)
    _write(pkg / 'backend' / 'tests' / 'test_router.py', 'def test_router(): ...\n')
    _write(pkg / 'frontend' / 'module.ts', PACKAGE_FRONTEND)

    script = tmp_path / 'loop.sh'
    script.write_text(
        _documented_loop()
        .replace('INV=/path/to/inventari', f'INV={inv}')
        .replace('NAME=warranty_tracker', f'NAME={name}'),
        encoding='utf-8',
    )

    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    docker = bin_dir / 'docker'
    docker.write_text(STUB_DOCKER, encoding='utf-8')
    docker.chmod(0o755)

    staged = installed_backend / 'router.py'
    probe = tmp_path / 'staged-during-run.txt'
    docker_log = tmp_path / 'docker.log'

    def run() -> 'subprocess.CompletedProcess[str]':
        bash = shutil.which('bash')
        assert bash is not None, 'bash is required to execute the documented loop'
        env = {
            **os.environ,
            'PATH': f'{bin_dir}{os.pathsep}{os.environ["PATH"]}',
            'DOCKER_LOG': str(docker_log),
            'STAGED_BACKEND': str(staged),
            'STAGED_PROBE': str(probe),
        }
        return subprocess.run(
            [bash, str(script)],
            cwd=pkg,
            env=env,
            capture_output=True,
            text=True,
            encoding='utf-8',
            check=False,
        )

    parks = _park_paths(script.read_text(encoding='utf-8'), name)
    yield _Loop(
        name=name,
        inv=inv,
        parks=parks,
        probe=probe,
        docker_log=docker_log,
        run=run,
    )
    for park in parks:
        shutil.rmtree(park, ignore_errors=True)


@pytest.mark.unit
def test_stages_the_package_then_restores_the_installed_copy(loop: _Loop) -> None:
    result = loop.run()
    assert result.returncode == 0, result.stderr

    # the package's half was in place, in the checkout, while its tests ran
    assert loop.probe.read_text(encoding='utf-8') == PACKAGE_BACKEND
    assert _calls(loop) == [
        'compose stop backend',
        'compose run --rm --entrypoint uv backend run pytest '
        f'app/modules/{loop.name} -n 4 -q',
        'compose exec frontend npx tsc --noEmit',
        'compose start backend',
    ]

    # …and is gone again: what is installed is the copy step 2 parked
    backend_router = loop.half('backend') / 'router.py'
    frontend_module = loop.half('frontend') / 'module.ts'
    assert backend_router.read_text(encoding='utf-8') == INSTALLED_BACKEND
    assert not (loop.half('backend') / 'tests').exists()
    assert frontend_module.read_text(encoding='utf-8') == INSTALLED_FRONTEND
    for park in loop.parks:
        assert not park.exists()


@pytest.mark.unit
@pytest.mark.parametrize(
    'held',
    [('backend',), ('frontend',), ('backend', 'frontend')],
    ids=['backend-park', 'frontend-park', 'both-parks'],
)
def test_occupied_park_is_refused_before_any_installed_file_moves(
    loop: _Loop,
    held: Sequence[str],
) -> None:
    for park, kind in zip(loop.parks, ('backend', 'frontend'), strict=True):
        if kind in held:
            _write(park / 'marker.txt', PARKED[kind])

    result = loop.run()

    # the loop stops at the refusal and names the path in the way
    assert result.returncode != 0, result.stdout
    assert 'Refusing to stage' in result.stderr
    assert str(loop.parks[0] if 'backend' in held else loop.parks[1]) in result.stderr
    assert not loop.probe.exists()
    assert _calls(loop) == ['compose stop backend']

    # neither installed half was touched — even the one whose park was free
    backend_router = loop.half('backend') / 'router.py'
    frontend_module = loop.half('frontend') / 'module.ts'
    assert backend_router.read_text(encoding='utf-8') == INSTALLED_BACKEND
    assert frontend_module.read_text(encoding='utf-8') == INSTALLED_FRONTEND

    # the parked copies stand where they stood, with nothing nested inside
    for park, kind in zip(loop.parks, ('backend', 'frontend'), strict=True):
        if kind in held:
            assert (park / 'marker.txt').read_text(encoding='utf-8') == PARKED[kind]
            assert not (park / loop.name).exists()
        else:
            assert not park.exists()

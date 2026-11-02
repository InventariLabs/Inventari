"""The key-generation command the module docs document, run from the documents.

Both public documents carry the signing step — MODULES_GUIDE.md and
MODULE_QUICKSTART.md — and this gate reads the command out of them, never
copies it. The two must show the same command; the guide's copy must run as
written; and the key pair it produces must be accepted by the documented
`module sign` and `module install` steps. A copy garbled in either document
fails here.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from app.cli import _module_meta, module_packaging
from app.config import settings
from manage import app

GUIDE_KEYGEN = '<!-- modules-guide-check: keygen -->'
GUIDE_SIGN = '<!-- modules-guide-check: sign -->'
QUICKSTART_KEYGEN = '<!-- quickstart-check: keygen -->'

WRAPPER = ('docker', 'compose', 'exec', 'backend', 'uv', 'run', 'python')


def _repo_root() -> Path:
    return Path(os.environ.get('INVENTARI_REPO_ROOT', Path(__file__).parents[3]))


def _documented_command(document: Path, marker: str) -> str:
    match = re.search(
        re.escape(marker) + r'\s*```bash\n(.*?)\n```',
        document.read_text(encoding='utf-8'),
        re.DOTALL,
    )
    assert match, f'No bash block follows {marker} in {document}'
    return match.group(1)


def _command_args(block: str) -> list[str]:
    """The one command the block documents, comment lines aside."""
    body = '\n'.join(
        line for line in block.splitlines() if not line.lstrip().startswith('#')
    )
    return shlex.split(body.replace('\\\n', ''))


def _run_keygen(args: list[str], workspace: Path) -> subprocess.CompletedProcess[str]:
    """Run the documented key-generation command here.

    The command runs `python -c <script>` inside the backend container; here
    that is this interpreter, and `/modules-workspace` is the temporary
    workspace.
    """
    args = [arg.replace('/modules-workspace', str(workspace)) for arg in args]
    at = args.index('python')
    return subprocess.run(
        [sys.executable, *args[at + 1 :]],
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.unit
def test_the_guide_and_the_quickstart_show_the_same_key_generation_command() -> None:
    root = _repo_root()
    guide = _command_args(_documented_command(root / 'MODULES_GUIDE.md', GUIDE_KEYGEN))
    quickstart = _command_args(
        _documented_command(root / 'MODULE_QUICKSTART.md', QUICKSTART_KEYGEN)
    )
    assert guide == quickstart, (
        'MODULES_GUIDE.md and MODULE_QUICKSTART.md must show the same '
        f'key-generation command:\nguide:      {guide}\nquickstart: {quickstart}'
    )


@pytest.mark.unit
def test_the_key_generation_command_makes_a_key_pair_sign_and_install_accept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _repo_root()
    workspace = tmp_path / 'workspace'
    workspace.mkdir(parents=True)
    backend = tmp_path / 'app' / 'modules'
    frontend = tmp_path / 'frontend' / 'src' / 'modules'
    frontend.mkdir(parents=True)
    for module in (_module_meta, module_packaging):
        monkeypatch.setattr(module, 'BACKEND_MODULES_DIR', backend)
        monkeypatch.setattr(module, 'FRONTEND_MODULES_DIR', frontend)
    monkeypatch.setattr(_module_meta, 'TRACKING_FILE', tmp_path / 'tracking.json')
    monkeypatch.setattr(_module_meta, 'LEGACY_TRACKING_FILE', tmp_path / 'legacy.json')

    generated = _run_keygen(
        _command_args(_documented_command(root / 'MODULES_GUIDE.md', GUIDE_KEYGEN)),
        workspace,
    )
    assert generated.returncode == 0, (
        'The documented key-generation command does not run:\n' + generated.stderr
    )
    shown = re.search(r'public key: (\S+)', generated.stdout)
    assert shown, f'The command printed no public key:\n{generated.stdout}'

    sign_args = _command_args(
        _documented_command(root / 'MODULES_GUIDE.md', GUIDE_SIGN)
    )
    assert sign_args[: len(WRAPPER)] == list(WRAPPER), (
        f'Unexpected CLI wrapper: {sign_args}'
    )
    sign_args = [
        arg.replace('/modules-workspace', str(workspace))
        for arg in sign_args[len(WRAPPER) + 1 :]
    ]
    source = Path(sign_args[2])
    key_file = Path(sign_args[sign_args.index('--key') + 1])
    key_id = sign_args[sign_args.index('--key-id') + 1]
    assert key_file.is_file(), (
        f'The documented key-generation command did not write {key_file} — '
        'the documented sign step reads that file'
    )
    assert key_file.stat().st_mode & 0o077 == 0, (
        f'{key_file} holds the private signing key and must be readable by its '
        'owner only'
    )

    runner = CliRunner()
    scaffold = runner.invoke(
        app,
        ['module', 'new-community', source.name, '--output', str(source.parent)],
    )
    assert scaffold.exit_code == 0, f'{scaffold.output}\n{scaffold.exception!r}'
    signed = runner.invoke(app, sign_args)
    assert signed.exit_code == 0, f'{signed.output}\n{signed.exception!r}'

    monkeypatch.setattr(
        settings, 'MODULE_SIGNING_PUBLIC_KEYS', f'{key_id}={shown.group(1)}'
    )
    installed = runner.invoke(app, ['module', 'install', str(source)])
    assert installed.exit_code == 0, f'{installed.output}\n{installed.exception!r}'

    tracking = json.loads((tmp_path / 'tracking.json').read_text(encoding='utf-8'))
    entry = tracking['modules'][source.name]
    assert entry['signature_status'] == 'verified'
    assert entry['signature_key_id'] == key_id

"""Execute the community quickstart's local-development commands, in order.

Docker's exec prefix and workspace mount are adapted to this process and a
temporary directory. The CLI, scaffold, key generation, trust checks,
installer and validator are real; neither the checkout nor the running
installation is written to.
"""

import importlib.util
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
from manage import app


@pytest.mark.unit
def test_community_quickstart_commands_work_in_document_order(tmp_path, monkeypatch):
    repo = Path(os.environ.get('INVENTARI_REPO_ROOT', Path(__file__).parents[3]))
    document = (repo / 'MODULE_QUICKSTART.md').read_text(encoding='utf-8')
    steps = re.findall(
        r'<!-- quickstart-check: (\w+) -->\s*```bash\n(.*?)\n```',
        document,
        re.DOTALL,
    )
    assert [name for name, _ in steps] == ['scaffold', 'keygen', 'install', 'smoke']

    backend = tmp_path / 'app' / 'modules'
    frontend = tmp_path / 'frontend' / 'src' / 'modules'
    frontend.mkdir(parents=True)
    for module in (_module_meta, module_packaging):
        monkeypatch.setattr(module, 'BACKEND_MODULES_DIR', backend)
        monkeypatch.setattr(module, 'FRONTEND_MODULES_DIR', frontend)
    monkeypatch.setattr(_module_meta, 'TRACKING_FILE', tmp_path / 'tracking.json')
    monkeypatch.setattr(_module_meta, 'LEGACY_TRACKING_FILE', tmp_path / 'legacy.json')
    monkeypatch.chdir(tmp_path)

    prefix = [
        'docker',
        'compose',
        'exec',
        'backend',
        'uv',
        'run',
        'python',
    ]
    runner = CliRunner()
    for name, command in steps:
        body = '\n'.join(
            line for line in command.splitlines() if not line.lstrip().startswith('#')
        )
        args = shlex.split(body.replace('\\\n', ''))
        assert args[: len(prefix)] == prefix, f'Unexpected CLI wrapper: {command}'
        args = [
            arg.replace('/modules-workspace', str(tmp_path / 'workspace'))
            for arg in args[len(prefix) :]
        ]
        if args[0] == 'manage.py':
            result = runner.invoke(app, args[1:])
            assert result.exit_code == 0, (
                f'Quickstart step {name} failed:\n{command}\n{result.output}\n'
                f'{result.exception!r}'
            )
        else:
            # the key-generation step: `python -c <script>`, run for real
            assert args[0] == '-c', f'Unexpected command form: {command}'
            ran = subprocess.run(
                [sys.executable, *args], capture_output=True, text=True, check=False
            )
            assert ran.returncode == 0, (
                f'Quickstart step {name} failed:\n{command}\n{ran.stderr}'
            )

    assert (backend / 'warranty_tracker' / 'router.py').is_file()
    assert (frontend / 'warranty_tracker' / 'module.ts').is_file()
    tracking = json.loads((tmp_path / 'tracking.json').read_text())
    assert tracking['modules']['warranty_tracker']['has_frontend'] is True
    assert tracking['modules']['warranty_tracker']['signature_status'] == 'unsigned'


@pytest.mark.unit
def test_the_quickstarts_model_example_is_a_complete_mapping(tmp_path):
    """The block an author copies must configure as a mapper, not only read well.

    A class with no primary key fails when the mapper is built ("could not
    assemble any primary key columns"), so the document has to be executed to
    be checked.
    """
    from sqlalchemy.orm import configure_mappers

    from app.core.contracts import ModuleModelBase

    repo = Path(os.environ.get('INVENTARI_REPO_ROOT', Path(__file__).parents[3]))
    document = (repo / 'MODULE_QUICKSTART.md').read_text(encoding='utf-8')
    blocks = re.findall(r'```python\n(.*?)```', document, re.DOTALL)
    source = next(
        block for block in blocks if 'class Warranty(ModuleModelBase)' in block
    )
    example = tmp_path / 'quickstart_model.py'
    example.write_text(source, encoding='utf-8')

    spec = importlib.util.spec_from_file_location('quickstart_model', example)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        configure_mappers()
    finally:
        ModuleModelBase.registry.dispose()
        ModuleModelBase.metadata.clear()


# What the quickstart calls each check the commit hook runs -> the text of its
# `entry:` line in .pre-commit-config.yaml.
_RUN_BY_THE_COMMIT_HOOK = {
    'ruff': 'ruff check',
    'architecture': 'arch lint',
    'prettier': 'format:check',
    'eslint': 'npm run lint',
    'catalog snapshot': 'check-module-catalog',
}


@pytest.mark.unit
def test_the_quickstart_does_not_say_the_commit_hook_skips_what_it_runs():
    """Step 7 sends the author to `make lint` for what the hook leaves out.

    It once listed ruff and the architecture lint there while the next
    paragraph said the hook runs both — the hook's coverage is the one fact in
    that step the reader cannot check from the page.
    """
    repo = Path(os.environ.get('INVENTARI_REPO_ROOT', Path(__file__).parents[3]))
    document = (repo / 'MODULE_QUICKSTART.md').read_text(encoding='utf-8')
    hook = (repo / '.pre-commit-config.yaml').read_text(encoding='utf-8')
    entries = ' '.join(re.findall(r'^\s+entry: (.*)$', hook, re.MULTILINE))

    step = document.split('### 7. Check it', 1)[1].split('\n### ', 1)[0]
    make_lint = re.search(r'^make lint\b.*$', step, re.MULTILINE)
    assert make_lint is not None, 'step 7 no longer names `make lint`'
    claimed = re.search(r'commit hook checks the rest[^.]*\.', step, re.DOTALL)
    assert claimed is not None, 'step 7 no longer says what the commit hook checks'

    for word, fragment in _RUN_BY_THE_COMMIT_HOOK.items():
        assert fragment in entries, f'no hook entry runs {word!r} any more'
    named_as_left_out = [w for w in _RUN_BY_THE_COMMIT_HOOK if w in make_lint.group(0)]
    assert not named_as_left_out, (
        f'step 7 sends the reader to `make lint` for {named_as_left_out}, '
        'which the commit hook already runs'
    )
    assert {'ruff', 'architecture'} <= {
        w for w in _RUN_BY_THE_COMMIT_HOOK if w in claimed.group(0)
    }

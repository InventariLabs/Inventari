"""CI drift detection: verify committed CORE_API.md matches the generator output.

Runs the generator script via subprocess and compares its stdout against the
committed docs file. ``docker-compose.yml`` mounts the checkout read-only into
the backend container and names it in ``INVENTARI_REPO_ROOT``, so this measures
in the container as well as on the host and in CI.

A missing ``CORE_API.md`` is a failure, not a skip: skipping it reported green
for a check that had read nothing, and the document is tracked, so it is only
ever absent when the tree this reads is not the tree it claims to be.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Paths (resolved relative to this file)
# ---------------------------------------------------------------------------
_BACKEND_DIR = Path(__file__).resolve().parents[2]  # backend/
# `_BACKEND_DIR.parent` is the repository root in a checkout and `/` inside the
# backend container, which mounts nothing there. When docker-compose.yml points
# this at the mounted checkout, the test reads the same tree the host does.
_PROJECT_ROOT = Path(os.environ.get('INVENTARI_REPO_ROOT') or _BACKEND_DIR.parent)
_GENERATOR_SCRIPT = _BACKEND_DIR / 'scripts' / 'generate_core_api_reference.py'
_DOCS_PATH = _PROJECT_ROOT / 'docs' / 'subsystems' / 'CORE_API.md'
_SNAPSHOT_PATH = _BACKEND_DIR / 'app' / 'core' / 'core_api_snapshot.json'


def _rows_by_method(markdown: str) -> dict[tuple[str, str], str]:
    """Each table row keyed by ``(namespace, method)``.

    Method names repeat across namespaces (``items.count_async`` and
    ``users.count_async``), so a row is found under the
    ``### `core_api.<namespace>``` heading above it, never by its name alone.
    """
    rows: dict[tuple[str, str], str] = {}
    namespace = ''
    for line in markdown.splitlines():
        if line.startswith('### `core_api.'):
            namespace = line.split('`')[1].removeprefix('core_api.')
        elif namespace and line.startswith('| `'):
            rows[(namespace, line.split('`')[1])] = line
    return rows


@pytest.mark.integration
class TestCoreAPIDocsDrift:
    """Ensure the committed CoreAPI reference docs match the generator output."""

    def test_docs_are_in_sync_with_generator(self) -> None:
        """Generated markdown must exactly match the committed CORE_API.md."""
        assert _DOCS_PATH.exists(), (
            f'{_DOCS_PATH} is not reachable from here. It is tracked and '
            f'docker-compose.yml mounts it for the backend service, so its '
            f'absence means this check would read nothing while reporting green.'
        )

        # 1. Run the generator script — stdout contains the fresh markdown.
        gen_result = subprocess.run(
            [sys.executable, str(_GENERATOR_SCRIPT)],
            capture_output=True,
            text=True,
            cwd=str(_BACKEND_DIR),
        )
        assert gen_result.returncode == 0, (
            f'Generator script failed:\n{gen_result.stderr}'
        )
        generated = gen_result.stdout

        # 2. Read the committed docs file.
        committed = _DOCS_PATH.read_text(encoding='utf-8')

        # 3. Compare (strip trailing whitespace / newline for robustness).
        assert generated.rstrip() == committed.rstrip(), (
            'docs/subsystems/CORE_API.md is out of sync with the generator.\n'
            'Run `make generate-api-docs` to update.'
        )

    def test_every_snapshot_method_is_documented(self) -> None:
        """The reference lists every method the CoreAPI snapshot promises.

        The generator walked ``vars(cls)`` with ``inspect.isfunction``, which is
        false for a ``staticmethod`` object, so every static method dropped out
        unnoticed: ``core_api.email`` came out as a heading over an empty table.
        """
        snapshot = json.loads(_SNAPSHOT_PATH.read_text(encoding='utf-8'))
        gen_result = subprocess.run(
            [sys.executable, str(_GENERATOR_SCRIPT)],
            capture_output=True,
            text=True,
            cwd=str(_BACKEND_DIR),
        )
        assert gen_result.returncode == 0, gen_result.stderr
        rows = _rows_by_method(gen_result.stdout)
        missing = [
            f'{namespace}.{method}'
            for namespace, entry in snapshot['namespaces'].items()
            for method in entry['methods']
            if (namespace, method) not in rows
        ]
        assert missing == []

    def test_keyword_only_parameters_keep_their_marker(self) -> None:
        """A method whose snapshot has keyword-only parameters shows the ``*``.

        The generator wrote names, annotations and defaults but not the
        parameter kind, so ``get_global_stats_async(db, *, user)`` read as
        ``(db, user)`` — a call that raises — in a file the freshness check
        called up to date.
        """
        snapshot = json.loads(_SNAPSHOT_PATH.read_text(encoding='utf-8'))
        rows = _rows_by_method(_DOCS_PATH.read_text(encoding='utf-8'))
        lacking = []
        for namespace, entry in snapshot['namespaces'].items():
            for method, spec in entry['methods'].items():
                kinds = {param['kind'] for param in spec['params']}
                if 'KEYWORD_ONLY' in kinds and 'VAR_POSITIONAL' not in kinds:
                    row = rows.get((namespace, method), '')
                    if ', *,' not in row and '(*,' not in row:
                        lacking.append(f'{namespace}.{method}')
        assert lacking == []

"""Dev-only import guard — fast feedback on forbidden imports in module routers.

Runs ONLY when ``INVENTARI_ENV`` (or its ``ENVIRONMENT`` alias, as the CLI
guard reads it) says ``development``.  Scans ``app/modules/*/router.py``
at startup and raises a clear RuntimeError if any file imports directly from
``app.models`` or ``app.database`` instead of using the public CoreAPI.

This does NOT replace the CI architecture-lint (AST-based, catches more patterns).
It only provides faster local feedback for the most common violation.
"""

from __future__ import annotations

import os
from pathlib import Path


def check_module_router_imports() -> list[str]:
    errors: list[str] = []
    modules_dir = Path('app/modules')

    if not modules_dir.exists():
        modules_dir = Path(__file__).resolve().parent.parent / 'modules'
        if not modules_dir.exists():
            return errors

    forbidden_patterns = (
        'from app.models import',
        'from app.database import',
        'import app.models',
        'import app.database',
    )

    for router_path in sorted(modules_dir.glob('*/router.py')):
        try:
            content = router_path.read_text(encoding='utf-8')
        except (OSError, UnicodeDecodeError):
            continue

        for line_no, line in enumerate(content.splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith('#'):
                continue
            for pattern in forbidden_patterns:
                if pattern in stripped:
                    rel = (
                        router_path.relative_to(Path.cwd())
                        if router_path.is_relative_to(Path.cwd())
                        else router_path
                    )
                    errors.append(
                        f'{rel}:{line_no}: {pattern} — forbidden in module router. '
                        f"Use 'from app.core.public_api import core_api' instead. "
                        f'See MODULES_GUIDE.md#data-access'
                    )

    return errors


def run_dev_guard() -> None:
    # Settings ignores unknown keys, so the switch is read from the process
    # environment the way app.cli's disposable-install guard reads it:
    # INVENTARI_ENV is the name, ENVIRONMENT an alias, the name wins.
    declared = os.environ.get('INVENTARI_ENV')
    if declared is None:
        declared = os.environ.get('ENVIRONMENT', '')
    if declared.lower() != 'development':
        return

    errors = check_module_router_imports()
    if errors:
        msg = '\n'.join(errors)
        raise RuntimeError(
            f'Dev guard: forbidden imports detected in module routers:\n{msg}'
        )

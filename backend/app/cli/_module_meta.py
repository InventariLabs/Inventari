"""Metadata parsing, validation, and tracking helpers for community modules.

Extracted from module_packaging.py to keep file sizes manageable.
"""

import json
import os
import re
from pathlib import Path
from typing import TypedDict

import yaml  # type: ignore[import-untyped]

from app.core.logging import get_logger
from app.core.module_manifest_schema import MODULE_NAME_PATTERN
from app.core.module_tracking import (
    LEGACY_TRACKING_FILE,
    TRACKING_FILE,
    ModuleTrackingEntry,
)
from app.core.operator_error import OperatorError

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


def _get_reserved_module_names() -> frozenset[str]:
    """Names a community module may not be installed under.

    The union of everything the repository answers to with code — core
    feature names, virtual modules and the module directories it ships
    (``module_safety.reserved_module_names``). URL prefixes of core routes
    are reserved too and are refused at discovery; the CLI cannot see the
    built router without importing the whole app, so it relies on the
    discovery gate for those, which every hand-placed directory meets as
    well.
    """
    from app.core.module_safety import reserved_module_names

    return reserved_module_names()


def _reserved_name_refusal(name: str) -> str | None:
    """Why a community module may not be called *name*, or ``None``.

    One wording for every command that meets the rule: ``module install``
    refuses the name, and ``module validate`` and the scaffold refuse it
    first, before the author has written a module around it.
    """
    from app.core.module_safety import reserved_name_reason

    if name not in _get_reserved_module_names():
        return None
    reason = reserved_name_reason(name) or 'the core answers to it with code of its own'
    return f"'{name}' is reserved: {reason}. A community module cannot take that name."


# The same name rule manifest.json applies; module.yaml is read first.
_VALID_NAME_RE = re.compile(MODULE_NAME_PATTERN)


def _resolve_project_dirs() -> tuple[Path, Path, Path]:
    """Return (project_root, backend_modules_dir, frontend_modules_dir).

    Supports two layouts:
    1. Running on host: project_root = repo root, both backend/ and frontend/ exist.
    2. Running inside Docker (backend container): /app = backend/. The frontend
       tree is its sibling on the host and nothing under /app leads to it, so
       the dev compose file bind-mounts frontend/src/modules and names the
       mount point in INVENTARI_FRONTEND_MODULES_DIR. Without that mount an
       install can only ever land half of a module.

    INVENTARI_PROJECT_ROOT overrides the detection wholesale;
    INVENTARI_FRONTEND_MODULES_DIR overrides just the frontend half, which is
    the one a container can be missing.
    """
    env_root = os.environ.get('INVENTARI_PROJECT_ROOT')
    if env_root:
        project_root = Path(env_root).expanduser().resolve()
        backend_modules = project_root / 'backend' / 'app' / 'modules'
        frontend_modules = project_root / 'frontend' / 'src' / 'modules'
    else:
        # Heuristic: walk up from this file (app/cli/) until we find both backend/ and frontend/
        candidate = Path(__file__).parent
        for _ in range(6):
            candidate = candidate.parent
            if (candidate / 'backend').exists() and (candidate / 'frontend').exists():
                project_root = candidate
                backend_modules = project_root / 'backend' / 'app' / 'modules'
                frontend_modules = project_root / 'frontend' / 'src' / 'modules'
                break
        else:
            # Fallback: we are inside the backend container (/app = backend/).
            # backend modules are at /app/app/modules/; the frontend path below
            # exists only when the mount above put it there.
            project_root = Path('/app')
            backend_modules = project_root / 'app' / 'modules'
            frontend_modules = project_root.parent / 'frontend' / 'src' / 'modules'

    mounted_frontend = os.environ.get('INVENTARI_FRONTEND_MODULES_DIR')
    if mounted_frontend:
        frontend_modules = Path(mounted_frontend).expanduser().resolve()

    return project_root, backend_modules, frontend_modules


_PROJECT_ROOT, BACKEND_MODULES_DIR, FRONTEND_MODULES_DIR = _resolve_project_dirs()

# Tracking file location is owned by app.core.module_tracking (imported above)
# so services can read it without importing CLI internals. Kept as a module
# global here because tests monkeypatch ``_module_meta.TRACKING_FILE`` and the
# helpers below read it at call time.


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


class ModuleYaml(TypedDict):
    name: str
    version: str
    inventari_min_version: str
    author: str
    description: str
    license: str
    homepage: str
    requires: list[str]
    components: dict[str, bool]


# Alias — the canonical definition lives in app.core.module_tracking so that
# services never import CLI internals. Re-exported (also via module_packaging)
# for backward compatibility.
TrackingEntry = ModuleTrackingEntry


# ---------------------------------------------------------------------------
# Tracking file helpers
# ---------------------------------------------------------------------------


def _load_tracking() -> dict[str, TrackingEntry]:
    # An installation made before the registry moved out of the tracked tree
    # still has its list at the old path; reading it keeps those modules known.
    path = TRACKING_FILE if TRACKING_FILE.exists() else LEGACY_TRACKING_FILE
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        return data.get('modules', {})
    except (OSError, json.JSONDecodeError):  # the tracking file is best-effort
        return {}


def _save_tracking(modules: dict[str, TrackingEntry]) -> None:
    # The directory is deployment state, so it is not in the repository and
    # a fresh checkout does not have it yet.
    TRACKING_FILE.parent.mkdir(parents=True, exist_ok=True)
    TRACKING_FILE.write_text(
        json.dumps({'modules': modules}, indent=2, ensure_ascii=False) + '\n',
        encoding='utf-8',
    )


# ---------------------------------------------------------------------------
# module.yaml parsing & validation
# ---------------------------------------------------------------------------


def _parse_module_yaml(source_dir: Path) -> ModuleYaml:
    """Parse and validate module.yaml from *source_dir*. Raises ValueError on invalid content."""
    yaml_path = source_dir / 'module.yaml'
    if not yaml_path.exists():
        raise OperatorError(f'module.yaml not found in {source_dir}')

    try:
        raw = yaml.safe_load(yaml_path.read_text(encoding='utf-8'))
    except yaml.YAMLError as exc:
        raise OperatorError(f'module.yaml is not valid YAML: {exc}') from exc

    if not isinstance(raw, dict):
        raise OperatorError('module.yaml must be a YAML mapping.')

    name = raw.get('name', '')
    version = raw.get('version', '')

    if not isinstance(name, str) or not _VALID_NAME_RE.match(name):
        raise OperatorError(
            f"module.yaml 'name' must match ^[a-z][a-z0-9_]*$, got: {name!r}"
        )

    if not isinstance(version, str) or not version:
        raise OperatorError("module.yaml 'version' must be a non-empty string.")

    components = raw.get('components', {})
    if not isinstance(components, dict):
        raise OperatorError("module.yaml 'components' must be a mapping.")

    return ModuleYaml(
        name=name,
        version=str(version),
        inventari_min_version=str(raw.get('inventari_min_version', '')),
        author=str(raw.get('author', 'unknown')),
        description=str(raw.get('description', '')),
        license=str(raw.get('license', '')),
        homepage=str(raw.get('homepage', '')),
        requires=list(raw.get('requires', [])),
        components={
            'backend': bool(components.get('backend', True)),
            'frontend': bool(components.get('frontend', True)),
        },
    )


# ---------------------------------------------------------------------------
# Restart instructions
# ---------------------------------------------------------------------------

#: The compose file a production installation runs, as DEPLOYMENT.md spells it.
PRODUCTION_COMPOSE_FILE = 'docker-compose.prod.yml'


def uses_production_compose() -> bool:
    """Whether this process runs on a ``docker-compose.prod.yml`` installation.

    ``docker-compose.prod.yml`` sets ``INVENTARI_DEPLOYMENT=production`` on the
    backend service; the development stack sets nothing. Read on every call,
    not at import: the answer decides what the CLI tells the operator to type
    next, and that depends on the process the command runs in.

    ``DEBUG`` cannot answer it: the shipped development ``.env`` sets
    ``DEBUG=false`` too, which is why the production checklist asks for
    positive answers rather than looking for the word "production".
    """
    return os.environ.get('INVENTARI_DEPLOYMENT', '').strip().lower() == 'production'


def compose_command() -> str:
    """The compose invocation the next-step commands must use here.

    A bare ``docker compose`` on a production host picks up the development
    ``docker-compose.yml`` — the wrong stack, rebuilt from the wrong file.
    """
    if uses_production_compose():
        return f'docker compose -f {PRODUCTION_COMPOSE_FILE}'
    return 'docker compose'


def deployment_steps(*, backend: bool, frontend: bool) -> list[str]:
    """The host commands that make a module change take effect here.

    Development mounts the checkout into the backend container and serves the
    frontend with a Vite dev server, so a restart of each picks the change up.
    Production mounts the module trees into the backend too, but bakes the
    frontend bundle into its nginx image: only a rebuild puts a screen on the
    wire, and the production frontend image ships no npm to run one. The
    backend image is not rebuilt — its module directory is the checkout's.
    """
    compose = compose_command()
    steps: list[str] = []
    if backend:
        steps.append(f'{compose} restart backend')
    if frontend:
        steps.append(
            f'{compose} build frontend && {compose} up -d frontend'
            if uses_production_compose()
            else f'{compose} restart frontend'
        )
    return steps


#: Where the production compose file mounts the two module trees inside the
#: backend container. The installer writes through these paths; the host
#: directories behind them belong to whoever cloned the checkout.
MODULE_TREE_MOUNTS = ('/app/app/modules', '/frontend-modules')


def module_tree_permissions_command() -> str:
    """The host command that lets the container's user write the module trees.

    A deployment checkout belongs to the user who cloned it — ``root`` included
    — while the installer runs as the image's ``appuser`` (uid 1000). On a
    root-owned 0755 checkout the signature verifies and the copy then fails
    with ``EACCES``. This grants that user access through the group instead of
    changing the owner, so the deployment's own git operations keep working.
    Runs as root only for the two metadata changes, in the container that
    already has both trees mounted.
    """
    compose = compose_command()
    mounts = ' '.join(MODULE_TREE_MOUNTS)
    return (
        f'{compose} exec --user root backend sh -c '
        f"'chgrp -R appuser {mounts} && chmod -R g+rwX {mounts}'"
    )


# ---------------------------------------------------------------------------
# Safety validation (delegates to module_registry internals)
# ---------------------------------------------------------------------------


def _run_ast_validation(module_dir: Path) -> list[str]:
    """Run the same AST safety checks as module_registry on *module_dir*.

    Returns a list of violation strings (empty = clean).
    """
    from app.cli.module_validator import validate_manifest, validate_safety
    from app.core.module_manifest_schema import ModuleManifest

    declared_caps: list[str] = []
    try:
        manifest = ModuleManifest.load(module_dir)
        declared_caps = [str(c) for c in manifest.capabilities]
    except (FileNotFoundError, ValueError, TypeError, json.JSONDecodeError) as exc:
        logger.warning(
            'manifest.json unreadable for %s; declared_caps left empty',
            module_dir,
            exc_info=exc,
        )

    errors = validate_manifest(module_dir)
    errors += validate_safety(module_dir, declared_caps)
    return errors

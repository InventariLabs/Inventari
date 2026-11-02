"""Read access to the community-module install tracking file.

The tracking file (``community_modules.json``) is written by the CLI
installer (``app.cli._module_meta``). It records which modules an
installation has, which is deployment state and not repository content —
it used to sit in ``backend/`` as a tracked file, so installing any module
left a modified file the operator never edited and a conflict on the
documented update path (``git pull``). It now lives in ``backend/data/``,
which is ignored by git and shares a bind mount with the module files
themselves, so registry and modules cannot drift apart.

A registry left over at the old path is still read once, so an installation
that predates the move does not appear to have lost its modules; the next
write lands in the new place.

Services must read it through THIS module — importing the private CLI
helpers from ``app.services`` inverts the layering (services -> core,
never services -> cli).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TypedDict, cast

# app/core/module_tracking.py -> parents[2] == backend/ (container: /app/).
_BACKEND_DIR = Path(__file__).resolve().parents[2]
TRACKING_FILE = _BACKEND_DIR / 'data' / 'community_modules.json'
#: Where the registry lived while it was a tracked file. Read-only fallback.
LEGACY_TRACKING_FILE = _BACKEND_DIR / 'community_modules.json'


def tracking_file_to_read() -> Path:
    """The registry to read: the current one, or the pre-move one if that is all there is."""
    if TRACKING_FILE.exists():
        return TRACKING_FILE
    return LEGACY_TRACKING_FILE


class ModuleTrackingEntry(TypedDict, total=False):
    version: str
    source: str
    #: Ref requested at install time (tag or commit); absent for local sources.
    source_rev: str
    #: Commit actually checked out. A tag can be moved; this cannot — it is
    #: what tells you months later which code is really installed.
    source_commit: str
    installed_at: str
    has_backend: bool
    #: Whether the frontend half actually landed on this installation.
    has_frontend: bool
    #: Whether the package declared a frontend at all. The two differ exactly
    #: when an install could not reach the frontend module tree, and only that
    #: difference distinguishes a module that is headless by design from one
    #: that is headless because its install never finished.
    declares_frontend: bool
    requires: list[str]
    inventari_min_version: str
    #: Signature verification record: who signed the package and
    #: when the install verified it. For an unsigned install there was no
    #: verification, so there is no timestamp — the install record writes
    #: the field as an explicit null, and that null is what a reader sees:
    #: ``manage.py module list --json`` prints it, while the HTTP API leaves
    #: the field out of its module payload entirely.
    signature_status: str
    signature_key_id: str
    signature_verified_at: str | None
    #: Set by ``module upgrade``: the version this installation replaced and
    #: when. An installation that was upgraded and one that was installed
    #: fresh at the same version are otherwise indistinguishable, and they
    #: are not the same thing — the first one has data from before the bump.
    previous_version: str
    upgraded_at: str


def load_module_tracking() -> dict[str, ModuleTrackingEntry]:
    """Return the tracked community modules (``{}`` when missing/unreadable).

    Best-effort by design: a missing or corrupt tracking file must never
    block core functionality (module enable/disable, settings).
    """
    path = tracking_file_to_read()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    modules = data.get('modules', {})
    if not isinstance(modules, dict):
        return {}
    return cast('dict[str, ModuleTrackingEntry]', modules)

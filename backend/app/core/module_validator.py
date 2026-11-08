"""Module validation functions for the runtime registry.

Provides manifest validation and AST safety analysis used during module
discovery (``_registry_class.py``).  For the CLI variant used by
``manage.py module validate``, see ``app.cli.module_validator``.

Both share one scanner — :mod:`app.core.module_safety_analysis`. Only the
wording of the reported violations differs; see that module for why the two
were merged.
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app.core.logging import get_logger
from app.core.module_manifest_schema import ManifestNotReadableError, ModuleManifest
from app.core.module_safety import REPO_SHIPPED_MODULES
from app.core.module_safety_analysis import SafetyFinding, analyze_module_safety
from app.core.version import check_min_version

logger = get_logger(__name__)


@dataclass(frozen=True)
class RejectedModule:
    module_name: str
    reason: str


def _format_violation(finding: SafetyFinding) -> str:
    """Registry wording: the module is already known from the rejection record."""
    if finding.kind == 'parse_error':
        return f'Cannot parse {finding.rel_path}: {finding.subject}'
    if finding.kind == 'forbidden_import':
        return (
            f'FORBIDDEN import in {finding.rel_path}:{finding.lineno} '
            f'-> {finding.subject}'
        )
    if finding.kind == 'off_surface_import':
        hint = f' {finding.hint}' if finding.hint else ''
        return (
            f'Import outside the module SDK in {finding.rel_path}:{finding.lineno} '
            f'-> {finding.subject}.{hint}'
        )
    if finding.kind == 'forbidden_call':
        return (
            f'Forbidden function call in {finding.rel_path}:{finding.lineno} '
            f'-> {finding.subject}()'
        )
    noun = 'call' if finding.subject.endswith('()') else 'import'
    return (
        f'UNDECLARED capability "{finding.capability}" required for '
        f'{noun} "{finding.subject}" at {finding.rel_path}:{finding.lineno}'
    )


def _find_safety_violations(
    module_dir: Path, declared_capabilities: list[str]
) -> list[str]:
    """Performs AST analysis to find forbidden imports and dangerous function calls."""
    return [
        _format_violation(finding)
        for finding in analyze_module_safety(module_dir, declared_capabilities)
    ]


def untrusted_title_refusal(module_dir: Path, manifest: ModuleManifest) -> str | None:
    """Why the manifest's trust title is not *module_dir*'s to claim.

    Who stands behind the module is the one fact a store reader cannot
    guess. Until signatures exist (ADR-019), the registry is the only
    issuer of first-party standing, and it issues it to the directories
    the repository ships. A hand-placed directory keeping its manifest's
    'official' or 'core' would be certifying the file its own dropper
    wrote. A directory wearing a shipped name never reaches this check
    unless it is the repository's own path — the reserved-name guard
    already refused the rest.
    """
    if module_dir.name in REPO_SHIPPED_MODULES or manifest.module_type == 'community':
        return None
    return (
        f'untrusted module claims module_type {manifest.module_type!r}; '
        f'only a directory the repository ships may stand above community'
    )


def manifest_refusal(module_dir: Path, manifest: ModuleManifest) -> str | None:
    """Why discovery refuses a manifest it could read, or ``None``.

    The one answer for every gate in front of a start: discovery reads it
    here, and ``module validate``, ``module install`` and ``module upgrade``
    read it through ``app.cli.module_validator.validate_manifest``, so none
    of them can pass a package the next start refuses.
    """
    if manifest.name != module_dir.name:
        return (
            f"Manifest name '{manifest.name}' does not match directory "
            f"'{module_dir.name}'"
        )

    version_error = check_min_version(manifest.inventari_min_version)
    if version_error:
        # A module built against a newer platform half-works at best: it will
        # import a name that is not there yet, at some later moment, in front
        # of a user. Refusing it here costs the module and says why; the
        # rejection is recorded and the rest of the installation comes up.
        return f'Module {manifest.name!r} {version_error}.'

    return untrusted_title_refusal(module_dir, manifest)


def _validate_manifest(
    module_dir: Path, reject_fn: Callable[[str, str], None]
) -> ModuleManifest | None:
    """Validate manifest.json using the Pydantic schema.

    Returns a typed ``ModuleManifest`` on success, ``None`` on failure.
    """
    try:
        manifest = ModuleManifest.load(module_dir)
    except FileNotFoundError:
        reject_fn(module_dir.name, 'Missing manifest.json')
        return None
    except ManifestNotReadableError as exc:
        reject_fn(module_dir.name, f'Module {module_dir.name!r} {exc}.')
        return None
    except (OSError, TypeError, ValueError) as exc:
        reject_fn(module_dir.name, f'Invalid manifest.json: {exc}')
        return None

    refusal = manifest_refusal(module_dir, manifest)
    if refusal is not None:
        reject_fn(module_dir.name, refusal)
        return None

    return manifest

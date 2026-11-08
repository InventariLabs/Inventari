"""Pydantic schema for module manifest.json — single source of truth.

Usage:
    manifest = ModuleManifest.load(module_dir)          # load from manifest.json
    manifest = ModuleManifest(**raw_dict)               # parse from dict
    ModuleManifest.model_json_schema()                  # JSON Schema for IDE / CLI
"""

from __future__ import annotations

import json
import re
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from app.core.operator_error import OperatorError
from app.core.version import check_min_version

# Core keys such as 'org:settings:write' carry three segments, so a permission
# is one or more colon-separated segments — not exactly two.
#: The one rule for a module's name. ``module.yaml`` (read by the installer)
#: and ``manifest.json`` (read by the registry) both apply it.
MODULE_NAME_PATTERN = r'^[a-z][a-z0-9_]*$'

#: The ``manifest_version`` values this platform reads. A manifest declares the
#: shape of its own file; a platform that does not know that shape says so
#: instead of listing every field it fails to recognise.
SUPPORTED_MANIFEST_VERSIONS = (1,)

_FLOOR_RE = re.compile(r'\d+(\.\d+){0,2}')

_PERMISSION_RE = re.compile(r'^[a-z][a-z0-9_]*(:[a-z][a-z0-9_]*)+$')

# Mirrors SystemPermission in app.core.contracts._system_dtos. Duplicated
# deliberately: this schema is imported by the packaging CLI, which validates
# third-party manifests without loading the application's contract layer.
# Pinned against the enum by tests/unit/test_manifest_permissions.py.
CORE_PERMISSION_KEYS = frozenset(
    {
        'items:read',
        'items:write',
        'items:delete',
        'items:purge',
        'categories:read',
        'categories:write',
        'locations:read',
        'locations:write',
        'partners:read',
        'partners:write',
        'org:read',
        'org:settings:write',
        'org:members:write',
        'admin:access',
        'system:config:write',
    }
)

# The actions a module's permission keys are spelled with — "<module>:<action>".
# A key is stored by name in every organization's roles, so a word picked
# outside this list is renamed later only by a data migration in every
# installation. ``module validate`` warns about any other action; a module
# that needs one gives the reason in ``permission_action_exceptions``.
PERMISSION_ACTIONS = frozenset(
    {
        'read',  # see the module's records
        'write',  # create and change them in day-to-day work
        'manage',  # set up and remove what day-to-day work runs on
        'approve',  # sign off what someone else submitted or a rule held back
        'configure',  # change how the module behaves for the organization
        'consume',  # use stock up through the module (a recipe cooked)
        'extract',  # read data out of an outside source (a photograph)
    }
)


# Where a module sits in the store's taxonomy. The store used to read this off
# the frontend launcher tile, which only modules with a tile declare — six had
# none, so three of the eight filters returned nothing and answered "no modules
# found", the same sentence a failed search gets. It belongs to the module, not
# to its tile, so it is declared here and travels through the API.
ModuleCategory = Literal[
    'core',
    'business',
    'analytics',
    'integrations',
    'system',
    'other',
]


class ManifestCapability(StrEnum):
    """Capabilities a module can declare in manifest.json."""

    NETWORK = 'network'
    FILESYSTEM = 'filesystem'
    PROCESS = 'process'
    DATABASE = 'database'


class PermissionDef(BaseModel):
    """One permission a module defines, with the labels the admin UI renders.

    Mirrors the frontend ``PermissionDefinition`` field for field, so the
    frontend type becomes a projection of this contract rather than a parallel
    declaration that has to be kept in step by hand.

    Manifests may still write a bare string. It is widened here to a full
    definition with conventional label keys, which keeps the common case
    (``"maker:write"``) a one-liner while the catalog always receives objects.
    """

    model_config = ConfigDict(extra='forbid')

    key: str = Field(description='Permission key, "<module>:<action>"')
    label_key: str = Field(
        default='',
        description=(
            'i18n key for the human-readable label. Defaults to '
            '"<module>:permissions.<action>".'
        ),
    )
    description_key: str | None = Field(
        default=None,
        description='i18n key for a longer explanation shown in the RBAC matrix',
    )
    default_roles: list[str] = Field(
        default_factory=list,
        description=(
            'Role names that receive this permission when the module is enabled '
            'for an organization. Roles are never created — a name with no '
            'matching role in the org simply grants nothing.'
        ),
    )

    @field_validator('key')
    @classmethod
    def validate_key(cls, v: str) -> str:
        if not _PERMISSION_RE.match(v):
            raise OperatorError(
                f'permission key must be "<module>:<action>", got {v!r}'
            )
        return v

    @model_validator(mode='after')
    def default_label_key(self) -> PermissionDef:
        """Fill in the conventional label key when the manifest omits it."""
        if not self.label_key:
            namespace, _, action = self.key.partition(':')
            object.__setattr__(
                self, 'label_key', f'{namespace}:permissions.{action.replace(":", "_")}'
            )
        return self


def permission_action(key: str) -> str:
    """The action of ``"<module>:<action>"`` — everything after the module."""
    return key.partition(':')[2]


class ManifestNotReadableError(ValueError):
    """The manifest is for a platform other than this one; the message says which."""


def _unsupported_manifest_version(version: object) -> str:
    reads = ', '.join(str(v) for v in SUPPORTED_MANIFEST_VERSIONS)
    return (
        f'declares manifest_version {version!r}, which this platform does not '
        f'read (it reads: {reads})'
    )


def _platform_cannot_read(raw: object) -> str | None:
    """Why a manifest that failed strict parsing is for another platform, if it is.

    Looks at the raw JSON only, so it still works when the file carries a
    field this platform has never heard of.
    """
    if not isinstance(raw, dict):
        return None
    floor = raw.get('inventari_min_version')
    if isinstance(floor, str) and _FLOOR_RE.fullmatch(floor):
        if reason := check_min_version(floor):
            return reason
    version = raw.get('manifest_version')
    if isinstance(version, int) and version not in SUPPORTED_MANIFEST_VERSIONS:
        return _unsupported_manifest_version(version)
    return None


class ModuleManifest(BaseModel):
    """Schema for manifest.json files. Strict — unknown fields are rejected."""

    model_config = ConfigDict(extra='forbid')

    manifest_version: int = Field(
        default=1,
        description=(
            'Which shape of manifest.json this file is written in. Omitted '
            'means 1, the only shape so far. A platform that reads other '
            'shapes than the file declares refuses it by naming the ones it '
            'reads (SUPPORTED_MANIFEST_VERSIONS).'
        ),
    )
    name: str = Field(
        min_length=1,
        max_length=64,
        pattern=MODULE_NAME_PATTERN,
        description='Module identifier (must match directory name)',
    )
    version: str = Field(
        # Anchored at both ends, as ``app.core.version.parse_version`` is: a
        # suffix (``0.3.0-beta``, ``1.0.0.5``) validated here and then could
        # not be compared by the upgrade check or the version ceiling.
        pattern=r'^\d+\.\d+\.\d+$',
        description='Version as MAJOR.MINOR.PATCH, numbers only',
    )
    inventari_min_version: str = Field(
        default='',
        pattern=r'^(\d+(\.\d+){0,2})?$',
        description=(
            'Oldest platform version the module is known to run on. Empty '
            'means no constraint — the honest answer for a module nobody has '
            'placed against a floor. The registry refuses to load a module '
            'whose floor is above the running platform, so this is a promise '
            'the installation checks, not a note.'
        ),
    )
    capabilities: list[ManifestCapability] = Field(
        default_factory=list,
        description=(
            "Import capabilities the AST safety scan checks a module's import "
            'statements against by literal name (see '
            'module_safety.CAPABILITY_MAP) — a review aid, not a security '
            'sandbox (ADR-019). Not permissions — those go in "permissions".'
        ),
    )
    permissions: list[PermissionDef] = Field(
        default_factory=list,
        description=(
            'Permissions the module defines, either as "<module>:<action>" '
            'strings or as objects with label keys and default roles. Keys must '
            "sit in the module's own namespace; core keys may be listed to "
            'declare a dependency but are not redefined by the module. The '
            'action is one of read, write, manage, approve, configure, consume '
            'and extract; any other is listed in "permission_action_exceptions".'
        ),
    )
    permission_action_exceptions: dict[str, str] = Field(
        default_factory=dict,
        description=(
            'Permission keys whose action stands outside the vocabulary, each '
            'with the reason it does. Without a reason such a key draws a '
            'validation warning, and so does an entry naming a key the module '
            'does not define or one the vocabulary already covers.'
        ),
    )
    display_name: str | None = Field(
        default=None,
        max_length=128,
        description='Human-readable name (falls back to name.title())',
    )
    description: str | None = Field(
        default=None,
        max_length=512,
        description='Short module description',
    )
    icon: str | None = Field(
        default=None,
        description='Lucide icon name',
    )
    # Required on purpose: the trust level is the one fact a store reader
    # cannot guess, and a manifest that omits it used to fall back to
    # 'community' — the lowest level — without declaring anything.
    module_type: Literal['core', 'official', 'cloud', 'community'] = Field(
        description='Module classification: who stands behind this module',
    )
    is_reference: bool = Field(
        default=False,
        description=(
            'A module that exists to show how modules are written. It stays '
            'registered, importable and testable — the scaffold copies it — '
            'but it is not offered in the store and not switched on for an '
            'organization that has expressed no opinion. Nobody installs a '
            'worked example next to their warehouse documents.'
        ),
    )
    category: ModuleCategory = Field(
        default='other',
        description=(
            'Where the module belongs in the store taxonomy. "other" is the '
            'honest answer for a module that fits none of the buckets — the '
            'store shows that group only when something is in it.'
        ),
    )
    requires: list[str] = Field(
        default_factory=list,
        description='Module names this module depends on',
    )
    optional_requires: list[str] = Field(
        default_factory=list,
        description=(
            'Module names this one integrates with but does not depend on. '
            'Enabling is allowed without them; the store warns instead. '
            'Validated like "requires" so a mistyped name fails loudly.'
        ),
    )
    requires_api_key: bool = Field(
        default=False,
        description='Whether the module requires an external API key',
    )
    has_settings_schema: bool = Field(
        default=False,
        description=(
            'Whether the module exposes module-level settings — that is, '
            'whether BaseModule.get_settings_schema returns a schema. The '
            'method is the implementation; this is the declaration, so the '
            'fact can be read without importing Python. Pinned against the '
            'method by tests/unit/test_manifest_settings_schema.py.'
        ),
    )
    author: str | None = Field(
        default=None,
        max_length=128,
        description='Module author',
    )
    license: str | None = Field(
        default=None,
        max_length=64,
        description='License identifier (e.g. "MIT", "Apache-2.0")',
    )
    homepage: str | None = Field(
        default=None,
        max_length=256,
        description=(
            'Project page for the module. Carried from module.yaml at install '
            'time and exposed through the store API.'
        ),
    )

    # `capabilities` needs no validator — the ManifestCapability enum rejects
    # anything outside the capability set, which is what the old hand-rolled
    # "must be non-empty strings" check could never do.

    @model_validator(mode='after')
    def manifest_version_is_one_we_read(self) -> ModuleManifest:
        if self.manifest_version not in SUPPORTED_MANIFEST_VERSIONS:
            raise OperatorError(_unsupported_manifest_version(self.manifest_version))
        return self

    @field_validator('permissions', mode='before')
    @classmethod
    def widen_permission_strings(cls, v: object) -> object:
        """Accept the shorthand ``"maker:write"`` alongside full objects."""
        if not isinstance(v, list):
            raise OperatorError('permissions must be a list')
        return [{'key': p} if isinstance(p, str) else p for p in v]

    @model_validator(mode='after')
    def permissions_stay_in_namespace(self) -> ModuleManifest:
        """A module may define keys under its own name, and nothing else.

        Without this a module could declare ``admin:access`` and have the
        registry publish it as its own — the catalog would then offer an admin
        grant that looks like it belongs to a third-party module.

        Core keys are the one allowed exception, and only as a *dependency*
        statement: a module that reads items legitimately names ``items:read``.
        Such keys are filtered out of the module's catalog section, since the
        system section already defines them (see ``defined_permissions``).
        """
        for perm in self.permissions:
            namespace = perm.key.split(':', 1)[0]
            if namespace != self.name and perm.key not in CORE_PERMISSION_KEYS:
                raise OperatorError(
                    f'permission {perm.key!r} is outside the "{self.name}:" '
                    f'namespace and is not a core permission'
                )
        return self

    @property
    def unexplained_actions(self) -> list[str]:
        """Defined keys whose action is outside the vocabulary, with no reason."""
        return [
            p.key
            for p in self.defined_permissions
            if permission_action(p.key) not in PERMISSION_ACTIONS
            and not self.permission_action_exceptions.get(p.key, '').strip()
        ]

    @property
    def idle_action_exceptions(self) -> list[str]:
        """Exceptions that explain no key: not defined here, or in the vocabulary."""
        outside = {
            p.key
            for p in self.defined_permissions
            if permission_action(p.key) not in PERMISSION_ACTIONS
        }
        return [key for key in self.permission_action_exceptions if key not in outside]

    @property
    def defined_permissions(self) -> list[PermissionDef]:
        """Only the permissions this module actually owns.

        Core keys listed as dependencies are excluded: the catalog publishes
        them once, in the system section.
        """
        return [p for p in self.permissions if p.key not in CORE_PERMISSION_KEYS]

    @field_validator('requires', mode='before')
    @classmethod
    def validate_requires(cls, v: list[str]) -> list[str]:
        if not isinstance(v, list):
            raise OperatorError('requires must be a list')
        for dep in v:
            if not isinstance(dep, str) or not dep.strip():
                raise OperatorError(f'requires must be non-empty strings, got {dep!r}')
        return v

    @field_validator('optional_requires', mode='before')
    @classmethod
    def validate_optional_requires(cls, v: list[str]) -> list[str]:
        if not isinstance(v, list):
            raise OperatorError('optional_requires must be a list')
        for dep in v:
            if not isinstance(dep, str) or not dep.strip():
                raise OperatorError(
                    f'optional_requires must be non-empty strings, got {dep!r}'
                )
        return v

    @classmethod
    def load(cls, module_dir: Path) -> ModuleManifest:
        """Load and validate manifest.json from a module directory.

        Raises FileNotFoundError if manifest.json is missing.
        Raises ValidationError if manifest.json is invalid.
        """
        manifest_path = module_dir / 'manifest.json'
        if not manifest_path.exists():
            raise FileNotFoundError(f'manifest.json not found in {module_dir}')
        raw = json.loads(manifest_path.read_text(encoding='utf-8'))
        try:
            return cls(**raw)
        except ValidationError as exc:
            # The strict parse is the wrong witness for a manifest written
            # for a newer platform: a field it does not know is reported as
            # "extra inputs", when the useful sentence is the floor.
            reason = _platform_cannot_read(raw)
            if reason:
                raise ManifestNotReadableError(reason) from exc
            raise

    def to_dict(self) -> dict[str, object]:
        """Serialize to plain dict (excludes None values for compact output)."""
        return self.model_dump(exclude_none=True)

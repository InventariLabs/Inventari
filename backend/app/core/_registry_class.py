import importlib
from collections.abc import Collection
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import select

from app.core.logging import get_logger
from app.core.module_manifest_schema import ModuleManifest, PermissionDef
from app.core.module_safety import (
    REPO_SHIPPED_MODULES,
    TRUSTED_SHIPPED_MODULES,
    reserved_module_names,
    reserved_name_reason,
)
from app.core.module_validator import (
    RejectedModule,
    _find_safety_violations,
    _validate_manifest,
)
from app.core.modules import BaseModule

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)

#: Where the repository's own module directories live. A discovered
#: directory keeps a reserved name only when it IS this path — the real
#: ``app/modules/<name>`` — never a same-named directory somewhere else.
REPO_MODULES_ROOT = Path(__file__).parent.parent / 'modules'


class ModuleRegistry:
    """Central registry for all system modules."""

    def __init__(self) -> None:
        self._modules: dict[str, BaseModule] = {}
        self._rejected_modules: dict[str, RejectedModule] = {}
        self._safety_warnings: dict[str, list[str]] = {}
        self._custom_permissions: dict[str, list[PermissionDef]] = {}
        self._degraded_modules: set[str] = set()

    def _reject(self, module_name: str, reason: str) -> None:
        self._rejected_modules[module_name] = RejectedModule(
            module_name=module_name,
            reason=reason,
        )
        logger.error('Rejected module %s: %s', module_name, reason)

    def _reserved_name_refusal(
        self, module_dir: Path, reserved: Collection[str]
    ) -> str | None:
        """Why *module_dir* may not take its name, or ``None``.

        A hand-placed directory bypasses every installer guard, so this is
        the only gate it meets. A name the repository already answers to
        with code is not available to a drop: taking it attaches the module
        to the core's routes or to a shipped module's identity, and the
        core's routers register first, so the module's paths are silently
        unreachable while its new sub-paths answer under the core resource's
        URL. The repository's own directories keep their names — and only
        the directory that actually sits at the repository's path is the
        repository's: a directory of the same name discovered elsewhere is
        a drop wearing it.
        """
        if module_dir.name not in reserved:
            return None
        repo_dir = REPO_MODULES_ROOT / module_dir.name
        if repo_dir.exists() and repo_dir.resolve() == module_dir.resolve():
            return None
        reason = reserved_name_reason(module_dir.name) or (
            'the core mounts its own API routes under it'
        )
        return f'name {module_dir.name!r} is reserved: {reason}'

    @staticmethod
    def _untrusted_title_refusal(
        module_dir: Path, manifest: ModuleManifest
    ) -> str | None:
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
        if (
            module_dir.name in REPO_SHIPPED_MODULES
            or manifest.module_type == 'community'
        ):
            return None
        return (
            f'untrusted module claims module_type {manifest.module_type!r}; '
            f'only a directory the repository ships may stand above community'
        )

    @staticmethod
    def _strip_borrowed_author(module_dir: Path, instance: BaseModule) -> None:
        """Drop a community module's claim to the first-party author name.

        The manifest author is a claim the installer copies from
        module.yaml, and a community package may write the core team's name
        into it. The registry is the only issuer of that name, so a claim
        from an unshipped directory is stripped with a log. An honest
        community author stays — the store labels it unsigned, it does not
        erase the attribution.
        """
        if module_dir.name in REPO_SHIPPED_MODULES:
            return
        if (instance.metadata.author or '').strip().lower() != 'core team':
            return
        logger.warning(
            'Module %s claims the core team as its author; the registry is '
            'the only issuer of that name, so the claim is stripped.',
            module_dir.name,
        )
        instance.metadata.author = None

    def discover_modules(  # noqa: C901, PLR0915 - existing complexity/size
        self,
        base_path: Path | None = None,
        extra_reserved_names: Collection[str] = (),
    ) -> None:
        """Automatically discovers modules in the app/modules/ directory."""
        if base_path is None:
            base_path = REPO_MODULES_ROOT

        if not base_path.exists():
            base_path.mkdir(parents=True, exist_ok=True)
            return

        logger.info('Discovering modules in %s...', base_path)
        reserved = reserved_module_names(extra_reserved_names)
        # sorted(): iterdir() yields whatever order the filesystem stores, which
        # differs between a developer's ext4 and a CI runner's overlayfs. Module
        # discovery order decides router registration order, which decides the
        # order of `paths` in the OpenAPI schema — so an unsorted walk makes the
        # generated API types differ per machine while describing the same API,
        # and the contract gate fails on a diff nobody can act on.
        for module_dir in sorted(base_path.iterdir()):
            if not module_dir.is_dir() or module_dir.name.startswith('_'):
                continue

            refusal = self._reserved_name_refusal(module_dir, reserved)
            if refusal is not None:
                self._reject(module_dir.name, refusal)
                continue

            manifest = _validate_manifest(module_dir, self._reject)
            if manifest is None:
                continue

            refusal = self._untrusted_title_refusal(module_dir, manifest)
            if refusal is not None:
                self._reject(module_dir.name, refusal)
                continue

            # The manifest is the only place these permissions are declared;
            # without registering them here the role UI has no way to learn that
            # a module permission exists, and require_permission() guards a
            # string nobody can grant. Core keys the module merely depends on
            # are excluded — the system section already publishes those.
            if manifest.defined_permissions:
                self.register_permission_defs(
                    manifest.name, list(manifest.defined_permissions)
                )

            declared_caps = [str(c) for c in manifest.capabilities]
            violations = _find_safety_violations(module_dir, declared_caps)
            # First-party trust by shipped-directory name only — the
            # feature names without directories stay reserved, but a
            # dropped directory wearing one is not the core team's work
            # (module_safety.TRUSTED_SHIPPED_MODULES).
            is_core = module_dir.name in TRUSTED_SHIPPED_MODULES

            if violations:
                for violation in violations:
                    logger.error(
                        f'🚨 Module {module_dir.name} has safety AST violations: {violation}'
                    )
                self._safety_warnings.setdefault(module_dir.name, []).extend(violations)

                self._reject(module_dir.name, '; '.join(violations))
                continue

            try:
                module_path = f'app.modules.{module_dir.name}'
                logger.info('Attempting to import %s', module_path)
                module_pkg = importlib.import_module(module_path)

                found = False
                for attr_name in dir(module_pkg):
                    attr = getattr(module_pkg, attr_name)
                    instance = None

                    if (
                        isinstance(attr, type)
                        and issubclass(attr, BaseModule)
                        and attr is not BaseModule
                    ):
                        instance = attr()
                    elif isinstance(attr, BaseModule):
                        instance = attr

                    if instance is not None:
                        if is_core:
                            instance.metadata.is_trusted = True
                            # Core modules are the core team's work; say so.
                            # A community module with no author stays unsigned —
                            # the default is None precisely so it cannot borrow
                            # this signature.
                            instance.metadata.author = (
                                instance.metadata.author or 'Core Team'
                            )
                        else:
                            self._strip_borrowed_author(module_dir, instance)

                        if instance.metadata.name != manifest.name:
                            self._reject(
                                module_dir.name,
                                'Module metadata.name mismatch with manifest name',
                            )
                            found = True
                            break

                        if instance.metadata.version is None:
                            instance.metadata.version = manifest.version
                        elif instance.metadata.version != manifest.version:
                            self._reject(
                                module_dir.name,
                                'Module metadata.version mismatch with manifest version',
                            )
                            found = True
                            break

                        # The manifest is the one declaration point for what
                        # a module touches, the same way it is for the
                        # permissions above. A BaseModule subclass builds its
                        # metadata in code, and code never carried the
                        # manifest's capabilities — four in-tree modules read
                        # as touching nothing, Webhooks among them, whose
                        # whole work is outbound HTTP.
                        instance.metadata.capabilities = declared_caps

                        # One field over, the same declaration point for the
                        # trust level the store shows. A code-built module
                        # carries ModuleMetadata's default ('community'),
                        # which is indistinguishable from an explicit choice,
                        # so there is no mismatch to reject the way version
                        # has — the manifest value wins outright.
                        instance.metadata.module_type = manifest.module_type

                        self.register(instance)
                        found = True

                        from app.i18n.service import load_module_translations

                        i18n_path = module_dir / 'i18n'
                        if i18n_path.exists():
                            load_module_translations(instance.metadata.name, i18n_path)
                        break

                if not found:
                    self._reject(
                        module_dir.name, 'No BaseModule subclass or instance found'
                    )
            except Exception as e:  # noqa: BLE001 — module discovery must continue past broken modules
                self._reject(module_dir.name, f'Import failed: {e}')

        self._validate_dependencies()

    def _validate_dependencies(self) -> None:
        """Reject modules whose ``requires`` are not registered.

        Uses a fixpoint iteration so that removing a module also triggers
        rejection of modules that transitively depend on it.  Rejected modules
        are **not** considered available — only currently-loaded modules count.

        ``optional_requires`` is checked once, after the fixpoint: a name that
        is neither registered nor always-on is a typo and rejects the module
        just like a hard dependency would, but a soft edge never cascades —
        a companion that is merely switched off for an organization is the
        normal case, not a load error, and the registry does not track
        per-organization enablement at all.
        """
        from app.core.module_safety import ALWAYS_ON_MODULES

        while True:
            changed = False
            registered = set(self._modules.keys())
            for name in list(self._modules.keys()):
                module = self._modules[name]
                for req in module.metadata.requires:
                    if req in ALWAYS_ON_MODULES:
                        continue
                    if req not in registered:
                        reason = f'Missing required module or dependency failed: {req}'
                        self._reject(name, reason)
                        del self._modules[name]
                        changed = True
                        break
            if not changed:
                break

        registered = set(self._modules.keys())
        for name, module in list(self._modules.items()):
            for opt in module.metadata.optional_requires:
                if opt in ALWAYS_ON_MODULES:
                    continue
                if opt not in registered:
                    self._reject(name, f'Unknown optional dependency: {opt}')
                    del self._modules[name]
                    break

    def register(self, module: BaseModule) -> None:
        """Registers a module instance."""
        metadata = module.metadata
        if metadata.name in self._modules:
            return

        self._modules[metadata.name] = module
        logger.info(
            f'✅ Registered module: {metadata.display_name} v{metadata.version}'
        )

    def get(self, name: str) -> BaseModule | None:
        """Gets a module by name."""
        return self._modules.get(name)

    def get_all(self) -> list[BaseModule]:
        """Returns all registered modules."""
        return list(self._modules.values())

    def get_rejected_modules(self) -> list[RejectedModule]:
        """Returns modules rejected by strict loader checks."""
        return list(self._rejected_modules.values())

    def get_safety_warnings(self, module_name: str) -> list[str]:
        """Returns safety warnings for a module found during discovery."""
        return self._safety_warnings.get(module_name, [])

    def mark_degraded(self, module_name: str) -> None:
        """Mark a module as degraded (partially failed during startup).

        Degraded modules are still registered but may have missing routes,
        contributions, or startup state. Surfaced via ``GET /modules/available``
        so operators can diagnose startup issues.
        """
        self._degraded_modules.add(module_name)

    def is_degraded(self, module_name: str) -> bool:
        """Check if a module is in a degraded state."""
        return module_name in self._degraded_modules

    def register_permission_defs(
        self, module_name: str, permissions: list[PermissionDef]
    ) -> None:
        """Register a module's permission definitions (called at discovery)."""
        self._custom_permissions[module_name] = list(permissions)

    def get_default_permissions_for_role(self, role_name: str) -> list[str]:
        """Module permission keys a manifest hands to *role_name* by default.

        ``grant_default_permissions`` writes these onto a matching role row when
        a module is enabled, but a member with no role row at all resolves their
        permissions from the legacy ``User.role`` string. Without this, enforcing
        a module permission would lock out every such member — including whole
        organizations that enabled the module before it declared defaults.
        """
        return [
            p.key
            for perms in self._custom_permissions.values()
            for p in perms
            if role_name in p.default_roles
        ]

    def get_all_permissions(self) -> list[str]:
        """Return all known permission keys: system-level + module-registered."""
        from app.core.contracts import SystemPermission

        system_perms = [p.value for p in SystemPermission]
        module_perms = [
            p.key for perms in self._custom_permissions.values() for p in perms
        ]
        return list(dict.fromkeys(system_perms + module_perms))

    def get_permissions_catalog(
        self, enabled_modules: Collection[str] | None = None
    ) -> dict[str, object]:
        """The permission catalog the roles admin UI renders.

        ``enabled_modules`` restricts the module sections to what an
        organization actually has switched on: the matrix must not offer a
        permission that can never apply. Passing ``None`` returns everything,
        which is what the CLI and tests want.

        System permissions are always present and always first — they exist
        regardless of which modules are installed.
        """
        from app.core.contracts import SystemPermission

        system: list[dict[str, object]] = [
            {
                'key': p.value,
                'label_key': f'permissions:system.{p.name.lower()}',
                # A module permission carries a description and a system one
                # used to carry None, so half the roles editor could say what a
                # tick does and the other half could not.
                'description_key': f'permissions:system.{p.name.lower()}Desc',
                'default_roles': [],
            }
            for p in SystemPermission
        ]

        modules: list[dict[str, object]] = [
            {
                'module': name,
                # The manifest's name, for a screen that has no translation of
                # its own for this module (a scaffold, a community module):
                # better than the technical identifier.
                'display_name': (
                    self._modules[name].metadata.display_name
                    if name in self._modules
                    else None
                ),
                'permissions': [p.model_dump() for p in perms],
            }
            for name, perms in sorted(self._custom_permissions.items())
            if perms and (enabled_modules is None or name in enabled_modules)
        ]

        return {'system': system, 'modules': modules}

    async def check_module_version_async(
        self, module: BaseModule, db: 'AsyncSession'
    ) -> None:
        """Async: check if a module was installed/upgraded and call lifecycle hooks."""
        from sqlalchemy.exc import IntegrityError

        from app.core.context import ModuleContext
        from app.core.events import event_bus
        from app.core.module_identity import module_scope
        from app.models.module_installation import ModuleInstallation

        record = (
            await db.scalars(
                select(ModuleInstallation).where(
                    ModuleInstallation.module_name == module.metadata.name
                )
            )
        ).first()
        # db travels on the context so a hook can run the per-organization
        # settings pass (context.migrate_settings) over the boot session.
        context = ModuleContext(event_bus=event_bus, db=db)

        if record is None:
            # Claim first, then do the work. The unique index on module_name
            # is the only thing that can decide between workers booting
            # together, and it can only decide about the row -- so a hook run
            # before the insert was run by every worker that got past the
            # read above, migrations included. The module's own log line
            # ("already registered by another worker") admits the situation.
            #
            # Claim and hook share one savepoint, so a hook that fails takes
            # the claim down with it and the next boot tries again.
            try:
                async with db.begin_nested():
                    db.add(
                        ModuleInstallation(
                            module_name=module.metadata.name,
                            installed_version=module.metadata.version,
                        )
                    )
                    await db.flush()
                    with module_scope(module.metadata.name):
                        await module.on_install_async(context)
            except IntegrityError:
                logger.info(
                    f'[ModuleRegistry] Module {module.metadata.name} already '
                    f'registered by another worker — skipping duplicate insert.'
                )
                return
            logger.info(
                f'[ModuleRegistry] Installed module: {module.metadata.name} '
                f'v{module.metadata.version}'
            )
        elif record.installed_version != module.metadata.version:
            # Same situation as the claim above, one row later: every worker
            # booting after an upgrade reads the old version and would run
            # the hook. Take the row with FOR UPDATE and read the version
            # again under the lock -- the worker that loses finds the new
            # version already written and does nothing. Without this an
            # on_upgrade that rewrites stored data rewrites it once per
            # worker.
            locked = (
                await db.scalars(
                    select(ModuleInstallation)
                    .where(ModuleInstallation.id == record.id)
                    .with_for_update()
                    # Without this the row comes back from the session's
                    # identity map with the version read before the lock,
                    # and the re-check compares the stale value against
                    # itself -- the lock serialises the workers and every
                    # one of them still runs the hook.
                    .execution_options(populate_existing=True)
                )
            ).first()
            if locked is None or locked.installed_version == module.metadata.version:
                return
            old_version = locked.installed_version
            with module_scope(module.metadata.name):
                module.on_upgrade(old_version, context)
                await module.on_upgrade_async(old_version, context)
            locked.installed_version = module.metadata.version or ''
            await db.flush()
            logger.info(
                f'[ModuleRegistry] Upgraded module: {module.metadata.name} '
                f'{old_version} → {module.metadata.version}'
            )


module_registry = ModuleRegistry()

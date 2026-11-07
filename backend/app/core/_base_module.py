from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable
from typing import TYPE_CHECKING, Any
from uuid import UUID

from fastapi import APIRouter
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core._module_declarations import ModuleMetadata
from app.core.context import ModuleContext
from app.core.logging import get_logger

if TYPE_CHECKING:
    from app.core.container import ServiceContainer

logger = get_logger(__name__)


def _merge_declared_field_definitions(
    current: list[dict[str, Any]] | None, declared: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Merge a module's declared field definitions into the stored ones.

    Declared fields are marked ``is_system=True`` and overwrite their stored
    counterparts by ``key``; fields the organization added itself (no matching
    declaration) are kept as they are.

    Not the merge of a category *update* — that one, with the label rule,
    is ``_merge_field_definitions`` in ``app/services/_category_reads.py``.
    Here the label comes from the manifest and is taken as declared.
    """
    merged = list(current or [])
    for decl_field in declared:
        decl_field['is_system'] = True
        for i, cur_field in enumerate(merged):
            if cur_field.get('key') == decl_field.get('key'):
                merged[i] = decl_field
                break
        else:
            merged.append(decl_field)
    return merged


class BaseModule(ABC):
    """Base class for all application modules."""

    # Additional providers needed only while this module is the focus choice.
    # The profile planner expands their ordinary dependency closure.
    focus_background_modules: tuple[str, ...] = ()

    @property
    @abstractmethod
    def metadata(self) -> ModuleMetadata:
        """Returns the module metadata."""
        pass

    @abstractmethod
    def register_routes(self) -> APIRouter:
        """Returns a FastAPI router with module endpoints."""
        pass

    def register_services(self, container: ServiceContainer) -> None:
        """Register services in the global ServiceContainer."""
        pass

    def on_install(self, context: ModuleContext) -> None:
        """Called when the module is installed (first time).

        Default behavior: runs per-module Alembic migrations if
        ``migrations/`` directory exists. Override to add custom logic.
        """
        self._run_module_migrations('upgrade')

    async def on_install_async(self, context: ModuleContext) -> None:
        """Async variant of ``on_install`` for hooks that need async DB.

        Default: delegates to the sync ``on_install``. Override (or use
        ``on_install_async_hook`` in ``define_module``) when the install
        hook performs async operations.
        """
        self.on_install(context)

    def on_uninstall(self, context: ModuleContext) -> None:
        """Called when the module is uninstalled.

        Default behavior: runs per-module Alembic downgrade if
        ``migrations/`` directory exists. Override to add custom logic.
        """
        self._run_module_migrations('downgrade')

    def _run_module_migrations(self, action: str) -> None:
        """Run per-module migrations if the module has a migrations/ directory."""
        from app.core.module_migrations import (
            module_migrations_dir,
            run_module_migrations,
        )

        module_name = self.metadata.name
        try:
            module_migrations_dir(module_name)
        except FileNotFoundError:
            logger.debug(
                'Module %s has no migrations/ — skipping migration %s',
                module_name,
                action,
            )
            return

        try:
            run_module_migrations(module_name, action)  # type: ignore[arg-type]
            logger.info('Module %s: migration %s completed', module_name, action)
        except Exception as exc:  # a duplicate table is reconciled, else re-raised
            from psycopg2.errors import DuplicateTable  # type: ignore[import-untyped]

            orig = getattr(exc, 'orig', exc.__cause__)
            reconciled = (
                isinstance(orig, DuplicateTable)
                and action == 'upgrade'
                and self._reconcile_existing_schema(module_name)
            )
            if reconciled:
                return
            logger.exception('Module %s: migration %s failed', module_name, action)
            raise

    def _reconcile_existing_schema(self, module_name: str) -> bool:
        """A migration hit tables that already exist — stamp only what is proven.

        This used to stamp ``head`` outright. That skipped every revision after
        the one that collided: a module whose 002 adds a column ended up marked
        up to date with the column missing, and the first query using it 500s —
        a quieter failure than the crash it was avoiding.

        ``suggest_stamp_revision`` advances only over revisions whose DDL the
        database actually contains, so the upgrade re-run afterwards applies
        whatever is genuinely outstanding.

        Returns False when the database gives no evidence to stamp on; the
        caller then re-raises the original error rather than guessing.
        """
        import os

        from sqlalchemy import create_engine

        from app.core.migration_doctor import (
            read_schema_state,
            suggest_stamp_revision,
        )
        from app.core.module_migrations import run_module_migrations

        db_url = os.getenv('DATABASE_URL')
        engine = create_engine(
            (db_url or '').replace('postgresql+asyncpg', 'postgresql')
        )
        try:
            with engine.connect() as conn:
                target = suggest_stamp_revision(module_name, read_schema_state(conn))
        finally:
            engine.dispose()

        if target is None:
            logger.error(
                'Module %s: migration collided with existing tables, but none of '
                'the migration DDL is present — refusing to guess a revision. '
                'Run "manage.py db doctor" to see the state.',
                module_name,
            )
            return False

        logger.info(
            'Module %s: tables already exist — stamping %s and continuing',
            module_name,
            target,
        )
        run_module_migrations(module_name, 'stamp', revision=target)
        run_module_migrations(module_name, 'upgrade')
        return True

    def on_upgrade(self, old_version: str, context: ModuleContext) -> None:
        """Called when the module is upgraded from an older version."""
        pass

    async def on_upgrade_async(self, old_version: str, context: ModuleContext) -> None:
        """Async variant of :meth:`on_upgrade` — the registry awaits it.

        Override this instead of the sync hook when reshaping stored data
        needs the database, or anything else that has to be awaited. Both
        hooks run on the first boot after the installed version changes,
        under the same module identity and the same row lock, so a module
        that overrides only one of them pays nothing for the other.
        """

    def on_startup(self, context: ModuleContext) -> None:
        """Hook called on server startup."""
        from app.core.container import service_container

        self.register_services(service_container)
        self.register_contributions()
        self._wire_interceptors()

    async def on_startup_async(self, context: ModuleContext) -> None:
        """Async hook called on server startup. Override for async DB operations."""
        pass

    def on_modules_ready(self, context: ModuleContext) -> None:
        """Hook called after every module's startup hooks have run.

        ``on_startup`` runs in an alphabetical walk of the modules directory,
        so a module cannot see what a later-named one contributes to a shared
        catalogue. Anything that consumes such a catalogue belongs here: by the
        time this is called, every module has registered and the catalogue is
        complete whatever the names happen to sort to.
        """
        pass

    def _wire_interceptors(self) -> None:
        """Wire interceptor contributions from ContributionRegistry to the pipeline."""
        from app.core.contributions import contribution_registry
        from app.core.interceptors import (
            CategoryInterceptor,
            ItemInterceptor,
            StorageInterceptor,
            interceptor_pipeline,
        )

        for i in contribution_registry.get('item_interceptors'):
            if isinstance(i, ItemInterceptor):
                interceptor_pipeline.register_item_interceptor(i)

        for i in contribution_registry.get('storage_interceptors'):
            if isinstance(i, StorageInterceptor):
                interceptor_pipeline.register_storage_interceptor(i)

        for i in contribution_registry.get('category_interceptors'):
            if isinstance(i, CategoryInterceptor):
                interceptor_pipeline.register_category_interceptor(i)

    def register_contributions(self) -> None:
        """Hook for modules to register their contributions (ScanProviders, etc)."""
        pass

    async def _seed_declared_storage_types(
        self, organization_id: Any, db: AsyncSession
    ) -> None:
        """Give *organization_id* the storage types this module declares.

               Declared types used to be written once per installation with
               ``organization_id IS NULL`` by a startup sync, which meant every
               tenant saw every enabled module's types whether or not they had the
        module. They are copied per organization now, the same way
               categories and default locations are.

        The name is written in the language the module is being enabled in,
        like a location's (see ``_seed_declared_storage_locations``): a type's
        name is data — it stands in the storage picker, on the storage's card
        and in every exported row — so it is written once in the reader's
        language rather than stored in English and translated by whichever
        screen happens to know how. A row still carrying the declaration's own
        literal is one nobody has touched, including one seeded before the
        language was chosen here; it joins the language of this enable and a
        name that differs is the organization's and is never rewritten.
        """
        from sqlalchemy import select

        from app.i18n.service import get_current_lang
        from app.models.storage_type import STORAGE_TYPE_ORDER, StorageType

        lang = get_current_lang()

        for st_decl in self.metadata.storage_types:
            localized = st_decl.translations.get(lang)
            name = localized.name if localized else st_decl.name
            stmt = (
                select(StorageType)
                .where(
                    StorageType.type_code == st_decl.code,
                    StorageType.organization_id == organization_id,
                )
                .order_by(*STORAGE_TYPE_ORDER)
            )
            existing = (await db.execute(stmt)).scalars().first()

            if existing:
                if existing.context_schema != st_decl.context_schema:
                    existing.context_schema = st_decl.context_schema
                    db.add(existing)
                # The same test the profile seeder applies: a name still equal
                # to the literal is one nobody has renamed. The row's
                # ``is_system`` flag is not part of it — a type forked from a
                # global one is not flagged, and its name is as untouched.
                if existing.name == st_decl.name != name:
                    existing.name = name
                    db.add(existing)
                continue

            db.add(
                StorageType(
                    name=name,
                    type_code=st_decl.code,
                    behavior_mode=st_decl.behavior_mode,
                    context_schema=st_decl.context_schema,
                    icon=st_decl.icon,
                    is_system=True,
                    organization_id=organization_id,
                )
            )

    async def system_on_enable(
        self, organization_id: UUID, db: AsyncSession, *, user: Any | None = None
    ) -> None:
        """Internal framework hook for copying master metadata schemas.

               Runs on every enable path (onboarding, profile switch, App Store
               toggle) — unlike the class-level ``on_enable``, which onboarding
               intentionally skips. Modules must declare their per-organization
               start data in ``metadata`` (categories, default storage locations)
        so this hook seeds it identically everywhere.
        """
        from sqlalchemy import select

        from app.models.category import Category

        hh_id = organization_id

        if self.metadata.storage_types:
            await self._seed_declared_storage_types(hh_id, db)

        cat_decls = self.metadata.categories
        for cat_decl in cat_decls:
            stmt = select(Category).where(
                Category.code == cat_decl.code, Category.organization_id == hh_id
            )
            existing = (await db.execute(stmt)).scalars().first()

            if existing:
                existing.is_active = True
                existing.name = cat_decl.name
                existing.icon = cat_decl.icon or existing.icon
                if cat_decl.context_tag:
                    existing.context_tag = cat_decl.context_tag
                existing.field_definitions = _merge_declared_field_definitions(
                    existing.field_definitions, cat_decl.field_definitions
                )
                db.add(existing)
            else:
                new_cat = Category(
                    name=cat_decl.name,
                    code=cat_decl.code,
                    context_tag=cat_decl.context_tag,
                    icon=cat_decl.icon,
                    field_definitions=_merge_declared_field_definitions(
                        [], cat_decl.field_definitions
                    ),
                    organization_id=hh_id,
                    module_name=self.metadata.name,
                    is_active=True,
                )
                db.add(new_cat)

        if self.metadata.default_storage_locations:
            if user is None:
                logger.warning(
                    'Module %s declares default_storage_locations but no user '
                    'context was provided — skipping the seed for org %s',
                    self.metadata.name,
                    hh_id,
                )
            else:
                await self._seed_default_storage_locations(hh_id, db, user)

        await db.flush()

    async def _seed_default_storage_locations(
        self, organization_id: Any, db: AsyncSession, user: Any
    ) -> None:
        """Seed ``metadata.default_storage_locations`` for *organization_id*.

        Locations carrying a ``context_tag`` are skipped wholesale when the
        organization already has any location with that tag — the same
        guard the equipment module's historical ``on_enable`` used, so a
        re-enable never duplicates the seed. Existing tags are collected
        up front: a per-declaration check would see rows added by this very
        run through autoflush and treat them as pre-existing.

        An untagged declaration reads the same guard the other way round:
        an organization holding any unclaimed location the document picker
        would actually offer already has a place for goods to land, so the
        neutral seed is skipped — and one seeded by an earlier enable
        counts, which is what keeps a re-enable from stacking second and
        third copies of it. "Would actually offer" is the picker's own
        question: an internal, unarchived location with no context tag. A
        bare ``context_tag IS NULL`` counted the virtual counterparts
        (consumed, inventory loss, production) and archived rows — rows the
        picker never offers — so an organization whose only unclaimed
        locations were those concluded it needed no neutral one and was
        left with a picker that had nothing to show.
        """
        from sqlalchemy import select

        from app.i18n.service import get_current_lang
        from app.models.storage_location import LocationUsage, StorageLocation
        from app.services.storage._queries import not_archived_condition

        tags = {
            decl.context_tag
            for decl in self.metadata.default_storage_locations
            if decl.context_tag
        }
        existing_tags: set[str] = set()
        for tag in tags:
            row = (
                await db.execute(
                    select(StorageLocation.id).where(
                        StorageLocation.organization_id == organization_id,
                        StorageLocation.context_tag == tag,
                    )
                )
            ).first()
            if row is not None:
                existing_tags.add(tag)

        has_untagged = False
        if any(
            not decl.context_tag for decl in self.metadata.default_storage_locations
        ):
            untagged_row = (
                await db.execute(
                    select(StorageLocation.id).where(
                        StorageLocation.organization_id == organization_id,
                        StorageLocation.context_tag.is_(None),
                        StorageLocation.usage == LocationUsage.INTERNAL,
                        not_archived_condition(),
                    )
                )
            ).first()
            has_untagged = untagged_row is not None

        # The language the module is being enabled in. A location's name is
        # data -- editable, printed on labels, written into exported documents
        # -- so it is written once in the reader's language rather than stored
        # in English and translated by whichever screen happens to know how.
        lang = get_current_lang()

        for decl in self.metadata.default_storage_locations:
            if decl.context_tag and decl.context_tag in existing_tags:
                logger.info(
                    'Module %s: org %s already has a location with '
                    'context_tag %r — skipping default location seed',
                    self.metadata.name,
                    organization_id,
                    decl.context_tag,
                )
                await self._align_seeded_name(organization_id, decl, lang, db)
                continue
            if not decl.context_tag and has_untagged:
                logger.info(
                    'Module %s: org %s already has an unclaimed location '
                    '— skipping the neutral seed %r',
                    self.metadata.name,
                    organization_id,
                    decl.code or decl.name,
                )
                await self._align_seeded_name(organization_id, decl, lang, db)
                continue
            localized = decl.translations.get(lang)
            name = localized.name if localized else decl.name
            description = (
                localized.description
                if localized and localized.description
                else decl.description
            )
            db.add(
                StorageLocation(
                    name=name,
                    description=description,
                    behavior_mode=decl.behavior_mode,
                    context_tag=decl.context_tag,
                    usage='internal',
                    organization_id=organization_id,
                    created_by=user.id,
                    # The handle, plus the name that was actually written —
                    # so a later pass can tell an untouched row from a renamed
                    # one. Recording the declaration's English here instead
                    # would make every seeded row read as already renamed.
                    settings=(
                        {'seed': {'code': decl.code, 'name': name}}
                        if decl.code
                        else None
                    ),
                )
            )

    async def _align_seeded_name(
        self, organization_id: Any, decl: Any, lang: str, db: AsyncSession
    ) -> None:
        """Bring a row still carrying the declaration's own literal into *lang*.

        Organizations seeded before the language was chosen at write time hold
        the English literal, and a handle recording that same literal — which
        is precisely what says nobody has touched the row. Those join the
        language of the session enabling the module; the handle then records
        the new name, so enabling again in a third language leaves the row
        alone. A row whose name differs from its handle is one the user named,
        and is never touched.
        """
        from sqlalchemy import select

        from app.models.storage_location import StorageLocation

        localized = decl.translations.get(lang)
        if not decl.code or localized is None or localized.name == decl.name:
            return

        rows = (
            (
                await db.execute(
                    select(StorageLocation).where(
                        StorageLocation.organization_id == organization_id,
                        StorageLocation.context_tag == decl.context_tag,
                    )
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            seed = (row.settings or {}).get('seed') or {}
            if seed.get('code') != decl.code or seed.get('name') != row.name:
                continue
            row.name = localized.name
            if localized.description and row.description == decl.description:
                row.description = localized.description
            # Mutating the dict in place is invisible to SQLAlchemy's change
            # tracking on a JSON column; the row needs a new object.
            row.settings = {
                **(row.settings or {}),
                'seed': {**seed, 'name': localized.name},
            }
            db.add(row)

    def on_enable(
        self, organization_id: UUID, context: ModuleContext
    ) -> Awaitable[None] | None:
        """Hook called when the module is enabled for a organization.

        May return an awaitable — the lifecycle executor awaits it.
        """

    def on_disable(
        self, organization_id: UUID, context: ModuleContext
    ) -> Awaitable[None] | None:
        """Hook called when the module is disabled for a organization.

        May return an awaitable — the lifecycle executor awaits it.
        """

    async def enable_preview(
        self, organization_id: UUID, db: AsyncSession
    ) -> int | None:
        """How many things already saved start acting the moment this is switched on.

        Switching a module off keeps what it holds, so switching it back on can
        put something into motion that nobody present remembers — endpoints
        that start receiving, keys that start authenticating. The store asks
        before it does it and says the number. ``None`` (the default) or zero
        means there is nothing saved to resume, and the switch-on needs no
        question.
        """

    def get_settings_schema(self) -> dict[str, object] | None:
        """Return a JSON Schema describing module-level configurable settings.

        Field entries may carry ``title``/``description`` literals and/or
        ``title_key``/``description_key`` i18n keys (full form, e.g.
        ``'recipes:settings.jinaApiKey'``). The frontend resolves the keys
        against the module's translation catalog and falls back to the
        literals — keys are the preferred form for user-visible modules.
        """
        return None

    def get_default_settings(self) -> dict[str, object]:
        """Return the default settings for this module."""
        return {}

    def get_secret_columns(self) -> list[Any]:
        """Columns of this module's own tables that hold secrets it sealed.

        Return the mapped attributes (``[MyModel.token]``) of every column
        written through ``core_api.secrets.encrypt_for_module`` with this
        module's name. ``manage.py secrets reencrypt`` rewrites them under
        the current key when an administrator rotates it, the same way it
        rewrites the ``format: secret`` fields of :meth:`get_settings_schema`
        — which need no entry here. A column left out keeps its old key and
        stops opening once the previous key is dropped.
        """
        return []

    async def system_on_disable(self, organization_id: UUID, db: AsyncSession) -> None:
        """Internal framework hook for archiving organization forks."""
        from app.models.category import Category

        await db.execute(
            update(Category)
            .where(
                Category.organization_id == organization_id,
                Category.module_name == self.metadata.name,
            )
            .values({'is_active': False})
        )
        await db.flush()

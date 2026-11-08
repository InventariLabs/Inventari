from __future__ import annotations

from typing import Any, Protocol, TypeVar
from uuid import UUID

from sqlalchemy import Executable, Table, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select
from sqlalchemy.sql.selectable import CTE, Subquery

from app.core.logging import get_logger

logger = get_logger(__name__)


class TenantIsolationError(RuntimeError):
    """A statement the scoped session refused because it would cross tenants.

    Raised where a module's code reaches past its organization: a row of
    another organization added, deleted or fetched, a table with no
    ``organization_id`` queried, a subquery the filter cannot scope. That is a
    defect in the calling code, not a refusal a person caused, so it is
    deliberately not a ``PermissionError``: the routes and
    :func:`~app.core.exceptions.map_service_errors` answer a
    ``PermissionError`` with a 403 carrying its message, and this message
    names tables, rows and organizations. Nothing maps it; the global handler
    answers 500 and the log keeps the detail.
    """


class _HasOrgId(Protocol):
    organization_id: UUID | None


T = TypeVar('T', bound=_HasOrgId)


def _inject_org_filter(
    statement: Select[tuple[Any]], organization_id: UUID
) -> Select[tuple[Any]]:
    """Inject organization_id WHERE clause into a SELECT statement.

    Adds an org filter for every selected ORM entity that has an
    ``organization_id`` column. ``column_descriptions`` is the SQLAlchemy
    2.0 API for resolving the mapped class behind each raw column (the
    old ``froms[].entity`` walk silently matched nothing for plain
    ``select(Model)`` statements). Aliases resolve through the same
    API, so ``select(aliased(Item))`` is covered here.

    ``column_descriptions`` carries no entity for
    ``select(func.count()).select_from(Item)`` — the only column is a bare
    function — so that shape used to slip through unfiltered and counted
    every organization's rows. When nothing matched, fall back to the FROM
    clause:

    * plain tables are filtered directly;
    * a subquery or CTE is filtered on its own ``organization_id`` column
      when it exposes one, and **rejected** when it does not — a narrowed
      subquery like ``select(Item.id).subquery()`` gives this function
      nothing to filter on, and answering with every tenant's rows is the
      one outcome that must not happen quietly;
    * a join is left alone, which is deliberate: its ``organization_id`` is
      ambiguous and guessing which side to filter would be worse. Joins
      normally select an entity, so they are already handled above.
    """
    injected = False
    for description in statement.column_descriptions:
        entity = description.get('entity')
        if entity is not None and hasattr(entity, 'organization_id'):
            statement = statement.where(entity.organization_id == organization_id)
            injected = True
    if injected:
        return statement

    for from_clause in statement.get_final_froms():
        if isinstance(from_clause, Table) and 'organization_id' in from_clause.c:
            statement = statement.where(
                from_clause.c.organization_id == organization_id
            )
        elif isinstance(from_clause, Subquery | CTE):
            if 'organization_id' not in from_clause.c:
                raise TenantIsolationError(
                    'Cannot scope this statement to an organization: its '
                    'subquery/CTE does not expose an organization_id column. '
                    'Filter inside the subquery and run it through '
                    'raw_session, or select organization_id in it.'
                )
            statement = statement.where(
                from_clause.c.organization_id == organization_id
            )
    return statement


class AsyncModuleScopedSession:
    """
    A secure proxy around SQLAlchemy AsyncSession for use inside modules.

    Mirrors :class:`ModuleScopedSession` but wraps ``AsyncSession`` instead of
    sync ``Session``.  All data-access methods are ``async`` and automatically
    filter by ``organization_id`` to prevent cross-tenant data leaks.

    Typical usage in background workers or async seeders::

        async with AsyncSessionLocal() as raw:
            scoped = AsyncModuleScopedSession(raw, org_id)
            items = await scoped.scalars(scoped.query(Item))

    Where the automatic filter reaches — and where it stops — is spelled out
    in :func:`_inject_org_filter`. The short version: entities, aliases,
    plain tables and org-exposing subqueries/CTEs are filtered; a subquery
    without an ``organization_id`` column raises rather than returning
    every tenant's rows; in an explicit join every *selected* entity is
    filtered and a joined table the statement does not select is not, so
    write that table's org filter yourself.
    """

    def __init__(self, db: AsyncSession, organization_id: UUID) -> None:
        self._db = db
        self._organization_id = organization_id

    # ------------------------------------------------------------------
    # Secured query interface
    # ------------------------------------------------------------------

    def query(self, model: type, *entities: Any) -> Select[tuple[Any]]:
        """
        Return a SQLAlchemy ``select()`` for *model*.

        The tenant filter is applied exactly once, by :meth:`execute`
        — the statement itself carries no WHERE clause, so
        ``scoped.query(Model)`` executed through this session is filtered
        a single time.

        Raises ``TenantIsolationError`` if the model does not have an
        ``organization_id`` column (i.e. it's a system-wide table that
        modules should not access directly).
        """
        if not hasattr(model, 'organization_id'):
            table_name = getattr(model, '__tablename__', model.__name__)
            raise TenantIsolationError(
                f"Module cannot access table '{table_name}': "
                f'no organization_id column.  Use the public API instead.'
            )

        return select(model, *entities)

    async def get(self, model: type[T], pk: UUID | int | str) -> T | None:
        """
        Fetch a single record by primary key and verify it belongs to
        the current organization.

        Raises ``TenantIsolationError`` on ownership mismatch (instead of
        leaking the record), and falls back to ``None`` when not found.
        """
        if not hasattr(model, 'organization_id'):
            table_name = getattr(model, '__tablename__', model.__name__)
            raise TenantIsolationError(
                f"Module cannot access table '{table_name}': no organization_id column."
            )
        obj = await self._db.get(model, pk)
        if obj is None:
            return None
        if obj.organization_id != self._organization_id:
            logger.warning(
                'AsyncModuleScopedSession.get: org mismatch for %s pk=%s '
                '(requested org=%s, actual org=%s)',
                model.__name__,
                pk,
                self._organization_id,
                obj.organization_id,
            )
            raise TenantIsolationError(
                f"Access denied: record '{pk}' does not belong to "
                f'organization {self._organization_id}.'
            )
        return obj

    # ------------------------------------------------------------------
    # Passthrough write operations
    # ------------------------------------------------------------------

    def add(self, instance: object) -> None:
        """Add an ORM object to the session, validating tenant ownership.

        If the instance has an ``organization_id`` attribute, it must match
        the session's scoped organization.  Objects without the attribute
        (module-local models) are allowed through.
        """
        if hasattr(instance, 'organization_id'):
            instance_org = instance.organization_id
            if instance_org is not None and instance_org != self._organization_id:
                model_name = type(instance).__name__
                raise TenantIsolationError(
                    f'Tenant isolation violation: {model_name} '
                    f'organization_id={instance_org} does not match '
                    f'session scope {self._organization_id}'
                )
        self._db.add(instance)

    async def delete(self, instance: object) -> None:
        """Mark an ORM object for deletion, validating tenant ownership.

        If the instance has an ``organization_id`` attribute, it must match
        the session's scoped organization.  Objects without the attribute
        (module-local models) are allowed through.
        """
        if hasattr(instance, 'organization_id'):
            instance_org = instance.organization_id
            if instance_org is not None and instance_org != self._organization_id:
                model_name = type(instance).__name__
                raise TenantIsolationError(
                    f'Tenant isolation violation: cannot delete {model_name} '
                    f'organization_id={instance_org} — session scope is '
                    f'{self._organization_id}'
                )
        await self._db.delete(instance)

    async def flush(self, objects: list[Any] | None = None) -> None:
        """Flush pending changes to the DB (passthrough)."""
        await self._db.flush(objects)

    async def commit(self) -> None:
        """Commit the current transaction (passthrough)."""
        await self._db.commit()

    async def rollback(self) -> None:
        """Roll back the current transaction (passthrough)."""
        await self._db.rollback()

    async def refresh(self, instance: object) -> None:
        """Refresh an ORM instance from the DB (passthrough)."""
        await self._db.refresh(instance)

    # ------------------------------------------------------------------
    # SQLAlchemy 2.0-style query interface (with auto-filtering)
    # ------------------------------------------------------------------

    async def execute(
        self, statement: Executable, *multiparams: Any, **params: Any
    ) -> Any:
        """
        Execute a SQLAlchemy 2.0 statement with automatic tenant filtering.

        For ``SELECT`` statements on models that have an ``organization_id``
        column, this method automatically injects a
        ``WHERE organization_id = :org_id`` clause.  Non-SELECT statements
        and statements on models without ``organization_id`` are passed
        through unchanged.
        """
        if isinstance(statement, Select):
            statement = _inject_org_filter(statement, self._organization_id)
        return await self._db.execute(statement, *multiparams, **params)

    async def scalars(
        self, statement: Executable, *multiparams: Any, **params: Any
    ) -> Any:
        """
        Execute and return a ScalarResult (passthrough).

        Convenience shortcut for ``(await self.execute(statement)).scalars()``.
        """
        result = await self.execute(statement, *multiparams, **params)
        return result.scalars()

    async def scalar(
        self, statement: Executable, *multiparams: Any, **params: Any
    ) -> Any:
        """
        Execute and return the first column of the first row, or None.

        Convenience shortcut for ``(await self.execute(statement)).scalar()``.
        """
        result = await self.execute(statement, *multiparams, **params)
        return result.scalar()

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    @property
    def organization_id(self) -> UUID:
        """The organization this session is scoped to."""
        return self._organization_id

    @property
    def raw_session(self) -> AsyncSession:
        """The underlying AsyncSession (unscoped).

        Use only when passing to CoreAPI methods that require a raw
        ``AsyncSession`` (e.g. ``core_api.locations.find_by_context_tag_async()``).
        Prefer the scoped methods (:meth:`query`, :meth:`execute`) whenever possible.
        """
        return self._db

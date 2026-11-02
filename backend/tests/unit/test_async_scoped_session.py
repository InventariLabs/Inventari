"""Unit tests for AsyncModuleScopedSession."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import Column, String, select
from sqlalchemy.orm import DeclarativeBase

from app.core.scoped_session import AsyncModuleScopedSession, TenantIsolationError

ORG_ID = uuid4()
OTHER_ORG_ID = uuid4()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class Base(DeclarativeBase):
    pass


class Item(Base):
    __tablename__ = 'items'
    id = Column(String, primary_key=True)
    organization_id = Column(String)


class SystemTable(Base):
    __tablename__ = 'system_settings'
    id = Column(String, primary_key=True)


def _make_async_session():
    """Return a mock AsyncSession."""
    db = AsyncMock()
    db.execute = AsyncMock()
    db.scalars = AsyncMock()
    db.scalar = AsyncMock()
    db.get = AsyncMock()
    db.add = MagicMock()
    db.delete = AsyncMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.refresh = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# query()
# ---------------------------------------------------------------------------


class TestAsyncModuleScopedSessionQuery:
    def test_query_returns_select_without_where(self):
        """query() must return a plain select; execute() applies the org filter once."""
        db = _make_async_session()
        session = AsyncModuleScopedSession(db, ORG_ID)
        result = session.query(Item)

        from sqlalchemy import Select

        assert isinstance(result, Select)
        assert 'organization_id =' not in str(result)

    def test_query_raises_for_model_without_org_id(self):
        """query() must raise TenantIsolationError for system tables without organization_id."""
        db = _make_async_session()
        session = AsyncModuleScopedSession(db, ORG_ID)
        with pytest.raises(TenantIsolationError, match='system_settings'):
            session.query(SystemTable)


# ---------------------------------------------------------------------------
# get()
# ---------------------------------------------------------------------------


class TestAsyncModuleScopedSessionGet:
    @pytest.mark.asyncio
    async def test_get_returns_record_for_correct_org(self):
        """get() returns the record when organization_id matches."""
        db = _make_async_session()
        record = MagicMock()
        record.organization_id = ORG_ID
        db.get.return_value = record

        session = AsyncModuleScopedSession(db, ORG_ID)
        result = await session.get(Item, 'some-pk')

        assert result is record

    @pytest.mark.asyncio
    async def test_get_raises_for_wrong_org(self):
        """get() must raise TenantIsolationError when record belongs to a different tenant."""
        db = _make_async_session()
        record = MagicMock()
        record.organization_id = OTHER_ORG_ID
        db.get.return_value = record

        session = AsyncModuleScopedSession(db, ORG_ID)
        with pytest.raises(TenantIsolationError):
            await session.get(Item, 'some-pk')

    @pytest.mark.asyncio
    async def test_get_returns_none_when_not_found(self):
        """get() returns None when underlying db.get returns None."""
        db = _make_async_session()
        db.get.return_value = None

        session = AsyncModuleScopedSession(db, ORG_ID)
        result = await session.get(Item, 'missing-pk')
        assert result is None

    @pytest.mark.asyncio
    async def test_get_raises_for_model_without_org_id(self):
        """get() must raise TenantIsolationError for system tables."""
        db = _make_async_session()

        session = AsyncModuleScopedSession(db, ORG_ID)
        with pytest.raises(TenantIsolationError):
            await session.get(SystemTable, 1)


# ---------------------------------------------------------------------------
# execute() — auto-filtering
# ---------------------------------------------------------------------------


class TestAsyncModuleScopedSessionExecute:
    @pytest.mark.asyncio
    async def test_execute_injects_org_filter_for_model_with_org_id(self):
        """execute() must inject organization_id WHERE clause for tenant-scoped models."""
        db = _make_async_session()
        mock_result = MagicMock()
        db.execute.return_value = mock_result

        session = AsyncModuleScopedSession(db, ORG_ID)
        stmt = select(Item)
        result = await session.execute(stmt)

        # Verify execute was called with a statement whose WHERE clause
        # contains exactly one org predicate (column list alone is not proof).
        called_stmt = db.execute.call_args[0][0]
        assert str(called_stmt).count('organization_id =') == 1
        assert result is mock_result

    @pytest.mark.asyncio
    async def test_query_then_execute_filters_exactly_once(self):
        """query() + execute() must produce a single org filter."""
        db = _make_async_session()
        db.execute.return_value = MagicMock()

        session = AsyncModuleScopedSession(db, ORG_ID)
        stmt = session.query(Item)
        await session.execute(stmt)

        called_stmt = db.execute.call_args[0][0]
        assert str(called_stmt).count('organization_id =') == 1

    @pytest.mark.asyncio
    async def test_execute_passes_through_for_model_without_org_id(self):
        """execute() must pass through statements for non-tenant models (no injection)."""
        db = _make_async_session()
        mock_result = MagicMock()
        db.execute.return_value = mock_result

        session = AsyncModuleScopedSession(db, ORG_ID)
        stmt = select(SystemTable)
        result = await session.execute(stmt)

        # Statement should NOT have org filter injected
        called_stmt = db.execute.call_args[0][0]
        called_str = str(called_stmt)
        assert 'organization_id' not in called_str
        assert result is mock_result

    @pytest.mark.asyncio
    async def test_execute_passes_through_for_non_select_statements(self):
        """execute() must pass through non-SELECT statements (INSERT, UPDATE, DELETE)."""
        from sqlalchemy import text

        db = _make_async_session()
        mock_result = MagicMock()
        db.execute.return_value = mock_result

        session = AsyncModuleScopedSession(db, ORG_ID)
        stmt = text('SELECT 1')
        result = await session.execute(stmt)

        assert result is mock_result


# ---------------------------------------------------------------------------
# scalars() / scalar()
# ---------------------------------------------------------------------------


class TestAsyncModuleScopedSessionScalars:
    @pytest.mark.asyncio
    async def test_scalars_delegates_to_execute(self):
        """scalars() must call execute and return .scalars() on the result."""
        db = _make_async_session()
        mock_scalars_result = MagicMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars_result
        db.execute.return_value = mock_result

        session = AsyncModuleScopedSession(db, ORG_ID)
        stmt = select(Item)
        result = await session.scalars(stmt)

        assert result is mock_scalars_result

    @pytest.mark.asyncio
    async def test_scalar_delegates_to_execute(self):
        """scalar() must call execute and return .scalar() on the result."""
        db = _make_async_session()
        mock_result = MagicMock()
        mock_result.scalar.return_value = 'value'
        db.execute.return_value = mock_result

        session = AsyncModuleScopedSession(db, ORG_ID)
        stmt = select(Item)
        result = await session.scalar(stmt)

        assert result == 'value'


# ---------------------------------------------------------------------------
# add()
# ---------------------------------------------------------------------------


class TestAsyncModuleScopedSessionAdd:
    def test_add_rejects_wrong_org(self):
        """add() must raise TenantIsolationError when organization_id mismatches."""
        db = _make_async_session()
        session = AsyncModuleScopedSession(db, ORG_ID)

        obj = MagicMock()
        obj.organization_id = OTHER_ORG_ID

        with pytest.raises(TenantIsolationError, match='Tenant isolation violation'):
            session.add(obj)

    def test_add_allows_matching_org(self):
        """add() allows objects with matching organization_id."""
        db = _make_async_session()
        session = AsyncModuleScopedSession(db, ORG_ID)

        obj = MagicMock()
        obj.organization_id = ORG_ID

        session.add(obj)
        db.add.assert_called_once_with(obj)

    def test_add_allows_object_without_org_id(self):
        """add() allows module-local models without organization_id."""
        db = _make_async_session()
        session = AsyncModuleScopedSession(db, ORG_ID)

        obj = MagicMock(spec=[])  # No organization_id attribute

        session.add(obj)
        db.add.assert_called_once_with(obj)


# ---------------------------------------------------------------------------
# delete()
# ---------------------------------------------------------------------------


class TestAsyncModuleScopedSessionDelete:
    @pytest.mark.asyncio
    async def test_delete_rejects_wrong_org(self):
        """delete() must raise TenantIsolationError when organization_id mismatches."""
        db = _make_async_session()
        session = AsyncModuleScopedSession(db, ORG_ID)

        obj = MagicMock()
        obj.organization_id = OTHER_ORG_ID

        with pytest.raises(TenantIsolationError, match='Tenant isolation violation'):
            await session.delete(obj)

    @pytest.mark.asyncio
    async def test_delete_allows_matching_org(self):
        """delete() allows objects with matching organization_id."""
        db = _make_async_session()
        session = AsyncModuleScopedSession(db, ORG_ID)

        obj = MagicMock()
        obj.organization_id = ORG_ID

        await session.delete(obj)
        db.delete.assert_called_once_with(obj)


# ---------------------------------------------------------------------------
# Passthrough methods
# ---------------------------------------------------------------------------


class TestAsyncModuleScopedSessionPassthrough:
    def _session(self):
        db = _make_async_session()
        return AsyncModuleScopedSession(db, ORG_ID), db

    @pytest.mark.asyncio
    async def test_flush(self):
        session, db = self._session()
        await session.flush()
        db.flush.assert_called_once_with(None)

    @pytest.mark.asyncio
    async def test_commit(self):
        session, db = self._session()
        await session.commit()
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_rollback(self):
        session, db = self._session()
        await session.rollback()
        db.rollback.assert_called_once()

    @pytest.mark.asyncio
    async def test_refresh(self):
        session, db = self._session()
        obj = MagicMock()
        await session.refresh(obj)
        db.refresh.assert_called_once_with(obj)

    def test_organization_id_property(self):
        session, _ = self._session()
        assert session.organization_id == ORG_ID


# ---------------------------------------------------------------------------
# Shapes that carry no entity in column_descriptions
# ---------------------------------------------------------------------------


class TestSelectFromIsFiltered:
    """``select(func.count()).select_from(Item)`` names no entity in
    ``column_descriptions``, so it used to reach the database unfiltered and
    count every organization's rows."""

    @staticmethod
    def _executed_sql(statement) -> str:
        db = _make_async_session()
        session = AsyncModuleScopedSession(db, ORG_ID)
        import asyncio

        asyncio.run(session.execute(statement))
        return str(db.execute.call_args[0][0])

    def test_bare_count_over_select_from_is_filtered(self):
        from sqlalchemy import func

        sql = self._executed_sql(select(func.count()).select_from(Item))

        assert 'organization_id =' in sql

    def test_entity_shapes_are_still_filtered_exactly_once(self):
        from sqlalchemy import func

        for statement in (
            select(Item),
            select(Item.id),
            select(func.count(Item.id)),
        ):
            sql = self._executed_sql(statement)
            assert sql.count('organization_id =') == 1, sql

    def test_table_without_organization_id_is_left_alone(self):
        from sqlalchemy import func

        sql = self._executed_sql(select(func.count()).select_from(SystemTable))

        assert 'organization_id' not in sql


# ---------------------------------------------------------------------------
# Subqueries, CTEs and aliases: shapes the FROM-clause fallback has to reach
# ---------------------------------------------------------------------------


class TestDerivedFromClauses:
    @staticmethod
    def _executed_sql(statement) -> str:
        db = _make_async_session()
        session = AsyncModuleScopedSession(db, ORG_ID)
        import asyncio

        asyncio.run(session.execute(statement))
        return str(db.execute.call_args[0][0])

    def test_alias_is_filtered(self):
        from sqlalchemy.orm import aliased

        sql = self._executed_sql(select(aliased(Item)))

        assert 'organization_id =' in sql

    def test_count_over_a_subquery_is_filtered(self):
        """The count sees no entity, and the FROM is a subquery rather than a
        table — the shape that used to count every tenant's rows."""
        from sqlalchemy import func

        sub = select(Item).subquery()
        sql = self._executed_sql(select(func.count()).select_from(sub))

        assert 'organization_id =' in sql

    def test_count_over_a_cte_is_filtered(self):
        from sqlalchemy import func

        cte = select(Item).cte('scoped_items')
        sql = self._executed_sql(select(func.count()).select_from(cte))

        assert 'organization_id =' in sql

    def test_subquery_without_org_column_is_refused(self):
        """Nothing to filter on: returning every tenant's rows would be the
        one wrong answer, so this is a hard error instead."""
        from sqlalchemy import func

        sub = select(Item.id).subquery()

        with pytest.raises(TenantIsolationError, match='organization_id'):
            self._executed_sql(select(func.count()).select_from(sub))

    def test_subquery_selecting_org_column_is_filtered(self):
        from sqlalchemy import func

        sub = select(Item.id, Item.organization_id).subquery()
        sql = self._executed_sql(select(func.count()).select_from(sub))

        assert 'organization_id =' in sql

"""Tests for shared DB utilities: ``paginate*``, ``get_org_owned_or_404*``, ``after_commit``.

These hit the real PostgreSQL test DB (same as integration tests) because the
helpers compile real SQL — the fixtures come from the root ``conftest.py``.
"""

import uuid
from collections.abc import Awaitable, Callable

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.db_utils import (
    after_commit,
    escape_ilike,
    get_org_owned_or_404,
    get_org_owned_or_404_async,
    paginate,
    paginate_async,
)
from app.core.events import SystemEvent, TenantEventPayload, event_bus
from app.core.exceptions import NotFoundException
from app.core.public_api import core_api
from app.database import dispatch_committed_events
from app.models.category import Category
from app.models.organization import Organization
from app.models.partner import Partner


def _seed_partners(db_session: Session, org_id: uuid.UUID, count: int = 5) -> None:
    """Insert *count* partners named 'Partner 0'..'Partner N-1' for *org_id*."""
    for i in range(count):
        db_session.add(
            Partner(organization_id=org_id, name=f'Partner {i}', type='SUPPLIER')
        )
    db_session.commit()


@pytest.fixture
def partner_org(db_session: Session) -> Organization:
    org = Organization(name='DB Utils Test Org')
    db_session.add(org)
    db_session.commit()
    db_session.refresh(org)
    return org


@pytest.fixture
async def async_partner_org(real_async_db_session: AsyncSession) -> Organization:
    org = Organization(name='DB Utils Async Test Org')
    real_async_db_session.add(org)
    await real_async_db_session.flush()
    await real_async_db_session.refresh(org)
    return org


def _partners_stmt(org_id: uuid.UUID):
    return (
        select(Partner).where(Partner.organization_id == org_id).order_by(Partner.name)
    )


class TestEscapeIlike:
    """Wildcard-injection guard for user-supplied LIKE/ILIKE search terms."""

    def test_escapes_percent_underscore_and_backslash(self) -> None:
        assert escape_ilike('100%') == r'100\%'
        assert escape_ilike('a_b') == r'a\_b'
        # Backslash first, so the escapes it introduces are not re-escaped.
        assert escape_ilike(r'a\b') == r'a\\b'

    def test_leaves_ordinary_text_untouched(self) -> None:
        assert escape_ilike('Partner 1') == 'Partner 1'
        assert escape_ilike('') == ''


@pytest.mark.integration
class TestEscapeIlikeAgainstDatabase:
    """The escaping must actually change what PostgreSQL matches.

    Without it, a user typing `%` turns a "contains" search into "match
    everything" — the wildcard-injection bug that finding #21 is about. A
    unit test on the string alone would not prove the SQL behaves, so this
    runs the real query.
    """

    def test_bare_percent_matches_everything_without_escaping(
        self, db_session: Session, partner_org: Organization
    ) -> None:
        _seed_partners(db_session, partner_org.id, count=3)
        rows = db_session.scalars(
            _partners_stmt(partner_org.id).where(Partner.name.ilike('%%%'))
        ).all()
        assert len(rows) == 3  # the vulnerable behaviour, pinned for contrast

    def test_escaped_percent_matches_only_literal_percent(
        self, db_session: Session, partner_org: Organization
    ) -> None:
        _seed_partners(db_session, partner_org.id, count=3)
        db_session.add(
            Partner(organization_id=partner_org.id, name='100% Cotton', type='SUPPLIER')
        )
        db_session.commit()

        pattern = f'%{escape_ilike("%")}%'
        rows = db_session.scalars(
            _partners_stmt(partner_org.id).where(Partner.name.ilike(pattern))
        ).all()

        assert [r.name for r in rows] == ['100% Cotton']

    def test_escaped_underscore_is_not_a_single_char_wildcard(
        self, db_session: Session, partner_org: Organization
    ) -> None:
        db_session.add_all(
            [
                Partner(organization_id=partner_org.id, name='ab', type='SUPPLIER'),
                Partner(organization_id=partner_org.id, name='a_b', type='SUPPLIER'),
            ]
        )
        db_session.commit()

        pattern = f'%{escape_ilike("a_b")}%'
        rows = db_session.scalars(
            _partners_stmt(partner_org.id).where(Partner.name.ilike(pattern))
        ).all()

        assert [r.name for r in rows] == ['a_b']


@pytest.mark.integration
class TestPaginate:
    """Sync ``paginate`` variant."""

    def test_returns_items_and_total(
        self, db_session: Session, partner_org: Organization
    ):
        _seed_partners(db_session, partner_org.id, count=5)

        items, total = paginate(
            db_session, _partners_stmt(partner_org.id), limit=2, offset=1
        )

        assert total == 5
        assert len(items) == 2
        assert [p.name for p in items] == ['Partner 1', 'Partner 2']

    def test_total_ignores_preexisting_limit_on_statement(
        self, db_session: Session, partner_org: Organization
    ):
        _seed_partners(db_session, partner_org.id, count=5)
        stmt = _partners_stmt(partner_org.id).limit(3)

        items, total = paginate(db_session, stmt, limit=2, offset=0)

        assert total == 5
        assert len(items) == 2

    def test_returns_empty_when_no_rows(
        self, db_session: Session, partner_org: Organization
    ):
        items, total = paginate(
            db_session, _partners_stmt(partner_org.id), limit=10, offset=0
        )

        assert items == []
        assert total == 0


@pytest.mark.integration
class TestPaginateAsync:
    """Async ``paginate_async`` variant."""

    @pytest.mark.asyncio
    async def test_returns_items_and_total(
        self, real_async_db_session: AsyncSession, async_partner_org: Organization
    ):
        for i in range(5):
            real_async_db_session.add(
                Partner(
                    organization_id=async_partner_org.id,
                    name=f'Partner {i}',
                    type='SUPPLIER',
                )
            )
        await real_async_db_session.flush()

        items, total = await paginate_async(
            real_async_db_session,
            _partners_stmt(async_partner_org.id),
            limit=2,
            offset=2,
        )

        assert total == 5
        assert len(items) == 2
        assert [p.name for p in items] == ['Partner 2', 'Partner 3']

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_rows(
        self, real_async_db_session: AsyncSession, async_partner_org: Organization
    ):
        items, total = await paginate_async(
            real_async_db_session,
            _partners_stmt(async_partner_org.id),
            limit=10,
            offset=0,
        )

        assert items == []
        assert total == 0


@pytest.mark.integration
class TestGetOrgOwnedOr404:
    """Sync ``get_org_owned_or_404`` variant."""

    def test_returns_row_for_matching_org(
        self, db_session: Session, partner_org: Organization
    ):
        partner = Partner(organization_id=partner_org.id, name='Acme', type='SUPPLIER')
        db_session.add(partner)
        db_session.commit()

        result = get_org_owned_or_404(db_session, Partner, partner.id, partner_org.id)

        assert result.id == partner.id
        assert result.name == 'Acme'

    def test_raises_404_when_id_missing(
        self, db_session: Session, partner_org: Organization
    ):
        with pytest.raises(NotFoundException) as excinfo:
            get_org_owned_or_404(db_session, Partner, uuid.uuid4(), partner_org.id)

        assert excinfo.value.status_code == 404
        assert excinfo.value.detail['code'] == 'PARTNER_NOT_FOUND'

    def test_raises_404_when_org_mismatch(
        self, db_session: Session, partner_org: Organization
    ):
        partner = Partner(organization_id=partner_org.id, name='Acme', type='SUPPLIER')
        other_org = Organization(name='Other Test Org')
        db_session.add_all([partner, other_org])
        db_session.commit()

        with pytest.raises(NotFoundException) as excinfo:
            get_org_owned_or_404(db_session, Partner, partner.id, other_org.id)

        assert excinfo.value.status_code == 404

    def test_irregular_plural_resource_maps_categories_to_category(
        self, db_session: Session, partner_org: Organization
    ):
        """``categories`` must map to ``category``, not ``categorie``."""
        with pytest.raises(NotFoundException) as excinfo:
            get_org_owned_or_404(db_session, Category, uuid.uuid4(), partner_org.id)

        assert excinfo.value.status_code == 404
        assert excinfo.value.detail['code'] == 'CATEGORY_NOT_FOUND'


@pytest.mark.integration
class TestGetOrgOwnedOr404Async:
    """Async ``get_org_owned_or_404_async`` variant."""

    @pytest.mark.asyncio
    async def test_returns_row_for_matching_org(
        self, real_async_db_session: AsyncSession, async_partner_org: Organization
    ):
        partner = Partner(
            organization_id=async_partner_org.id, name='Acme', type='SUPPLIER'
        )
        real_async_db_session.add(partner)
        await real_async_db_session.flush()

        result = await get_org_owned_or_404_async(
            real_async_db_session, Partner, partner.id, async_partner_org.id
        )

        assert result.id == partner.id
        assert result.name == 'Acme'

    @pytest.mark.asyncio
    async def test_raises_404_when_id_missing(
        self, real_async_db_session: AsyncSession, async_partner_org: Organization
    ):
        with pytest.raises(NotFoundException) as excinfo:
            await get_org_owned_or_404_async(
                real_async_db_session, Partner, uuid.uuid4(), async_partner_org.id
            )

        assert excinfo.value.status_code == 404
        assert excinfo.value.detail['code'] == 'PARTNER_NOT_FOUND'

    @pytest.mark.asyncio
    async def test_raises_404_when_org_mismatch(
        self, real_async_db_session: AsyncSession, async_partner_org: Organization
    ):
        partner = Partner(
            organization_id=async_partner_org.id, name='Acme', type='SUPPLIER'
        )
        other_org = Organization(name='Other Async Test Org')
        real_async_db_session.add_all([partner, other_org])
        await real_async_db_session.flush()

        with pytest.raises(NotFoundException) as excinfo:
            await get_org_owned_or_404_async(
                real_async_db_session, Partner, partner.id, other_org.id
            )

        assert excinfo.value.status_code == 404


class TestGetOrgOwnedRefusesMissingOrg:
    """``org_id=None`` is a refusal, not a query for org-less rows.

    ``organization_id == None`` compiles to ``IS NULL``, so a caller that
    lost its tenant on the way here used to read system/global rows instead
    of being turned away. Both tests pass ``db=None``: reaching the session
    at all would raise ``AttributeError``, so a passing test also proves the
    refusal happens *before* the query is built.
    """

    @pytest.mark.asyncio
    async def test_async_refuses_none_org_before_querying(self):
        with pytest.raises(RuntimeError, match='requires an organization id'):
            await get_org_owned_or_404_async(
                None,
                Partner,
                uuid.uuid4(),
                None,
            )

    def test_sync_refuses_none_org_before_querying(self):
        with pytest.raises(RuntimeError, match='requires an organization id'):
            get_org_owned_or_404(
                None,
                Partner,
                uuid.uuid4(),
                None,
            )


@pytest.mark.integration
class TestAfterCommit:
    """Work a service defers runs after the request's commit, never after a rollback."""

    @pytest.mark.asyncio
    async def test_deferred_work_runs_after_the_commit_and_one_failure_spares_the_rest(
        self, real_async_db_session: AsyncSession
    ):
        ran: list[str] = []

        async def failing() -> None:
            ran.append('failing')
            raise RuntimeError('mail server down')

        async def notice() -> None:
            ran.append('notice')

        after_commit(real_async_db_session, failing)
        after_commit(real_async_db_session, notice)
        assert ran == []

        await real_async_db_session.commit()
        await dispatch_committed_events(real_async_db_session)
        assert ran == ['failing', 'notice']

        # Run once: a later commit on the same session does not repeat them.
        await dispatch_committed_events(real_async_db_session)
        assert ran == ['failing', 'notice']

    @pytest.mark.asyncio
    async def test_a_rollback_drops_the_deferred_work(
        self, real_async_db_session: AsyncSession
    ):
        ran: list[str] = []

        async def notice() -> None:
            ran.append('notice')

        # A transaction has to be open for its rollback to reach the database.
        await real_async_db_session.execute(select(1))
        after_commit(real_async_db_session, notice)
        await real_async_db_session.rollback()

        await real_async_db_session.commit()
        await dispatch_committed_events(real_async_db_session)
        assert ran == []

    @pytest.mark.asyncio
    async def test_a_failed_savepoint_drops_only_what_was_deferred_inside_it(
        self, real_async_db_session: AsyncSession
    ):
        """A service that undoes its own part with a savepoint leaves the
        caller's deferred work and buffered events alone: the outer commit
        still runs them, once, and nothing the savepoint took back."""
        db = real_async_db_session
        ran: list[str] = []
        seen = []
        core_api.events.subscribe(SystemEvent.MODULE_ENABLED, seen.append)

        def deferred(name: str) -> Callable[[], Awaitable[None]]:
            async def callback() -> None:
                ran.append(name)

            return callback

        def payload(module_name: str) -> TenantEventPayload:
            return TenantEventPayload.model_validate(
                {'organization_id': str(uuid.uuid4()), 'module_name': module_name}
            )

        await db.execute(select(1))
        after_commit(db, deferred('outer'))
        await event_bus.emit_transactional(
            db, SystemEvent.MODULE_ENABLED, payload('outer')
        )
        with pytest.raises(RuntimeError):
            async with db.begin_nested():
                after_commit(db, deferred('inner'))
                await event_bus.emit_transactional(
                    db, SystemEvent.MODULE_ENABLED, payload('inner')
                )
                raise RuntimeError('the service failed halfway')

        await db.commit()
        await dispatch_committed_events(db)
        await dispatch_committed_events(db)

        assert ran == ['outer']
        assert [event.module_name for event in seen] == ['outer']

    @pytest.mark.asyncio
    async def test_a_released_savepoint_keeps_what_was_deferred_inside_it(
        self, real_async_db_session: AsyncSession
    ):
        db = real_async_db_session
        ran: list[str] = []

        async def inner() -> None:
            ran.append('inner')

        await db.execute(select(1))
        async with db.begin_nested():
            after_commit(db, inner)

        await db.commit()
        await dispatch_committed_events(db)
        assert ran == ['inner']
